package handlers

import (
	"encoding/json"
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

// visiblePassthroughIDs lists the passthrough model ids a caller may actually
// call: enabled providers whose passthrough is on, ids permitted by the token's
// allow-list, and ids the caller's role groups may reach. A passthrough id keeps
// its access control on an exposed-model row of the same id (created when an
// admin sets role groups on the model card); without one it is staff-only,
// matching a regular model with no groups selected.
func (a *App) visiblePassthroughIDs(token *database.VoidToken, uv *core.UserView) []string {
	var providers []database.Provider
	a.GDB.Where("enabled = ? AND passthrough_enabled = ?", true, true).Order("slug").Find(&providers)
	if len(providers) == 0 {
		return nil
	}

	// One query for the access rows of every candidate id keeps this off N+1.
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

	groupsByID := make(map[string][]int, len(candidates))
	rowIDByModel := make(map[string]int, len(candidates))
	routedIDs := make(map[int]bool, len(candidates))
	if len(candidates) > 0 {
		var rows []database.ExposedModel
		a.GDB.Select("id", "model_id", "allowed_role_group_ids").
			Where("model_id IN ?", candidates).Find(&rows)
		if len(rows) > 0 {
			ids := make([]int, 0, len(rows))
			for i := range rows {
				var groups []int
				database.DecodeJSON(rows[i].AllowedRoleGroupIDs, &groups)
				groupsByID[rows[i].ModelID] = groups
				rowIDByModel[rows[i].ModelID] = rows[i].ID
				ids = append(ids, rows[i].ID)
			}
			// An id that owns a route is an ordinary model: it is already listed
			// from the exposed catalog, so listing it here too would double it in
			// /v1/models/sync's count.
			var routeRows []database.Route
			a.GDB.Select("exposed_model_id").Where("exposed_model_id IN ?", ids).Find(&routeRows)
			for i := range routeRows {
				routedIDs[routeRows[i].ExposedModelID] = true
			}
		}
	}

	isStaff := uv.IsStaff()
	out := []string{}
	for pi := range perProvider {
		for _, id := range perProvider[pi] {
			if routedIDs[rowIDByModel[id]] {
				continue
			}
			if passthroughAllowedForGroups(groupsByID[id], uv.GroupIDs, isStaff) {
				out = append(out, id)
			}
		}
	}
	return out
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

	models, refs, err := a.loadModelsWithUpstreams()
	if err != nil {
		a.internal(c, err)
		return
	}
	data := make([]gin.H, 0, len(models))
	seen := make(map[string]bool, len(models))
	add := func(id string, created int64) {
		if id == "" || seen[id] {
			return
		}
		seen[id] = true
		data = append(data, gin.H{
			"id": id, "object": "model", "created": created, "owned_by": "voidswitch",
		})
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
		add(m.ModelID, m.CreatedAt.Unix())
	}

	// Passthrough models are callable as "<provider-slug>/<exposed-id>" but have
	// no exposed-model row of their own route, so they are enumerated from the
	// providers and gated exactly like a regular model.
	for _, id := range a.visiblePassthroughIDs(token, uv) {
		add(id, 0)
	}

	c.JSON(http.StatusOK, gin.H{"object": "list", "data": data})
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
		status := constants.UpstreamUnavailable
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
	var models []database.ExposedModel
	a.GDB.Where("enabled = ?", true).Order("model_id").Find(&models)
	count := 0
	for i := range models {
		m := &models[i]
		if !modelAllowedForToken(token, m.ModelID) {
			continue
		}
		if !uv.IsStaff() && !services.ModelAllowedForGroups(m, uv.GroupIDs, false) {
			continue
		}
		count++
	}
	// Passthrough models are callable too, so the sync count must include them;
	// otherwise the picker reports fewer models than /v1/models lists.
	count += len(a.visiblePassthroughIDs(token, uv))
	c.JSON(http.StatusOK, gin.H{
		"added":                  0,
		"total":                  count,
		"opencode_default_model": services.GetString("opencode_default_model", "claude-opus-4-8"),
		"opencode_small_model":   services.GetString("opencode_small_model", ""),
	})
}
