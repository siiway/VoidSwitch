package services

import (
	"context"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// Egress is a resolved outbound path for one request.
type Egress struct {
	// NodeKind is "", "direct", "http", "socks5" or "agent".
	NodeKind string
	// ProxyURL is set for http/socks5 nodes and the static proxy.
	ProxyURL *string
	// LocalAddress binds the outbound socket.
	LocalAddress *string
	// AgentURL + AgentToken are set for agent nodes.
	AgentURL   string
	AgentToken string
	NodeID     int
}

// ResolveEgress picks an outbound node for the provider's node group.
// Ordering: when proxy switching is disabled → static proxy or direct. Otherwise
// choose the healthiest enabled node from the group (EWMA latency + failure
// penalty), falling back to direct.
func ResolveEgress(db *gorm.DB, provider *database.Provider, secretKey string) Egress {
	if !GetBool("proxy_switching_enabled", true) {
		if static := GetString("static_proxy_url", ""); static != "" {
			s := static
			return Egress{NodeKind: nodeKindForURL(static), ProxyURL: &s, LocalAddress: nil}
		}
		return Egress{NodeKind: "direct"}
	}

	groupID := provider.NodeGroupID
	if groupID == nil {
		id := DefaultNodeGroupID(db)
		if id == 0 {
			return Egress{NodeKind: "direct"}
		}
		groupID = &id
	}

	nodes := expandGroupNodes(db, *groupID)
	if len(nodes) == 0 {
		return Egress{NodeKind: "direct"}
	}
	sort.SliceStable(nodes, func(i, j int) bool {
		return nodeScore(&nodes[i]) < nodeScore(&nodes[j])
	})
	n := nodes[0]
	return EgressFromNode(db, &n, secretKey)
}

// EgressFromNode builds an Egress from a node row.
func EgressFromNode(db *gorm.DB, n *database.Node, secretKey string) Egress {
	switch constants.NodeType(n.Type) {
	case constants.NodeTypeDirect:
		return Egress{NodeKind: "direct", NodeID: n.ID}
	case constants.NodeTypeAgent:
		token := ""
		if n.TokenCiphertext != nil && *n.TokenCiphertext != "" {
			if pt, err := decryptSecret(*n.TokenCiphertext, secretKey); err == nil {
				token = pt
			}
		}
		return Egress{NodeKind: "agent", AgentURL: n.URL, AgentToken: token, NodeID: n.ID}
	case constants.NodeTypeSocks5:
		u := n.URL
		return Egress{NodeKind: "socks5", ProxyURL: &u, LocalAddress: n.LocalAddress, NodeID: n.ID}
	default:
		u := findProxyURL(db, n)
		kind := nodeKindForURL(u)
		return Egress{NodeKind: kind, ProxyURL: &u, LocalAddress: n.LocalAddress, NodeID: n.ID}
	}
}

func findProxyURL(_ *gorm.DB, n *database.Node) string {
	if n.URL != "" {
		return n.URL
	}
	return ""
}

func nodeKindForURL(raw string) string {
	lower := strings.ToLower(raw)
	switch {
	case strings.HasPrefix(lower, "socks5://"), strings.HasPrefix(lower, "socks5h://"),
		strings.HasPrefix(lower, "socks4://"), strings.HasPrefix(lower, "socks4a://"):
		return "socks5"
	case strings.HasPrefix(lower, "http://"), strings.HasPrefix(lower, "https://"):
		return "http"
	case raw == "":
		return "direct"
	default:
		return "http"
	}
}

// nodeScore ranks nodes ascending (lower is better). EWMA latency dominates;
// failures add a large penalty; weight breaks ties.
func nodeScore(n *database.Node) float64 {
	latency := 0.0
	if n.LatencyEWMA != nil {
		latency = *n.LatencyEWMA
	} else if n.LatencyMs != nil {
		latency = *n.LatencyMs
	}
	alpha := GetFloat("node_rank_alpha", 1.0)
	beta := GetFloat("node_rank_beta", 100.0)
	return alpha*latency + beta*float64(n.FailedCount)
}

// expandGroupNodes resolves a node group's members to concrete nodes, including
// inherited groups (flattened), skipping disabled nodes.
func expandGroupNodes(db *gorm.DB, groupID int) []database.Node {
	seenGroups := map[int]bool{}
	var out []database.Node
	var walk func(gid int)
	walk = func(gid int) {
		if seenGroups[gid] {
			return
		}
		seenGroups[gid] = true
		var members []database.NodeGroupMember
		db.Where("group_id = ?", gid).Order("id").Find(&members)
		for _, m := range members {
			if m.NodeID != nil {
				var n database.Node
				if err := db.Where("id = ? AND enabled = ? AND status = ?", *m.NodeID, true, string(constants.NodeStatusActive)).First(&n).Error; err == nil {
					out = append(out, n)
				}
			}
			if m.SourceGroupID != nil {
				walk(*m.SourceGroupID)
			}
		}
	}
	walk(groupID)
	return out
}

// SendThroughAgent performs an upstream request via a voidswitch-agent relay.
func SendThroughAgent(ctx context.Context, e Egress, method, upstreamURL string, headers map[string]string, body []byte, timeout time.Duration) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(e.AgentURL, "/")+"/", strings.NewReader(string(body)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-VS-Upstream-URL", upstreamURL)
	if e.AgentToken != "" {
		req.Header.Set("Authorization", "Bearer "+e.AgentToken)
	}
	for k, v := range headers {
		// Do not leak the upstream credential to the agent's own auth header.
		if strings.EqualFold(k, "Authorization") && e.AgentToken != "" {
			req.Header.Set("X-VS-Upstream-Authorization", v)
			continue
		}
		req.Header.Set(k, v)
	}
	client := &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			MaxIdleConns:      50,
			IdleConnTimeout:   90 * time.Second,
			ForceAttemptHTTP2: true,
		},
	}
	return client.Do(req)
}

func fmtEgress(e Egress) string {
	if e.NodeKind == "agent" {
		return fmt.Sprintf("agent(%s)", e.AgentURL)
	}
	if e.ProxyURL != nil {
		return fmt.Sprintf("%s(%s)", e.NodeKind, *e.ProxyURL)
	}
	return e.NodeKind
}

func decryptSecret(ciphertext, secretKey string) (string, error) {
	return cryptoutil.DecryptSecret(ciphertext, secretKey)
}
