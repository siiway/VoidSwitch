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
// the model catalog as virtual entries (provider=true).
func (a *App) mergePassthroughVirtuals(exposed []services.ModelEntryView, isStaff bool) []services.ModelEntryView {
	byID := make(map[string]int, len(exposed))
	for i := range exposed {
		byID[exposed[i].ModelID] = i
	}
	var providers []database.Provider
	a.GDB.Where("enabled = ? AND passthrough_enabled = ?", true, true).Find(&providers)

	virtualID := -1
	passthroughIDs := map[string]bool{}
	var virtuals []services.ModelEntryView
	for pi := range providers {
		p := &providers[pi]
		var list []string
		database.DecodeJSON(p.PassthroughModels, &list)
		seen := map[string]bool{}
		for _, entry := range list {
			exposedID := parsePassthroughExposed(entry)
			modelID := p.Slug + "/" + exposedID
			if seen[modelID] {
				continue
			}
			seen[modelID] = true
			passthroughIDs[modelID] = true

			if idx, ok := byID[modelID]; ok {
				v := exposed[idx]
				if !isStaff && !v.Enabled {
					continue
				}
				v.Provider = true
				name, slug := p.Name, p.Slug
				v.CategoryName = &name
				v.CategorySlug = &slug
				if v.DisplayName == nil || *v.DisplayName == "" {
					dn := exposedID
					v.DisplayName = &dn
				}
				virtuals = append(virtuals, v)
			} else {
				id := virtualID
				virtualID--
				dn := exposedID
				name, slug := p.Name, p.Slug
				virtuals = append(virtuals, services.ModelEntryView{
					ID: &id, ModelID: modelID, DisplayName: &dn, Enabled: true,
					CategoryName: &name, CategorySlug: &slug, Provider: true,
					OpenCodeConfig: map[string]any{}, Capabilities: map[string]any{},
					Modalities: map[string]any{}, AllowedRoleGroupIDs: []int{}, Upstreams: []string{},
				})
			}
		}
	}

	// Drop exposed rows whose id is now served as a passthrough virtual, then
	// append the virtuals.
	out := make([]services.ModelEntryView, 0, len(exposed)+len(virtuals))
	for i := range exposed {
		if passthroughIDs[exposed[i].ModelID] {
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
