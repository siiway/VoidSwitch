package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// ---- model upsert (PUT /api/models) --------------------------------------

type modelUpsertIn struct {
	ModelID             string          `json:"model_id"`
	DisplayName         *string         `json:"display_name"`
	Description         *string         `json:"description"`
	OpenCodeConfig      json.RawMessage `json:"opencode_config"`
	Enabled             *bool           `json:"enabled"`
	AllowedRoleGroupIDs *[]int          `json:"allowed_role_group_ids"`
	LimitContext        *int            `json:"limit_context"`
	LimitInput          *int            `json:"limit_input"`
	LimitOutput         *int            `json:"limit_output"`
	Reasoning           *bool           `json:"reasoning"`
	Capabilities        json.RawMessage `json:"capabilities"`
	Modalities          json.RawMessage `json:"modalities"`
	ModelsDevID         *string         `json:"models_dev_id"`
	Brand               *string         `json:"brand"`
	CategoryID          *int            `json:"category_id"`
}

func (a *App) modelsUpsert(c *gin.Context) {
	uv := core.GetUser(c)
	var in modelUpsertIn
	if err := c.ShouldBindJSON(&in); err != nil || strings.TrimSpace(in.ModelID) == "" {
		a.fail(c, http.StatusUnprocessableEntity, "model_id is required.")
		return
	}
	var m database.ExposedModel
	err := a.GDB.Where("model_id = ?", in.ModelID).First(&m).Error
	created := false
	if err != nil {
		created = true
		m = database.ExposedModel{
			ModelID: in.ModelID, Enabled: true,
			OpenCodeConfig:      database.JSONOf(map[string]any{}),
			AllowedRoleGroupIDs: database.JSONOf([]int{}),
			Capabilities:        database.JSONOf(map[string]any{}),
			Modalities:          database.JSONOf(map[string]any{}),
			AddedBy:             &uv.User.ID, AddedByName: uv.User.Username,
		}
	}
	if in.DisplayName != nil {
		m.DisplayName = in.DisplayName
	}
	if in.Description != nil {
		m.Description = in.Description
	}
	if len(in.OpenCodeConfig) > 0 {
		m.OpenCodeConfig = database.JSON(in.OpenCodeConfig)
	}
	if in.Enabled != nil {
		m.Enabled = *in.Enabled
	}
	if in.AllowedRoleGroupIDs != nil {
		m.AllowedRoleGroupIDs = database.JSONOf(*in.AllowedRoleGroupIDs)
	}
	if in.LimitContext != nil {
		m.LimitContext = in.LimitContext
	}
	if in.LimitInput != nil {
		m.LimitInput = in.LimitInput
	}
	if in.LimitOutput != nil {
		m.LimitOutput = in.LimitOutput
	}
	if in.Reasoning != nil {
		m.Reasoning = in.Reasoning
	}
	if len(in.Capabilities) > 0 {
		m.Capabilities = database.JSON(in.Capabilities)
	}
	if len(in.Modalities) > 0 {
		m.Modalities = database.JSON(in.Modalities)
	}
	if in.ModelsDevID != nil {
		m.ModelsDevID = in.ModelsDevID
	}
	if in.Brand != nil {
		if strings.TrimSpace(*in.Brand) == "" {
			m.Brand = nil
		} else {
			m.Brand = in.Brand
		}
	}
	if in.CategoryID != nil {
		m.CategoryID = in.CategoryID
	}
	if created {
		if err := a.GDB.Create(&m).Error; err != nil {
			a.internal(c, err)
			return
		}
	} else {
		if err := a.GDB.Save(&m).Error; err != nil {
			a.internal(c, err)
			return
		}
	}
	a.modelsOut(c, &m, http.StatusOK)
}

func (a *App) modelsOut(c *gin.Context, m *database.ExposedModel, status int) {
	_, refs, _ := a.loadModelsWithUpstreams()
	c.JSON(status, services.BuildModelEntryView(m, refs[m.ID]))
}

func (a *App) modelDelete(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	res := a.GDB.Delete(&database.ExposedModel{}, id)
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	if res.RowsAffected == 0 {
		a.fail(c, http.StatusNotFound, "Model not found.")
		return
	}
	c.Status(http.StatusNoContent)
}

// ---- batch update / delete / clean ---------------------------------------

func (a *App) modelsBatch(c *gin.Context) {
	var in struct {
		ModelIDs       []string        `json:"model_ids"`
		Description    *string         `json:"description"`
		OpenCodeConfig json.RawMessage `json:"opencode_config"`
		Enabled        *bool           `json:"enabled"`
		CategoryID     *int            `json:"category_id"`
		Mode           string          `json:"mode"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || len(in.ModelIDs) == 0 {
		a.fail(c, http.StatusUnprocessableEntity, "model_ids are required.")
		return
	}
	var models []database.ExposedModel
	if err := a.GDB.Where("model_id IN ?", in.ModelIDs).Find(&models).Error; err != nil {
		a.internal(c, err)
		return
	}
	for i := range models {
		m := &models[i]
		if in.Description != nil {
			m.Description = in.Description
		}
		if in.Enabled != nil {
			m.Enabled = *in.Enabled
		}
		if in.CategoryID != nil {
			m.CategoryID = in.CategoryID
		}
		if len(in.OpenCodeConfig) > 0 {
			if in.Mode == "merge" {
				m.OpenCodeConfig = mergeJSON(m.OpenCodeConfig, database.JSON(in.OpenCodeConfig))
			} else {
				m.OpenCodeConfig = database.JSON(in.OpenCodeConfig)
			}
		}
		a.GDB.Save(m)
	}
	c.JSON(http.StatusOK, gin.H{"updated": len(models)})
}

func mergeJSON(base, patch database.JSON) database.JSON {
	var b, p map[string]any
	_ = json.Unmarshal(base, &b)
	_ = json.Unmarshal(patch, &p)
	if b == nil {
		b = map[string]any{}
	}
	for k, v := range p {
		if bv, ok := b[k].(map[string]any); ok {
			if pv, ok := v.(map[string]any); ok {
				for kk, vv := range pv {
					bv[kk] = vv
				}
				b[k] = bv
				continue
			}
		}
		b[k] = v
	}
	return database.JSONOf(b)
}

func (a *App) modelsBatchDelete(c *gin.Context) {
	var in struct {
		ModelIDs []string `json:"model_ids"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	res := a.GDB.Where("model_id IN ?", in.ModelIDs).Delete(&database.ExposedModel{})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	c.JSON(http.StatusOK, gin.H{"deleted": res.RowsAffected, "model_ids": in.ModelIDs})
}

func (a *App) modelsClean(c *gin.Context) {
	// Delete exposed models that have no route or an empty/disabled route.
	var models []database.ExposedModel
	a.GDB.Find(&models)
	var removed []string
	for _, m := range models {
		var route database.Route
		if err := a.GDB.Where("exposed_model_id = ?", m.ID).First(&route).Error; err != nil {
			removed = append(removed, m.ModelID)
			a.GDB.Delete(&m)
			continue
		}
		var count int64
		a.GDB.Model(&database.RouteUpstream{}).Where("route_id = ? AND enabled = ?", route.ID, true).Count(&count)
		if count == 0 {
			removed = append(removed, m.ModelID)
			a.GDB.Delete(&m)
		}
	}
	c.JSON(http.StatusOK, gin.H{"deleted": len(removed), "model_ids": removed})
}

// ---- categories -----------------------------------------------------------

func (a *App) categoriesList(c *gin.Context) {
	var cats []database.ModelCategory
	if err := a.GDB.Order("position, id").Find(&cats).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, cats)
}

func (a *App) categoriesCreate(c *gin.Context) {
	var in struct {
		Name     string `json:"name"`
		Position int    `json:"position"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || strings.TrimSpace(in.Name) == "" {
		a.fail(c, http.StatusUnprocessableEntity, "name is required.")
		return
	}
	cat := database.ModelCategory{Name: in.Name, Slug: slugify(in.Name), Position: in.Position}
	if err := a.GDB.Create(&cat).Error; err != nil {
		a.fail(c, http.StatusConflict, "Category name or slug already exists.")
		return
	}
	c.JSON(http.StatusCreated, cat)
}

func (a *App) categoriesUpdate(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var cat database.ModelCategory
	if err := a.GDB.First(&cat, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Category not found.")
		return
	}
	var in struct {
		Name     *string `json:"name"`
		Position *int    `json:"position"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Name != nil {
		cat.Name = *in.Name
		cat.Slug = slugify(*in.Name)
	}
	if in.Position != nil {
		cat.Position = *in.Position
	}
	if err := a.GDB.Save(&cat).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, cat)
}

func (a *App) categoriesDelete(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	a.GDB.Model(&database.ExposedModel{}).Where("category_id = ?", id).Update("category_id", nil)
	res := a.GDB.Delete(&database.ModelCategory{}, id)
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	c.Status(http.StatusNoContent)
}

// ---- provider-groups (delete a provider's passthrough namespace) ----------

func (a *App) providerGroupDelete(c *gin.Context) {
	slug := c.Param("slug")
	res := a.GDB.Where("slug = ?", slug).Delete(&database.Provider{})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	c.Status(http.StatusNoContent)
}

// ---- passthrough ----------------------------------------------------------

func (a *App) passthroughDelete(c *gin.Context) {
	slug := c.Param("slug")
	exposed := c.Param("exposed")
	var p database.Provider
	if err := a.GDB.Where("slug = ?", slug).First(&p).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	var list []string
	database.DecodeJSON(p.PassthroughModels, &list)
	var kept []string
	for _, e := range list {
		exp := parsePassthroughExposed(e)
		if exp != exposed {
			kept = append(kept, e)
		}
	}
	a.GDB.Model(&p).Update("passthrough_models", database.JSONOf(kept))
	c.Status(http.StatusNoContent)
}

func parsePassthroughExposed(entry string) string {
	e := strings.TrimSpace(entry)
	if i := strings.Index(e, "=>"); i >= 0 {
		e = strings.TrimSpace(e[:i])
	}
	if i := strings.Index(e, "@"); i >= 0 {
		e = strings.TrimSpace(e[:i])
	}
	return e
}

// ---- route ---------------------------------------------------------------

func (a *App) modelRouteGet(c *gin.Context) {
	modelID := c.Param("id")
	var m database.ExposedModel
	if err := a.GDB.Where("model_id = ?", modelID).First(&m).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Model not found.")
		return
	}
	var route database.Route
	rerr := a.GDB.Where("exposed_model_id = ?", m.ID).First(&route).Error
	out := gin.H{
		"id": m.ID, "model_id": m.ModelID, "display_name": m.DisplayName,
		"enabled": m.Enabled, "route": nil,
	}
	if rerr == nil {
		var ups []database.RouteUpstream
		a.GDB.Where("route_id = ?", route.ID).Order("group_position, position").Find(&ups)
		var provs []database.Provider
		a.GDB.Find(&provs)
		names := map[int]*database.Provider{}
		for i := range provs {
			names[provs[i].ID] = &provs[i]
		}
		ur := make([]gin.H, 0, len(ups))
		for _, u := range ups {
			var pname, pslug *string
			if u.ProviderID != nil {
				if p, ok := names[*u.ProviderID]; ok {
					pname = &p.Name
					pslug = &p.Slug
				}
			}
			var codes []int
			database.DecodeJSON(u.CooldownStatusCodes, &codes)
			ur = append(ur, gin.H{
				"id": u.ID, "provider_id": u.ProviderID, "provider_name": pname, "provider_slug": pslug,
				"upstream_model": u.UpstreamModel, "weight": u.Weight, "enabled": u.Enabled,
				"key_pool": u.KeyPool, "group_position": u.GroupPosition, "position": u.Position,
				"cooldown_status_codes": codes, "cooldown_seconds": u.CooldownSeconds,
			})
		}
		out["route"] = gin.H{
			"id": route.ID, "exposed_model_id": route.ExposedModelID,
			"upstream_select_mode":         route.UpstreamSelectMode,
			"upstream_rank_algorithm":      route.UpstreamRankAlgorithm,
			"max_upstream_attempts":        route.MaxUpstreamAttempts,
			"upstream_all_cooled_behavior": route.UpstreamAllCooledBehavior,
			"upstreams":                    ur,
		}
	}
	c.JSON(http.StatusOK, out)
}

type routeUpstreamIn struct {
	ID                  *int   `json:"id"`
	ProviderID          *int   `json:"provider_id"`
	UpstreamModel       string `json:"upstream_model"`
	Weight              *int   `json:"weight"`
	Enabled             *bool  `json:"enabled"`
	KeyPool             string `json:"key_pool"`
	GroupPosition       *int   `json:"group_position"`
	Position            *int   `json:"position"`
	CooldownStatusCodes *[]int `json:"cooldown_status_codes"`
	CooldownSeconds     *int   `json:"cooldown_seconds"`
}

func (a *App) modelRoutePut(c *gin.Context) {
	modelID := c.Param("id")
	var m database.ExposedModel
	if err := a.GDB.Where("model_id = ?", modelID).First(&m).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Model not found.")
		return
	}
	var in struct {
		UpstreamSelectMode        string            `json:"upstream_select_mode"`
		UpstreamRankAlgorithm     string            `json:"upstream_rank_algorithm"`
		MaxUpstreamAttempts       int               `json:"max_upstream_attempts"`
		UpstreamAllCooledBehavior string            `json:"upstream_all_cooled_behavior"`
		Upstreams                 []routeUpstreamIn `json:"upstreams"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	var route database.Route
	if err := a.GDB.Where("exposed_model_id = ?", m.ID).First(&route).Error; err != nil {
		route = database.Route{ExposedModelID: m.ID}
		a.GDB.Create(&route)
	}
	route.UpstreamSelectMode = in.UpstreamSelectMode
	route.UpstreamRankAlgorithm = in.UpstreamRankAlgorithm
	route.MaxUpstreamAttempts = in.MaxUpstreamAttempts
	route.UpstreamAllCooledBehavior = in.UpstreamAllCooledBehavior
	if err := a.GDB.Save(&route).Error; err != nil {
		a.internal(c, err)
		return
	}
	// Replace upstreams. Keep cooldown records keyed by tuple (they may be stale).
	if err := a.GDB.Where("route_id = ?", route.ID).Delete(&database.RouteUpstream{}).Error; err != nil {
		a.internal(c, err)
		return
	}
	for _, u := range in.Upstreams {
		if u.ProviderID == nil || strings.TrimSpace(u.UpstreamModel) == "" {
			continue
		}
		weight := 1
		if u.Weight != nil {
			weight = *u.Weight
		}
		enabled := true
		if u.Enabled != nil {
			enabled = *u.Enabled
		}
		gp, pos := 0, 0
		if u.GroupPosition != nil {
			gp = *u.GroupPosition
		}
		if u.Position != nil {
			pos = *u.Position
		}
		codes := []int{}
		if u.CooldownStatusCodes != nil {
			codes = *u.CooldownStatusCodes
		}
		cs := 0
		if u.CooldownSeconds != nil {
			cs = *u.CooldownSeconds
		}
		row := database.RouteUpstream{
			RouteID: route.ID, ProviderID: u.ProviderID, UpstreamModel: u.UpstreamModel,
			GroupPosition: gp, Position: pos, Weight: weight, Enabled: enabled,
			KeyPool: u.KeyPool, CooldownStatusCodes: database.JSONOf(codes), CooldownSeconds: cs,
		}
		a.GDB.Create(&row)
	}
	a.modelRouteGet(c)
}

func (a *App) routeClearCooldown(c *gin.Context) {
	upstreamID, _ := strconv.Atoi(c.Param("upstreamId"))
	var u database.RouteUpstream
	if err := a.GDB.First(&u, upstreamID).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Upstream not found.")
		return
	}
	if u.ProviderID != nil {
		a.GDB.Where("provider_id = ? AND upstream_model = ? AND key_pool = ?",
			*u.ProviderID, u.UpstreamModel, u.KeyPool).Delete(&database.UpstreamCooldown{})
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// ---- models.dev -----------------------------------------------------------

func (a *App) modelsDevSearch(c *gin.Context) {
	q := strings.TrimSpace(c.Query("q"))
	var rows []database.ModelsDevCache
	if q == "" {
		c.JSON(http.StatusOK, gin.H{"results": []any{}})
		return
	}
	a.GDB.Where("id ILIKE ?", "%"+q+"%").Limit(50).Find(&rows)
	results := make([]gin.H, 0, len(rows))
	for _, r := range rows {
		var data map[string]any
		database.DecodeJSON(r.Data, &data)
		results = append(results, gin.H{"id": r.ID, "name": data["name"], "raw": data})
	}
	c.JSON(http.StatusOK, gin.H{"results": results})
}

func (a *App) modelsDevSync(c *gin.Context) {
	n, err := services.SyncModelsDev(c.Request.Context(), a.GDB)
	if err != nil {
		a.fail(c, http.StatusBadGateway, err.Error())
		return
	}
	c.JSON(http.StatusOK, gin.H{"synced": n})
}

// RegisterModelAdminRoutes wires the models write surface under /api/models.
func registerModelRoutesImpl(r *gin.RouterGroup, a *App) {
	g := r.Group("/models", core.RequireUser())
	g.GET("", a.modelsList)
	g.PUT("", a.modelsUpsert)
	g.POST("/batch", a.modelsBatch)
	g.POST("/batch-delete", a.modelsBatchDelete)
	g.POST("/clean", a.modelsClean)
	g.GET("/categories", a.categoriesList)
	g.POST("/categories", a.categoriesCreate)
	g.PATCH("/categories/:id", a.categoriesUpdate)
	g.DELETE("/categories/:id", a.categoriesDelete)
	g.DELETE("/provider-groups/:slug", a.providerGroupDelete)
	g.DELETE("/passthrough/:slug/:exposed", a.passthroughDelete)
	g.GET("/models-dev/search", a.modelsDevSearch)
	g.POST("/models-dev/sync", a.modelsDevSync)
	g.GET("/:id/route", a.modelRouteGet)
	g.PUT("/:id/route", a.modelRoutePut)
	g.POST("/:id/route/upstreams/:upstreamId/clear-cooldown", a.routeClearCooldown)
	g.DELETE("/:id", a.modelDelete)
}
