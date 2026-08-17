// Package auth provides constant-time token verification and a CIDR allowlist.
package auth

import (
	"crypto/subtle"
	"net"
	"net/http"
)

// Verifier authenticates requests arriving at the agent.
type Verifier struct {
	token       string
	allowedIPs  []*net.IPNet
	allowAllIPs bool
}

// New builds a Verifier. An empty token disables auth (not allowed by config).
// allowedCIDRs may be nil/empty to allow every source IP.
func New(token string, allowedCIDRs []string) (*Verifier, error) {
	v := &Verifier{token: token, allowAllIPs: true}
	for _, cidr := range allowedCIDRs {
		_, ipnet, err := net.ParseCIDR(cidr)
		if err != nil {
			return nil, err
		}
		v.allowedIPs = append(v.allowedIPs, ipnet)
		v.allowAllIPs = false
	}
	return v, nil
}

// Authorized checks the bearer token and source IP on a request.
func (v *Verifier) Authorized(r *http.Request) bool {
	if v == nil || v.token == "" {
		return false
	}
	const prefix = "Bearer "
	hd := r.Header.Get("Authorization")
	if len(hd) <= len(prefix) || hd[:len(prefix)] != prefix {
		// Also accept the token as a raw query/header fallback? Keep it strict:
		return false
	}
	given := hd[len(prefix):]
	if subtle.ConstantTimeCompare([]byte(given), []byte(v.token)) != 1 {
		return false
	}
	return v.ipAllowed(r.RemoteAddr)
}

func (v *Verifier) ipAllowed(remoteAddr string) bool {
	if v.allowAllIPs {
		return true
	}
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	ip := net.ParseIP(host)
	if ip == nil {
		return false
	}
	for _, n := range v.allowedIPs {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}
