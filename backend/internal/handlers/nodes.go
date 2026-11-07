package handlers

import (
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/core"
	"github.com/siiway/voidswitch/internal/database"
	"github.com/siiway/voidswitch/internal/services"
)

type nodeView struct {
	ID             int        `json:"id"`
	URL            string     `json:"url"`
	Type           string     `json:"type"`
	LocalAddress   *string    `json:"local_address"`
	Enabled        bool       `json:"enabled"`
	Status         string     `json:"status"`
	FailedCount    int        `json:"failed_count"`
	Weight         int        `json:"weight"`
	LatencyMs      *float64   `json:"latency_ms"`
	LatencyEWMA    *float64   `json:"latency_ewma"`
	Note           *string    `json:"note"`
	DisabledReason *string    `json:"disabled_reason"`
	LastUsedAt     *time.Time `json:"last_used_at"`
	LastCheckedAt  *time.Time `json:"last_checked_at"`
	CreatedAt      time.Time  `json:"created_at"`
	TokenPreview   *string    `json:"token_preview"`
}

func buildNodeView(n *database.Node) nodeView {
	return nodeView{
		ID: n.ID, URL: n.URL, Type: n.Type, LocalAddress: n.LocalAddress,
		Enabled: n.Enabled, Status: n.Status, FailedCount: n.FailedCount,
		Weight: n.Weight, LatencyMs: n.LatencyMs, LatencyEWMA: n.LatencyEWMA,
		Note: n.Note, DisabledReason: n.DisabledReason, LastUsedAt: n.LastUsedAt,
		LastCheckedAt: n.LastCheckedAt, CreatedAt: n.CreatedAt, TokenPreview: nil,
	}
}

type nodeGroupMemberView struct {
	NodeID              *int     `json:"node_id"`
	SourceGroupID       *int     `json:"source_group_id"`
	Weight              int      `json:"weight"`
	Pinned              bool     `json:"pinned"`
	NodeURL             *string  `json:"node_url"`
	NodeNote            *string  `json:"node_note"`
	NodeStatus          *string  `json:"node_status"`
	NodeLatencyMs       *float64 `json:"node_latency_ms"`
	NodeLatencyEWMA     *float64 `json:"node_latency_ewma"`
	SourceGroupName     *string  `json:"source_group_name"`
	SourceGroupIsSystem bool     `json:"source_group_is_system"`
	Rank                *int     `json:"rank"`
}

type nodeGroupView struct {
	ID                   int                   `json:"id"`
	Slug                 *string               `json:"slug"`
	Name                 string                `json:"name"`
	Description          *string               `json:"description"`
	ProbeURL             *string               `json:"probe_url"`
	ProbeIntervalSeconds int                   `json:"probe_interval_seconds"`
	IsSystem             bool                  `json:"is_system"`
	MemberCount          int                   `json:"member_count"`
	Members              []nodeGroupMemberView `json:"members"`
	CreatedAt            time.Time             `json:"created_at"`
	UpdatedAt            time.Time             `json:"updated_at"`
}

func (a *App) buildNodeGroupView(g *database.NodeGroup) nodeGroupView {
	var members []database.NodeGroupMember
	a.GDB.Where("group_id = ?", g.ID).Order("id").Find(&members)

	nodeCache := map[int]*database.Node{}
	var directNodes []database.Node
	a.GDB.Find(&directNodes)
	for i := range directNodes {
		nodeCache[directNodes[i].ID] = &directNodes[i]
	}

	groupCache := map[int]*database.NodeGroup{}
	var groups []database.NodeGroup
	a.GDB.Find(&groups)
	for i := range groups {
		groupCache[groups[i].ID] = &groups[i]
	}

	out := make([]nodeGroupMemberView, 0, len(members))
	rank := 0
	for i := range members {
		m := &members[i]
		mv := nodeGroupMemberView{
			NodeID: m.NodeID, SourceGroupID: m.SourceGroupID,
			Weight: m.Weight, Pinned: m.Pinned,
		}
		if m.NodeID != nil {
			if n, ok := nodeCache[*m.NodeID]; ok {
				u, note, st := n.URL, n.Note, n.Status
				mv.NodeURL, mv.NodeNote, mv.NodeStatus = &u, note, &st
				mv.NodeLatencyMs, mv.NodeLatencyEWMA = n.LatencyMs, n.LatencyEWMA
				r := rank
				mv.Rank = &r
				rank++
			}
		}
		if m.SourceGroupID != nil {
			if sg, ok := groupCache[*m.SourceGroupID]; ok {
				name := sg.Name
				mv.SourceGroupName = &name
				mv.SourceGroupIsSystem = sg.IsSystem
			}
		}
		out = append(out, mv)
	}

	return nodeGroupView{
		ID: g.ID, Slug: g.Slug, Name: g.Name, Description: g.Description,
		ProbeURL: g.ProbeURL, ProbeIntervalSeconds: g.ProbeIntervalSeconds,
		IsSystem: g.IsSystem, MemberCount: len(members), Members: out,
		CreatedAt: g.CreatedAt, UpdatedAt: g.UpdatedAt,
	}
}

// ---- nodes ----------------------------------------------------------------

func (a *App) nodesList(c *gin.Context) {
	uv := core.GetUser(c)
	_ = uv
	var rows []database.Node
	if err := a.GDB.Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]nodeView, 0, len(rows))
	for i := range rows {
		out = append(out, buildNodeView(&rows[i]))
	}
	c.JSON(http.StatusOK, out)
}

type nodeInput struct {
	URL          *string `json:"url"`
	Type         *string `json:"type"`
	LocalAddress *string `json:"local_address"`
	Note         *string `json:"note"`
	Weight       *int    `json:"weight"`
}

type nodeBulkPayload struct {
	URLs  []string     `json:"urls"`
	Nodes *[]nodeInput `json:"nodes"`
}

func normalizeNodeType(s string, raw string) string {
	switch s {
	case string(constants.NodeTypeDirect), string(constants.NodeTypeHTTP),
		string(constants.NodeTypeSocks5), string(constants.NodeTypeAgent):
		return s
	}
	switch {
	case strings.HasPrefix(raw, "direct"):
		return string(constants.NodeTypeDirect)
	case strings.HasPrefix(raw, "socks5"):
		return string(constants.NodeTypeSocks5)
	}
	return string(constants.NodeTypeHTTP)
}

func (a *App) nodesCreate(c *gin.Context) {
	uv := core.GetUser(c)

	var rawBody map[string]any
	_ = c.ShouldBindJSON(&rawBody)

	var inputs []nodeInput
	if arr, ok := rawBody["urls"].([]any); ok {
		for _, x := range arr {
			if s, ok := x.(string); ok {
				if t := strings.TrimSpace(s); t != "" {
					inputs = append(inputs, nodeInput{URL: strPtr(t)})
				}
			}
		}
	} else if arr, ok := rawBody["nodes"].([]any); ok {
		for _, x := range arr {
			if m, ok := x.(map[string]any); ok {
				in := nodeInput{}
				if s, ok := m["url"].(string); ok {
					in.URL = &s
				}
				if s, ok := m["type"].(string); ok {
					in.Type = &s
				}
				if s, ok := m["local_address"].(string); ok {
					in.LocalAddress = &s
				}
				if s, ok := m["note"].(string); ok {
					in.Note = &s
				}
				if f, ok := m["weight"].(float64); ok {
					w := int(f)
					in.Weight = &w
				}
				inputs = append(inputs, in)
			}
		}
	} else if s, ok := rawBody["url"].(string); ok {
		in := nodeInput{URL: &s}
		if t, ok := rawBody["type"].(string); ok {
			in.Type = &t
		}
		if la, ok := rawBody["local_address"].(string); ok {
			in.LocalAddress = &la
		}
		if n, ok := rawBody["note"].(string); ok {
			in.Note = &n
		}
		if f, ok := rawBody["weight"].(float64); ok {
			w := int(f)
			in.Weight = &w
		}
		inputs = append(inputs, in)
	}

	if len(inputs) == 0 {
		a.fail(c, http.StatusUnprocessableEntity, "at least one node url is required.")
		return
	}

	out := make([]nodeView, 0, len(inputs))
	for i := range inputs {
		in := &inputs[i]
		rawURL := ""
		if in.URL != nil {
			rawURL = strings.TrimSpace(*in.URL)
		}
		if rawURL == "" {
			a.fail(c, http.StatusUnprocessableEntity, "node url is required.")
			return
		}
		var existing int64
		a.GDB.Model(&database.Node{}).Where("url = ?", rawURL).Count(&existing)
		if existing > 0 {
			continue
		}
		weight := 1
		if in.Weight != nil {
			weight = *in.Weight
			if weight < 0 {
				weight = 0
			}
		}
		n := database.Node{
			URL:          rawURL,
			Type:         normalizeNodeType(deref(in.Type), rawURL),
			LocalAddress: in.LocalAddress, Note: in.Note,
			Enabled: true, Status: string(constants.NodeStatusActive),
			Weight: weight, FailedCount: 0,
		}
		if err := a.GDB.Create(&n).Error; err != nil {
			a.internal(c, err)
			return
		}
		out = append(out, buildNodeView(&n))
	}

	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "node.create", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("node"), Detail: map[string]any{"count": len(out)},
		IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusCreated, out)
}

type nodePatch struct {
	Enabled      *bool   `json:"enabled"`
	LocalAddress *string `json:"local_address"`
	Note         *string `json:"note"`
	Weight       *int    `json:"weight"`
	Type         *string `json:"type"`
	URL          *string `json:"url"`
}

func (a *App) nodesUpdate(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var n database.Node
	if err := a.GDB.First(&n, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Node not found.")
		return
	}
	var in nodePatch
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.URL != nil && strings.TrimSpace(*in.URL) != n.URL {
		var clash int64
		a.GDB.Model(&database.Node{}).Where("url = ? AND id <> ?", strings.TrimSpace(*in.URL), n.ID).Count(&clash)
		if clash > 0 {
			a.fail(c, http.StatusConflict, "Node url already exists.")
			return
		}
		var u string
		if in.URL != nil {
			u = strings.TrimSpace(*in.URL)
		}
		n.URL = u
	}
	if in.Type != nil {
		n.Type = normalizeNodeType(*in.Type, n.URL)
	}
	if in.LocalAddress != nil {
		v := *in.LocalAddress
		n.LocalAddress = &v
	}
	if in.Note != nil {
		v := *in.Note
		n.Note = &v
	}
	if in.Weight != nil {
		w := *in.Weight
		if w < 0 {
			w = 0
		}
		n.Weight = w
	}
	if in.Enabled != nil {
		n.Enabled = *in.Enabled
		if !n.Enabled {
			n.Status = string(constants.NodeStatusDisabled)
		} else {
			n.Status = string(constants.NodeStatusActive)
			n.DisabledReason = nil
		}
	}
	if err := a.GDB.Save(&n).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(n.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "node.update", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("node"), TargetID: &tid, Detail: map[string]any{"url": n.URL},
		IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusOK, buildNodeView(&n))
}

func (a *App) nodesDelete(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var n database.Node
	if err := a.GDB.First(&n, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Node not found.")
		return
	}
	if err := a.GDB.Delete(&n).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(id)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "node.delete", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("node"), TargetID: &tid, Detail: map[string]any{"url": n.URL},
	})
	c.Status(http.StatusNoContent)
}

func (a *App) nodesProbe(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var n database.Node
	if err := a.GDB.First(&n, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Node not found.")
		return
	}

	probeURL := services.GetString("node_default_probe_url", "")
	now := time.Now().UTC()
	n.LastCheckedAt = &now

	reachable := false
	if probeURL != "" {
		reachable = probeReachable(probeURL)
	}

	if reachable {
		n.Status = string(constants.NodeStatusActive)
		n.FailedCount = 0
		n.DisabledReason = nil
	} else {
		n.Status = string(constants.NodeStatusDisabled)
		n.FailedCount++
		n.DisabledReason = strPtr("probe unreachable")
	}
	if err := a.GDB.Save(&n).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, buildNodeView(&n))
}

func probeReachable(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil {
		return false
	}
	host := u.Hostname()
	if host == "" {
		return false
	}
	port := u.Port()
	if port == "" {
		if u.Scheme == "https" {
			port = "443"
		} else {
			port = "80"
		}
	}
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(fmt.Sprintf("%s://%s", u.Scheme, u.Host))
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
}

// ---- node groups ----------------------------------------------------------

func (a *App) nodeGroupsList(c *gin.Context) {
	var rows []database.NodeGroup
	if err := a.GDB.Order("id").Find(&rows).Error; err != nil {
		a.internal(c, err)
		return
	}
	out := make([]nodeGroupView, 0, len(rows))
	for i := range rows {
		out = append(out, a.buildNodeGroupView(&rows[i]))
	}
	c.JSON(http.StatusOK, out)
}

type nodeGroupInput struct {
	Name                 *string `json:"name"`
	Description          *string `json:"description"`
	ProbeURL             *string `json:"probe_url"`
	ProbeIntervalSeconds *int    `json:"probe_interval_seconds"`
}

func (a *App) uniqueNodeGroupSlug(base string) string {
	slug := slugify(base)
	candidate := slug
	n := 2
	for {
		var count int64
		a.GDB.Model(&database.NodeGroup{}).Where("slug = ?", candidate).Count(&count)
		if count == 0 {
			return candidate
		}
		candidate = fmt.Sprintf("%s-%d", slug, n)
		n++
	}
}

func (a *App) nodeGroupsCreate(c *gin.Context) {
	uv := core.GetUser(c)
	var in nodeGroupInput
	if err := c.ShouldBindJSON(&in); err != nil || in.Name == nil || strings.TrimSpace(*in.Name) == "" {
		a.fail(c, http.StatusUnprocessableEntity, "name is required.")
		return
	}
	var clash int64
	a.GDB.Model(&database.NodeGroup{}).Where("name = ?", *in.Name).Count(&clash)
	if clash > 0 {
		a.fail(c, http.StatusConflict, "Node group name already exists.")
		return
	}
	slug := a.uniqueNodeGroupSlug(*in.Name)
	g := database.NodeGroup{
		Slug: &slug, Name: strings.TrimSpace(*in.Name),
		Description: in.Description, ProbeURL: in.ProbeURL,
	}
	if in.ProbeIntervalSeconds != nil && *in.ProbeIntervalSeconds > 0 {
		g.ProbeIntervalSeconds = *in.ProbeIntervalSeconds
	}
	if err := a.GDB.Create(&g).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(g.ID)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "node_group.create", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("node_group"), TargetID: &tid, Detail: map[string]any{"name": g.Name},
		IP: strPtr(clientIP(c)),
	})
	c.JSON(http.StatusCreated, a.buildNodeGroupView(&g))
}

func (a *App) nodeGroupsUpdate(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var g database.NodeGroup
	if err := a.GDB.First(&g, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Node group not found.")
		return
	}
	var in nodeGroupInput
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}
	if in.Name != nil && strings.TrimSpace(*in.Name) != g.Name {
		var clash int64
		a.GDB.Model(&database.NodeGroup{}).Where("name = ? AND id <> ?", strings.TrimSpace(*in.Name), g.ID).Count(&clash)
		if clash > 0 {
			a.fail(c, http.StatusConflict, "Node group name already exists.")
			return
		}
		g.Name = strings.TrimSpace(*in.Name)
	}
	if in.Description != nil {
		g.Description = in.Description
	}
	if in.ProbeURL != nil {
		if strings.TrimSpace(*in.ProbeURL) == "" {
			g.ProbeURL = nil
		} else {
			g.ProbeURL = in.ProbeURL
		}
	}
	if in.ProbeIntervalSeconds != nil {
		v := *in.ProbeIntervalSeconds
		if v < 0 {
			v = 0
		}
		g.ProbeIntervalSeconds = v
	}
	if err := a.GDB.Save(&g).Error; err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, a.buildNodeGroupView(&g))
}

func (a *App) nodeGroupsDelete(c *gin.Context) {
	uv := core.GetUser(c)
	id, _ := strconv.Atoi(c.Param("id"))
	var g database.NodeGroup
	if err := a.GDB.First(&g, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Node group not found.")
		return
	}
	if g.IsSystem || (g.Slug != nil && (*g.Slug == "default" || *g.Slug == "system")) {
		a.fail(c, http.StatusBadRequest, "System node groups cannot be deleted.")
		return
	}
	if err := a.GDB.Where("group_id = ?", g.ID).Delete(&database.NodeGroupMember{}).Error; err != nil {
		a.internal(c, err)
		return
	}
	if err := a.GDB.Delete(&g).Error; err != nil {
		a.internal(c, err)
		return
	}
	sub, name := uv.User.Sub, services.BuildUserView(uv.User).Username
	tid := strconv.Itoa(id)
	_ = core.RecordAudit(a.GDB, core.AuditInput{
		Action: "node_group.delete", ActorSub: &sub, ActorName: name, Scope: core.AuditScopeAdmin,
		TargetType: strPtr("node_group"), TargetID: &tid, Detail: map[string]any{"name": g.Name},
		IP: strPtr(clientIP(c)),
	})
	c.Status(http.StatusNoContent)
}

type nodeGroupMemberInput struct {
	NodeID        *int  `json:"node_id"`
	SourceGroupID *int  `json:"source_group_id"`
	Weight        *int  `json:"weight"`
	Pinned        *bool `json:"pinned"`
}

func (a *App) nodeGroupsMembers(c *gin.Context) {
	id, _ := strconv.Atoi(c.Param("id"))
	var g database.NodeGroup
	if err := a.GDB.First(&g, id).Error; err != nil {
		a.fail(c, http.StatusNotFound, "Node group not found.")
		return
	}
	var in []nodeGroupMemberInput
	if err := c.ShouldBindJSON(&in); err != nil {
		a.fail(c, http.StatusUnprocessableEntity, "invalid payload.")
		return
	}

	rows := make([]database.NodeGroupMember, 0, len(in))
	seenNodes := map[int]bool{}
	seenGroups := map[int]bool{}
	for i := range in {
		m := &in[i]
		weight := 1
		if m.Weight != nil {
			weight = *m.Weight
			if weight < 0 {
				weight = 0
			}
		}
		pinned := false
		if m.Pinned != nil {
			pinned = *m.Pinned
		}
		if m.NodeID != nil {
			if seenNodes[*m.NodeID] {
				continue
			}
			var n database.Node
			if err := a.GDB.First(&n, *m.NodeID).Error; err != nil {
				a.fail(c, http.StatusUnprocessableEntity, "unknown node_id.")
				return
			}
			seenNodes[*m.NodeID] = true
			rows = append(rows, database.NodeGroupMember{
				GroupID: g.ID, NodeID: m.NodeID, Weight: weight, Pinned: pinned,
			})
		} else if m.SourceGroupID != nil {
			if *m.SourceGroupID == g.ID || seenGroups[*m.SourceGroupID] {
				continue
			}
			var sg database.NodeGroup
			if err := a.GDB.First(&sg, *m.SourceGroupID).Error; err != nil {
				if err == gorm.ErrRecordNotFound {
					a.fail(c, http.StatusUnprocessableEntity, "unknown source_group_id.")
					return
				}
				a.internal(c, err)
				return
			}
			seenGroups[*m.SourceGroupID] = true
			rows = append(rows, database.NodeGroupMember{
				GroupID: g.ID, SourceGroupID: m.SourceGroupID, Weight: weight,
			})
		}
	}

	err := a.GDB.Transaction(func(tx *gorm.DB) error {
		if err := tx.Where("group_id = ?", g.ID).Delete(&database.NodeGroupMember{}).Error; err != nil {
			return err
		}
		if len(rows) == 0 {
			return nil
		}
		return tx.Create(&rows).Error
	})
	if err != nil {
		a.internal(c, err)
		return
	}
	c.JSON(http.StatusOK, a.buildNodeGroupView(&g))
}

// RegisterNodeRoutes wires /api/admin/nodes and /api/admin/node-groups.
func RegisterNodeRoutes(g *gin.RouterGroup, a *App) {
	g.GET("/nodes", a.nodesList)
	g.POST("/nodes", a.nodesCreate)
	g.PATCH("/nodes/:id", a.nodesUpdate)
	g.DELETE("/nodes/:id", core.RequireOwner(), a.nodesDelete)
	g.POST("/nodes/:id/probe", a.nodesProbe)
	g.GET("/node-groups", a.nodeGroupsList)
	g.POST("/node-groups", a.nodeGroupsCreate)
	g.PATCH("/node-groups/:id", a.nodeGroupsUpdate)
	g.DELETE("/node-groups/:id", core.RequireOwner(), a.nodeGroupsDelete)
	g.PUT("/node-groups/:id/members", a.nodeGroupsMembers)
}
