package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// gatewayAuth resolves the caller's Void-Token from the Authorization bearer and
// loads the owning user. Returns false (having written a 401) on failure.
func (a *App) gatewayAuth(c *gin.Context) (*database.VoidToken, *database.User, bool) {
	raw := ""
	if auth := c.GetHeader("Authorization"); strings.HasPrefix(strings.ToLower(auth), "bearer ") {
		raw = strings.TrimSpace(auth[len("bearer "):])
	}
	if raw == "" {
		raw = strings.TrimSpace(c.GetHeader("X-API-Key"))
	}
	if raw == "" {
		a.fail(c, http.StatusUnauthorized, "Missing API key.")
		return nil, nil, false
	}
	hash := core.HashToken(raw)
	var token database.VoidToken
	if err := a.GDB.Where("token_hash = ? AND deleted = ?", hash, false).First(&token).Error; err != nil || !token.Enabled {
		a.fail(c, http.StatusUnauthorized, "Invalid API key.")
		return nil, nil, false
	}
	if token.ExpiresAt != nil && token.ExpiresAt.Before(time.Now().UTC()) {
		a.fail(c, http.StatusUnauthorized, "API key expired.")
		return nil, nil, false
	}
	var user database.User
	if err := a.GDB.Where("id = ?", token.UserID).First(&user).Error; err != nil || !user.Enabled {
		a.fail(c, http.StatusUnauthorized, "Token owner disabled.")
		return nil, nil, false
	}
	return &token, &user, true
}

// passthroughModelRef is one visible passthrough id plus the model card that
// carries its metadata and access control (nil when no card exists).
type passthroughModelRef struct {
	id  string
	row *database.ExposedModel
}

// visiblePassthroughModels lists the passthrough models a caller may actually
// call: enabled providers whose passthrough is on, ids permitted by the token's
// allow-list, and ids the caller's role groups may reach. A passthrough id keeps
// its access control on an exposed-model row of the same id (created when an
// admin sets role groups on the model card); without one it is staff-only,
// matching a regular model with no groups selected.
//
// An id that owns a route is an ordinary model: it is listed from the exposed
// catalog instead, so it is excluded here to avoid advertising it twice.
func (a *App) visiblePassthroughModels(token *database.VoidToken, uv *core.UserView) []passthroughModelRef {
	var providers []database.Provider
	a.GDB.Where("enabled = ? AND passthrough_enabled = ?", true, true).Order("slug").Find(&providers)
	if len(providers) == 0 {
		return nil
	}

	candidates := make([]string, 0, len(providers))
	perProvider := make([][]string, len(providers))
	for pi := range providers {
		p := &providers[pi]
		var list []string
		database.DecodeJSON(p.PassthroughModels, &list)
		for _, entry := range list {
			exposed, _, _ := services.ParsePassthroughEntry(entry)
			if exposed == "" {
				continue
			}
			id := p.Slug + "/" + exposed
			if !modelAllowedForToken(token, id) {
				continue
			}
			perProvider[pi] = append(perProvider[pi], id)
			candidates = append(candidates, id)
		}
	}
	if len(candidates) == 0 {
		return nil
	}

	// One query for every candidate's card keeps this off N+1.
	rowsByID := make(map[string]*database.ExposedModel, len(candidates))
	ids := make([]int, 0, len(candidates))
	if candidates != nil {
		var rows []database.ExposedModel
		a.GDB.Where("model_id IN ?", candidates).Find(&rows)
		for i := range rows {
			rowsByID[rows[i].ModelID] = &rows[i]
			ids = append(ids, rows[i].ID)
		}
	}
	routedIDs := make(map[int]bool, len(ids))
	if len(ids) > 0 {
		var routeRows []database.Route
		a.GDB.Select("exposed_model_id").Where("exposed_model_id IN ?", ids).Find(&routeRows)
		for i := range routeRows {
			routedIDs[routeRows[i].ExposedModelID] = true
		}
	}

	isStaff := uv.IsStaff()
	out := []passthroughModelRef{}
	for pi := range perProvider {
		for _, id := range perProvider[pi] {
			row := rowsByID[id]
			if row != nil {
				if routedIDs[row.ID] {
					continue
				}
				// Members must not see a hidden passthrough model.
				if !isStaff && !row.Enabled {
					continue
				}
			}
			var groups []int
			if row != nil {
				database.DecodeJSON(row.AllowedRoleGroupIDs, &groups)
			}
			if !passthroughAllowedForGroups(groups, uv.GroupIDs, isStaff) {
				continue
			}
			out = append(out, passthroughModelRef{id: id, row: row})
		}
	}
	return out
}

// gatewayModelItem is one entry of the `/v1/models` payload (the PY contract):
// identity plus the merged downstream config a client should apply.
func gatewayModelItem(id string, created int64, m *database.ExposedModel, slot *database.ExposedModel, mdIndex map[string]any) gin.H {
	item := gin.H{"id": id, "object": "model", "created": created, "owned_by": "voidswitch"}
	// `slot` carries metadata for a passthrough id (its model card, when one
	// exists); regular models are their own slot.
	meta := m
	if meta == nil {
		meta = slot
	}
	if meta == nil {
		return item
	}
	var devEntry any
	if meta.ModelsDevID != nil && *meta.ModelsDevID != "" {
		devEntry = mdIndex[*meta.ModelsDevID]
	}
	item["opencode"] = services.BuildOpencodeConfig(meta, devEntry)
	if meta.DisplayName != nil && *meta.DisplayName != "" {
		item["display_name"] = *meta.DisplayName
	}
	if meta.Description != nil && *meta.Description != "" {
		item["description"] = *meta.Description
	}
	return item
}

// modelsDevIndex resolves every advertised model's models.dev entry in one pass,
// so rendering the list does not query the registry per model.
func (a *App) modelsDevIndex() map[string]any {
	out := map[string]any{}
	var rows []database.ModelsDevCache
	a.GDB.Find(&rows)
	byProvider := make(map[string]map[string]any, len(rows))
	for i := range rows {
		var data map[string]any
		database.DecodeJSON(rows[i].Data, &data)
		if data != nil {
			byProvider[rows[i].ID] = data
		}
	}
	// Registry ids are "provider/model"; resolve that pair out of the cached
	// provider blobs.
	var exposed []database.ExposedModel
	a.GDB.Select("models_dev_id").Where("models_dev_id IS NOT NULL AND models_dev_id <> ''").Find(&exposed)
	for i := range exposed {
		id := *exposed[i].ModelsDevID
		if _, done := out[id]; done {
			continue
		}
		provider, mid, ok := splitModelsDevID(id)
		if !ok {
			continue
		}
		providerBlob, ok := byProvider[provider]
		if !ok {
			continue
		}
		models, ok := providerBlob["models"].(map[string]any)
		if !ok {
			continue
		}
		if entry, ok := models[mid]; ok {
			out[id] = entry
		}
	}
	return out
}

// splitModelsDevID splits "provider/model" at the first slash.
func splitModelsDevID(id string) (provider, model string, ok bool) {
	for i := 0; i < len(id); i++ {
		if id[i] == '/' {
			return id[:i], id[i+1:], true
		}
	}
	return "", "", false
}

// gatewayModels returns the OpenAI-compatible model list: every model the
// presenting token may actually call. That is the enabled exposed models plus
// the enabled providers' passthrough whitelists, each filtered by the token
// allow-list and (for non-staff) role-group access — the same gates a real call
// passes, so the list never advertises an id that would be rejected.
func (a *App) gatewayModels(c *gin.Context) {
	token, user, ok := a.gatewayAuth(c)
	if !ok {
		return
	}
	uv := a.gatewayUserView(user)

	data, err := a.advertisedModels(token, uv)
	if err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"object": "list", "data": data})
}

// advertisedModels builds the `/v1/models` payload for one caller.
func (a *App) advertisedModels(token *database.VoidToken, uv *core.UserView) ([]gin.H, error) {
	models, refs, err := a.loadModelsWithUpstreams()
	if err != nil {
		return nil, err
	}
	mdIndex := a.modelsDevIndex()

	data := make([]gin.H, 0, len(models))
	seen := make(map[string]bool, len(models))
	push := func(item gin.H) {
		id, _ := item["id"].(string)
		if id == "" || seen[id] {
			return
		}
		seen[id] = true
		data = append(data, item)
	}

	for i := range models {
		m := &models[i]
		if !m.Enabled || len(refs[m.ID]) == 0 {
			continue
		}
		if !modelAllowedForToken(token, m.ModelID) {
			continue
		}
		if !uv.IsStaff() && !services.ModelAllowedForGroups(m, uv.GroupIDs, false) {
			continue
		}
		// created is 0 for every entry, matching the Python contract: the field
		// exists for OpenAI-client compatibility, not as model metadata, and a
		// per-model timestamp made clients treat the list as changing.
		push(gatewayModelItem(m.ModelID, 0, m, nil, mdIndex))
	}

	// Passthrough models are callable as "<provider-slug>/<exposed-id>" but have
	// no route of their own, so they are enumerated from the providers and gated
	// exactly like a regular model.
	for _, pt := range a.visiblePassthroughModels(token, uv) {
		push(gatewayModelItem(pt.id, 0, nil, pt.row, mdIndex))
	}
	return data, nil
}

func (a *App) chatCompletions(c *gin.Context) {
	a.relay(c, constants.ApiStyleOpenAI, services.KindChat)
}
func (a *App) messages(c *gin.Context) {
	a.relay(c, constants.ApiStyleAnthropic, services.KindMessages)
}
func (a *App) responses(c *gin.Context) {
	a.relay(c, constants.ApiStyleOpenAIResponses, services.KindResponses)
}

// relay is the shared gateway handler for all three inbound styles.
func (a *App) relay(c *gin.Context, inbound constants.ApiStyle, kind services.RelayKind) {
	token, user, ok := a.gatewayAuth(c)
	if !ok {
		return
	}
	bodyBytes, err := io.ReadAll(io.LimitReader(c.Request.Body, 32<<20))
	if err != nil {
		a.fail(c, http.StatusBadRequest, "Cannot read body.")
		return
	}
	var body map[string]any
	if err := json.Unmarshal(bodyBytes, &body); err != nil {
		a.fail(c, http.StatusBadRequest, "Invalid JSON body.")
		return
	}
	modelID, _ := body["model"].(string)
	if modelID == "" {
		a.fail(c, http.StatusBadRequest, "Missing model.")
		return
	}
	// A body in the wrong shape (messages as a string, tools as an object) would
	// only fail deep inside the translator — after the upstream has been called
	// and billed. Reject it up front instead.
	for _, field := range []string{"messages", "tools", "input"} {
		v, ok := body[field]
		if !ok || v == nil {
			continue
		}
		_, isList := v.([]any)
		_, isString := v.(string)
		valid := isList || (field == "input" && isString)
		if !valid {
			a.fail(c, http.StatusBadRequest, fmt.Sprintf("'%s' must be a list.", field))
			return
		}
	}
	// Gateway access gates: token allow-list, RPM, daily quota, model resolution,
	// role-group access, per-role-group call rate limit.
	uv := a.gatewayUserView(user)
	if aerr, _ := a.checkGatewayAccess(c, uv, token, modelID); aerr != nil {
		a.fail(c, aerr.Status, aerr.Msg)
		return
	}

	stream, _ := body["stream"].(bool)
	start := time.Now()
	sessionID := c.GetHeader(constants.SessionHeader)
	sessionKey := services.SessionKey(token.ID, sessionID, body)
	clientType := c.GetHeader(constants.ClientHintHeader)

	subPtr := user.Sub
	req := &services.DispatchRequest{
		Ctx: c.Request.Context(), DB: a.GDB, Cfg: a.Cfg, Pool: services.GetPool(),
		ExposedModel: modelID, InboundStyle: inbound, Stream: stream, Body: body,
		Kind: kind, TokenID: &token.ID, UserSub: &subPtr,
	}
	disp := services.NewDispatcher(req)
	res, err := disp.Do()
	if err != nil {
		msg := err.Error()
		// 543 is a VoidSwitch-specific "no upstream could serve this" code that
		// the OpenCode plugin renders as "Upstream Failed". Every other client
		// keeps the standard 502: SDKs and intermediaries are entitled to treat
		// an unfamiliar status as a protocol error.
		status := http.StatusBadGateway
		if clientType == constants.OpenCodeClientHint {
			status = constants.UpstreamUnavailable
		}
		a.logRequest(c, requestLogInfo{
			TokenID: token.ID, UserSub: user.Sub, Model: modelID, Upstream: modelID,
			Inbound: string(inbound), Stream: stream, Start: start, StatusCode: status,
			Success: false, Attempts: 0, Err: &msg, SessionKey: sessionKey, ClientType: clientType,
		})
		a.fail(c, status, msg)
		return
	}

	if res.Stream != nil {
		defer res.Stream.Close()
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		c.Header("Connection", "keep-alive")
		c.Status(http.StatusOK)

		flusher, _ := c.Writer.(http.Flusher)
		buf := make([]byte, 32*1024)
		for {
			n, rerr := res.Stream.Read(buf)
			if n > 0 {
				_, _ = c.Writer.Write(buf[:n])
				if flusher != nil {
					flusher.Flush()
				}
			}
			if rerr != nil {
				break
			}
		}
		// Wait for the usage tee to finalise, then persist the log.
		if res.UsageReady != nil {
			select {
			case <-res.UsageReady:
			case <-time.After(2 * time.Second):
			}
		}
		a.logRequest(c, requestLogInfo{
			TokenID: token.ID, UserSub: user.Sub, Model: modelID, Upstream: upstream(res),
			Inbound: string(inbound), Stream: true, Start: start,
			FirstToken: res.Usage.FirstTokenMs, Provider: providerName(res), KeyID: keyID(res),
			StatusCode: res.StatusCode, Success: true, Attempts: res.Attempts, Usage: res.Usage,
			SessionKey: sessionKey, ClientType: clientType,
		})
		return
	}

	c.Data(res.StatusCode, "application/json", res.Body)
	a.logRequest(c, requestLogInfo{
		TokenID: token.ID, UserSub: user.Sub, Model: modelID, Upstream: upstream(res),
		Inbound: string(inbound), Stream: false, Start: start,
		Provider: providerName(res), KeyID: keyID(res),
		StatusCode: res.StatusCode, Success: true, Attempts: res.Attempts, Usage: res.Usage,
		SessionKey: sessionKey, ClientType: clientType,
	})
}

func upstream(res *services.DispatchResult) string {
	if res.Upstream != "" {
		return res.Upstream
	}
	return ""
}

func providerName(res *services.DispatchResult) string {
	if res.Provider != nil {
		return res.Provider.Name
	}
	return ""
}

func keyID(res *services.DispatchResult) int {
	if res.Key != nil {
		return res.Key.ID
	}
	return 0
}

// RegisterGatewayRoutes wires the public /v1 gateway.
func RegisterGatewayRoutes(r *gin.RouterGroup, a *App) {
	r.GET("/models", a.gatewayModels)
	r.POST("/chat/completions", a.chatCompletions)
	r.POST("/messages", a.messages)
	r.POST("/responses", a.responses)
	r.POST("/models/sync", a.modelsSync)
}

// modelsSync returns the models the presenting Void-Token may call (OpenCode
// /sync-models), applying role-group access + the token allow-list.
func (a *App) modelsSync(c *gin.Context) {
	token, user, ok := a.gatewayAuth(c)
	if !ok {
		return
	}
	uv := a.gatewayUserView(user)
	// Count from the same enumeration /v1/models uses, so the picker and the
	// list can never disagree: a model with no reachable upstream is advertised
	// by neither, and passthrough ids are included by both.
	advertised, err := a.advertisedModels(token, uv)
	if err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"added":                  0,
		"total":                  len(advertised),
		"opencode_default_model": services.GetString("opencode_default_model", "claude-opus-4-8"),
		"opencode_small_model":   services.GetString("opencode_small_model", ""),
	})
}
