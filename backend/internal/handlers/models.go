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
		out = append(out, services.BuildModelEntryView(m, refs[m.ID]))
	}
	c.JSON(http.StatusOK, out)
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
