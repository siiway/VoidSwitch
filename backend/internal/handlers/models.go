package handlers

import (
	"fmt"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// loadModelsWithUpstreams loads exposed models plus their reachable upstream refs
// ("slug/upstream-model") from the routing graph.
func (a *App) loadModelsWithUpstreams() ([]database.ExposedModel, map[int][]string, error) {
	var models []database.ExposedModel
	if err := a.GDB.Order("model_id").Find(&models).Error; err != nil {
		return nil, nil, err
	}
	var routes []database.Route
	if err := a.GDB.Find(&routes).Error; err != nil {
		return nil, nil, err
	}
	routeByModel := map[int]int{}
	for _, r := range routes {
		routeByModel[r.ExposedModelID] = r.ID
	}
	var upstreams []database.RouteUpstream
	if err := a.GDB.Find(&upstreams).Error; err != nil {
		return nil, nil, err
	}
	// provider slug map
	var providers []database.Provider
	if err := a.GDB.Find(&providers).Error; err != nil {
		return nil, nil, err
	}
	slugByID := map[int]string{}
	for _, p := range providers {
		slugByID[p.ID] = p.Slug
	}

	refsByRoute := map[int][]string{}
	for _, u := range upstreams {
		if u.ProviderID == nil {
			continue
		}
		slug := slugByID[*u.ProviderID]
		refsByRoute[u.RouteID] = append(refsByRoute[u.RouteID], fmt.Sprintf("%s/%s", slug, u.UpstreamModel))
	}

	out := map[int][]string{}
	for _, m := range models {
		if rid, ok := routeByModel[m.ID]; ok {
			out[m.ID] = refsByRoute[rid]
		}
	}
	return models, out, nil
}

// modelsList returns exposed models visible to the caller.
func (a *App) modelsList(c *gin.Context) {
	uv := core.GetUser(c)
	models, refs, err := a.loadModelsWithUpstreams()
	if err != nil {
		a.internal(c, err)
		return
	}
	cats := a.categoryLookup()
	groupSet := map[int]bool{}
	for _, id := range uv.GroupIDs {
		groupSet[id] = true
	}
	out := make([]services.ModelEntryView, 0, len(models))
	for i := range models {
		m := &models[i]
		if !uv.IsStaff() {
			if !m.Enabled || !modelAllowed(m, groupSet, false) {
				continue
			}
		}
		v := services.BuildModelEntryView(m, refs[m.ID])
		applyCategory(&v, cats)
		out = append(out, v)
	}

	// Provider passthrough virtual entries: each enabled passthrough provider
	// contributes its whitelisted models as "slug/exposed" entries. A passthrough
	// id takes over any matching exposed-model row (merged metadata), so the same
	// id never appears twice.
	out = a.mergePassthroughVirtuals(out, uv.IsStaff())
	c.JSON(http.StatusOK, out)
}

// mergePassthroughVirtuals folds enabled providers' passthrough whitelists into
// the model catalog as provider-owned entries.
//
// A passthrough id takes over any matching exposed-model row: the row supplies
// metadata (name, role groups, limits) while the entry is marked `provider=true`
// so the UI treats it as passthrough (no route editor, no unserved/clean
// accounting). That row exists precisely because an admin configured the
// passthrough id from the dashboard, which is not the same thing as the id
// owning a route of its own.
func (a *App) mergePassthroughVirtuals(exposed []services.ModelEntryView, isStaff bool) []services.ModelEntryView {
	byID := make(map[string]int, len(exposed))
	for i := range exposed {
		byID[exposed[i].ModelID] = i
	}
	var providers []database.Provider
	a.GDB.Where("enabled = ? AND passthrough_enabled = ?", true, true).Find(&providers)

	// Which exposed rows own a route. Such a row is an ordinary model and must
	// not be absorbed by a passthrough entry that happens to share its id.
	routedExposedIDs := map[string]bool{}
	if len(exposed) > 0 {
		ids := make([]int, 0, len(exposed))
		for i := range exposed {
			if exposed[i].ID != nil {
				ids = append(ids, *exposed[i].ID)
			}
		}
		if len(ids) > 0 {
			var routeRows []database.Route
			a.GDB.Select("exposed_model_id").Where("exposed_model_id IN ?", ids).Find(&routeRows)
			routed := make(map[int]bool, len(routeRows))
			for i := range routeRows {
				routed[routeRows[i].ExposedModelID] = true
			}
			for i := range exposed {
				if exposed[i].ID != nil && routed[*exposed[i].ID] {
					routedExposedIDs[exposed[i].ModelID] = true
				}
			}
		}
	}

	virtualID := -1
	taken := map[string]bool{}
	var virtuals []services.ModelEntryView
	for pi := range providers {
		p := &providers[pi]
		var list []string
		database.DecodeJSON(p.PassthroughModels, &list)
		for _, entry := range list {
			exposedID := parsePassthroughExposed(entry)
			modelID := p.Slug + "/" + exposedID
			if taken[modelID] {
				continue
			}
			// A row that owns a route is an ordinary model the admin created; it
			// merely happens to look like a passthrough id. Leave it alone so it
			// keeps its route editor and its own category.
			if routedExposedIDs[modelID] {
				continue
			}
			taken[modelID] = true

			name, slug := p.Name, p.Slug
			if idx, ok := byID[modelID]; ok {
				v := exposed[idx]
				if !isStaff && !v.Enabled {
					continue
				}
				v.Provider = true
				// The provider travels in its own fields; the model keeps the
				// category it was given.
				v.ProviderName = &name
				v.ProviderSlug = &slug
				if v.DisplayName == nil || *v.DisplayName == "" {
					dn := exposedID
					v.DisplayName = &dn
				}
				virtuals = append(virtuals, v)
				continue
			}
			id := virtualID
			virtualID--
			dn := exposedID
			virtuals = append(virtuals, services.ModelEntryView{
				ID: &id, ModelID: modelID, DisplayName: &dn, Enabled: true,
				ProviderName: &name, ProviderSlug: &slug, Provider: true,
				OpenCodeConfig: map[string]any{}, Capabilities: map[string]any{},
				Modalities: map[string]any{}, AllowedRoleGroupIDs: []int{}, Upstreams: []string{},
			})
		}
	}

	// Exposed rows whose id is served as passthrough are replaced by the virtual
	// above, so the same id never appears twice.
	out := make([]services.ModelEntryView, 0, len(exposed)+len(virtuals))
	for i := range exposed {
		if taken[exposed[i].ModelID] {
			continue
		}
		out = append(out, exposed[i])
	}
	return append(out, virtuals...)
}

// categoryLookup maps category id -> (name, slug).
func (a *App) categoryLookup() map[int]database.ModelCategory {
	var cats []database.ModelCategory
	a.GDB.Find(&cats)
	out := make(map[int]database.ModelCategory, len(cats))
	for _, c := range cats {
		out[c.ID] = c
	}
	return out
}

// applyCategory fills category_name/category_slug from the category id.
func applyCategory(v *services.ModelEntryView, cats map[int]database.ModelCategory) {
	if v.CategoryID == nil {
		return
	}
	if c, ok := cats[*v.CategoryID]; ok {
		name, slug := c.Name, c.Slug
		v.CategoryName = &name
		v.CategorySlug = &slug
	}
}

func modelAllowed(m *database.ExposedModel, groupSet map[int]bool, isMod bool) bool {
	if isMod {
		return true
	}
	var allowed []int
	database.DecodeJSON(m.AllowedRoleGroupIDs, &allowed)
	for _, id := range allowed {
		if groupSet[id] {
			return true
		}
	}
	return false
}

// RegisterModelRoutes wires all /api/models/* routes (read + write).
func RegisterModelRoutes(r *gin.RouterGroup, a *App) {
	registerModelRoutesImpl(r, a)
}
