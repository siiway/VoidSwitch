package handlers

import (
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// logRequest persists a request_log row and updates the token counters plus the
// usage_daily / session_spans rollups. It is safe to call once per request.
func (a *App) logRequest(c *gin.Context, tokenID int, userSub string, model string,
	inbound, upstream string, stream bool, start time.Time, firstTokenMs *float64,
	providerName string, keyID int, statusCode int, success bool, attempts int,
	errMsg *string, usage services.Usage) {

	end := time.Now().UTC()
	latency := float64(end.Sub(start).Milliseconds())
	ip := clientIP(c)
	ua := c.Request.UserAgent()
	isOC := c.GetHeader(constants.ClientHintHeader) == constants.OpenCodeClientHint

	row := database.RequestLog{
		TS:               start.UTC(),
		StartedAt:        ptrTime(start.UTC()),
		FinishedAt:       ptrTime(end),
		FirstTokenMs:     firstTokenMs,
		ReqStatus:        strPtr(statusWord(success)),
		ClientIP:         strPtr(ip),
		TokenID:          &tokenID,
		UserSub:          &userSub,
		ProviderName:     strPtr(providerName),
		KeyID:            &keyID,
		Model:            strPtr(model),
		UpstreamModel:    strPtr(upstream),
		InboundStyle:     strPtr(inbound),
		UpstreamStyle:    strPtr(upstream),
		StatusCode:       &statusCode,
		Success:          success,
		LatencyMs:        &latency,
		PromptTokens:     usage.PromptTokens,
		CompletionTokens: usage.CompletionTokens,
		TotalTokens:      usage.TotalTokens,
		Stream:           stream,
		Attempts:         attempts,
		ProviderAttempts: attempts,
		NetworkAttempts:  1,
		Error:            errMsg,
		UserAgent:        strPtr(ua),
		IsOpenCode:       isOC,
		Debug:            false,
	}
	if err := a.GDB.Create(&row).Error; err != nil {
		return
	}
	a.bumpTokenUsage(tokenID, usage.TotalTokens)
	if success {
		a.rollupUsage(userSub, usage.TotalTokens)
	}
}

func (a *App) bumpTokenUsage(tokenID int, tokens int64) {
	now := time.Now().UTC()
	a.GDB.Model(&database.VoidToken{}).Where("id = ?", tokenID).Updates(map[string]any{
		"last_used_at":   now,
		"total_requests": gorm.Expr("total_requests + 1"),
		"total_tokens":   gorm.Expr("total_tokens + ?", tokens),
	})
}

// rollupUsage upserts the per-user/day usage_daily row (heatmap backing).
func (a *App) rollupUsage(userSub string, tokens int64) {
	day := time.Now().UTC().Format("2006-01-02")
	var row database.UsageDaily
	err := a.GDB.Where("user_sub = ? AND day = ?", userSub, day).First(&row).Error
	if err == gorm.ErrRecordNotFound {
		a.GDB.Create(&database.UsageDaily{
			UserSub: userSub, Day: day, Tokens: tokens, Requests: 1, UpdatedAt: time.Now().UTC(),
		})
		return
	} else if err != nil {
		return
	}
	a.GDB.Model(&row).Updates(map[string]any{
		"tokens":     gorm.Expr("tokens + ?", tokens),
		"requests":   gorm.Expr("requests + 1"),
		"updated_at": time.Now().UTC(),
	})
}

func ptrTime(t time.Time) *time.Time { return &t }

func statusWord(success bool) string {
	if success {
		return "completed"
	}
	return "error"
}
