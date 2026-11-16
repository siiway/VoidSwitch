package services

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

// ResurrectNodes probes every enabled-but-disabled egress node through its proxy
// and revives the ones that answer, recording a health sample either way.
//
// Without this the pool only ever drains: a node disabled by a transient failure
// stays disabled until an operator probes it by hand, and a deployment that
// relies on switching gradually runs out of exits.
func ResurrectNodes(ctx context.Context, db *gorm.DB, secretKey string) (revived int, err error) {
	if !GetBool("proxy_switching_enabled", true) {
		// An external proxy handles egress: there is no pool to resurrect.
		return 0, nil
	}
	defaultProbe := GetString("node_default_probe_url", "")

	var nodes []database.Node
	if err := db.Where("enabled = ? AND status = ?", true, string(constants.NodeStatusDisabled)).
		Order("id").Find(&nodes).Error; err != nil {
		return 0, err
	}
	if len(nodes) == 0 {
		return 0, nil
	}
	// A node group may carry its own probe URL (often a private endpoint that is
	// only reachable through that group's egress); fall back to the global one.
	groupProbe := loadGroupProbeURLs(db, secretKey)

	for i := range nodes {
		if ctx.Err() != nil {
			return revived, ctx.Err()
		}
		n := &nodes[i]
		probeURL := groupProbe[n.ID]
		if probeURL == "" {
			probeURL = defaultProbe
		}
		if probeURL == "" {
			continue
		}
		egress := EgressFromNode(db, n, secretKey)
		ok, latency, statusCode, probeErr := probeEgress(ctx, egress, probeURL)

		now := time.Now().UTC()
		n.LastCheckedAt = &now
		if latency > 0 {
			l := latency
			n.LatencyMs = &l
		}
		if ok {
			n.Status = string(constants.NodeStatusActive)
			n.FailedCount = 0
			n.DisabledReason = nil
			revived++
		} else {
			n.FailedCount++
			reason := "probe failed"
			if probeErr != nil {
				reason = probeErr.Error()
				if len(reason) > 200 {
					reason = reason[:200]
				}
			}
			n.DisabledReason = &reason
		}
		if err := db.Save(n).Error; err != nil {
			return revived, err
		}

		sample := database.NodeHealthSample{
			NodeID: n.ID, TS: now, Source: "probe", Success: ok,
			StatusCode: statusCode,
		}
		if latency > 0 {
			l := latency
			sample.LatencyMs = &l
		}
		if probeErr != nil {
			msg := probeErr.Error()
			if len(msg) > 255 {
				msg = msg[:255]
			}
			sample.Error = &msg
		}
		db.Create(&sample)
	}
	return revived, nil
}

// loadGroupProbeURLs maps each node id to the probe URL of the first group that
// contains it (directly or through an inherited group). An empty value means the
// group has none and the global default applies.
func loadGroupProbeURLs(db *gorm.DB, secretKey string) map[int]string {
	var groups []database.NodeGroup
	db.Find(&groups)
	out := map[int]string{}
	for i := range groups {
		g := &groups[i]
		if g.ProbeURL == nil || strings.TrimSpace(*g.ProbeURL) == "" {
			continue
		}
		for _, n := range ExpandGroupNodesAll(db, g.ID) {
			if _, ok := out[n.ID]; !ok {
				out[n.ID] = *g.ProbeURL
			}
		}
	}
	return out
}

// probeEgress issues a lightweight GET through the egress path. Any HTTP answer
// proves reachability, including an error status: the point is that the proxy is
// alive, not that the probe URL likes us.
func probeEgress(ctx context.Context, e Egress, probeURL string) (bool, float64, *int, error) {
	timeout := time.Duration(GetInt("node_probe_timeout_seconds", 5)) * time.Second
	if timeout <= 0 {
		timeout = 5 * time.Second
	}
	reqCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	if e.NodeKind == "agent" {
		resp, err := SendThroughAgent(reqCtx, e, http.MethodGet, probeURL, nil, nil, timeout)
		if err != nil {
			return false, 0, nil, err
		}
		defer resp.Body.Close()
		io.Copy(io.Discard, io.LimitReader(resp.Body, 512))
		code := resp.StatusCode
		return true, 0, &code, nil
	}

	dialer := &net.Dialer{Timeout: timeout}
	if e.LocalAddress != nil && *e.LocalAddress != "" {
		if addr, err := net.ResolveTCPAddr("tcp", *e.LocalAddress); err == nil {
			dialer.LocalAddr = addr
		}
	}
	transport := &http.Transport{DialContext: dialer.DialContext}
	if e.ProxyURL != nil && *e.ProxyURL != "" && e.NodeKind != "direct" {
		pu, err := url.Parse(*e.ProxyURL)
		if err != nil {
			return false, 0, nil, err
		}
		if !strings.Contains(pu.Scheme, "socks") && pu.Scheme != "http" && pu.Scheme != "https" {
			// A bare host:port is a plain HTTP proxy.
			pu, err = url.Parse("http://" + *e.ProxyURL)
			if err != nil {
				return false, 0, nil, err
			}
		}
		transport.Proxy = http.ProxyURL(pu)
	}
	client := &http.Client{Transport: transport, Timeout: timeout}
	start := time.Now()
	resp, err := client.Get(probeURL)
	if err != nil {
		return false, 0, nil, err
	}
	elapsed := float64(time.Since(start).Milliseconds())
	defer resp.Body.Close()
	io.Copy(io.Discard, io.LimitReader(resp.Body, 512))
	code := resp.StatusCode
	return true, elapsed, &code, nil
}
