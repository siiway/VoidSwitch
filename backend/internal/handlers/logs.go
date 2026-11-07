package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

type requestLogView struct {
	ID               int        `json:"id"`
	TS               time.Time  `json:"ts"`
	StartedAt        *time.Time `json:"started_at"`
	FinishedAt       *time.Time `json:"finished_at"`
	FirstTokenMs     *float64   `json:"first_token_ms"`
	ReqStatus        *string    `json:"req_status"`
	ClientIP         *string    `json:"client_ip"`
	UserSub          *string    `json:"user_sub"`
	UserName         *string    `json:"user_name"`
	TokenID          *int       `json:"token_id"`
	TokenName        *string    `json:"token_name"`
	ProviderName     *string    `json:"provider_name"`
	Model            *string    `json:"model"`
	UpstreamModel    *string    `json:"upstream_model"`
	InboundStyle     *string    `json:"inbound_style"`
	UpstreamStyle    *string    `json:"upstream_style"`
	StatusCode       *int       `json:"status_code"`
	Success          bool       `json:"success"`
	LatencyMs        *float64   `json:"latency_ms"`
	PromptTokens     int64      `json:"prompt_tokens"`
	CompletionTokens int64      `json:"completion_tokens"`
	TotalTokens      int64      `json:"total_tokens"`
	Stream           bool       `json:"stream"`
	Attempts         int        `json:"attempts"`
	ProviderAttempts int        `json:"provider_attempts"`
	NetworkAttempts  int        `json:"network_attempts"`
	Error            *string    `json:"error"`
	UserAgent        *string    `json:"user_agent"`
	ClientType       *string    `json:"client_type"`
	IsOpenCode       bool       `json:"is_opencode"`
	Debug            bool       `json:"debug"`
}

type requestLogDetailView struct {
	requestLogView
	KeyID           *int    `json:"key_id"`
	ProxyID         *int    `json:"proxy_id"`
	ProxyURL        *string `json:"proxy_url"`
	UpstreamURL     *string `json:"upstream_url"`
	ReqMethod       *string `json:"req_method"`
	ReqHeaders      any     `json:"req_headers"`
	ReqBody         any     `json:"req_body"`
	RespHeaders     any     `json:"resp_headers"`
	RespBody        any     `json:"resp_body"`
	DebugAttempts   any     `json:"debug_attempts"`
	AttemptsSummary any     `json:"attempts_summary"`
}

type auditLogView struct {
	ID           int             `json:"id"`
	TS           time.Time       `json:"ts"`
	ActorSub     *string         `json:"actor_sub"`
	ActorName    *string         `json:"actor_name"`
	Action       string          `json:"action"`
	Scope        string          `json:"scope"`
	TargetType   *string         `json:"target_type"`
	TargetID     *string         `json:"target_id"`
	Detail       json.RawMessage `json:"detail"`
	IP           *string         `json:"ip"`
	UserAgent    *string         `json:"user_agent"`
	HasSensitive bool            `json:"has_sensitive"`
}

func jsonAny(j database.JSON) any {
	if len(j) == 0 {
		return nil
	}
	var v any
	if err := json.Unmarshal(j, &v); err != nil {
		return nil
	}
	return v
}

func jsonObject(j database.JSON) json.RawMessage {
	if len(j) == 0 || string(j) == "null" {
		return json.RawMessage("{}")
	}
	return json.RawMessage(j)
}

func paginate(rawOffset, rawLimit, defLimit string) (int, int) {
	offset, _ := strconv.Atoi(rawOffset)
	limit, _ := strconv.Atoi(rawLimit)
	if limit <= 0 {
		limit = 50
		if defLimit != "" {
			if d, err := strconv.Atoi(defLimit); err == nil && d > 0 {
				limit = d
			}
		}
	}
	if limit > 500 {
		limit = 500
	}
	if offset < 0 {
		offset = 0
	}
	return offset, limit
}

func parseTimeParam(s string) (time.Time, bool) {
	if s == "" {
		return time.Time{}, false
	}
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t.UTC(), true
	}
	if t, err := time.Parse("2006-01-02", s); err == nil {
		return t.UTC(), true
	}
	return time.Time{}, false
}

func applyStatusFilter(q *gorm.DB, raw string) *gorm.DB {
	s := strings.TrimSpace(strings.ToLower(raw))
	if s == "" {
		return q
	}
	if len(s) == 3 && (s[1:] == "xx") && s[0] >= '1' && s[0] <= '5' {
		lo, _ := strconv.Atoi(string(s[0]) + "00")
		hi, _ := strconv.Atoi(string(s[0]) + "99")
		return q.Where("status_code BETWEEN ? AND ?", lo, hi)
	}
	m := statusRangeRe.FindStringSubmatch(s)
	if m == nil {
		return q
	}
	if m[3] == "" {
		return q.Where("status_code = ?", mustAtoi(m[1]))
	}
	lo, hi := mustAtoi(m[1]), mustAtoi(m[3])
	if lo > hi {
		lo, hi = hi, lo
	}
	return q.Where("status_code BETWEEN ? AND ?", lo, hi)
}

func mustAtoi(s string) int { n, _ := strconv.Atoi(s); return n }

func (a *App) requestLogsQuery(c *gin.Context, uv *core.UserView) *gorm.DB {
	q := a.GDB.Model(&database.RequestLog{})
	if !uv.IsStaff() {
		q = q.Where("user_sub = ?", uv.User.Sub)
	} else if sub := c.Query("user_sub"); sub != "" {
		q = q.Where("user_sub = ?", sub)
	}
	if m := c.Query("model"); m != "" {
		q = q.Where("model = ?", m)
	}
	if p := c.Query("provider"); p != "" {
		q = q.Where("provider_name = ?", p)
	}
	if t := c.Query("token_id"); t != "" {
		q = q.Where("token_id = ?", mustAtoi(t))
	}
	if ip := c.Query("client_ip"); ip != "" {
		q = q.Where("client_ip = ?", ip)
	}
	if rs := c.Query("req_status"); rs != "" {
		q = q.Where("req_status = ?", rs)
	}
	q = applyStatusFilter(q, c.Query("status_code"))
	q = applyStatusFilter(q, c.Query("status"))
	if v := c.Query("success"); v != "" {
		q = q.Where("success = ?", v == "true" || v == "1")
	}
	if v := c.Query("debug"); v != "" {
		q = q.Where("debug = ?", v == "true" || v == "1")
	}
	if t, ok := parseTimeParam(c.Query("start")); ok {
		q = q.Where("ts >= ?", t)
	}
	if t, ok := parseTimeParam(c.Query("end")); ok {
		q = q.Where("ts <= ?", t)
	}
	return q
}

func (a *App) enrichRequestLogs(rows []database.RequestLog) (map[string]string, map[int]string) {
	subs := map[string]bool{}
	tids := map[int]bool{}
	for i := range rows {
		if rows[i].UserSub != nil {
			subs[*rows[i].UserSub] = true
		}
		if rows[i].TokenID != nil {
			tids[*rows[i].TokenID] = true
		}
	}
	userNames := map[string]string{}
	if len(subs) > 0 {
		keys := make([]string, 0, len(subs))
		for k := range subs {
			keys = append(keys, k)
		}
		var users []database.User
		a.GDB.Where("sub IN ?", keys).Find(&users)
		for i := range users {
			userNames[users[i].Sub] = displayUserName(&users[i])
		}
	}
	tokenNames := map[int]string{}
	if len(tids) > 0 {
		keys := make([]int, 0, len(tids))
		for k := range tids {
			keys = append(keys, k)
		}
		var tokens []database.VoidToken
		a.GDB.Where("id IN ?", keys).Find(&tokens)
		for i := range tokens {
			tokenNames[tokens[i].ID] = tokens[i].Name
		}
	}
	return userNames, tokenNames
}

func displayUserName(u *database.User) string {
	if u.Username != nil && *u.Username != "" {
		return *u.Username
	}
	if u.Name != nil {
		return *u.Name
	}
	return u.Sub
}

func toRequestLogView(r *database.RequestLog) requestLogView {
	return requestLogView{
		ID: r.ID, TS: r.TS, StartedAt: r.StartedAt, FinishedAt: r.FinishedAt,
		FirstTokenMs: r.FirstTokenMs, ReqStatus: r.ReqStatus, ClientIP: r.ClientIP,
		UserSub: r.UserSub, TokenID: r.TokenID, ProviderName: r.ProviderName,
		Model: r.Model, UpstreamModel: r.UpstreamModel, InboundStyle: r.InboundStyle,
		UpstreamStyle: r.UpstreamStyle, StatusCode: r.StatusCode, Success: r.Success,
		LatencyMs: r.LatencyMs, PromptTokens: r.PromptTokens,
		CompletionTokens: r.CompletionTokens, TotalTokens: r.TotalTokens,
		Stream: r.Stream, Attempts: r.Attempts, ProviderAttempts: r.ProviderAttempts,
		NetworkAttempts: r.NetworkAttempts, Error: r.Error, UserAgent: r.UserAgent,
		ClientType: r.ClientType, IsOpenCode: r.IsOpenCode, Debug: r.Debug,
	}
}

func (a *App) logsRequestsList(c *gin.Context) {
	uv := core.GetUser(c)
	def := "50"
	if v, ok := a.settingInt("logs_page_size"); ok && v > 0 {
		def = strconv.Itoa(v)
	}
	offset, limit := paginate(c.Query("offset"), c.Query("limit"), def)

	q := a.requestLogsQuery(c, uv)
	var total int64
	if err := q.Count(&total).Error; err != nil {
		a.internal(c, err)
		return
	}

	dq := a.requestLogsQuery(c, uv)
	if b := c.Query("before_id"); b != "" {
		dq = dq.Where("id < ?", mustAtoi(b))
	}
	if af := c.Query("after_id"); af != "" {
		dq = dq.Where("id > ?", mustAtoi(af))
	}
	var rows []database.RequestLog
	if err := dq.Order("id DESC").Offset(offset).Limit(limit).Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	userNames, tokenNames := a.enrichRequestLogs(rows)

	items := make([]requestLogView, 0, len(rows))
	for i := range rows {
		v := toRequestLogView(&rows[i])
		if rows[i].UserSub != nil {
			if n, ok := userNames[*rows[i].UserSub]; ok {
				v.UserName = strPtr(n)
			}
		}
		if rows[i].TokenID != nil {
			if n, ok := tokenNames[*rows[i].TokenID]; ok {
				v.TokenName = strPtr(n)
			}
		}
		items = append(items, v)
	}
	c.JSON(http.StatusOK, gin.H{
		"items": items, "total": total, "limit": limit, "offset": offset,
	})
}

func (a *App) logsRequestDetail(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var r database.RequestLog
	if err := a.GDB.First(&r, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Request log not found.")
		return
	}
	if !uv.IsStaff() && (r.UserSub == nil || *r.UserSub != uv.User.Sub) {
		a.fail(c, http.StatusNotFound, "Request log not found.")
		return
	}

	userNames, tokenNames := a.enrichRequestLogs([]database.RequestLog{r})
	v := requestLogDetailView{requestLogView: toRequestLogView(&r)}
	if r.UserSub != nil {
		if n, ok := userNames[*r.UserSub]; ok {
			v.UserName = strPtr(n)
		}
	}
	if r.TokenID != nil {
		if n, ok := tokenNames[*r.TokenID]; ok {
			v.TokenName = strPtr(n)
		}
	}
	v.KeyID = r.KeyID
	v.ProxyID = r.ProxyID
	v.ProxyURL = r.ProxyURL
	v.UpstreamURL = r.UpstreamURL
	v.ReqMethod = r.ReqMethod
	if uv.IsOwner() {
		v.ReqHeaders = jsonAny(r.ReqHeaders)
		v.ReqBody = jsonAny(r.ReqBody)
		v.RespHeaders = jsonAny(r.RespHeaders)
		v.RespBody = jsonAny(r.RespBody)
	}
	v.DebugAttempts = jsonAny(r.DebugAttempts)
	v.AttemptsSummary = jsonAny(r.AttemptsSummary)
	c.JSON(http.StatusOK, v)
}

func (a *App) logsRequestFilters(c *gin.Context) {
	uv := core.GetUser(c)
	base := a.GDB.Model(&database.RequestLog{})
	if !uv.IsStaff() {
		base = base.Where("user_sub = ?", uv.User.Sub)
	}

	var models []string
	base.Session(&gorm.Session{}).Where("model IS NOT NULL AND model <> ''").
		Distinct().Order("model").Pluck("model", &models)
	if models == nil {
		models = []string{}
	}

	var providers []string
	a.GDB.Model(&database.RequestLog{}).Where("provider_name IS NOT NULL AND provider_name <> ''").
		Distinct().Order("provider_name").Pluck("provider_name", &providers)
	if providers == nil {
		providers = []string{}
	}

	var subs []string
	base.Session(&gorm.Session{}).Where("user_sub IS NOT NULL AND user_sub <> ''").
		Distinct().Pluck("user_sub", &subs)
	users := make([]gin.H, 0, len(subs))
	if len(subs) > 0 {
		var userRows []database.User
		a.GDB.Where("sub IN ?", subs).Find(&userRows)
		bySub := map[string]*database.User{}
		for i := range userRows {
			bySub[userRows[i].Sub] = &userRows[i]
		}
		for _, s := range subs {
			name := s
			if u, ok := bySub[s]; ok {
				name = displayUserName(u)
			}
			users = append(users, gin.H{"sub": s, "name": name})
		}
	}
	c.JSON(http.StatusOK, gin.H{"models": models, "providers": providers, "users": users})
}

func (a *App) logsRequestLocate(c *gin.Context) {
	uv := core.GetUser(c)
	id, err := strconv.Atoi(c.Query("id"))
	if err != nil || id <= 0 {
		c.JSON(http.StatusOK, gin.H{"offset": -1, "found": false})
		return
	}
	q := a.requestLogsQuery(c, uv)
	var exists int64
	if err := q.Session(&gorm.Session{}).Where("id = ?", id).Count(&exists).Error; err != nil {
		a.internal(c, err)
		return
	}
	if exists == 0 {
		c.JSON(http.StatusOK, gin.H{"offset": -1, "found": false})
		return
	}
	var newer int64
	cq := a.requestLogsQuery(c, uv)
	if err := cq.Where("id > ?", id).Count(&newer).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"offset": int(newer), "found": true})
}

func (a *App) logsRequestStream(c *gin.Context) {
	uv := core.GetUser(c)
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	lastID := mustAtoi(c.Query("after_id"))
	if lastID <= 0 {
		lastID = mustAtoi(c.DefaultQuery("afterId", "0"))
	}
	if lastID <= 0 {
		var maxID *int
		a.GDB.Model(&database.RequestLog{}).Select("MAX(id)").Scan(&maxID)
		if maxID != nil {
			lastID = *maxID
		}
	}

	flusher, _ := c.Writer.(http.Flusher)
	_, _ = fmt.Fprint(c.Writer, ": connected\n\n")
	if flusher != nil {
		flusher.Flush()
	}

	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	ctx := c.Request.Context()
	heartbeat := time.NewTicker(20 * time.Second)
	defer heartbeat.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-heartbeat.C:
			_, _ = fmt.Fprint(c.Writer, ": ping\n\n")
			if flusher != nil {
				flusher.Flush()
			}
		case <-ticker.C:
			var rows []database.RequestLog
			q := a.GDB.Model(&database.RequestLog{}).Where("id > ?", lastID)
			if !uv.IsStaff() {
				q = q.Where("user_sub = ?", uv.User.Sub)
			} else if sub := c.Query("user_sub"); sub != "" {
				q = q.Where("user_sub = ?", sub)
			}
			if err := q.Order("id ASC").Limit(200).Find(&rows).Error; err != nil {
				continue
			}
			if len(rows) == 0 {
				continue
			}
			userNames, tokenNames := a.enrichRequestLogs(rows)
			for i := range rows {
				lastID = rows[i].ID
				v := toRequestLogView(&rows[i])
				if rows[i].UserSub != nil {
					if n, ok := userNames[*rows[i].UserSub]; ok {
						v.UserName = strPtr(n)
					}
				}
				if rows[i].TokenID != nil {
					if n, ok := tokenNames[*rows[i].TokenID]; ok {
						v.TokenName = strPtr(n)
					}
				}
				payload, err := json.Marshal(v)
				if err != nil {
					continue
				}
				_, _ = fmt.Fprintf(c.Writer, "event: row\ndata: %s\n\n", payload)
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
	}
}

func (a *App) auditLogsQuery(c *gin.Context, uv *core.UserView) *gorm.DB {
	q := a.GDB.Model(&database.AuditLog{})
	if !uv.IsStaff() {
		q = q.Where("actor_sub = ?", uv.User.Sub)
	} else if sub := c.Query("actor_sub"); sub != "" {
		q = q.Where("actor_sub = ?", sub)
	}
	if act := c.Query("action"); act != "" {
		q = q.Where("action = ?", act)
	}
	if sc := c.Query("scope"); sc != "" {
		q = q.Where("scope = ?", sc)
	}
	if tt := c.Query("target_type"); tt != "" {
		q = q.Where("target_type = ?", tt)
	}
	if ip := c.Query("ip"); ip != "" {
		q = q.Where("ip = ?", ip)
	}
	if ua := c.Query("user_agent"); ua != "" {
		q = q.Where("user_agent LIKE ?", "%"+ua+"%")
	}
	if s, ok := parseTimeParam(c.Query("since")); ok {
		q = q.Where("ts >= ?", s)
	}
	if s, ok := parseTimeParam(c.Query("start")); ok {
		q = q.Where("ts >= ?", s)
	}
	if u, ok := parseTimeParam(c.Query("until")); ok {
		q = q.Where("ts <= ?", u)
	}
	if e, ok := parseTimeParam(c.Query("end")); ok {
		q = q.Where("ts <= ?", e)
	}
	return q
}

func toAuditLogView(r *database.AuditLog) auditLogView {
	return auditLogView{
		ID: r.ID, TS: r.TS, ActorSub: r.ActorSub, ActorName: r.ActorName,
		Action: r.Action, Scope: r.Scope, TargetType: r.TargetType,
		TargetID: r.TargetID, Detail: jsonObject(r.Detail), IP: r.IP,
		UserAgent: r.UserAgent, HasSensitive: r.SensitiveCiphertext != nil && *r.SensitiveCiphertext != "",
	}
}

func (a *App) logsAuditList(c *gin.Context) {
	uv := core.GetUser(c)
	offset, limit := paginate(c.Query("offset"), c.Query("limit"), "50")

	q := a.auditLogsQuery(c, uv)
	var total int64
	if err := q.Count(&total).Error; err != nil {
		a.internal(c, err)
		return
	}
	var rows []database.AuditLog
	if err := a.auditLogsQuery(c, uv).Order("id DESC").Offset(offset).Limit(limit).Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	items := make([]auditLogView, 0, len(rows))
	for i := range rows {
		items = append(items, toAuditLogView(&rows[i]))
	}
	c.JSON(http.StatusOK, gin.H{
		"items": items, "total": total, "limit": limit, "offset": offset,
	})
}

func (a *App) logsAuditFilters(c *gin.Context) {
	uv := core.GetUser(c)
	var actions []string
	q := a.GDB.Model(&database.AuditLog{})
	if !uv.IsStaff() {
		q = q.Where("actor_sub = ?", uv.User.Sub)
	}
	q.Distinct().Order("action").Pluck("action", &actions)
	if actions == nil {
		actions = []string{}
	}

	var scopes []string
	sq := a.GDB.Model(&database.AuditLog{})
	if !uv.IsStaff() {
		sq = sq.Where("actor_sub = ?", uv.User.Sub)
	}
	sq.Distinct().Order("scope").Pluck("scope", &scopes)
	if scopes == nil {
		scopes = []string{}
	}

	var subs []string
	aq := a.GDB.Model(&database.AuditLog{})
	if !uv.IsStaff() {
		aq = aq.Where("actor_sub = ?", uv.User.Sub)
	}
	aq.Where("actor_sub IS NOT NULL AND actor_sub <> ''").Distinct().Pluck("actor_sub", &subs)

	var targetTypes []string
	tq := a.GDB.Model(&database.AuditLog{})
	if !uv.IsStaff() {
		tq = tq.Where("actor_sub = ?", uv.User.Sub)
	}
	tq.Where("target_type IS NOT NULL AND target_type <> ''").Distinct().Order("target_type").Pluck("target_type", &targetTypes)
	if targetTypes == nil {
		targetTypes = []string{}
	}

	actors := make([]gin.H, 0, len(subs))
	if len(subs) > 0 {
		var userRows []database.User
		a.GDB.Where("sub IN ?", subs).Find(&userRows)
		bySub := map[string]*database.User{}
		for i := range userRows {
			bySub[userRows[i].Sub] = &userRows[i]
		}
		for _, s := range subs {
			name := s
			if u, ok := bySub[s]; ok {
				name = displayUserName(u)
			}
			actors = append(actors, gin.H{"sub": s, "name": name})
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"actions": actions, "scopes": scopes, "target_types": targetTypes, "actors": actors,
	})
}

func (a *App) logsAuditLocate(c *gin.Context) {
	uv := core.GetUser(c)
	id, err := strconv.Atoi(c.Query("id"))
	if err != nil || id <= 0 {
		c.JSON(http.StatusOK, gin.H{"offset": -1, "found": false})
		return
	}
	var exists int64
	if err := a.auditLogsQuery(c, uv).Where("id = ?", id).Count(&exists).Error; err != nil {
		a.internal(c, err)
		return
	}
	if exists == 0 {
		c.JSON(http.StatusOK, gin.H{"offset": -1, "found": false})
		return
	}
	var newer int64
	if err := a.auditLogsQuery(c, uv).Where("id > ?", id).Count(&newer).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"offset": int(newer), "found": true})
}

func (a *App) logsAuditReveal(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var r database.AuditLog
	if err := a.GDB.First(&r, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Audit log not found.")
		return
	}
	if r.SensitiveCiphertext == nil || *r.SensitiveCiphertext == "" {
		a.fail(c, http.StatusBadRequest, "No sensitive payload is stored for this entry.")
		return
	}
	plain, err := cryptoutil.DecryptSecret(*r.SensitiveCiphertext, a.Cfg.Server.SecretKey)
	if err != nil {
		a.fail(c, http.StatusBadRequest, "Stored payload could not be decrypted (secret key changed?).")
		return
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(plain), &out); err != nil || out == nil {
		out = map[string]any{"raw": plain}
	}
	c.JSON(http.StatusOK, gin.H{"action": r.Action, "sensitive": out})
}

func (a *App) settingInt(key string) (int, bool) {
	var s database.Setting
	if err := a.GDB.Where("key = ?", key).First(&s).Error; err != nil {
		return 0, false
	}
	var n int
	if err := json.Unmarshal(s.Value, &n); err != nil {
		return 0, false
	}
	return n, true
}

func RegisterLogRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/logs/requests", a.logsRequestsList)
	g.GET("/logs/requests/filters", a.logsRequestFilters)
	g.GET("/logs/requests/locate", a.logsRequestLocate)
	g.GET("/logs/requests/stream", a.logsRequestStream)
	g.GET("/logs/requests/:id", a.logsRequestDetail)
	g.GET("/logs/audit", a.logsAuditList)
	g.GET("/logs/audit/filters", a.logsAuditFilters)
	g.GET("/logs/audit/locate", a.logsAuditLocate)
	g.POST("/logs/audit/:id/reveal", core.RequireOwner(), a.logsAuditReveal)
}
