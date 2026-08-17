// Package metrics exposes minimal Prometheus-style counters about the agent.
package metrics

import (
	"fmt"
	"sync/atomic"
)

// Metrics holds simple counters for the agent's status endpoint.
type Metrics struct {
	RelayRequests  atomic.Int64
	RelayBytesIn   atomic.Int64
	RelayBytesOut  atomic.Int64
	ActiveStreams  atomic.Int64
	AuthFailures   atomic.Int64
	ConnectTunnels atomic.Int64
}

// Render returns the plain-text /metrics body.
func (m *Metrics) Render() string {
	return fmt.Sprintf(
		"# TYPE vs_agent_relay_requests counter\n"+
			"vs_agent_relay_requests %d\n"+
			"# TYPE vs_agent_relay_bytes_in counter\n"+
			"vs_agent_relay_bytes_in %d\n"+
			"# TYPE vs_agent_relay_bytes_out counter\n"+
			"vs_agent_relay_bytes_out %d\n"+
			"# TYPE vs_agent_active_streams gauge\n"+
			"vs_agent_active_streams %d\n"+
			"# TYPE vs_agent_auth_failures counter\n"+
			"vs_agent_auth_failures %d\n"+
			"# TYPE vs_agent_connect_tunnels counter\n"+
			"vs_agent_connect_tunnels %d\n",
		m.RelayRequests.Load(),
		m.RelayBytesIn.Load(),
		m.RelayBytesOut.Load(),
		m.ActiveStreams.Load(),
		m.AuthFailures.Load(),
		m.ConnectTunnels.Load(),
	)
}
