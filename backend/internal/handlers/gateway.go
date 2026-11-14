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

// gatewayModels returns the OpenAI-compatible model list.
func (a *App) gatewayModels(c *gin.Context) {
	models, refs, err := a.loadModelsWithUpstreams()
	if err != nil {
		a.internal(c, err)
		return
	}
	data := make([]gin.H, 0, len(models))
	for i := range models {
		m := &models[i]
		if !m.Enabled || len(refs[m.ID]) == 0 {
			continue
		}
		data = append(data, gin.H{
			"id": m.ModelID, "object": "model", "created": m.CreatedAt.Unix(),
			"owned_by": "voidswitch",
		})
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
	c.JSON(http.StatusOK, gin.H{
		"added":                  0,
		"total":                  count,
		"opencode_default_model": services.GetString("opencode_default_model", "claude-opus-4-8"),
		"opencode_small_model":   services.GetString("opencode_small_model", ""),
	})
}
