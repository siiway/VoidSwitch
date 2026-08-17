// Package relay implements the two agent modes:
//
//   - "relay": a custom application-layer HTTP relay. The client sends its
//     upstream request to the agent with an X-VS-Upstream-URL header naming the
//     real upstream; the agent strips that header, forwards over a pooled
//     HTTP/2 transport, and streams the response back (SSE-safe). This is the
//     primary, VS-native transport.
//   - "connect": a standard HTTP CONNECT forward proxy (also over HTTP/2 via
//     RFC 8441 when probed), an optional compatibility/debug mode.
package relay

import (
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/siiway/voidswitch-agent/internal/auth"
	"github.com/siiway/voidswitch-agent/internal/config"
	"github.com/siiway/voidswitch-agent/internal/metrics"
	"github.com/siiway/voidswitch-agent/internal/upstream"
)

// Agent wires together auth, the upstream transport and metrics into handlers.
type Agent struct {
	Cfg      *config.Config
	Auth     *auth.Verifier
	Upstream *http.Transport
	Metrics  *metrics.Metrics
	Log      *slog.Logger
}

// New constructs an Agent.
func New(cfg *config.Config, log *slog.Logger) (*Agent, error) {
	verifier, err := auth.New(cfg.Token, cfg.AllowlistIPs)
	if err != nil {
		return nil, err
	}
	tr, err := upstream.NewTransport(upstream.Options{
		ProxyURL:    cfg.UpstreamProxy,
		BindAddress: cfg.BindAddress,
		DialTimeout: time.Duration(cfg.DialTimeout) * time.Second,
		IdleTimeout: time.Duration(cfg.IdleTimeout) * time.Second,
	}, log)
	if err != nil {
		return nil, err
	}
	return &Agent{
		Cfg:      cfg,
		Auth:     verifier,
		Upstream: tr,
		Metrics:  &metrics.Metrics{},
		Log:      log,
	}, nil
}

// Handler returns the root http.Handler for the configured mode.
func (a *Agent) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", a.handleRoot)
	if a.Cfg.MetricsPath != "" {
		mux.HandleFunc(a.Cfg.MetricsPath, a.handleMetrics)
	}
	return a.recoverMid(mux)
}

func (a *Agent) recoverMid(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				a.Log.Error("panic", "err", rec)
				http.Error(w, "internal error", http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func (a *Agent) handleMetrics(w http.ResponseWriter, r *http.Request) {
	if !a.Auth.Authorized(r) {
		a.Metrics.AuthFailures.Add(1)
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	w.Header().Set("content-type", "text/plain; version=0.0.4")
	_, _ = io.WriteString(w, a.Metrics.Render())
}

func (a *Agent) handleRoot(w http.ResponseWriter, r *http.Request) {
	// Health check (no auth — used by orchestration to see liveness).
	if r.URL.Path == "/healthz" {
		w.Header().Set("content-type", "application/json")
		_, _ = io.WriteString(w, `{"status":"ok"}`)
		return
	}
	if !a.Auth.Authorized(r) {
		a.Metrics.AuthFailures.Add(1)
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	switch a.Cfg.Mode {
	case "connect":
		a.handleConnectMeta(w, r)
	default:
		a.handleRelay(w, r)
	}
}

// handleConnectMeta dispatches CONNECT tunnels or rejects non-CONNECT in connect mode.
func (a *Agent) handleConnectMeta(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodConnect {
		a.connectTunnel(w, r)
		return
	}
	http.Error(w, "connect mode only accepts CONNECT", http.StatusMethodNotAllowed)
}

// handleRelay is the custom application-layer relay handler.
func (a *Agent) handleRelay(w http.ResponseWriter, r *http.Request) {
	target := strings.TrimSpace(r.Header.Get(config.UpstreamTargetHeader))
	if target == "" {
		http.Error(w, "missing "+config.UpstreamTargetHeader, http.StatusBadRequest)
		return
	}
	u, err := url.Parse(target)
	if err != nil || u.Scheme == "" || u.Host == "" {
		http.Error(w, "invalid target url", http.StatusBadRequest)
		return
	}
	// Reject the loop / malformed schemes.
	if u.Scheme != "http" && u.Scheme != "https" {
		http.Error(w, "unsupported target scheme", http.StatusBadRequest)
		return
	}
	a.Metrics.RelayRequests.Add(1)
	a.Metrics.ActiveStreams.Add(1)
	defer a.Metrics.ActiveStreams.Add(-1)

	// Build the upstream request: copy method/body, hop-by-hop headers dropped,
	// and the target header removed (never forwarded upstream).
	upReq, err := http.NewRequestWithContext(r.Context(), r.Method, u.String(), r.Body)
	if err != nil {
		http.Error(w, "cannot build upstream request", http.StatusBadRequest)
		return
	}
	copyHeaders(upReq.Header, r.Header)
	upReq.Header.Del(config.UpstreamTargetHeader)
	upReq.Header.Del("Authorization") // the VS token must NOT reach the upstream
	upReq.Header.Del("Connection")
	upReq.Header.Del("Proxy-Connection")
	keep := r.Header.Get("User-Agent")
	if keep != "" {
		upReq.Header.Set("User-Agent", keep)
	}

	start := time.Now()
	resp, err := a.Upstream.RoundTrip(upReq)
	if err != nil {
		a.Log.Warn("relay_upstream_error", "url", u.String(), "err", err)
		http.Error(w, "upstream error: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	a.Log.Info("relay", "method", r.Method, "host", u.Host, "status", resp.StatusCode,
		"dur_ms", time.Since(start).Milliseconds())

	copyHeader(w.Header(), resp.Header)
	w.Header().Del("Content-Length") // let chunked/streaming flow
	w.WriteHeader(resp.StatusCode)
	// Stream the body (SSE-safe). A Flusher is used for long-lived streams so
	// chunks reach the client promptly.
	if f, ok := w.(http.Flusher); ok {
		buf := make([]byte, 32*1024)
		for {
			n, rerr := resp.Body.Read(buf)
			if n > 0 {
				w.Write(buf[:n])
				f.Flush()
				a.Metrics.RelayBytesIn.Add(int64(n))
			}
			if rerr != nil {
				break
			}
		}
	} else {
		written, cerr := io.Copy(w, resp.Body)
		a.Metrics.RelayBytesIn.Add(written)
		_ = cerr
	}
}

// connectTunnel proxies a raw TCP tunnel (CONNECT). Over HTTP/2 the context is
// used to hijack the stream when supported; over HTTP/1.1 we hijack the conn.
func (a *Agent) connectTunnel(w http.ResponseWriter, r *http.Request) {
	a.Metrics.ActiveStreams.Add(1)
	defer a.Metrics.ActiveStreams.Add(-1)
	host := r.Host
	if !strings.Contains(host, ":") {
		host += ":80"
	}
	timeout := time.Duration(a.Cfg.DialTimeout) * time.Second
	out, err := net.DialTimeout("tcp", host, timeout)
	if err != nil {
		http.Error(w, "cannot reach "+host, http.StatusBadGateway)
		return
	}
	a.Metrics.ConnectTunnels.Add(1)
	// HTTP/1.1: hijack the connection and pipe bytes. HTTP/2 CONNECT is handled
	// by the server (h2c/http2) as a stream; a full impl would use the stream's
	// ReadWriteCloser. For this compatibility mode we support HTTP/1.1.
	hj, ok := w.(http.Hijacker)
	if !ok {
		out.Close()
		http.Error(w, "hijacking unsupported", http.StatusInternalServerError)
		return
	}
	conn, _, err := hj.Hijack()
	if err != nil {
		out.Close()
		http.Error(w, "hijack failed", http.StatusInternalServerError)
		return
	}
	_, _ = conn.Write([]byte("HTTP/1.1 200 Connection established\r\n\r\n"))
	go func() {
		io.Copy(out, conn)
		out.Close()
	}()
	io.Copy(conn, out)
	conn.Close()
}

func copyHeader(dst, src http.Header) {
	for k, vv := range src {
		for _, v := range vv {
			dst.Add(k, v)
		}
	}
}

func copyHeaders(dst, src http.Header) {
	for k, vv := range src {
		if isHopByHop(k) {
			continue
		}
		for _, v := range vv {
			dst.Add(k, v)
		}
	}
}

func isHopByHop(k string) bool {
	switch strings.ToLower(k) {
	case "connection", "proxy-connection", "keep-alive", "proxy-authenticate",
		"proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade":
		return true
	}
	return false
}
