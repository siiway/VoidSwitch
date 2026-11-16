package handlers

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

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

// validateRoleGroupIDs rejects unknown ids and drops duplicates instead of
// storing them silently: a stale dashboard tab would otherwise persist a group
// that no longer exists, and the model would then be callable by nobody.
func (a *App) validateRoleGroupIDs(ids []int) ([]int, []int) {
	var existing []int
	a.GDB.Model(&database.RoleGroup{}).Where("builtin = ?", false).Pluck("id", &existing)
	known := make(map[int]bool, len(existing))
	for _, id := range existing {
		known[id] = true
	}
	seen := make(map[int]bool, len(ids))
	out := make([]int, 0, len(ids))
	var unknown []int
	for _, id := range ids {
		if !known[id] {
			unknown = append(unknown, id)
			continue
		}
		if seen[id] {
			continue
		}
		seen[id] = true
		out = append(out, id)
	}
	return out, unknown
}

// auditModel records a model-admin action. Model changes were previously
// unaudited, so the audit page could not answer "who removed this model".
func (a *App) auditModel(c *gin.Context, action, targetType string, targetID *string, detail map[string]any) {
	uv := core.GetUser(c)
	if uv == nil || uv.User == nil {
		return
	}
	sub := uv.User.Sub
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: action, ActorSub: &sub, ActorName: servicesName(uv),
		Scope: core.AuditScopeAdmin, TargetType: &targetType, TargetID: targetID,
		Detail: detail, IP: strPtr(clientIP(c)),
	})
}

// modelMetadata returns the metadata row for a public id, creating an empty one
// (without a route) when the admin is editing an id that only exists as a
// passthrough entry. Editing a passthrough model's name, groups or limits must
// work exactly like editing a regular model; the entry simply has no route.
func (a *App) modelsUpsert(c *gin.Context) {
	uv := core.GetUser(c)
	var in modelUpsertIn
	if err := c.ShouldBindJSON(&in); err != nil || strings.TrimSpace(in.ModelID) == "" {
		a.fail(c, http.StatusUnprocessableEntity, "model_id is required.")
		return
	}
	if in.AllowedRoleGroupIDs != nil {
		kept, unknown := a.validateRoleGroupIDs(*in.AllowedRoleGroupIDs)
		if len(unknown) > 0 {
			a.fail(c, http.StatusUnprocessableEntity, fmt.Sprintf("Unknown role group id(s): %v.", unknown))
			return
		}
		in.AllowedRoleGroupIDs = &kept
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

	detail := map[string]any{"model_id": m.ModelID}
	if created {
		detail["created"] = true
	}
	a.auditModel(c, "model.upsert", "model", strPtr(strconv.Itoa(m.ID)), detail)
}

func (a *App) modelsOut(c *gin.Context, m *database.ExposedModel, status int) {
	_, refs, _ := a.loadModelsWithUpstreams()
	v := services.BuildModelEntryView(m, refs[m.ID])
	applyCategory(&v, a.categoryLookup())
	c.JSON(status, v)
}

func (a *App) modelDelete(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var m database.ExposedModel
	if err := a.GDB.First(&m, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Model not found.")
		return
	}
	if err := a.GDB.Delete(&m).Error; err != nil {
		a.internal(c, err)
		return
	}
	a.auditModel(c, "model.delete", "model", strPtr(strconv.Itoa(id)),
		map[string]any{"model_id": m.ModelID})
	c.Status(http.StatusNoContent)
}

// ---- batch update / delete / clean ---------------------------------------

// modelsBatch applies the same metadata to many models at once. Every field the
// single-model editor accepts is accepted here too, otherwise the batch dialog
// silently drops most of what it offers (access groups, capabilities, reasoning,
// limits, category) and reports success anyway.
func (a *App) modelsBatch(c *gin.Context) {
	var in struct {
		ModelIDs       []string        `json:"model_ids"`
		DisplayName    *string         `json:"display_name"`
		Description    *string         `json:"description"`
		OpenCodeConfig json.RawMessage `json:"opencode_config"`
		// ConfigMode is the documented contract; Mode keeps the older spelling.
		ConfigMode          string          `json:"opencode_config_mode"`
		Mode                string          `json:"mode"`
		Enabled             *bool           `json:"enabled"`
		CategoryID          *int            `json:"category_id"`
		Reasoning           *bool           `json:"reasoning"`
		Capabilities        json.RawMessage `json:"capabilities"`
		Modalities          json.RawMessage `json:"modalities"`
		LimitContext        *int            `json:"limit_context"`
		LimitInput          *int            `json:"limit_input"`
		LimitOutput         *int            `json:"limit_output"`
		AllowedRoleGroupIDs *[]int          `json:"allowed_role_group_ids"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || len(in.ModelIDs) == 0 {
		a.fail(c, http.StatusUnprocessableEntity, "model_ids are required.")
		return
	}
	var groupIDs []int
	if in.AllowedRoleGroupIDs != nil {
		kept, unknown := a.validateRoleGroupIDs(*in.AllowedRoleGroupIDs)
		if len(unknown) > 0 {
			a.fail(c, http.StatusUnprocessableEntity, fmt.Sprintf("Unknown role group id(s): %v.", unknown))
			return
		}
		groupIDs = kept
	}
	merge := in.ConfigMode != "overwrite" && in.Mode != "overwrite"

	updated := 0
	for _, rawID := range in.ModelIDs {
		modelID := strings.TrimSpace(rawID)
		if modelID == "" {
			continue
		}
		// A passthrough id has no row until its metadata is first edited; the
		// batch dialog selects those ids too, so create the row on demand.
		m, created, err := a.modelMetadataWithUser(modelID, core.GetUser(c))
		if err != nil {
			a.internal(c, err)
			return
		}
		if in.DisplayName != nil {
			m.DisplayName = blankToNil(*in.DisplayName)
		}
		if in.Description != nil {
			m.Description = in.Description
		}
		if in.Enabled != nil {
			m.Enabled = *in.Enabled
		}
		if in.CategoryID != nil {
			if *in.CategoryID <= 0 {
				m.CategoryID = nil
			} else {
				m.CategoryID = in.CategoryID
			}
		}
		if in.Reasoning != nil {
			m.Reasoning = in.Reasoning
		}
		if in.LimitContext != nil {
			m.LimitContext = nonNegative(in.LimitContext)
		}
		if in.LimitInput != nil {
			m.LimitInput = nonNegative(in.LimitInput)
		}
		if in.LimitOutput != nil {
			m.LimitOutput = nonNegative(in.LimitOutput)
		}
		if len(in.Capabilities) > 0 {
			m.Capabilities = database.JSON(in.Capabilities)
		}
		if len(in.Modalities) > 0 {
			m.Modalities = database.JSON(in.Modalities)
		}
		if in.AllowedRoleGroupIDs != nil {
			m.AllowedRoleGroupIDs = database.JSONOf(groupIDs)
		}
		if len(in.OpenCodeConfig) > 0 {
			if merge {
				m.OpenCodeConfig = mergeJSON(m.OpenCodeConfig, database.JSON(in.OpenCodeConfig))
			} else {
				m.OpenCodeConfig = database.JSON(in.OpenCodeConfig)
			}
		}
		if created {
			if err := a.GDB.Create(m).Error; err != nil {
				a.internal(c, err)
				return
			}
		} else if err := a.GDB.Save(m).Error; err != nil {
			a.internal(c, err)
			return
		}
		updated++
	}
	a.auditModel(c, "model.batch_update", "model", nil, map[string]any{
		"model_ids": in.ModelIDs,
	})
	c.JSON(http.StatusOK, gin.H{"updated": updated})
}

func blankToNil(s string) *string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	return &s
}

func nonNegative(v *int) *int {
	if v == nil || *v < 0 {
		zero := 0
		return &zero
	}
	return v
}

// modelMetadataWithUser is modelMetadata with an explicit actor, so the row a
// batch edit creates records who added it.
func (a *App) modelMetadataWithUser(modelID string, uv *core.UserView) (*database.ExposedModel, bool, error) {
	var m database.ExposedModel
	err := a.GDB.Where("model_id = ?", modelID).First(&m).Error
	if err == nil {
		return &m, false, nil
	}
	if !errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, false, err
	}
	m = database.ExposedModel{
		ModelID: modelID, Enabled: true,
		OpenCodeConfig:      database.JSONOf(map[string]any{}),
		AllowedRoleGroupIDs: database.JSONOf([]int{}),
		Capabilities:        database.JSONOf(map[string]any{}),
		Modalities:          database.JSONOf(map[string]any{}),
	}
	if uv != nil && uv.User != nil {
		m.AddedBy = &uv.User.ID
		m.AddedByName = uv.User.Username
	}
	return &m, true, nil
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

// modelsBatchDelete deletes models by public id. An id may be a metadata row, a
// passthrough entry, or (as the UI presents it) both at once: a passthrough id
// the operator has edited carries a metadata row *and* an entry in its
// provider's whitelist. Deleting it must clear both, otherwise the model
// reappears on the next catalog build.
func (a *App) modelsBatchDelete(c *gin.Context) {
	var in struct {
		ModelIDs []string `json:"model_ids"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || len(in.ModelIDs) == 0 {
		a.fail(c, http.StatusUnprocessableEntity, "model_ids is required.")
		return
	}

	seen := map[string]bool{}
	var ordered []string
	for _, raw := range in.ModelIDs {
		id := strings.TrimSpace(raw)
		if id == "" || seen[id] {
			continue
		}
		seen[id] = true
		ordered = append(ordered, id)
	}

	removedEntries, err := a.deletePassthroughEntries(ordered)
	if err != nil {
		a.internal(c, err)
		return
	}
	var existing []string
	a.GDB.Model(&database.ExposedModel{}).Where("model_id IN ?", ordered).Pluck("model_id", &existing)
	res := a.GDB.Where("model_id IN ?", ordered).Delete(&database.ExposedModel{})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	removed := removedIDs(ordered, existing, removedEntries)
	if len(removed) > 0 {
		a.auditModel(c, "model.delete", "model", nil,
			map[string]any{"model_ids": removed, "batch": true})
	}
	c.JSON(http.StatusOK, gin.H{"deleted": len(removed), "model_ids": removed})
}

// removedIDs returns the requested ids that actually existed, in request order.
func removedIDs(requested, hadRow []string, passthrough map[string]bool) []string {
	exists := make(map[string]bool, len(hadRow)+len(passthrough))
	for _, id := range hadRow {
		exists[id] = true
	}
	for id := range passthrough {
		exists[id] = true
	}
	out := make([]string, 0, len(requested))
	for _, id := range requested {
		if exists[id] {
			out = append(out, id)
		}
	}
	return out
}

// deletePassthroughEntries strips every "slug/exposed" id from the matching
// provider's passthrough whitelist, returning the ids it removed. Ids that are
// not passthrough entries are ignored, so this is safe to call with a mixed
// selection.
func (a *App) deletePassthroughEntries(modelIDs []string) (map[string]bool, error) {
	var providers []database.Provider
	if err := a.GDB.Where("passthrough_enabled = ?", true).Find(&providers).Error; err != nil {
		return nil, err
	}
	removed := map[string]bool{}
	if len(providers) == 0 {
		return removed, nil
	}
	wanted := map[string]map[string]bool{}
	for _, id := range modelIDs {
		i := strings.Index(id, "/")
		if i <= 0 {
			continue
		}
		slug, exposed := id[:i], id[i+1:]
		if wanted[slug] == nil {
			wanted[slug] = map[string]bool{}
		}
		wanted[slug][exposed] = true
	}
	for pi := range providers {
		p := &providers[pi]
		targets := wanted[p.Slug]
		if len(targets) == 0 {
			continue
		}
		var list []string
		database.DecodeJSON(p.PassthroughModels, &list)
		kept := make([]string, 0, len(list))
		for _, entry := range list {
			exposed := parsePassthroughExposed(entry)
			if targets[exposed] {
				removed[p.Slug+"/"+exposed] = true
				continue
			}
			kept = append(kept, entry)
		}
		if len(kept) == len(list) {
			continue
		}
		if err := a.GDB.Model(p).Update("passthrough_models", database.JSONOf(kept)).Error; err != nil {
			return nil, err
		}
	}
	return removed, nil
}

// modelsClean deletes exposed models whose route resolves to no enabled
// upstream.
//
// A model served by passthrough is *not* unserved: the provider forwards it
// directly, so a passthrough id's metadata row (created when its access groups
// were edited) has no route by design and must survive. Python's clean_unserved
// skips these ids; deleting them here silently wiped every passthrough model's
// metadata and access control.
func (a *App) modelsClean(c *gin.Context) {
	passthroughIDs, err := a.passthroughModelIDs()
	if err != nil {
		a.internal(c, err)
		return
	}
	var models []database.ExposedModel
	a.GDB.Find(&models)
	removed := []string{}
	for _, m := range models {
		if passthroughIDs[m.ModelID] {
			continue
		}
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
	if len(removed) > 0 {
		a.auditModel(c, "model.clean_unserved", "model", nil,
			map[string]any{"model_ids": removed, "deleted": len(removed)})
	}
	c.JSON(http.StatusOK, gin.H{"deleted": len(removed), "model_ids": removed})
}

// passthroughModelIDs is the set of "slug/exposed" ids served by enabled
// passthrough providers.
func (a *App) passthroughModelIDs() (map[string]bool, error) {
	var providers []database.Provider
	err := a.GDB.Where("enabled = ? AND passthrough_enabled = ?", true, true).Find(&providers).Error
	if err != nil {
		return nil, err
	}
	out := make(map[string]bool)
	for pi := range providers {
		p := &providers[pi]
		var list []string
		database.DecodeJSON(p.PassthroughModels, &list)
		for _, entry := range list {
			exposed := parsePassthroughExposed(entry)
			if exposed != "" {
				out[p.Slug+"/"+exposed] = true
			}
		}
	}
	return out, nil
}

// ---- categories -----------------------------------------------------------

// modelCategoryView is the JSON shape the frontend expects (snake_case ids).
type modelCategoryView struct {
	ID        int       `json:"id"`
	Name      string    `json:"name"`
	Slug      string    `json:"slug"`
	Position  int       `json:"position"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

func toCategoryView(c *database.ModelCategory) modelCategoryView {
	return modelCategoryView{
		ID: c.ID, Name: c.Name, Slug: c.Slug, Position: c.Position,
		CreatedAt: c.CreatedAt, UpdatedAt: c.UpdatedAt,
	}
}

func (a *App) categoriesList(c *gin.Context) {
	var cats []database.ModelCategory
	if err := a.GDB.Order("position, id").Find(&cats).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]modelCategoryView, 0, len(cats))
	for i := range cats {
		out = append(out, toCategoryView(&cats[i]))
	}
	c.JSON(http.StatusOK, out)
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
	c.JSON(http.StatusCreated, toCategoryView(&cat))
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
	c.JSON(http.StatusOK, toCategoryView(&cat))
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

// providerGroupDelete disables a provider's passthrough namespace and removes
// the metadata rows it created. It deliberately preserves the provider itself
// (keys, base URL, model config): deleting the provider here would destroy an
// entity this action never presents itself as deleting.
func (a *App) providerGroupDelete(c *gin.Context) {
	slug := c.Param("slug")
	var p database.Provider
	if err := a.GDB.Where("slug = ? AND passthrough_enabled = ?", slug, true).First(&p).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Passthrough provider not found.")
		return
	}
	var stale []database.ExposedModel
	if err := a.GDB.Where("model_id LIKE ?", slug+"/%").Find(&stale).Error; err != nil {
		a.internal(c, err)
		return
	}
	deletedIDs := make([]string, 0, len(stale))
	for i := range stale {
		deletedIDs = append(deletedIDs, stale[i].ModelID)
	}
	if len(stale) > 0 {
		if err := a.GDB.Delete(&stale).Error; err != nil {
			a.internal(c, err)
			return
		}
	}
	if err := a.GDB.Model(&p).Updates(map[string]any{
		"passthrough_enabled": false,
		"passthrough_models":  database.JSONOf([]string{}),
	}).Error; err != nil {
		a.internal(c, err)
		return
	}
	tid := strconv.Itoa(p.ID)
	a.auditModel(c, "model.delete", "provider_passthrough_group", &tid, map[string]any{
		"provider_slug": slug, "deleted_model_ids": deletedIDs,
	})
	c.Status(http.StatusNoContent)
}

// ---- passthrough ----------------------------------------------------------

// passthroughDelete removes one passthrough model: its entry in the provider's
// whitelist plus any metadata row carrying that id.
//
// The exposed id may itself contain slashes ("openrouter/stealth/x"), which is
// why the route captures the remainder of the path rather than one segment;
// encoding the slash as %2F is equally accepted.
func (a *App) passthroughDelete(c *gin.Context) {
	slug := c.Param("slug")
	exposed := strings.TrimPrefix(c.Param("exposed"), "/")
	if exposed == "" {
		a.fail(c, http.StatusUnprocessableEntity, "The model id is required.")
		return
	}
	var p database.Provider
	if err := a.GDB.Where("slug = ?", slug).First(&p).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Passthrough provider not found.")
		return
	}
	var list []string
	database.DecodeJSON(p.PassthroughModels, &list)
	kept := make([]string, 0, len(list))
	removedEntries := 0
	for _, e := range list {
		if parsePassthroughExposed(e) == exposed {
			removedEntries++
			continue
		}
		kept = append(kept, e)
	}
	modelID := slug + "/" + exposed
	var stale database.ExposedModel
	staleErr := a.GDB.Where("model_id = ?", modelID).First(&stale).Error
	hadMetadata := staleErr == nil
	if !hadMetadata && !errors.Is(staleErr, gorm.ErrRecordNotFound) {
		a.internal(c, staleErr)
		return
	}
	if removedEntries == 0 && !hadMetadata {
		a.fail(c, http.StatusNotFound, "Passthrough model not found.")
		return
	}
	if removedEntries > 0 {
		if err := a.GDB.Model(&p).Update("passthrough_models", database.JSONOf(kept)).Error; err != nil {
			a.internal(c, err)
			return
		}
	}
	if hadMetadata {
		if err := a.GDB.Delete(&stale).Error; err != nil {
			a.internal(c, err)
			return
		}
	}
	tid := strconv.Itoa(p.ID)
	a.auditModel(c, "model.delete", "model", &tid, map[string]any{
		"model_id": modelID, "provider_id": p.ID, "passthrough_removed": removedEntries,
	})
	c.Status(http.StatusNoContent)
}

// parsePassthroughExposed returns the caller-facing id of a passthrough entry,
// delegating to the parser the dispatcher uses so both stay in agreement.
func parsePassthroughExposed(entry string) string {
	exposed, _, _ := services.ParsePassthroughEntry(entry)
	return exposed
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
	if q == "" {
		c.JSON(http.StatusOK, gin.H{"results": []any{}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"results": services.SearchModelsDev(a.GDB, q, 100)})
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
	// A passthrough exposed id may itself contain slashes
	// ("openrouter/stealth/space-bunny-alpha"), so the wildcard is required:
	// with a single-segment param Gin returns 404 for those ids.
	g.DELETE("/passthrough/:slug/*exposed", a.passthroughDelete)
	g.GET("/models-dev/search", a.modelsDevSearch)
	g.POST("/models-dev/sync", a.modelsDevSync)
	g.GET("/:id/route", a.modelRouteGet)
	g.PUT("/:id/route", a.modelRoutePut)
	g.POST("/:id/route/upstreams/:upstreamId/clear-cooldown", a.routeClearCooldown)
	g.DELETE("/:id", a.modelDelete)
}
