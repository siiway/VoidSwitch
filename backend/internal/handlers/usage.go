package handlers

import (
	"fmt"
	"math"
	"net/http"
	"strconv"
	"strings"
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

// usageWindow is the caller-requested time range. "All time" is represented by
// nil bounds rather than a fabricated 24h window: the Statistics page's "all"
// preset and the empty-range default must not silently become "last day".
type usageWindow struct {
	start *time.Time
	end   *time.Time
}

func (a *App) usageWindow(c *gin.Context) usageWindow {
	var w usageWindow
	if t, ok := parseTimeParam(c.Query("start")); ok {
		w.start = &t
	}
	if t, ok := parseTimeParam(c.Query("end")); ok {
		w.end = &t
	}
	return w
}

// apply adds the window predicate to a WHERE builder, so callers never inject a
// bound they were not given.
func (w usageWindow) apply(where string, args []any) (string, []any) {
	if w.start != nil {
		where += " AND ts >= ?"
		args = append(args, *w.start)
	}
	if w.end != nil {
		// Exclusive: the Statistics page's window end is "next day 00:00", so an
		// inclusive bound counted a record at exactly midnight in both adjacent
		// days.
		where += " AND ts < ?"
		args = append(args, *w.end)
	}
	return where, args
}

func (w usageWindow) bounded() bool { return w.start != nil || w.end != nil }

// usageScope resolves the traffic a caller may aggregate over.
//
//   - Staff: platform-wide, or one user via user_sub, or the union of members
//     of the requested group_ids (which for staff may be any group).
//   - Role-group admin: the union of their managed groups' members, narrowed to
//     one of them by group_ids; asking for a group they do not administer is a
//     403.
//   - Plain member: their own traffic.
//
// Returns an error status + message for the caller to fail with.
func (a *App) usageScope(c *gin.Context, uv *core.UserView) (subs []string, scoped bool, status int, msg string) {
	if sub := strings.TrimSpace(c.Query("user_sub")); sub != "" {
		if uv.IsStaff() {
			return []string{sub}, true, 0, ""
		}
		if sub == uv.User.Sub {
			return []string{sub}, true, 0, ""
		}
		return nil, true, http.StatusForbidden, "You may only read your own usage."
	}

	requested := parseIDQuery(c, "group_ids")
	staff := uv.IsStaff()
	managed := uv.AdminGroupIDs
	switch {
	case staff && len(requested) == 0:
		return nil, false, 0, ""
	case len(requested) == 0:
		if len(managed) == 0 {
			return []string{uv.User.Sub}, true, 0, ""
		}
		requested = managed
	default:
		if !staff {
			allowed := map[int]bool{}
			for _, id := range managed {
				allowed[id] = true
			}
			var outside []int
			for _, id := range requested {
				if !allowed[id] {
					outside = append(outside, id)
				}
			}
			if len(outside) > 0 {
				return nil, true, http.StatusForbidden,
					fmt.Sprintf("Not an admin of role group(s): %v.", outside)
			}
		}
	}

	members := a.GDB.Model(&database.RoleGroupMembership{}).
		Where("role_group_id IN ?", requested).Distinct().Select("user_id")
	var groupSubs []string
	a.GDB.Model(&database.User{}).Where("id IN (?)", members).Pluck("sub", &groupSubs)
	if len(groupSubs) == 0 {
		// A non-empty scope with no members must aggregate over nothing, not
		// fall back to the caller's own traffic.
		return []string{""}, true, 0, ""
	}
	return groupSubs, true, 0, ""
}

// parseIDQuery reads an id list from either repeated query params or a single
// comma-separated value.
func parseIDQuery(c *gin.Context, key string) []int {
	seen := map[int]bool{}
	var out []int
	for _, raw := range c.QueryArray(key) {
		for _, part := range strings.Split(raw, ",") {
			n, err := strconv.Atoi(strings.TrimSpace(part))
			if err != nil || seen[n] {
				continue
			}
			seen[n] = true
			out = append(out, n)
		}
	}
	return out
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

// autoGranularity picks a bucket size for the mode-B series, matching the
// thresholds the Python backend used.
func autoGranularity(start, end *time.Time) string {
	if start == nil || end == nil {
		return "year"
	}
	span := end.Sub(*start)
	switch {
	case span <= 48*time.Hour:
		return "hour"
	case span <= 95*24*time.Hour:
		return "day"
	case span <= 1150*24*time.Hour:
		return "month"
	default:
		return "year"
	}
}

// trailingLimits bounds the bucket count of an unbounded overview, one per
// granularity.
var trailingLimits = map[string]int{"hour": 48, "day": 30, "week": 12, "month": 12, "year": 5}

// periodExpr and periodTrunc map a granularity onto the PostgreSQL expressions
// that both label and group a bucket. They are constants, never user input.
func periodExpr(granularity string) (label, trunc string) {
	switch granularity {
	case "hour":
		return `to_char(date_trunc('hour', ts), 'YYYY-MM-DD HH24":00"')`, "date_trunc('hour', ts)"
	case "week":
		return `to_char(date_trunc('week', ts), 'IYYY-"W"IW')`, "date_trunc('week', ts)"
	case "month":
		return `to_char(date_trunc('month', ts), 'YYYY-MM')`, "date_trunc('month', ts)"
	case "year":
		return `to_char(date_trunc('year', ts), 'YYYY')`, "date_trunc('year', ts)"
	default:
		return `to_char(date_trunc('day', ts), 'YYYY-MM-DD')`, "date_trunc('day', ts)"
	}
}

// usageSeries returns one bucket series at the given granularity: the trailing N
// buckets when unbounded, or everything inside the window (capped) when bounded.
func (a *App) usageSeries(where string, args []any, w usageWindow, granularity string) []usageBucket {
	label, trunc := periodExpr(granularity)
	limit := 1000
	if !w.bounded() {
		limit = trailingLimits[granularity]
	}
	rows := []usageBucket{}
	a.GDB.Raw(`SELECT `+label+` AS period,
		COUNT(*) AS requests,
		COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END),0) AS success,
		COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
		COALESCE(SUM(completion_tokens),0) AS completion_tokens,
		COALESCE(SUM(total_tokens),0) AS total_tokens,
		AVG(first_token_ms) AS avg_first_token_ms
		FROM request_logs WHERE `+where+`
		GROUP BY `+trunc+` ORDER BY `+trunc+` DESC LIMIT ?`, append(args, limit)...).Scan(&rows)
	for i := range rows {
		rows[i].Failures = rows[i].Requests - rows[i].Success
		if rows[i].Failures < 0 {
			rows[i].Failures = 0
		}
	}
	// The query walks backwards to take the newest buckets; charts read
	// chronologically.
	for i, j := 0, len(rows)-1; i < j; i, j = i+1, j-1 {
		rows[i], rows[j] = rows[j], rows[i]
	}
	return rows
}

func (a *App) usageAnalytics(c *gin.Context) {
	uv := core.GetUser(c)
	w := a.usageWindow(c)
	subs, scoped, status, msg := a.usageScope(c, uv)
	if status != 0 {
		a.fail(c, status, msg)
		return
	}

	where := "1=1"
	args := []any{}
	if scoped {
		where += " AND user_sub IN ?"
		args = append(args, subs)
	}
	if m := c.Query("model"); m != "" {
		where += " AND model = ?"
		args = append(args, m)
	}
	if t := c.Query("token_id"); t != "" {
		where += " AND token_id = ?"
		args = append(args, mustAtoi(t))
	}
	// scopeWhere scopes by caller/model/token but deliberately excludes the
	// window: mode A's overview series spans all time regardless of the page's
	// selected range, exactly as the metric is defined.
	scopeWhere, scopeArgs := where, append([]any{}, args...)
	where, args = w.apply(where, args)

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
	// Latency and throughput come from the DB clock (finished_at - started_at),
	// the same expression the Logs page renders durations from. Rows written
	// before latency_ms existed still report a duration, and successful-only
	// averaging keeps a failed retry from dominating the figure.
	a.GDB.Raw(`SELECT
		AVG(first_token_ms) AS avg_first_token_ms,
		AVG(CASE WHEN success THEN EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000.0 END) AS avg_latency_ms,
		COALESCE(SUM(CASE WHEN stream THEN 1 ELSE 0 END),0) AS stream_requests,
		COALESCE(SUM(CASE WHEN stream THEN 0 ELSE 1 END),0) AS non_stream_requests
		FROM request_logs WHERE `+where, args...).Scan(&perf)
	var totalSeconds *float64
	a.GDB.Raw(`SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (finished_at - started_at))),0)
		FROM request_logs WHERE `+where, args...).Scan(&totalSeconds)
	if totals.Requests > 0 {
		perf.AvgTokensPerRequest =
			math.Round(float64(totals.TotalTokens)/float64(totals.Requests)*10) / 10
	}
	if totalSeconds != nil && *totalSeconds > 0 {
		secs := *totalSeconds
		tps := math.Round(float64(totals.TotalTokens)/secs*100) / 100
		perf.TokensPerSecond = &tps
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
	a.labelUsageGroups(byUser, byToken)

	var statuses []statusCount
	a.GDB.Raw(`SELECT status_code, COUNT(*) AS count FROM request_logs
		WHERE `+where+` AND status_code IS NOT NULL
		GROUP BY status_code ORDER BY status_code`, args...).Scan(&statuses)
	if statuses == nil {
		statuses = []statusCount{}
	}

	// Mode A is a trailing overview independent of the page window; mode B
	// returns one auto-sized series for the window; mode C returns the four
	// tabs clipped to the window. The response always carries the same keys so
	// the client can switch modes without a shape change.
	mode := strings.ToUpper(strings.TrimSpace(c.DefaultQuery("time_mode", "A")))
	daily, weekly, monthly, yearly := []usageBucket{}, []usageBucket{}, []usageBucket{}, []usageBucket{}
	var windowedSeries []usageBucket
	var windowedGranularity *string
	switch mode {
	case "B":
		g := autoGranularity(w.start, w.end)
		windowedGranularity = &g
		windowedSeries = a.usageSeries(where, args, w, g)
	case "C":
		daily = a.usageSeries(where, args, w, "day")
		weekly = a.usageSeries(where, args, w, "week")
		monthly = a.usageSeries(where, args, w, "month")
		yearly = a.usageSeries(where, args, w, "year")
	default:
		daily = a.usageSeries(scopeWhere, scopeArgs, usageWindow{}, "day")
		weekly = a.usageSeries(scopeWhere, scopeArgs, usageWindow{}, "week")
		monthly = a.usageSeries(scopeWhere, scopeArgs, usageWindow{}, "month")
		yearly = a.usageSeries(scopeWhere, scopeArgs, usageWindow{}, "year")
	}

	c.JSON(http.StatusOK, gin.H{
		"scope":                scope,
		"totals":               usageTotalsFromRow(&totals),
		"daily":                daily,
		"weekly":               weekly,
		"monthly":              monthly,
		"yearly":               yearly,
		"windowed_series":      windowedSeries,
		"windowed_granularity": windowedGranularity,
		"by_user":              byUser,
		"by_token":             byToken,
		"by_model":             byModel,
		"by_provider":          byProvider,
		"performance":          perf,
		"status_codes":         statuses,
	})
}

// labelUsageGroups replaces the raw grouping keys with human labels, the way the
// Python backend did: a user row shows "<name>#<id>" and a token row shows
// "<token name>#<id>" with its owner as the sublabel. Without this the
// Statistics breakdowns list bare subs and numeric ids.
func (a *App) labelUsageGroups(byUser, byToken []usageGroupRow) {
	if len(byUser) > 0 {
		subs := make([]string, 0, len(byUser))
		for i := range byUser {
			if byUser[i].Key != "" {
				subs = append(subs, byUser[i].Key)
			}
		}
		names := map[string]string{}
		if len(subs) > 0 {
			var users []database.User
			a.GDB.Where("sub IN ?", subs).Find(&users)
			for i := range users {
				names[users[i].Sub] = fmt.Sprintf("%s#%d", displayUserName(&users[i]), users[i].ID)
			}
		}
		for i := range byUser {
			if byUser[i].Key == "" {
				// Internal Claude Code token ops have no caller.
				byUser[i].Label = "<internal>"
				continue
			}
			if label, ok := names[byUser[i].Key]; ok {
				byUser[i].Label = label
			}
		}
	}

	if len(byToken) == 0 {
		return
	}
	ids := make([]int, 0, len(byToken))
	for i := range byToken {
		if id, err := strconv.Atoi(byToken[i].Key); err == nil {
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		for i := range byToken {
			byToken[i].Label = "<internal>"
		}
		return
	}
	var tokens []database.VoidToken
	a.GDB.Select("id", "name", "user_id").Where("id IN ?", ids).Find(&tokens)
	owners := make([]int, 0, len(tokens))
	names := map[int]string{}
	ownerOf := map[int]int{}
	for i := range tokens {
		names[tokens[i].ID] = tokens[i].Name
		ownerOf[tokens[i].ID] = tokens[i].UserID
		owners = append(owners, tokens[i].UserID)
	}
	ownerLabel := map[int]string{}
	if len(owners) > 0 {
		var users []database.User
		a.GDB.Where("id IN ?", owners).Find(&users)
		for i := range users {
			ownerLabel[users[i].ID] = fmt.Sprintf("%s#%d", displayUserName(&users[i]), users[i].ID)
		}
	}
	for i := range byToken {
		id, err := strconv.Atoi(byToken[i].Key)
		if err != nil {
			byToken[i].Label = "<internal>"
			continue
		}
		if name, ok := names[id]; ok {
			byToken[i].Label = fmt.Sprintf("%s#%d", name, id)
		} else {
			byToken[i].Label = fmt.Sprintf("#%d", id)
		}
		if owner, ok := ownerOf[id]; ok {
			if label, ok := ownerLabel[owner]; ok {
				byToken[i].Sublabel = &label
			}
		}
	}
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
