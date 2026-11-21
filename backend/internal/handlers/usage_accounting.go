package handlers

import (
	"encoding/json"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

// requestLogInfo carries the context for one request-log write.
type requestLogInfo struct {
	TokenID       int
	UserSub       string
	Model         string
	Upstream      string
	Inbound       string
	UpstreamStyle string
	Stream        bool
	Start         time.Time
	FirstToken    *float64
	Provider      string
	KeyID         int
	StatusCode    int
	Success       bool
	Attempts      []*services.AttemptRecord
	Err           *string
	Usage         services.Usage
	SessionKey    string
	ClientType    string
	Debug         bool
}

func jsonRaw(v any) database.JSON {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	return database.JSON(raw)
}

// logRequest persists a request_log row and updates the token counters plus the
// usage_daily / session_spans rollups. Safe to call exactly once per request.
func (a *App) logRequest(c *gin.Context, info requestLogInfo) {
	userSub, model, upstream, inbound := info.UserSub, info.Model, info.Upstream, info.Inbound
	stream, start, firstTokenMs := info.Stream, info.Start, info.FirstToken
	providerName, keyID, statusCode, success := info.Provider, info.KeyID, info.StatusCode, info.Success
	errMsg, usage := info.Err, info.Usage
	tokenID := info.TokenID
	attempts := info.Attempts

	end := time.Now().UTC()
	// LatencyMs is the upstream *connect* time of the attempt that served (or
	// last tried) the request: DNS + TCP + TLS. The whole-request wall clock is
	// started_at → finished_at, which the UI renders as "duration"; keeping the
	// two separate stops the two columns from showing the same number.
	var latency float64
	if n := len(attempts); n > 0 {
		if c := attempts[n-1].ConnectMs; c != nil {
			latency = *c
		}
	}
	ip := clientIP(c)
	ua := c.Request.UserAgent()
	// The version distinguishes the V1 and V2 plugins; "" means no plugin.
	pluginVersion := opencodePluginVersion(c)

	// A failed dispatch passes no provider/key/upstream; fall back to the last
	// attempt in the trail so the row still shows what was tried.
	if len(attempts) > 0 {
		last := attempts[len(attempts)-1]
		if providerName == "" && last.Provider != nil {
			providerName = *last.Provider
		}
		if keyID == 0 && last.KeyID != nil {
			keyID = *last.KeyID
		}
		if upstream == "" && last.UpstreamModel != nil {
			upstream = *last.UpstreamModel
		}
	}

	// A streamed response's usage is only known once the downstream SSE drains;
	// stamp it on the winning (last) attempt so the per-attempt trail accounts
	// for the tokens that attempt produced.
	if info.Stream && usage.TotalTokens > 0 && len(attempts) > 0 {
		last := attempts[len(attempts)-1]
		if last.TotalTokens == 0 {
			last.PromptTokens = usage.PromptTokens
			last.CompletionTokens = usage.CompletionTokens
			last.TotalTokens = usage.TotalTokens
		}
	}

	chain := make([]services.AttemptRecord, 0, len(attempts))
	full := make([]services.AttemptRecord, 0, len(attempts))
	networkAttempts := 0
	for _, at := range attempts {
		chain = append(chain, at.Chain())
		full = append(full, at.Full())
		networkAttempts += len(at.NetworkAttempts)
	}
	if networkAttempts == 0 && len(attempts) > 0 {
		networkAttempts = 1
	}

	// The capture level decides what this row keeps. The settings map a source
	// (success / debug token / error) onto a level; level 1 stores only the
	// routing chain, 2 adds headers, 3 adds bodies, and 4 keeps just the non-SSE
	// response body plus the error message.
	level := services.CapturePolicyFromSettings().LevelFor(info.Debug, !success)
	debugData := level >= services.LogLevelHeaders

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
		UpstreamModel:    nullableStr(upstream),
		InboundStyle:     strPtr(inbound),
		UpstreamStyle:    nullableStr(info.UpstreamStyle),
		StatusCode:       &statusCode,
		Success:          success,
		LatencyMs:        &latency,
		PromptTokens:     usage.PromptTokens,
		CompletionTokens: usage.CompletionTokens,
		TotalTokens:      usage.TotalTokens,
		Stream:           stream,
		Attempts:         len(attempts),
		ProviderAttempts: len(attempts),
		NetworkAttempts:  networkAttempts,
		Error:            errMsg,
		UserAgent:        strPtr(ua),
		IsOpenCode:       pluginVersion != "",
		OpenCodePlugin:   nullableStr(pluginVersion),
		Debug:            debugData,
		LogLevel:         int16(level),
		ReqMethod:        strPtr("POST"),
	}
	if len(chain) > 0 {
		row.AttemptsSummary = jsonRaw(chain)
		if debugData {
			row.DebugAttempts = jsonRaw(full)
		}
		last := attempts[len(attempts)-1]
		row.UpstreamURL = last.URL
		row.ProxyURL = last.ProxyURL
		row.ProviderID = last.ProviderID
		if len(last.NetworkAttempts) > 0 {
			row.ProxyID = last.NetworkAttempts[0].NodeID
		}
	}
	if info.SessionKey != "" {
		row.SessionID = strPtr(info.SessionKey)
	}
	if info.ClientType != "" {
		row.ClientType = strPtr(info.ClientType)
	}
	if err := a.GDB.Create(&row).Error; err != nil {
		return
	}
	a.bumpTokenUsage(tokenID, usage.TotalTokens)
	if success {
		a.rollupUsage(userSub, usage.TotalTokens)
		a.rollupSession(userSub, info.SessionKey, start)
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

// rollupSession upserts the session_spans row for a conversation: started_at is
// pinned to the first request, last_at advances, requests accumulate.
func (a *App) rollupSession(userSub, sessionKey string, start time.Time) {
	if sessionKey == "" {
		return
	}
	now := time.Now().UTC()
	var span database.SessionSpan
	err := a.GDB.Where("session_key = ?", sessionKey).First(&span).Error
	if err == gorm.ErrRecordNotFound {
		a.GDB.Create(&database.SessionSpan{
			SessionKey: sessionKey, UserSub: userSub, StartedAt: start.UTC(),
			LastAt: now, Requests: 1, UpdatedAt: now,
		})
		return
	} else if err != nil {
		return
	}
	a.GDB.Model(&span).Updates(map[string]any{
		"last_at":    now,
		"requests":   gorm.Expr("requests + 1"),
		"updated_at": now,
	})
}
