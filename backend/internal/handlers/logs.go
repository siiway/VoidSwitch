package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

type requestLogView struct {
	ID                 int        `json:"id"`
	TS                 time.Time  `json:"ts"`
	StartedAt          *time.Time `json:"started_at"`
	FinishedAt         *time.Time `json:"finished_at"`
	FirstTokenMs       *float64   `json:"first_token_ms"`
	ReqStatus          *string    `json:"req_status"`
	ClientIP           *string    `json:"client_ip"`
	UserSub            *string    `json:"user_sub"`
	UserName           *string    `json:"user_name"`
	UserNickname       *string    `json:"user_nickname"`
	TokenID            *int       `json:"token_id"`
	TokenName          *string    `json:"token_name"`
	TokenOwnerName     *string    `json:"token_owner_name"`
	TokenOwnerNickname *string    `json:"token_owner_nickname"`
	ProviderName       *string    `json:"provider_name"`
	Model              *string    `json:"model"`
	UpstreamModel      *string    `json:"upstream_model"`
	InboundStyle       *string    `json:"inbound_style"`
	UpstreamStyle      *string    `json:"upstream_style"`
	StatusCode         *int       `json:"status_code"`
	Success            bool       `json:"success"`
	LatencyMs          *float64   `json:"latency_ms"`
	PromptTokens       int64      `json:"prompt_tokens"`
	CompletionTokens   int64      `json:"completion_tokens"`
	TotalTokens        int64      `json:"total_tokens"`
	Stream             bool       `json:"stream"`
	Attempts           int        `json:"attempts"`
	ProviderAttempts   int        `json:"provider_attempts"`
	NetworkAttempts    int        `json:"network_attempts"`
	Error              *string    `json:"error"`
	UserAgent          *string    `json:"user_agent"`
	ClientType         *string    `json:"client_type"`
	IsOpenCode         bool       `json:"is_opencode"`
	// OpenCodePlugin is "v1", "v2", or null when the plugin was not used.
	OpenCodePlugin *string `json:"opencode_plugin"`
	Debug          bool    `json:"debug"`
}

type requestLogDetailView struct {
	requestLogView
	KeyID           *int    `json:"key_id"`
	KeyPreview      *string `json:"key_preview"`
	ProxyID         *int    `json:"proxy_id"`
	ProxyURL        *string `json:"proxy_url"`
	UpstreamURL     *string `json:"upstream_url"`
	ReqMethod       *string `json:"req_method"`
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
	// Credential is the platform API key fingerprint that performed the action,
	// null when a browser session did.
	Credential *string `json:"credential"`
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
	q := a.requestLogScope(a.GDB.Model(&database.RequestLog{}), uv)
	if sub := c.Query("user_sub"); sub != "" {
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
	// client_ip is a substring match, so a prefix such as "10.0." narrows to a
	// subnet the way it does on every other text filter in the table.
	if ip := strings.TrimSpace(c.Query("client_ip")); ip != "" {
		// Escape LIKE's own metacharacters first, then translate the glob ones,
		// so a literal "%" in the input cannot match everything.
		escaped := strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(ip)
		pattern := "%" + escaped + "%"
		if strings.ContainsAny(ip, "*?") {
			pattern = strings.NewReplacer("*", "%", "?", "_").Replace(escaped)
		}
		q = q.Where(`client_ip LIKE ? ESCAPE '\'`, pattern)
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

// applyLogLabels fills the display fields of one row from the looked-up labels.
// The identifier formats ("name#id") match the usage breakdowns, so the same
// person or key reads the same way on both pages.
func applyLogLabels(v *requestLogView, r *database.RequestLog, labels requestLogLabels) {
	if r.UserSub != nil {
		if n, ok := labels.UserName[*r.UserSub]; ok {
			v.UserName = strPtr(n)
		}
		if n, ok := labels.UserNickname[*r.UserSub]; ok {
			v.UserNickname = strPtr(n)
		}
	}
	if r.TokenID != nil {
		if n, ok := labels.TokenName[*r.TokenID]; ok {
			v.TokenName = strPtr(n)
		}
		if n, ok := labels.TokenOwnerName[*r.TokenID]; ok {
			v.TokenOwnerName = strPtr(n)
		}
		if n, ok := labels.TokenOwnerNickname[*r.TokenID]; ok {
			v.TokenOwnerNickname = strPtr(n)
		}
	}
}

// requestLogLabels carries the human labels for a page of request logs.
type requestLogLabels struct {
	// UserName is "name#id", the same identifier the usage breakdowns use.
	UserName map[string]string
	// UserNickname is the display nickname, which can differ from the login name.
	UserNickname map[string]string
	// TokenName is "key name#id".
	TokenName map[int]string
	// TokenOwnerName/TokenOwnerNickname describe who owns the token.
	TokenOwnerName     map[int]string
	TokenOwnerNickname map[int]string
	// KeyPreview is the stored preview of a provider key.
	KeyPreview map[int]string
}

func (a *App) enrichRequestLogs(rows []database.RequestLog) requestLogLabels {
	subs := map[string]bool{}
	tids := map[int]bool{}
	kids := map[int]bool{}
	for i := range rows {
		if rows[i].UserSub != nil {
			subs[*rows[i].UserSub] = true
		}
		if rows[i].TokenID != nil {
			tids[*rows[i].TokenID] = true
		}
		if rows[i].KeyID != nil {
			kids[*rows[i].KeyID] = true
		}
	}
	labels := requestLogLabels{
		UserName: map[string]string{}, UserNickname: map[string]string{},
		TokenName: map[int]string{}, TokenOwnerName: map[int]string{},
		TokenOwnerNickname: map[int]string{}, KeyPreview: map[int]string{},
	}
	if len(subs) > 0 {
		keys := make([]string, 0, len(subs))
		for k := range subs {
			keys = append(keys, k)
		}
		var users []database.User
		a.GDB.Where("sub IN ?", keys).Find(&users)
		for i := range users {
			u := &users[i]
			labels.UserName[u.Sub] = fmt.Sprintf("%s#%d", displayUserName(u), u.ID)
			if u.Name != nil {
				labels.UserNickname[u.Sub] = *u.Name
			}
		}
	}
	if len(tids) > 0 {
		keys := make([]int, 0, len(tids))
		for k := range tids {
			keys = append(keys, k)
		}
		var tokens []database.VoidToken
		a.GDB.Select("id", "name", "user_id").Where("id IN ?", keys).Find(&tokens)
		ownerIDs := make([]int, 0, len(tokens))
		for i := range tokens {
			labels.TokenName[tokens[i].ID] = fmt.Sprintf("%s#%d", tokens[i].Name, tokens[i].ID)
			ownerIDs = append(ownerIDs, tokens[i].UserID)
		}
		if len(ownerIDs) > 0 {
			var owners []database.User
			a.GDB.Where("id IN ?", ownerIDs).Find(&owners)
			byID := map[int]*database.User{}
			for i := range owners {
				byID[owners[i].ID] = &owners[i]
			}
			for i := range tokens {
				u, ok := byID[tokens[i].UserID]
				if !ok {
					continue
				}
				labels.TokenOwnerName[tokens[i].ID] = fmt.Sprintf("%s#%d", displayUserName(u), u.ID)
				if u.Name != nil {
					labels.TokenOwnerNickname[tokens[i].ID] = *u.Name
				}
			}
		}
	}
	if len(kids) > 0 {
		keys := make([]int, 0, len(kids))
		for k := range kids {
			keys = append(keys, k)
		}
		var keys2 []database.ApiKey
		a.GDB.Select("id", "key_preview").Where("id IN ?", keys).Find(&keys2)
		for i := range keys2 {
			labels.KeyPreview[keys2[i].ID] = keys2[i].KeyPreview
		}
	}
	return labels
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
		ClientType: r.ClientType, IsOpenCode: r.IsOpenCode, OpenCodePlugin: r.OpenCodePlugin, Debug: r.Debug,
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
	labels := a.enrichRequestLogs(rows)

	items := make([]requestLogView, 0, len(rows))
	for i := range rows {
		v := toRequestLogView(&rows[i])
		applyLogLabels(&v, &rows[i], labels)
		items = append(items, v)
	}
	c.JSON(http.StatusOK, gin.H{
		"items": items, "total": total, "limit": limit, "offset": offset,
	})
}

// logViewerTier maps the caller to the access ladder the log policy uses.
func (a *App) logViewerTier(uv *core.UserView) string {
	switch {
	case uv.IsOwner():
		return services.LogAccessOwner
	case uv.IsStaff():
		return services.LogAccessAdmin
	case uv.IsRoleGroupAdmin():
		return services.LogAccessRoleGroupAdmin
	default:
		return services.LogAccessUser
	}
}

// rowLogLevel is the capture level of a stored row. Rows written before the policy
// existed carry 0 and are read as level 3, which is the detail they could hold.
func rowLogLevel(r *database.RequestLog) int {
	if r.LogLevel <= 0 {
		return services.LogLevelBodies
	}
	return services.ClampLogLevel(int(r.LogLevel))
}

// logVisibility is what one caller may see of one row.
type logVisibility struct {
	headers bool
	bodies  bool
}

// logVisibilityFor applies the level → access mapping: the row's level decides
// which groups it *holds*, and the mapping decides who may *read* each group.
func (a *App) logVisibilityFor(r *database.RequestLog, uv *core.UserView) logVisibility {
	level := rowLogLevel(r)
	viewer := services.LogAccessRank(a.logViewerTier(uv))
	out := logVisibility{}
	// Headers are part of levels 2 and 3 only; level 4 deliberately drops them.
	if level == services.LogLevelHeaders || level == services.LogLevelBodies {
		out.headers = viewer >= services.LogAccessRank(services.LogAccessTier(services.LogLevelHeaders))
	}
	switch level {
	case services.LogLevelBodies:
		out.bodies = viewer >= services.LogAccessRank(services.LogAccessTier(services.LogLevelBodies))
	case services.LogLevelError:
		// Level 4 keeps the response body (non-SSE) as its only body.
		out.bodies = viewer >= services.LogAccessRank(services.LogAccessTier(services.LogLevelError))
	}
	return out
}

// buildRequestLogDetail assembles the detail/export view for one row, applying
// the caller's visibility once. The detail endpoint and the download endpoint
// share it so they cannot drift apart.
func (a *App) buildRequestLogDetail(r *database.RequestLog, uv *core.UserView) requestLogDetailView {
	labels := a.enrichRequestLogs([]database.RequestLog{*r})
	v := requestLogDetailView{requestLogView: toRequestLogView(r)}
	applyLogLabels(&v.requestLogView, r, labels)
	v.ProxyID = r.ProxyID
	v.ReqMethod = r.ReqMethod

	vis := a.logVisibilityFor(r, uv)
	// The egress address (which can carry proxy credentials) travels with the
	// headers group: it is an operator detail, not a caller detail.
	if vis.headers {
		v.UpstreamURL = r.UpstreamURL
	}
	if uv.IsOwner() {
		v.ProxyURL = r.ProxyURL
	}

	// Provider key: the raw id/preview only for owners, a masked preview for
	// admins and role-group admins, and nothing for a member's own row.
	if r.KeyID != nil && (uv.IsStaff() || uv.IsRoleGroupAdmin()) {
		var k database.ApiKey
		if err := a.GDB.Select("id", "key_preview").First(&k, *r.KeyID).Error; err == nil {
			v.KeyID = r.KeyID
			if uv.IsOwner() {
				v.KeyPreview = strPtr(k.KeyPreview)
			} else {
				v.KeyPreview = strPtr(maskKeyPreview(k.KeyPreview))
			}
		}
	}

	v.AttemptsSummary = redactAttemptSummaries(jsonAny(r.AttemptsSummary))
	switch {
	case vis.bodies:
		v.DebugAttempts = jsonAny(r.DebugAttempts)
	case vis.headers:
		v.DebugAttempts = stripAttemptBodies(redactAttemptSummaries(jsonAny(r.DebugAttempts)))
	default:
		v.DebugAttempts = nil
	}
	if !uv.IsStaff() && !uv.IsRoleGroupAdmin() {
		// A member's own detail stays anonymous: the provider key identifies which
		// credential pool served the request, an operator concern.
		v.AttemptsSummary = stripAttemptKeys(v.AttemptsSummary)
	}
	return v
}

func (a *App) logsRequestDetail(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var r database.RequestLog
	if err := a.GDB.First(&r, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Request log not found.")
		return
	}
	if !a.requestLogVisible(uv, r.UserSub) {
		a.fail(c, http.StatusNotFound, "Request log not found.")
		return
	}
	c.JSON(http.StatusOK, a.buildRequestLogDetail(&r, uv))
}

// logsRequestDownload serves one request log as a downloadable JSON document.
// It reuses the detail view (and therefore the same visibility scope and
// owner-only sensitive fields), then hands it to the browser as an attachment.
func (a *App) logsRequestDownload(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var r database.RequestLog
	if err := a.GDB.First(&r, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Request log not found.")
		return
	}
	uv := core.GetUser(c)
	if !a.requestLogVisible(uv, r.UserSub) {
		a.fail(c, http.StatusNotFound, "Request log not found.")
		return
	}
	v := a.buildRequestLogDetail(&r, uv)

	payload := a.exportPayload(&v, uv, &r)
	c.Header("Content-Disposition", fmt.Sprintf(`attachment; filename="voidswitch-request-%d.json"`, r.ID))
	c.Header("Content-Type", "application/json; charset=utf-8")
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, payload)
}

// exportPayload builds the downloadable JSON. The detail view carries two
// projections of the failover trail (the always-on chain and the debug view);
// the export keeps a single `attempts` array — the most detailed projection the
// caller may see — then scrubs credentials, egress addresses and, for
// non-owners, bodies.
func (a *App) exportPayload(v *requestLogDetailView, uv *core.UserView, r *database.RequestLog) any {
	m, _ := toPlainMap(v).(map[string]any)
	if m == nil {
		m = map[string]any{}
	}
	attempts := m["debug_attempts"]
	if attempts == nil {
		attempts = m["attempts_summary"]
	}
	if attempts == nil {
		attempts = []any{}
	}
	delete(m, "attempts_summary")
	delete(m, "debug_attempts")
	m["attempts"] = attempts
	vis := a.logVisibilityFor(r, uv)
	return downloadSafe(m, vis.bodies, a.exportSecrets(r))
}

// exportSecrets collects the values a request-log export must scrub anywhere
// they appear: the proxy's credentials/address, including inside error text. The
// provider key never reaches the row — request headers are redacted at capture
// time and upstream error text is scrubbed before it is stored.
func (a *App) exportSecrets(r *database.RequestLog) map[string]string {
	secrets := map[string]string{}
	if r.ProxyURL != nil && *r.ProxyURL != "" {
		secrets[*r.ProxyURL] = "<REDACTED:proxy>"
		if parsed, err := url.Parse(*r.ProxyURL); err == nil && parsed.Host != "" {
			secrets[parsed.Host] = "<REDACTED:proxy>"
		}
	}
	if r.ProxyID != nil {
		var node database.Node
		if err := a.GDB.First(&node, *r.ProxyID).Error; err == nil && node.URL != "" {
			secrets[node.URL] = "<REDACTED:local-address>"
			if parsed, err := url.Parse(node.URL); err == nil && parsed.Host != "" {
				secrets[parsed.Host] = "<REDACTED:local-address>"
			}
		}
	}
	return secrets
}

// toPlainMap round-trips the view through JSON so downloadSafe sees the same
// generic shape the client will (plain maps/slices, no struct tags or pointers).
func toPlainMap(v any) any {
	raw, err := json.Marshal(v)
	if err != nil {
		return map[string]any{}
	}
	var out any
	if err := json.Unmarshal(raw, &out); err != nil {
		return map[string]any{}
	}
	return out
}

func (a *App) logsRequestFilters(c *gin.Context) {
	uv := core.GetUser(c)
	base := a.requestLogScope(a.GDB.Model(&database.RequestLog{}), uv)

	var models []string
	base.Session(&gorm.Session{}).Where("model IS NOT NULL AND model <> ''").
		Distinct().Order("model").Pluck("model", &models)
	if models == nil {
		models = []string{}
	}

	var providers []string
	base.Session(&gorm.Session{}).Where("provider_name IS NOT NULL AND provider_name <> ''").
		Distinct().Order("provider_name").Pluck("provider_name", &providers)
	if providers == nil {
		providers = []string{}
	}

	var subs []string
	base.Session(&gorm.Session{}).Where("user_sub IS NOT NULL AND user_sub <> ''").
		Distinct().Pluck("user_sub", &subs)
	sort.Strings(subs)
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
				name = fmt.Sprintf("%s#%d", displayUserName(u), u.ID)
			}
			users = append(users, gin.H{"sub": s, "name": name})
		}
		sort.SliceStable(users, func(i, j int) bool {
			return toStr(users[i]["name"]) < toStr(users[j]["name"])
		})
	}

	// The token filter needs the tokens appearing in the caller's visible
	// traffic plus their owner, otherwise the dropdown stays empty and a member
	// cannot narrow the table to one key.
	var tokenIDs []int
	base.Session(&gorm.Session{}).Where("token_id IS NOT NULL").
		Distinct().Pluck("token_id", &tokenIDs)
	tokens := make([]gin.H, 0, len(tokenIDs))
	if len(tokenIDs) > 0 {
		var tokenRows []database.VoidToken
		a.GDB.Select("id", "name", "user_id").Where("id IN ?", tokenIDs).Find(&tokenRows)
		ownerIDs := make([]int, 0, len(tokenRows))
		for i := range tokenRows {
			ownerIDs = append(ownerIDs, tokenRows[i].UserID)
		}
		ownerName := map[int]string{}
		ownerSub := map[int]string{}
		if len(ownerIDs) > 0 {
			var owners []database.User
			a.GDB.Where("id IN ?", ownerIDs).Find(&owners)
			for i := range owners {
				ownerName[owners[i].ID] = fmt.Sprintf("%s#%d",
					displayUserName(&owners[i]), owners[i].ID)
				ownerSub[owners[i].ID] = owners[i].Sub
			}
		}
		for i := range tokenRows {
			tok := &tokenRows[i]
			tokens = append(tokens, gin.H{
				"id":        tok.ID,
				"name":      fmt.Sprintf("%s#%d", tok.Name, tok.ID),
				"user_sub":  ownerSub[tok.UserID],
				"user_name": ownerName[tok.UserID],
			})
		}
		sort.SliceStable(tokens, func(i, j int) bool {
			return toStr(tokens[i]["name"]) < toStr(tokens[j]["name"])
		})
	}

	c.JSON(http.StatusOK, gin.H{
		"models": models, "providers": providers, "users": users, "tokens": tokens,
	})
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
			q := a.requestLogScope(a.GDB.Model(&database.RequestLog{}).Where("id > ?", lastID), uv)
			if sub := c.Query("user_sub"); sub != "" {
				q = q.Where("user_sub = ?", sub)
			}
			if err := q.Order("id ASC").Limit(200).Find(&rows).Error; err != nil {
				continue
			}
			if len(rows) == 0 {
				continue
			}
			labels := a.enrichRequestLogs(rows)
			for i := range rows {
				lastID = rows[i].ID
				v := toRequestLogView(&rows[i])
				applyLogLabels(&v, &rows[i], labels)
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
	if uv.IsStaff() {
		if sub := c.Query("actor_sub"); sub != "" {
			q = q.Where("actor_sub = ?", sub)
		}
	} else {
		// A member always sees audit rows that concern them directly: rows they
		// acted in (actor_sub = me), rows targeting their user (target_type=user,
		// target_id=my id), and rows targeting their own resources (their
		// Void-Tokens: target_type=void_token, target_id=one of their token ids).
		// A role-group admin additionally sees rows targeting their managed
		// groups / those groups' members.
		myUserID := strconv.Itoa(uv.User.ID)
		tokenIDs := a.visibleTokenIDs(uv.User.ID)
		ownClauses := []string{"actor_sub = ?"}
		ownArgs := []any{uv.User.Sub}
		ownClauses = append(ownClauses, "(target_type = ? AND target_id = ?)")
		ownArgs = append(ownArgs, "user", myUserID)
		if len(tokenIDs) > 0 {
			ph := strings.TrimRight(strings.Repeat("?,", len(tokenIDs)), ",")
			ownClauses = append(ownClauses, "(target_type = ? AND target_id IN ("+ph+"))")
			ownArgs = append(ownArgs, "void_token")
			for _, id := range tokenIDs {
				ownArgs = append(ownArgs, strconv.Itoa(id))
			}
		}
		own := "(" + strings.Join(ownClauses, " OR ") + ")"
		q = q.Where(own, ownArgs...)

		if uv.IsRoleGroupAdmin() {
			userIDs := a.visibleUserIDs(uv.AdminGroupIDs)
			var extra []string
			var extraArgs []any
			if len(userIDs) > 0 {
				ids := make([]string, 0, len(userIDs))
				for _, id := range userIDs {
					ids = append(ids, strconv.Itoa(id))
				}
				ph := strings.TrimRight(strings.Repeat("?,", len(ids)), ",")
				extra = append(extra, "(target_type = ? AND target_id IN ("+ph+"))")
				extraArgs = append(extraArgs, "user")
				for _, id := range ids {
					extraArgs = append(extraArgs, id)
				}
			}
			groupIDs := make([]string, 0, len(uv.AdminGroupIDs))
			for _, id := range uv.AdminGroupIDs {
				groupIDs = append(groupIDs, strconv.Itoa(id))
			}
			if len(groupIDs) > 0 {
				ph := strings.TrimRight(strings.Repeat("?,", len(groupIDs)), ",")
				extra = append(extra, "(target_type = ? AND target_id IN ("+ph+"))")
				extraArgs = append(extraArgs, "role_group")
				for _, id := range groupIDs {
					extraArgs = append(extraArgs, id)
				}
			}
			if len(extra) > 0 {
				q = q.Where("("+strings.Join(extra, " OR ")+")", extraArgs...)
			}
		}
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
	if cred := c.Query("credential"); cred != "" {
		q = q.Where("credential = ?", cred)
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
		Credential: r.Credential,
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
	a.auditLogsQuery(c, uv).Distinct().Order("action").Pluck("action", &actions)
	if actions == nil {
		actions = []string{}
	}

	var scopes []string
	a.auditLogsQuery(c, uv).Distinct().Order("scope").Pluck("scope", &scopes)
	if scopes == nil {
		scopes = []string{}
	}

	var subs []string
	a.auditLogsQuery(c, uv).Where("actor_sub IS NOT NULL AND actor_sub <> ''").
		Distinct().Pluck("actor_sub", &subs)

	var targetTypes []string
	a.auditLogsQuery(c, uv).Where("target_type IS NOT NULL AND target_type <> ''").
		Distinct().Order("target_type").Pluck("target_type", &targetTypes)
	if targetTypes == nil {
		targetTypes = []string{}
	}

	// Credential identifies the platform API key that acted, so an operator can
	// narrow the table to one automation key.
	var credentials []string
	a.auditLogsQuery(c, uv).Where("credential IS NOT NULL AND credential <> ''").
		Distinct().Order("credential").Pluck("credential", &credentials)
	if credentials == nil {
		credentials = []string{}
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
		"credentials": credentials,
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
		a.fail(c, http.StatusNotFound, "No sensitive data for this entry.")
		return
	}
	plain, err := cryptoutil.DecryptSecret(*r.SensitiveCiphertext, a.Cfg.Server.SecretKey)
	if err != nil {
		// An unreadable ciphertext is a server-side problem (the secret key
		// changed), not a client mistake.
		a.internal(c, err)
		return
	}
	// Keep the stored JSON shape: a sensitive payload may be an array or a
	// scalar, and wrapping it in {"raw": …} would invent a structure.
	var out any
	if err := json.Unmarshal([]byte(plain), &out); err != nil {
		out = plain
	}

	// Who looked at a previously concealed payload is itself auditable.
	uv := core.GetUser(c)
	if uv != nil && uv.User != nil {
		sub := uv.User.Sub
		_ = a.audit(c, core.AuditInput{
			Action: "audit.reveal", ActorSub: &sub, ActorName: servicesName(uv),
			Scope: core.AuditScopeAdmin, TargetType: strPtr("audit"),
			TargetID: strPtr(strconv.Itoa(r.ID)),
			Detail: map[string]any{
				"revealed_action": r.Action, "revealed_actor": deref(r.ActorName),
			},
			IP: strPtr(clientIP(c)),
		})
	}
	c.JSON(http.StatusOK, gin.H{"id": r.ID, "action": r.Action, "sensitive": out})
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

// RegisterLogRoutes wires the log surface on the authenticated (member) group.
//
// Permission model (mirrors the Python backend):
//   - request logs  : any authenticated member, scoped to their own traffic;
//     role-group admins additionally see their groups' members;
//     staff see everything. The handlers enforce the WHERE scope.
//   - audit logs    : staff OR role-group admin (role-group admins see only
//     entries targeting their groups / members).
//   - audit reveal  : owner only.
func RegisterLogRoutes(authed *gin.RouterGroup, a *App) {
	// Request logs — members + everyone above.
	r := authed.Group("/logs/requests", core.RequireUser())
	r.GET("", a.logsRequestsList)
	r.GET("/filters", a.logsRequestFilters)
	r.GET("/locate", a.logsRequestLocate)
	r.GET("/stream", a.logsRequestStream)
	r.GET("/:id", a.logsRequestDetail)
	r.GET("/:id/download", a.logsRequestDownload)

	// Audit logs — any authenticated user, scoped by tier (member: own actor/target;
	// role-group admin: their groups' members/groups; staff: all). The handlers
	// apply the WHERE scope. Reveal stays owner-only.
	au := authed.Group("/logs/audit", core.RequireUser())
	au.GET("", a.logsAuditList)
	au.GET("/filters", a.logsAuditFilters)
	au.GET("/locate", a.logsAuditLocate)
	au.POST("/:id/reveal", core.RequireOwner(), a.logsAuditReveal)
}

// visibleUserIDs returns the user ids that are members of any of the given
// role groups (the audience a role-group admin may observe).
func (a *App) visibleUserIDs(groupIDs []int) []int {
	if len(groupIDs) == 0 {
		return nil
	}
	var ids []int
	a.GDB.Model(&database.RoleGroupMembership{}).
		Where("role_group_id IN ?", groupIDs).
		Distinct().Pluck("user_id", &ids)
	return ids
}

// visibleUserSubs returns the Prism subs of members of the given role groups.
func (a *App) visibleUserSubs(groupIDs []int) []string {
	ids := a.visibleUserIDs(groupIDs)
	if len(ids) == 0 {
		return nil
	}
	var subs []string
	a.GDB.Model(&database.User{}).Where("id IN ?", ids).Pluck("sub", &subs)
	return subs
}

// requestLogScope applies the member / role-group-admin / staff visibility rule:
// staff see everything; role-group admins see their own traffic plus that of
// members of their managed groups; everyone else sees only their own.
func (a *App) requestLogScope(q *gorm.DB, uv *core.UserView) *gorm.DB {
	if uv.IsStaff() {
		return q
	}
	subs := a.visibleUserSubs(uv.AdminGroupIDs)
	if len(subs) > 0 {
		own := append([]string{uv.User.Sub}, subs...)
		return q.Where("user_sub IN ?", own)
	}
	return q.Where("user_sub = ?", uv.User.Sub)
}

// requestLogVisible reports whether the caller may see a single request row.
func (a *App) requestLogVisible(uv *core.UserView, userSub *string) bool {
	if uv.IsStaff() {
		return true
	}
	if userSub == nil {
		return false
	}
	if *userSub == uv.User.Sub {
		return true
	}
	for _, s := range a.visibleUserSubs(uv.AdminGroupIDs) {
		if s == *userSub {
			return true
		}
	}
	return false
}

// visibleTokenIDs returns the ids of a user's (non-deleted) Void-Tokens, used to
// scope a member's audit view to actions on their own tokens.
func (a *App) visibleTokenIDs(userID int) []int {
	var ids []int
	a.GDB.Model(&database.VoidToken{}).
		Where("user_id = ? AND deleted = ?", userID, false).
		Pluck("id", &ids)
	return ids
}
