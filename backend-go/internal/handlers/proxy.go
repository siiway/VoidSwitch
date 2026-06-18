package handlers

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

const Version = "0.1.0"

func HandleRoot(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"name":    "VoidSwitch",
		"version": Version,
		"endpoints": []string{
			"/",
			"/healthz",
			"/v1/chat/completions",
			"/v1/messages",
			"/v1/models",
			"/v1/models/sync",
		},
	})
}

func HandleHealthz(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "ok",
		"version": Version,
	})
}

func HandleChatCompletions(c *gin.Context) {
	db := database.GetDatabase()

	authHeader := c.GetHeader("Authorization")
	xApiKey := c.GetHeader("X-API-Key")
	raw := extractBearer(authHeader)
	if raw == "" {
		raw = strings.TrimSpace(xApiKey)
	}
	if raw == "" {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": "Missing API key.",
				"type":    "auth_error",
				"code":    "auth_error",
			},
		})
		return
	}

	authed, err := core.AuthenticateVoidToken(db.DB, authHeader, xApiKey)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": fmt.Sprintf("Invalid API key: %v", err),
				"type":    "auth_error",
				"code":    "auth_error",
			},
		})
		return
	}

	var payload map[string]any
	if err := c.ShouldBindJSON(&payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{
				"message": "Invalid request body.",
				"type":    "invalid_request_error",
			},
		})
		return
	}

	stream := false
	if s, ok := payload["stream"]; ok {
		if b, ok := s.(bool); ok {
			stream = b
		}
	}

	model, _ := payload["model"].(string)
	userSub := authed.User.Sub

	req := &services.DispatchRequest{
		InboundStyle: constants.ApiStyleOpenAI,
		Model:        model,
		Payload:      payload,
		Stream:       stream,
		TokenID:      &authed.Token.ID,
		UserSub:      &userSub,
	}

	log.Printf("[proxy] chat/completions model=%s stream=%v token=%d user=%s",
		model, stream, authed.Token.ID, core.ActorDisplayName(authed.User))

	result, _ := services.Dispatch(req)

	if result.IsStream {
		writeSSE(c, result.StreamCh)
		return
	}

	c.Data(result.StatusCode, result.MediaType, result.Content)
}

func HandleMessages(c *gin.Context) {
	db := database.GetDatabase()

	authHeader := c.GetHeader("Authorization")
	xApiKey := c.GetHeader("X-API-Key")

	authed, err := core.AuthenticateVoidToken(db.DB, authHeader, xApiKey)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"type":    "authentication_error",
				"message": fmt.Sprintf("Invalid API key: %v", err),
			},
		})
		return
	}

	var payload map[string]any
	if err := c.ShouldBindJSON(&payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error": gin.H{
				"type":    "invalid_request_error",
				"message": "Invalid request body.",
			},
		})
		return
	}

	stream := false
	if s, ok := payload["stream"]; ok {
		if b, ok := s.(bool); ok {
			stream = b
		}
	}

	model, _ := payload["model"].(string)
	userSub := authed.User.Sub

	req := &services.DispatchRequest{
		InboundStyle: constants.ApiStyleAnthropic,
		Model:        model,
		Payload:      payload,
		Stream:       stream,
		TokenID:      &authed.Token.ID,
		UserSub:      &userSub,
	}

	log.Printf("[proxy] messages model=%s stream=%v token=%d user=%s",
		model, stream, authed.Token.ID, core.ActorDisplayName(authed.User))

	result, _ := services.Dispatch(req)

	if result.IsStream {
		writeSSE(c, result.StreamCh)
		return
	}

	c.Data(result.StatusCode, result.MediaType, result.Content)
}

func HandleModels(c *gin.Context) {
	db := database.GetDatabase()

	authHeader := c.GetHeader("Authorization")
	xApiKey := c.GetHeader("X-API-Key")

	_, err := core.AuthenticateVoidToken(db.DB, authHeader, xApiKey)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": fmt.Sprintf("Invalid API key: %v", err),
				"type":    "auth_error",
				"code":    "auth_error",
			},
		})
		return
	}

	catalog, err := services.BuildCatalog(db.DB)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": fmt.Sprintf("Failed to build catalog: %v", err),
				"type":    "internal_error",
			},
		})
		return
	}

	now := time.Now().Unix()

	models := make([]gin.H, 0, len(catalog))
	for _, m := range catalog {
		created := now
		if m.CreatedAt != nil {
			created = m.CreatedAt.Unix()
		}

		models = append(models, gin.H{
			"id":       m.ModelID,
			"object":   "model",
			"created":  created,
			"owned_by": "voidswitch",
		})
	}

	c.JSON(http.StatusOK, gin.H{
		"object": "list",
		"data":   models,
	})
}

func HandleModelsSync(c *gin.Context) {
	db := database.GetDatabase()

	authHeader := c.GetHeader("Authorization")
	xApiKey := c.GetHeader("X-API-Key")

	authed, err := core.AuthenticateVoidToken(db.DB, authHeader, xApiKey)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{
			"error": gin.H{
				"message": fmt.Sprintf("Invalid API key: %v", err),
				"type":    "auth_error",
				"code":    "auth_error",
			},
		})
		return
	}

	actorName := core.ActorDisplayName(authed.User)

	result, err := services.SyncCatalog(db.DB, &authed.User.ID, &actorName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": gin.H{
				"message": fmt.Sprintf("Failed to sync catalog: %v", err),
				"type":    "internal_error",
			},
		})
		return
	}

	log.Printf("[proxy] models/sync added=%d total=%d actor=%s", result.Added, result.Total, actorName)

	c.JSON(http.StatusOK, result)
}

func extractBearer(authorization string) string {
	if authorization == "" {
		return ""
	}
	parts := strings.SplitN(authorization, " ", 2)
	if len(parts) == 2 && strings.EqualFold(parts[0], "bearer") {
		return strings.TrimSpace(parts[1])
	}
	return strings.TrimSpace(authorization)
}

func writeSSE(c *gin.Context, ch <-chan []byte) {
	c.Writer.Header().Set("Content-Type", "text/event-stream")
	c.Writer.Header().Set("Cache-Control", "no-cache")
	c.Writer.Header().Set("Connection", "keep-alive")
	c.Writer.WriteHeader(http.StatusOK)

	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		return
	}

	for chunk := range ch {
		_, err := c.Writer.Write(chunk)
		if err != nil {
			return
		}
		flusher.Flush()
	}

	_, _ = io.WriteString(c.Writer, "data: [DONE]\n\n")
	flusher.Flush()
}

func RegisterProxyRoutes(router *gin.RouterGroup) {
	router.GET("/", HandleRoot)
	router.GET("/healthz", HandleHealthz)
	router.POST("/v1/chat/completions", HandleChatCompletions)
	router.POST("/v1/messages", HandleMessages)
	router.GET("/v1/models", HandleModels)
	router.POST("/v1/models/sync", HandleModelsSync)
}
