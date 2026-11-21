package handlers

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

var healthWindows = map[string]int{
	"30m": 1800, "1h": 3600, "3h": 10800, "12h": 43200,
	"1d": 86400, "3d": 259200, "7d": 604800,
}

// healthSnapshot returns {tab, models|nodes}.
func (a *App) healthSnapshot(c *gin.Context) {
	uv := core.GetUser(c)
	tab := c.DefaultQuery("tab", "models")
	window := c.DefaultQuery("window", "1d")
	if tab == "nodes" {
		if !uv.IsStaff() {
			a.fail(c, http.StatusForbidden, "Node health is staff-only.")
			return
		}
		c.JSON(http.StatusOK, gin.H{"tab": "nodes", "nodes": a.nodeHealth(window)})
		return
	}
	c.JSON(http.StatusOK, gin.H{"tab": "models", "models": a.modelHealth()})
}

// healthStream pushes snapshots over SSE (2s cadence).
func (a *App) healthStream(c *gin.Context) {
	uv := core.GetUser(c)
	tab := c.DefaultQuery("tab", "models")
	window := c.DefaultQuery("window", "1d")
	if tab == "nodes" && !uv.IsStaff() {
		a.fail(c, http.StatusForbidden, "Node health is staff-only.")
		return
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	flusher, _ := c.Writer.(http.Flusher)
	emit := func() {
		var payload gin.H
		if tab == "nodes" {
			payload = gin.H{"nodes": a.nodeHealth(window)}
		} else {
			payload = gin.H{"models": a.modelHealth()}
		}
		b, _ := jsonMarshal(payload)
		_, _ = c.Writer.Write([]byte("data: "))
		_, _ = c.Writer.Write(b)
		_, _ = c.Writer.Write([]byte("\n\n"))
		if flusher != nil {
			flusher.Flush()
		}
	}

	ctx := c.Request.Context()
	emit()
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			emit()
		}
	}
}

// modelHealth computes a per-exposed-model health summary from recent request
// logs (success rate, avg ttft) plus any active upstream cooldowns.
// recentHealthSamples is the number of most recent requests a health figure is
// computed over. It is clamped: a misconfigured 0 would sample nothing and make
// every model look like it is still learning.
func recentHealthSamples() int {
	n := services.GetInt("model_health_recent_request_count", 50)
	if n < 10 {
		return 10
	}
	if n > 500 {
		return 500
	}
	return n
}

func (a *App) modelHealth() []gin.H {
	recentCount := recentHealthSamples()
	since := time.Now().UTC().Add(-24 * time.Hour)
	var models []database.ExposedModel
	a.GDB.Where("enabled = ?", true).Order("model_id").Find(&models)
	out := make([]gin.H, 0, len(models))
	for i := range models {
		m := &models[i]
		var rows []database.RequestLog
		a.GDB.Where("model = ? AND ts >= ?", m.ModelID, since).
			Order("id DESC").Limit(recentCount).Find(&rows)
		var total, success int
		var ttftSum float64
		var ttftN int
		for j := range rows {
			total++
			if rows[j].Success {
				success++
			}
			if rows[j].FirstTokenMs != nil {
				ttftSum += *rows[j].FirstTokenMs
				ttftN++
			}
		}
		status := "learning"
		var rate *float64
		if total > 0 {
			r := float64(success) / float64(total)
			rate = &r
			switch {
			case r >= 0.9:
				status = "healthy"
			case r >= 0.5:
				status = "degraded"
			default:
				status = "unavailable"
			}
		}
		var ttft *float64
		if ttftN > 0 {
			avg := ttftSum / float64(ttftN)
			ttft = &avg
		}
		// Per-upstream health detail (route candidates + recent log stats + cooldowns).
		upstreams := a.modelUpstreamHealth(m.ModelID, since, recentCount)
		cooled := 0
		for _, u := range upstreams {
			if u["cooled_until"] != nil {
				cooled++
			}
		}
		if status == "healthy" && cooled > 0 {
			status = "degraded"
		}
		out = append(out, gin.H{
			"model_id":             m.ModelID,
			"status":               status,
			"recent_success_rate":  rate,
			"recent_request_count": total,
			"recent_avg_ttft_ms":   ttft,
			"sufficient_data":      total >= services.GetInt("upstream_min_samples", 10),
			"best_success_rate":    rate,
			"best_ttft_ms":         ttft,
			"upstreams":            upstreams,
			"recent_since":         recentSince(&rows),
		})
	}
	return out
}

// recentSince is the timestamp of the oldest sampled request, i.e. how far back
// the "recent" figures reach. The model card labels its line with it; without it
// the card's health block stayed hidden even when data existed.
func recentSince(rows *[]database.RequestLog) *time.Time {
	if len(*rows) == 0 {
		return nil
	}
	oldest := (*rows)[0].TS
	for i := 1; i < len(*rows); i++ {
		if (*rows)[i].TS.Before(oldest) {
			oldest = (*rows)[i].TS
		}
	}
	return &oldest
}

// modelHealthIndex computes the same per-model health the health tab shows, in
// one pass, so the model catalog can carry it without a query per model.
func (a *App) modelHealthIndex(now time.Time) map[string]gin.H {
	recentCount := recentHealthSamples()
	since := now.Add(-24 * time.Hour)
	minSamples := services.GetInt("upstream_min_samples", 10)

	var rows []database.RequestLog
	a.GDB.Select("model", "success", "first_token_ms", "total_tokens", "stream", "started_at", "finished_at", "ts").
		Where("ts >= ? AND model IS NOT NULL", since).Order("ts").Find(&rows)
	byModel := map[string][]database.RequestLog{}
	for i := range rows {
		if rows[i].Model == nil {
			continue
		}
		byModel[*rows[i].Model] = append(byModel[*rows[i].Model], rows[i])
	}

	out := make(map[string]gin.H, len(byModel))
	for model, modelRows := range byModel {
		// Only the newest recentCount samples count, matching the health tab.
		sample := modelRows
		if len(sample) > recentCount {
			sample = sample[len(sample)-recentCount:]
		}
		var total, success int
		var ttftSum float64
		var ttftN int
		var tokens int64
		var seconds float64
		for i := range sample {
			total++
			if sample[i].Success {
				success++
			}
			if sample[i].FirstTokenMs != nil {
				ttftSum += *sample[i].FirstTokenMs
				ttftN++
			}
			if sample[i].Stream {
				tokens += sample[i].TotalTokens
				if sample[i].FinishedAt != nil && sample[i].StartedAt != nil {
					seconds += sample[i].FinishedAt.Sub(*sample[i].StartedAt).Seconds()
				}
			}
		}
		status := "learning"
		var rate *float64
		if total > 0 {
			r := float64(success) / float64(total)
			rate = &r
			switch {
			case r >= 0.9:
				status = "healthy"
			case r >= 0.5:
				status = "degraded"
			default:
				status = "unavailable"
			}
		}
		var ttft *float64
		if ttftN > 0 {
			avg := ttftSum / float64(ttftN)
			ttft = &avg
		}
		out[model] = gin.H{
			"model_id":             model,
			"status":               status,
			"recent_success_rate":  rate,
			"recent_request_count": total,
			"recent_avg_ttft_ms":   ttft,
			"sufficient_data":      total >= minSamples,
			"best_success_rate":    rate,
			"best_ttft_ms":         ttft,
			"recent_since":         recentSince(&sample),
			"tokens_per_second":    streamThroughput(tokens, seconds),
		}
	}
	return out
}

// nodeHealth builds the node health view (score + samples) for staff.
func (a *App) nodeHealth(window string) []gin.H {
	secs := healthWindows[window]
	if secs == 0 {
		secs = 86400
	}
	since := time.Now().UTC().Add(-time.Duration(secs) * time.Second)

	var nodes []database.Node
	a.GDB.Order("id").Find(&nodes)

	// group membership names per node
	memberships := map[int][]string{}
	var groups []database.NodeGroup
	a.GDB.Find(&groups)
	for i := range groups {
		for _, n := range services.ExpandGroupNodes(a.GDB, groups[i].ID) {
			memberships[n.ID] = append(memberships[n.ID], groups[i].Name)
		}
	}

	var samples []database.NodeHealthSample
	a.GDB.Where("ts >= ?", since).Order("ts asc").Find(&samples)
	byNode := map[int][]database.NodeHealthSample{}
	for _, s := range samples {
		byNode[s.NodeID] = append(byNode[s.NodeID], s)
	}

	alpha := services.GetFloat("node_rank_alpha", 1.0)
	beta := services.GetFloat("node_rank_beta", 100.0)
	gamma := services.GetFloat("node_rank_gamma", 1000.0)
	threshold := float64(services.GetInt("max_proxy_failures", 3))
	if threshold < 1 {
		threshold = 1
	}

	out := make([]gin.H, 0, len(nodes))
	for i := range nodes {
		n := &nodes[i]
		latency := 0.0
		if n.LatencyEWMA != nil {
			latency = *n.LatencyEWMA
		}
		score := alpha*latency + beta*float64(n.FailedCount)
		fc := float64(n.FailedCount) / threshold
		if fc > 1 {
			fc = 1
		}
		score += gamma * fc

		grpNames := memberships[n.ID]
		if grpNames == nil {
			grpNames = []string{}
		}
		ns := byNode[n.ID]
		samplesOut := make([]gin.H, 0, len(ns))
		for _, s := range ns {
			samplesOut = append(samplesOut, gin.H{
				"ts": s.TS, "success": s.Success, "latency_ms": s.LatencyMs,
				"source": s.Source, "status_code": s.StatusCode,
			})
		}
		out = append(out, gin.H{
			"id": n.ID, "url": n.URL, "type": n.Type, "note": n.Note,
			"enabled": n.Enabled, "status": n.Status, "failed_count": n.FailedCount,
			"weight": n.Weight, "latency_ms": n.LatencyMs, "latency_ewma": n.LatencyEWMA,
			"score": score, "groups": grpNames,
			"last_used_at": n.LastUsedAt, "last_checked_at": n.LastCheckedAt,
			"disabled_reason": n.DisabledReason, "samples": samplesOut,
			"created_at": n.CreatedAt,
		})
	}
	return out
}

// modelDetail returns one model's health summary plus its per-upstream detail.
// It backs the model detail dialog on the Models page (the standalone Health
// page was folded into Models / Nodes). Upstreams are staff-only: which provider
// and key serves a model is an operator concern, so a member's payload omits
// them entirely rather than sending and hiding them client-side.
func (a *App) modelDetail(c *gin.Context) {
	uv := core.GetUser(c)
	modelID := strings.TrimSpace(c.Query("model_id"))
	if modelID == "" {
		a.fail(c, http.StatusBadRequest, "model_id is required.")
		return
	}
	now := time.Now().UTC()
	health, ok := a.modelHealthIndex(now)[modelID]
	if !ok {
		health = gin.H{
			"model_id": modelID, "status": "learning",
			"recent_success_rate": nil, "recent_request_count": 0,
			"recent_avg_ttft_ms": nil, "sufficient_data": false,
			"best_success_rate": nil, "best_ttft_ms": nil,
			"recent_since": nil, "tokens_per_second": nil,
		}
	}
	payload := gin.H{"model_id": modelID, "health": health}
	if uv.IsStaff() {
		since := now.Add(-24 * time.Hour)
		payload["upstreams"] = a.modelUpstreamHealth(modelID, since, recentHealthSamples())
	}
	c.JSON(http.StatusOK, payload)
}

// RegisterHealthRoutes wires /api/health + /api/health/stream (authenticated).
func RegisterHealthRoutes(authed *gin.RouterGroup, a *App) {
	g := authed.Group("/health", core.RequireUser())
	g.GET("", a.healthSnapshot)
	g.GET("/stream", a.healthStream)
	g.GET("/model", a.modelDetail)
}

// model: each route candidate with its recent success rate, TTFT, sample count
// and any active cooldown.
func (a *App) modelUpstreamHealth(modelID string, since time.Time, recentCount int) []gin.H {
	var m database.ExposedModel
	if err := a.GDB.Where("model_id = ?", modelID).First(&m).Error; err != nil {
		return []gin.H{}
	}
	var route database.Route
	if err := a.GDB.Where("exposed_model_id = ?", m.ID).First(&route).Error; err != nil {
		return []gin.H{}
	}
	var ups []database.RouteUpstream
	a.GDB.Where("route_id = ?", route.ID).Order("group_position, position").Find(&ups)

	var providers []database.Provider
	a.GDB.Find(&providers)
	pname := map[int]*database.Provider{}
	for i := range providers {
		pname[providers[i].ID] = &providers[i]
	}
	var cools []database.UpstreamCooldown
	a.GDB.Where("until > ?", time.Now().UTC()).Find(&cools)
	coolKey := map[string]time.Time{}
	for _, c := range cools {
		coolKey[cooldownKey(c.ProviderID, c.UpstreamModel, c.KeyPool)] = c.Until
	}

	out := make([]gin.H, 0, len(ups))
	for i := range ups {
		u := &ups[i]
		var provName, provSlug *string
		if u.ProviderID != nil {
			if p, ok := pname[*u.ProviderID]; ok {
				provName, provSlug = &p.Name, &p.Slug
			}
		}
		var rows []database.RequestLog
		q := a.GDB.Where("model = ? AND ts >= ?", modelID, since)
		if u.ProviderID != nil {
			q = q.Where("provider_name = ?", deref(provName))
		}
		q = q.Where("upstream_model = ?", u.UpstreamModel).Order("id DESC").Limit(recentCount).Find(&rows)
		var total, success int
		var ttftSum float64
		var ttftN int
		for j := range rows {
			total++
			if rows[j].Success {
				success++
			}
			if rows[j].FirstTokenMs != nil {
				ttftSum += *rows[j].FirstTokenMs
				ttftN++
			}
		}
		var rate *float64
		if total > 0 {
			r := float64(success) / float64(total)
			rate = &r
		}
		var ttft *float64
		if ttftN > 0 {
			avg := ttftSum / float64(ttftN)
			ttft = &avg
		}
		st := "learning"
		if total > 0 {
			switch {
			case *rate >= 0.9:
				st = "healthy"
			case *rate >= 0.5:
				st = "degraded"
			default:
				st = "unavailable"
			}
		}
		var cooledUntil *time.Time
		if u.ProviderID != nil {
			if t, ok := coolKey[cooldownKey(*u.ProviderID, u.UpstreamModel, u.KeyPool)]; ok {
				cooledUntil = &t
				st = "degraded"
			}
		}
		out = append(out, gin.H{
			"upstream_id":          u.ID,
			"provider_id":          u.ProviderID,
			"provider_name":        provName,
			"provider_slug":        provSlug,
			"upstream_model":       u.UpstreamModel,
			"status":               st,
			"success_rate":         rate,
			"ttft_ms":              ttft,
			"samples":              total,
			"requests":             total,
			"consecutive_failures": 0,
			"cooled_until":         cooledUntil,
		})
	}
	return out
}

func cooldownKey(providerID int, upstreamModel, pool string) string {
	return strconv.Itoa(providerID) + "|" + upstreamModel + "|" + pool
}
