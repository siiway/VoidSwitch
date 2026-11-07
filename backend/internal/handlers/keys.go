package handlers

import (
	"encoding/json"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

type apiKeyView struct {
	ID             int        `json:"id"`
	ProviderID     int        `json:"provider_id"`
	KeyPreview     string     `json:"key_preview"`
	Pool           string     `json:"pool"`
	SortOrder      int        `json:"sort_order"`
	Status         string     `json:"status"`
	FailedCount    int        `json:"failed_count"`
	Weight         int        `json:"weight"`
	Note           *string    `json:"note"`
	Balance        any        `json:"balance"`
	DisabledReason *string    `json:"disabled_reason"`
	TotalRequests  int64      `json:"total_requests"`
	LastUsedAt     *time.Time `json:"last_used_at"`
	LastCheckedAt  *time.Time `json:"last_checked_at"`
	CreatedAt      time.Time  `json:"created_at"`
	DisabledSince  *time.Time `json:"disabled_since"`
	RateLimitUntil *time.Time `json:"rate_limit_until"`
	AddedBy        *int       `json:"added_by"`
	AddedByName    *string    `json:"added_by_name"`
}

func toApiKeyView(k *database.ApiKey) apiKeyView {
	var bal any
	if len(k.Balance) > 0 {
		_ = json.Unmarshal(k.Balance, &bal)
	}
	if bal == nil {
		bal = map[string]any{}
	}
	return apiKeyView{
		ID: k.ID, ProviderID: k.ProviderID, KeyPreview: k.KeyPreview, Pool: k.Pool,
		SortOrder: k.SortOrder, Status: k.Status, FailedCount: k.FailedCount,
		Weight: k.Weight, Note: k.Note, Balance: bal, DisabledReason: k.DisabledReason,
		TotalRequests: k.TotalRequests, LastUsedAt: k.LastUsedAt,
		LastCheckedAt: k.LastCheckedAt, CreatedAt: k.CreatedAt,
		DisabledSince: k.DisabledSince, RateLimitUntil: k.RateLimitUntil,
		AddedBy: k.AddedBy, AddedByName: k.AddedByName,
	}
}

func keyPreview(raw string) string {
	raw = strings.TrimSpace(raw)
	if len(raw) <= 10 {
		return raw[:min(2, len(raw))] + "***"
	}
	return raw[:4] + "…" + raw[len(raw)-4:]
}

func parseKeyLine(line string) (secret string, comment *string) {
	secret, after, found := strings.Cut(line, "#")
	if found {
		c := strings.TrimSpace(after)
		if c != "" {
			return strings.TrimSpace(secret), &c
		}
	}
	return strings.TrimSpace(secret), nil
}

func (a *App) keysList(c *gin.Context) {
	uv := core.GetUser(c)
	pid, _ := strconv.Atoi(c.Param("id"))
	q := a.GDB.Where("provider_id = ?", pid)
	if !uv.IsStaff() {
		q = q.Where("added_by = ?", uv.User.ID)
	}
	var keys []database.ApiKey
	if err := q.Order("sort_order, id").Find(&keys).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]apiKeyView, 0, len(keys))
	for i := range keys {
		out = append(out, toApiKeyView(&keys[i]))
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) keysCreate(c *gin.Context) {
	uv := core.GetUser(c)
	pid, _ := strconv.Atoi(c.Param("id"))
	var provider database.Provider
	if err := a.GDB.First(&provider, pid).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	var in struct {
		Keys   []string `json:"keys"`
		Pool   string   `json:"pool"`
		Weight *int     `json:"weight"`
		Note   *string  `json:"note"`
	}
	if err := c.ShouldBindJSON(&in); err != nil || len(in.Keys) == 0 {
		a.fail(c, http.StatusUnprocessableEntity, "keys are required.")
		return
	}
	var existing []string
	a.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", pid).Pluck("key_hash", &existing)
	seen := map[string]bool{}
	for _, h := range existing {
		seen[h] = true
	}
	var maxOrder *int
	a.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", pid).Select("MAX(sort_order)").Scan(&maxOrder)
	next := 1
	if maxOrder != nil {
		next = *maxOrder + 1
	}
	weight := 1
	if in.Weight != nil {
		weight = *in.Weight
	}
	created := make([]database.ApiKey, 0, len(in.Keys))
	for _, line := range in.Keys {
		raw, comment := parseKeyLine(line)
		if raw == "" {
			continue
		}
		hash := core.HashToken(raw)
		if seen[hash] {
			continue
		}
		seen[hash] = true
		ct, err := cryptoutil.EncryptSecret(raw, a.Cfg.Server.SecretKey)
		if err != nil {
			a.internal(c, err)
			return
		}
		note := comment
		if note == nil {
			note = in.Note
		}
		k := database.ApiKey{
			ProviderID: pid, KeyCiphertext: ct, KeyHash: hash, KeyPreview: keyPreview(raw),
			Pool: in.Pool, SortOrder: next, Status: string(constants.KeyStatusActive),
			Weight: weight, Note: note, AddedBy: &uv.User.ID,
			Balance: database.JSONOf(map[string]any{}),
		}
		next++
		created = append(created, k)
	}
	if len(created) == 0 {
		a.fail(c, http.StatusBadRequest, "No new keys to add.")
		return
	}
	if err := a.GDB.Create(&created).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, servicesName(uv)
	tid := strconv.Itoa(pid)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "key.add", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("provider"), TargetID: &tid,
		Detail: map[string]any{"provider_name": provider.Name, "added": len(created)},
		IP:     strPtr(clientIP(c)),
	})
	out := make([]apiKeyView, 0, len(created))
	for i := range created {
		out = append(out, toApiKeyView(&created[i]))
	}
	c.JSON(http.StatusCreated, out)
}

func (a *App) keysUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	pid, _ := strconv.Atoi(c.Param("id"))
	kid, _ := strconv.Atoi(c.Param("kid"))
	var k database.ApiKey
	if err := a.GDB.Where("id = ? AND provider_id = ?", kid, pid).First(&k).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Key not found.")
		return
	}
	if !uv.IsStaff() && (k.AddedBy == nil || *k.AddedBy != uv.User.ID) {
		a.fail(c, http.StatusForbidden, "You can only modify keys you added.")
		return
	}
	var in struct {
		Key     *string `json:"key"`
		Status  *string `json:"status"`
		Weight  *int    `json:"weight"`
		Note    *string `json:"note"`
		Pool    *string `json:"pool"`
		Enabled *bool   `json:"enabled"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Key != nil && *in.Key != "" {
		raw := strings.TrimSpace(*in.Key)
		hash := core.HashToken(raw)
		ct, err := cryptoutil.EncryptSecret(raw, a.Cfg.Server.SecretKey)
		if err != nil {
			a.internal(c, err)
			return
		}
		k.KeyCiphertext = ct
		k.KeyHash = hash
		k.KeyPreview = keyPreview(raw)
	}
	if in.Status != nil {
		k.Status = *in.Status
	}
	if in.Enabled != nil {
		if *in.Enabled {
			k.Status = string(constants.KeyStatusActive)
			k.DisabledReason = nil
		} else {
			k.Status = string(constants.KeyStatusDisabled)
		}
	}
	if in.Weight != nil {
		k.Weight = *in.Weight
	}
	if in.Note != nil {
		k.Note = in.Note
	}
	if in.Pool != nil {
		k.Pool = *in.Pool
	}
	if err := a.GDB.Save(&k).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, toApiKeyView(&k))
}

func (a *App) keysDelete(c *gin.Context) {
	pid, _ := strconv.Atoi(c.Param("id"))
	kid, _ := strconv.Atoi(c.Param("kid"))
	res := a.GDB.Where("id = ? AND provider_id = ?", kid, pid).Delete(&database.ApiKey{})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	if res.RowsAffected == 0 {
		a.fail(c, http.StatusNotFound, "Key not found.")
		return
	}
	c.Status(http.StatusNoContent)
}

func (a *App) keysReveal(c *gin.Context) {
	pid, _ := strconv.Atoi(c.Param("id"))
	kid, _ := strconv.Atoi(c.Param("kid"))
	var k database.ApiKey
	if err := a.GDB.Where("id = ? AND provider_id = ?", kid, pid).First(&k).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Key not found.")
		return
	}
	raw, err := cryptoutil.DecryptSecret(k.KeyCiphertext, a.Cfg.Server.SecretKey)
	if err != nil {
		a.fail(c, http.StatusBadRequest, "Stored credential could not be decrypted (secret key changed?).")
		return
	}
	c.JSON(http.StatusOK, gin.H{"preview": k.KeyPreview, "key": raw})
}

func (a *App) keysReorder(c *gin.Context) {
	uv := core.GetUser(c)
	if !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Only staff may reorder a provider's keys.")
		return
	}
	pid, _ := strconv.Atoi(c.Param("id"))
	var in struct {
		Order []int `json:"order"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	var keys []database.ApiKey
	if err := a.GDB.Where("provider_id = ?", pid).Find(&keys).Error; err != nil {
		a.internal(c, err)
		return
	}
	byID := map[int]*database.ApiKey{}
	for i := range keys {
		byID[keys[i].ID] = &keys[i]
	}
	var final []int
	seen := map[int]bool{}
	for _, id := range in.Order {
		if _, ok := byID[id]; ok && !seen[id] {
			seen[id] = true
			final = append(final, id)
		}
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].SortOrder != keys[j].SortOrder {
			return keys[i].SortOrder < keys[j].SortOrder
		}
		return keys[i].ID < keys[j].ID
	})
	for _, k := range keys {
		if !seen[k.ID] {
			final = append(final, k.ID)
		}
	}
	for idx, id := range final {
		a.GDB.Model(&database.ApiKey{}).Where("id = ?", id).Update("sort_order", idx)
	}
	var fresh []database.ApiKey
	a.GDB.Where("provider_id = ?", pid).Order("sort_order, id").Find(&fresh)
	out := make([]apiKeyView, 0, len(fresh))
	for i := range fresh {
		out = append(out, toApiKeyView(&fresh[i]))
	}
	c.JSON(http.StatusOK, out)
}

func (a *App) keysRefreshBalance(c *gin.Context) {
	pid, _ := strconv.Atoi(c.Param("id"))
	kid, _ := strconv.Atoi(c.Param("kid"))
	var provider database.Provider
	if err := a.GDB.First(&provider, pid).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	autoDisable := services.GetBool("auto_disable_zero_balance", true)
	poolFilter := c.Query("pool")
	hasPool := c.Request.URL.Query().Has("pool")

	q := a.GDB.Where("provider_id = ?", pid)
	if kid > 0 {
		q = q.Where("id = ?", kid)
	}
	if hasPool {
		q = q.Where("pool = ?", poolFilter)
	}
	var keys []database.ApiKey
	q.Find(&keys)
	for i := range keys {
		services.RefreshKeyBalance(a.GDB, &keys[i], &provider, a.Cfg.Server.SecretKey, autoDisable)
	}
	c.JSON(http.StatusOK, gin.H{"checked": len(keys)})
}

func (a *App) keysRefreshToken(c *gin.Context) {
	pid, _ := strconv.Atoi(c.Param("id"))
	kid, _ := strconv.Atoi(c.Param("kid"))
	var k database.ApiKey
	if err := a.GDB.Where("id = ? AND provider_id = ?", kid, pid).First(&k).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Key not found.")
		return
	}
	if err := services.RefreshKeyToken(a.GDB, &k, a.Cfg.Server.SecretKey); err != nil {
		a.fail(c, http.StatusBadRequest, err.Error())
		return
	}
	a.GDB.Model(&k).Updates(map[string]any{
		"status": string(constants.KeyStatusActive), "failed_count": 0,
		"disabled_reason": nil, "last_checked_at": time.Now().UTC(),
	})
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

// keysOAuthStart begins an interactive OAuth login for a key.
func (a *App) keysOAuthStart(c *gin.Context) {
	pid, _ := strconv.Atoi(c.Param("id"))
	url, state := services.BeginOAuthLogin(pid)
	c.JSON(http.StatusOK, gin.H{"authorize_url": url, "state": state})
}

// keysOAuthComplete finishes the interactive login and adds the key.
func (a *App) keysOAuthComplete(c *gin.Context) {
	uv := core.GetUser(c)
	pid, _ := strconv.Atoi(c.Param("id"))
	var in struct {
		Code  string  `json:"code"`
		State string  `json:"state"`
		Note  *string `json:"note"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	bundle, err := services.CompleteOAuthLogin(in.Code, in.State, pid, a.GDB)
	if err != nil {
		a.fail(c, http.StatusBadRequest, err.Error())
		return
	}
	raw, _ := json.Marshal(bundle)
	ct, err := cryptoutil.EncryptSecret(string(raw), a.Cfg.Server.SecretKey)
	if err != nil {
		a.internal(c, err)
		return
	}
	preview := "oauth·" + keyPreview(string(raw))
	if len(preview) > 48 {
		preview = preview[:48]
	}
	var maxOrder *int
	a.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", pid).Select("MAX(sort_order)").Scan(&maxOrder)
	next := 1
	if maxOrder != nil {
		next = *maxOrder + 1
	}
	k := database.ApiKey{
		ProviderID: pid, KeyCiphertext: ct, KeyHash: core.HashToken(string(raw)), KeyPreview: preview,
		SortOrder: next, Status: string(constants.KeyStatusActive), Weight: 1, Note: in.Note,
		AddedBy: &uv.User.ID, Balance: database.JSONOf(map[string]any{}),
	}
	if err := a.GDB.Create(&k).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusCreated, toApiKeyView(&k))
}

// keysOAuthDeviceStart / Complete report device flow as unsupported here.
func (a *App) keysOAuthDeviceStart(c *gin.Context) {
	a.fail(c, http.StatusNotImplemented, "device flow is not supported for this provider")
}
func (a *App) keysOAuthDeviceComplete(c *gin.Context) {
	a.fail(c, http.StatusNotImplemented, "device flow is not supported for this provider")
}

func (a *App) keysCleanup(c *gin.Context) {
	pid, _ := strconv.Atoi(c.Param("id"))
	var in struct {
		Target  string `json:"target"`
		MinDays int    `json:"min_days"`
	}
	_ = c.ShouldBindJSON(&in)
	q := a.GDB.Where("provider_id = ?", pid)
	if in.Target == "invalid" {
		q = q.Where("status = ?", string(constants.KeyStatusInvalid))
	} else {
		q = q.Where("status = ?", string(constants.KeyStatusInsufficientBalance))
		if in.MinDays > 0 {
			cutoff := time.Now().UTC().AddDate(0, 0, -in.MinDays)
			q = q.Where("disabled_since IS NOT NULL AND disabled_since < ?", cutoff)
		}
	}
	res := q.Delete(&database.ApiKey{})
	if res.Error != nil {
		a.internal(c, res.Error)
		return
	}
	c.JSON(http.StatusOK, gin.H{"deleted": res.RowsAffected})
}

func (a *App) keysImport(c *gin.Context) {
	// Phase 2: accept pasted sources and import plain api-key lines.
	pid, _ := strconv.Atoi(c.Param("id"))
	var in struct {
		Sources []string `json:"sources"`
		Pool    string   `json:"pool"`
		Note    *string  `json:"note"`
	}
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	var lines []string
	for _, src := range in.Sources {
		for _, ln := range strings.Split(src, "\n") {
			ln = strings.TrimSpace(ln)
			if ln != "" && !strings.HasPrefix(ln, "#") {
				lines = append(lines, ln)
			}
		}
	}
	if len(lines) == 0 {
		c.JSON(http.StatusOK, gin.H{"imported": 0, "duplicates": 0, "unusable": 0,
			"by_platform": map[string]int{}, "by_source": map[string]int{}, "skipped": []any{}, "keys": []any{}})
		return
	}
	// Reuse create logic by synthesising a request body.
	c.Set("_import_keys", lines)
	c.Set("_import_pool", in.Pool)
	a.importKeysDirect(c, pid, lines, in.Pool, in.Note)
}

// RegisterKeyRoutes wires /api/admin/providers/:id/keys/*.
func RegisterKeyRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/providers/:id/keys", a.keysList)
	g.POST("/providers/:id/keys", a.keysCreate)
	g.POST("/providers/:id/keys/reorder", a.keysReorder)
	g.POST("/providers/:id/keys/cleanup", a.keysCleanup)
	g.POST("/providers/:id/keys/import", a.keysImport)
	g.POST("/providers/:id/keys/refresh-balance", a.keysRefreshBalance)
	g.PATCH("/providers/:id/keys/:kid", a.keysUpdate)
	g.DELETE("/providers/:id/keys/:kid", a.keysDelete)
	g.POST("/providers/:id/keys/:kid/reveal", a.keysReveal)
	g.POST("/providers/:id/keys/:kid/refresh-balance", a.keysRefreshBalance)
	g.POST("/providers/:id/keys/:kid/refresh-token", a.keysRefreshToken)
	g.POST("/providers/:id/keys/oauth/start", a.keysOAuthStart)
	g.POST("/providers/:id/keys/oauth/complete", a.keysOAuthComplete)
	g.POST("/providers/:id/keys/oauth/device/start", a.keysOAuthDeviceStart)
	g.POST("/providers/:id/keys/oauth/device/complete", a.keysOAuthDeviceComplete)
}

func servicesName(uv *core.UserView) *string {
	if uv.User.Username != nil {
		return uv.User.Username
	}
	return uv.User.Name
}

// importKeysDirect adds keys from raw lines, returning the same shape as the
// create endpoint plus import stats.
func (a *App) importKeysDirect(c *gin.Context, pid int, lines []string, pool string, note *string) {
	uv := core.GetUser(c)
	var provider database.Provider
	if err := a.GDB.First(&provider, pid).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Provider not found.")
		return
	}
	var existing []string
	a.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", pid).Pluck("key_hash", &existing)
	seen := map[string]bool{}
	for _, h := range existing {
		seen[h] = true
	}
	var maxOrder *int
	a.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", pid).Select("MAX(sort_order)").Scan(&maxOrder)
	next := 1
	if maxOrder != nil {
		next = *maxOrder + 1
	}
	imported, duplicates, unusable := 0, 0, 0
	var created []database.ApiKey
	for _, line := range lines {
		raw, comment := parseKeyLine(line)
		if raw == "" {
			unusable++
			continue
		}
		hash := core.HashToken(raw)
		if seen[hash] {
			duplicates++
			continue
		}
		seen[hash] = true
		ct, err := cryptoutil.EncryptSecret(raw, a.Cfg.Server.SecretKey)
		if err != nil {
			unusable++
			continue
		}
		n := comment
		if n == nil {
			n = note
		}
		k := database.ApiKey{
			ProviderID: pid, KeyCiphertext: ct, KeyHash: hash, KeyPreview: keyPreview(raw),
			Pool: pool, SortOrder: next, Status: string(constants.KeyStatusActive), Weight: 1,
			Note: n, AddedBy: &uv.User.ID, Balance: database.JSONOf(map[string]any{}),
		}
		next++
		created = append(created, k)
		imported++
	}
	if len(created) > 0 {
		if err := a.GDB.Create(&created).Error; err != nil {
			a.internal(c, err)
			return
		}
	}
	views := make([]apiKeyView, 0, len(created))
	for i := range created {
		views = append(views, toApiKeyView(&created[i]))
	}
	c.JSON(http.StatusOK, gin.H{
		"imported": imported, "duplicates": duplicates, "unusable": unusable,
		"by_platform": map[string]int{}, "by_source": map[string]int{},
		"skipped": []any{}, "keys": views,
	})
}

// addKeysForProvider adds raw key lines to a provider (deduped) and returns the
// created key views. Used by the provider-key-management API.
func (a *App) addKeysForProvider(pid int, lines []string, pool string, note *string) []apiKeyView {
	var existing []string
	a.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", pid).Pluck("key_hash", &existing)
	seen := map[string]bool{}
	for _, h := range existing {
		seen[h] = true
	}
	var maxOrder *int
	a.GDB.Model(&database.ApiKey{}).Where("provider_id = ?", pid).Select("MAX(sort_order)").Scan(&maxOrder)
	next := 1
	if maxOrder != nil {
		next = *maxOrder + 1
	}
	var created []database.ApiKey
	for _, line := range lines {
		raw, comment := parseKeyLine(line)
		if raw == "" {
			continue
		}
		hash := core.HashToken(raw)
		if seen[hash] {
			continue
		}
		seen[hash] = true
		ct, err := cryptoutil.EncryptSecret(raw, a.Cfg.Server.SecretKey)
		if err != nil {
			continue
		}
		n := comment
		if n == nil {
			n = note
		}
		k := database.ApiKey{
			ProviderID: pid, KeyCiphertext: ct, KeyHash: hash, KeyPreview: keyPreview(raw),
			Pool: pool, SortOrder: next, Status: string(constants.KeyStatusActive), Weight: 1,
			Note: n, Balance: database.JSONOf(map[string]any{}),
		}
		next++
		created = append(created, k)
	}
	if len(created) > 0 {
		a.GDB.Create(&created)
	}
	out := make([]apiKeyView, 0, len(created))
	for i := range created {
		out = append(out, toApiKeyView(&created[i]))
	}
	return out
}
