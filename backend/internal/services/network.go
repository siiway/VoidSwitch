package services

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"golang.org/x/net/proxy"
)

type Route struct {
	ProxyURL     *string
	LocalAddress *string
	IsDirect     bool
}

func NewRoute(proxyURL, localAddress *string) Route {
	return Route{
		ProxyURL:     proxyURL,
		LocalAddress: localAddress,
		IsDirect:     proxyURL == nil && localAddress == nil,
	}
}

func isSOCKS(u *string) bool {
	if u == nil {
		return false
	}
	s := strings.ToLower(*u)
	return strings.HasPrefix(s, "socks4://") ||
		strings.HasPrefix(s, "socks5://") ||
		strings.HasPrefix(s, "socks5h://") ||
		strings.HasPrefix(s, "socks4a://")
}

type ClientPool struct {
	clients map[string]*http.Client
	mu      sync.RWMutex
}

var pool *ClientPool
var poolOnce sync.Once

func GetPool() *ClientPool {
	poolOnce.Do(func() {
		pool = &ClientPool{
			clients: make(map[string]*http.Client),
		}
	})
	return pool
}

func (p *ClientPool) Get(route Route, connectTimeout, readTimeout time.Duration) (*http.Client, error) {
	key := p.hashKey(route, connectTimeout, readTimeout)

	p.mu.RLock()
	if client, ok := p.clients[key]; ok {
		p.mu.RUnlock()
		return client, nil
	}
	p.mu.RUnlock()

	p.mu.Lock()
	defer p.mu.Unlock()

	if client, ok := p.clients[key]; ok {
		return client, nil
	}

	transport := buildTransport(route)

	if connectTimeout > 0 || readTimeout > 0 {
		baseDial := transport.DialContext
		if baseDial == nil {
			baseDial = (&net.Dialer{}).DialContext
		}
		transport.DialContext = func(ctx context.Context, network, addr string) (net.Conn, error) {
			if connectTimeout > 0 {
				var cancel context.CancelFunc
				ctx, cancel = context.WithTimeout(ctx, connectTimeout)
				defer cancel()
			}
			return baseDial(ctx, network, addr)
		}
	}

	transport.ResponseHeaderTimeout = readTimeout

	client := &http.Client{
		Transport: transport,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	p.clients[key] = client
	return client, nil
}

func (p *ClientPool) Close() {
	p.mu.Lock()
	defer p.mu.Unlock()

	for _, client := range p.clients {
		transport, ok := client.Transport.(*http.Transport)
		if ok {
			transport.CloseIdleConnections()
		}
	}
	p.clients = make(map[string]*http.Client)
}

func (p *ClientPool) hashKey(route Route, connectTimeout, readTimeout time.Duration) string {
	h := sha256.New()
	if route.ProxyURL != nil {
		h.Write([]byte(*route.ProxyURL))
	} else {
		h.Write([]byte("nil"))
	}
	h.Write([]byte("|"))
	if route.LocalAddress != nil {
		h.Write([]byte(*route.LocalAddress))
	} else {
		h.Write([]byte("nil"))
	}
	h.Write([]byte("|"))
	fmt.Fprintf(h, "%d|%d", connectTimeout, readTimeout)
	return fmt.Sprintf("%x", h.Sum(nil))
}

func buildTransport(route Route) *http.Transport {
	transport := &http.Transport{
		MaxIdleConns:        200,
		MaxIdleConnsPerHost: 80,
		MaxConnsPerHost:     0,
		TLSNextProto:        make(map[string]func(authority string, c *tls.Conn) http.RoundTripper),
	}

	var baseDial func(ctx context.Context, network, addr string) (net.Conn, error)

	if route.ProxyURL != nil && isSOCKS(route.ProxyURL) {
		socksCfg, err := parseSOCKSProxyURL(*route.ProxyURL)
		if err != nil {
			baseDial = (&net.Dialer{}).DialContext
		} else {
			dialer, err := proxy.FromURL(socksCfg, proxy.Direct)
			if err != nil {
				baseDial = (&net.Dialer{}).DialContext
			} else if cd, ok := dialer.(proxy.ContextDialer); ok {
				baseDial = cd.DialContext
			} else {
				baseDial = func(ctx context.Context, network, addr string) (net.Conn, error) {
					return dialer.Dial(network, addr)
				}
			}
		}
	} else {
		baseDial = (&net.Dialer{}).DialContext

		if route.ProxyURL != nil {
			proxyURLStr := *route.ProxyURL
			transport.Proxy = func(req *http.Request) (*url.URL, error) {
				return url.Parse(proxyURLStr)
			}
		}
	}

	if route.LocalAddress != nil {
		localTCPAddr, err := net.ResolveTCPAddr("tcp", *route.LocalAddress)
		if err == nil && localTCPAddr != nil {
			bd := baseDial
			transport.DialContext = func(ctx context.Context, network, addr string) (net.Conn, error) {
				d := net.Dialer{LocalAddr: localTCPAddr}
				conn, err := d.DialContext(ctx, network, addr)
				if err != nil {
					return nil, err
				}
				return conn, nil
			}
			_ = bd
		} else {
			transport.DialContext = baseDial
		}
	} else {
		transport.DialContext = baseDial
	}

	return transport
}

func parseSOCKSProxyURL(raw string) (*url.URL, error) {
	u, err := url.Parse(raw)
	if err != nil {
		return nil, err
	}
	u.Scheme = "socks5"
	return u, nil
}

func ProbeRoute(route Route, targetURL string, headers map[string]string, timeout time.Duration) (ok bool, latencyMs float64, statusCode int, errStr string) {
	start := time.Now()

	transport := buildTransport(route)

	client := &http.Client{
		Transport: transport,
		Timeout:   timeout,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	req, err := http.NewRequest("GET", targetURL, nil)
	if err != nil {
		latencyMs = float64(time.Since(start).Microseconds()) / 1000.0
		return false, latencyMs, 0, err.Error()
	}

	for k, v := range headers {
		req.Header.Set(k, v)
	}

	resp, err := client.Do(req)
	if err != nil {
		latencyMs = float64(time.Since(start).Microseconds()) / 1000.0
		return false, latencyMs, 0, err.Error()
	}
	defer resp.Body.Close()

	latencyMs = float64(time.Since(start).Microseconds()) / 1000.0
	return true, latencyMs, resp.StatusCode, ""
}
