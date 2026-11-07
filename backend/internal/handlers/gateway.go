package handlers

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// gatewayAuth resolves the caller's Void-Token from the Authorization bearer and
// loads the owning user. Returns false (having written a 401) on failure.
func (a *App) gatewayAuth(c *gin.Context) (*database.VoidToken, *database.User, bool) {
	auth := c.GetHeader("Authorization")
	if !strings.HasPrefix(strings.ToLower(auth), "bearer ") {
		a.fail(c, http.StatusUnauthorized, "Missing bearer token.")
		return nil, nil, false
	}
	raw := strings.TrimSpace(auth[len("bearer "):])
	hash := core.HashToken(raw)
	var token database.VoidToken
	if err := a.GDB.Where("token_hash = ? AND deleted = ?", hash, false).First(&token).Error; err != nil {
		a.fail(c, http.StatusUnauthorized, "Invalid token.")
		return nil, nil, false
	}
	if !token.Enabled {
		a.fail(c, http.StatusForbidden, "Token disabled.")
		return nil, nil, false
	}
	var user database.User
	if err := a.GDB.Where("id = ?", token.UserID).First(&user).Error; err != nil || !user.Enabled {
		a.fail(c, http.StatusForbidden, "User disabled.")
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
	stream, _ := body["stream"].(bool)

	subPtr := user.Sub
	req := &services.DispatchRequest{
		Ctx: c.Request.Context(), DB: a.GDB, Cfg: a.Cfg, Pool: services.GetPool(),
		ExposedModel: modelID, InboundStyle: inbound, Stream: stream, Body: body,
		Kind: kind, TokenID: &token.ID, UserSub: &subPtr,
	}
	disp := services.NewDispatcher(req)
	res, err := disp.Do()
	if err != nil {
		a.fail(c, constants.UpstreamUnavailable, err.Error())
		return
	}

	if res.Stream != nil {
		defer res.Stream.Close()
		c.Header("Content-Type", "text/event-stream")
		c.Header("Cache-Control", "no-cache")
		c.Header("Connection", "keep-alive")
		c.Status(http.StatusOK)
		_, _ = io.Copy(c.Writer, res.Stream)
		return
	}

	c.Data(res.StatusCode, "application/json", res.Body)
}

// RegisterGatewayRoutes wires the public /v1 gateway.
func RegisterGatewayRoutes(r *gin.RouterGroup, a *App) {
	r.GET("/models", a.gatewayModels)
	r.POST("/chat/completions", a.chatCompletions)
	r.POST("/messages", a.messages)
	r.POST("/responses", a.responses)
}
