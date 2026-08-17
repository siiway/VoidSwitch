// Package upstream builds a shared http.Transport used to reach real upstream
// services, with optional proxy chaining and source-IP binding (the egress /
// path-optimisation layer of the voidswitch-agent).
package upstream

import (
	"crypto/tls"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"time"
)

// Options control egress for the shared transport.
type Options struct {
	ProxyURL   string // optional http/socks upstream proxy to chain through
	BindAddress string // optional source IP for outbound sockets
	DialTimeout time.Duration
	IdleTimeout time.Duration
}

// NewTransport builds a pooled *http.Transport with HTTP/2 enabled (used for
// requests the agent forwards to upstream AI services).
func NewTransport(o Options, log *slog.Logger) (*http.Transport, error) {
	dialer := &net.Dialer{
		Timeout:   o.DialTimeout,
		KeepAlive: 30 * time.Second,
	}
	if o.BindAddress != "" {
		dialer.LocalAddr = &net.TCPAddr{IP: net.ParseIP(o.BindAddress)}
	}
	proxyFunc := func(*http.Request) (*url.URL, error) { return nil, nil }
	if o.ProxyURL != "" {
		pu, err := url.Parse(o.ProxyURL)
		if err != nil {
			return nil, err
		}
		proxyFunc = http.ProxyURL(pu)
	}
	tr := &http.Transport{
		Proxy:                 proxyFunc,
		DialContext:           dialer.DialContext,
		ForceAttemptHTTP2:     true,
		MaxIdleConns:          256,
		MaxIdleConnsPerHost:   64,
		IdleConnTimeout:       o.IdleTimeout,
		TLSHandshakeTimeout:   10 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
		TLSClientConfig:       &tls.Config{MinVersion: tls.VersionTLS12},
	}
	return tr, nil
}
