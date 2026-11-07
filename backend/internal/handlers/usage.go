package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
)

type usageTotals struct {
	Requests         int64 `json:"requests"`
	Success          int64 `json:"success"`
	Failures         int64 `json:"failures"`
	PromptTokens     int64 `json:"prompt_tokens"`
	CompletionTokens int64 `json:"completion_tokens"`
	TotalTokens      int64 `json:"total_tokens"`
}

type usageBucket struct {
	usageTotals
	Period          string   `json:"period"`
	AvgFirstTokenMs *float64 `json:"avg_first_token_ms"`
}

type usageGroupRow struct {
	usageTotals
	Key      string  `json:"key"`
	Label    string  `json:"label"`
	Sublabel *string `json:"sublabel"`
}

type usagePerformance struct {
	AvgFirstTokenMs     *float64 `json:"avg_first_token_ms"`
	AvgLatencyMs        *float64 `json:"avg_latency_ms"`
	AvgTokensPerRequest float64  `json:"avg_tokens_per_request"`
	TokensPerSecond     *float64 `json:"tokens_per_second"`
	StreamRequests      int64    `json:"stream_requests"`
	NonStreamRequests   int64    `json:"non_stream_requests"`
}

type statusCount struct {
	StatusCode int   `json:"status_code"`
	Count      int64 `json:"count"`
}

type heatmapDay struct {
	Date     string `json:"date"`
	Tokens   int64  `json:"tokens"`
	Requests int64  `json:"requests"`
}

type heatmapStats struct {
	CumulativeTokens   int64 `json:"cumulative_tokens"`
	PeakTokens         int64 `json:"peak_tokens"`
	LongestTaskSeconds int64 `json:"longest_task_seconds"`
	CurrentStreak      int64 `json:"current_streak"`
	LongestStreak      int64 `json:"longest_streak"`
	ActiveDays         int64 `json:"active_days"`
}

type heatmap struct {
	Scope         string       `json:"scope"`
	RetentionDays int          `json:"retention_days"`
	WindowDays    int          `json:"window_days"`
	Stats         heatmapStats `json:"stats"`
	Days          []heatmapDay `json:"days"`
	Label         *string      `json:"label"`
}

func (a *App) usageRange(c *gin.Context) (time.Time, time.Time, bool) {
	start, sok := parseTimeParam(c.Query("start"))
	end, eok := parseTimeParam(c.Query("end"))
	if !eok {
		end = time.Now().UTC()
	}
	if !sok {
		start = end.Add(-24 * time.Hour)
	}
	return start, end, sok && eok
}

func (a *App) usageScopeSub(c *gin.Context, uv *core.UserView) (string, bool) {
	if uv.IsStaff() {
		if sub := c.Query("user_sub"); sub != "" {
			return sub, true
		}
		return "", false
	}
	return uv.User.Sub, true
}

func usageTotalsFromRow(r *usageTotals) usageTotals {
	if r == nil {
		return usageTotals{}
	}
	t := *r
	t.Failures = t.Requests - t.Success
	if t.Failures < 0 {
		t.Failures = 0
	}
	return t
}

func (a *App) usageAnalytics(c *gin.Context) {
	uv := core.GetUser(c)
	start, end, _ := a.usageRange(c)
	sub, scoped := a.usageScopeSub(c, uv)

	where := "ts >= ? AND ts <= ?"
	args := []any{start, end}
	if scoped {
		where += " AND user_sub = ?"
		args = append(args, sub)
	}
	if m := c.Query("model"); m != "" {
		where += " AND model = ?"
		args = append(args, m)
	}
	if t := c.Query("token_id"); t != "" {
		where += " AND token_id = ?"
		args = append(args, mustAtoi(t))
	}

	scope := "all"
	if scoped {
		scope = "self"
	}

	var totals usageTotals
	a.GDB.Raw(`SELECT COUNT(*) AS requests,
		COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END),0) AS success,
		COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
		COALESCE(SUM(completion_tokens),0) AS completion_tokens,
		COALESCE(SUM(total_tokens),0) AS total_tokens
		FROM request_logs WHERE `+where, args...).Scan(&totals)

	var perf usagePerformance
	a.GDB.Raw(`SELECT
		AVG(first_token_ms) AS avg_first_token_ms,
		AVG(latency_ms) AS avg_latency_ms,
		COALESCE(SUM(CASE WHEN stream THEN 1 ELSE 0 END),0) AS stream_requests,
		COALESCE(SUM(CASE WHEN stream THEN 0 ELSE 1 END),0) AS non_stream_requests
		FROM request_logs WHERE `+where, args...).Scan(&perf)
	if totals.Requests > 0 {
		perf.AvgTokensPerRequest = float64(totals.TotalTokens) / float64(totals.Requests)
	}

	var buckets []usageBucket
	a.GDB.Raw(`SELECT to_char(date_trunc('day', ts), 'YYYY-MM-DD') AS period,
		COUNT(*) AS requests,
		COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END),0) AS success,
		COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
		COALESCE(SUM(completion_tokens),0) AS completion_tokens,
		COALESCE(SUM(total_tokens),0) AS total_tokens,
		AVG(first_token_ms) AS avg_first_token_ms
		FROM request_logs WHERE `+where+`
		GROUP BY date_trunc('day', ts) ORDER BY date_trunc('day', ts)`, args...).Scan(&buckets)
	if buckets == nil {
		buckets = []usageBucket{}
	}
	for i := range buckets {
		buckets[i].Failures = buckets[i].Requests - buckets[i].Success
		if buckets[i].Failures < 0 {
			buckets[i].Failures = 0
		}
	}

	groupQuery := func(col, labelCol string) []usageGroupRow {
		rows := []usageGroupRow{}
		a.GDB.Raw(`SELECT CAST(`+col+` AS text) AS key, `+labelCol+` AS label,
			COUNT(*) AS requests,
			COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END),0) AS success,
			COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
			COALESCE(SUM(completion_tokens),0) AS completion_tokens,
			COALESCE(SUM(total_tokens),0) AS total_tokens
			FROM request_logs WHERE `+where+` AND `+col+` IS NOT NULL
			GROUP BY `+col+` ORDER BY SUM(total_tokens) DESC LIMIT 500`, args...).Scan(&rows)
		for i := range rows {
			rows[i].Failures = rows[i].Requests - rows[i].Success
			if rows[i].Failures < 0 {
				rows[i].Failures = 0
			}
		}
		return rows
	}

	byUser := groupQuery("user_sub", "COALESCE(user_sub,'')")
	byToken := groupQuery("token_id", "COALESCE(CAST(token_id AS text),'')")
	byModel := groupQuery("model", "COALESCE(model,'')")
	byProvider := groupQuery("provider_name", "COALESCE(provider_name,'')")

	var statuses []statusCount
	a.GDB.Raw(`SELECT status_code, COUNT(*) AS count FROM request_logs
		WHERE `+where+` AND status_code IS NOT NULL
		GROUP BY status_code ORDER BY status_code`, args...).Scan(&statuses)
	if statuses == nil {
		statuses = []statusCount{}
	}

	c.JSON(http.StatusOK, gin.H{
		"scope":                scope,
		"totals":               usageTotalsFromRow(&totals),
		"daily":                buckets,
		"weekly":               []usageBucket{},
		"monthly":              []usageBucket{},
		"yearly":               []usageBucket{},
		"windowed_series":      nil,
		"windowed_granularity": nil,
		"by_user":              byUser,
		"by_token":             byToken,
		"by_model":             byModel,
		"by_provider":          byProvider,
		"performance":          perf,
		"status_codes":         statuses,
	})
}

func (a *App) heatmapRetention() int {
	if v, ok := a.settingInt("heatmap_retention_days"); ok && v > 0 {
		return v
	}
	return 365
}

func (a *App) buildHeatmap(scope string, sub string, label *string) heatmap {
	retention := a.heatmapRetention()
	since := time.Now().UTC().AddDate(0, 0, -(retention - 1)).Format("2006-01-02")

	q := a.GDB.Table("usage_daily").Where("day >= ?", since)
	if sub != "" {
		q = q.Where("user_sub = ?", sub)
	}
	var rows []struct {
		Day      string
		Tokens   int64
		Requests int64
	}
	q.Select("day, SUM(tokens) AS tokens, SUM(requests) AS requests").
		Group("day").Order("day").Scan(&rows)

	days := make([]heatmapDay, 0, len(rows))
	var stats heatmapStats
	var longest int64
	var prev time.Time
	for _, r := range rows {
		days = append(days, heatmapDay{Date: r.Day, Tokens: r.Tokens, Requests: r.Requests})
		stats.CumulativeTokens += r.Tokens
		stats.ActiveDays++
		if r.Tokens > stats.PeakTokens {
			stats.PeakTokens = r.Tokens
		}
		if d, err := time.Parse("2006-01-02", r.Day); err == nil {
			if !prev.IsZero() && d.Sub(prev) == 24*time.Hour {
				longest++
			} else {
				longest = 1
			}
			if longest > stats.LongestStreak {
				stats.LongestStreak = longest
			}
			prev = d
		}
	}
	if !prev.IsZero() {
		today := time.Now().UTC().Truncate(24 * time.Hour)
		if today.Sub(prev) <= 24*time.Hour {
			stats.CurrentStreak = longest
		}
	}

	return heatmap{
		Scope: scope, RetentionDays: retention, WindowDays: retention,
		Stats: stats, Days: days, Label: label,
	}
}

func (a *App) usageHeatmap(c *gin.Context) {
	uv := core.GetUser(c)
	personal := a.buildHeatmap("self", uv.User.Sub, nil)
	out := gin.H{"personal": personal, "site": nil}
	if uv.IsStaff() {
		site := a.buildHeatmap("site", "", nil)
		out["site"] = site
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) usageHeatmapUser(c *gin.Context) {
	uv := core.GetUser(c)
	sub := c.Query("sub")
	if !uv.IsStaff() {
		sub = uv.User.Sub
	}
	if sub == "" {
		a.fail(c, http.StatusBadRequest, "sub is required.")
		return
	}
	var label *string
	var u database.User
	if err := a.GDB.Where("sub = ?", sub).First(&u).Error; err == nil {
		label = strPtr(displayUserName(&u))
	}
	result := a.buildHeatmap("user", sub, label)
	c.JSON(http.StatusOK, result)
}

func RegisterUsageRoutes(authed *gin.RouterGroup, a *App) {
	authed.GET("/usage", a.usageAnalytics)
	authed.GET("/usage/heatmap", a.usageHeatmap)
	authed.GET("/usage/heatmap/user", a.usageHeatmapUser)
}
