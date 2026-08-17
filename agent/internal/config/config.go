// Package config holds the voidswitch-agent runtime configuration, sourced
// from flags, environment variables, then defaults (flags > env > defaults).
package config

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// ErrHelp is returned by Parse when -h/--help was requested.
var ErrHelp = errors.New("help requested")

// Config is the immutable agent configuration resolved at startup.
type Config struct {
	// Listen address, e.g. ":8443".
	Listen string
	// Preshared token required on every relay request (constant-time compared).
	Token string
	// TLS certificate/key. When both are empty the agent serves plain HTTP
	// (intended to sit behind Caddy/nginx which terminates TLS).
	TLSCert string
	TLSKey  string
	// Mode: "relay" (custom X-VS-Upstream-URL H2 relay) or "connect"
	// (standard HTTP CONNECT forward proxy).
	Mode string
	// Egress options.
	UpstreamProxy string // chain outbound through another http/socks proxy
	BindAddress   string // bind outbound sockets to this source IP
	// Comma-separated CIDRs allowed to connect. Empty = allow all.
	AllowlistIPs []string
	// Timeouts.
	IdleTimeout  int // seconds for relay streams / CONNECT idle
	MaxStreams   int // relay: max concurrent H2 streams (0 = server default)
	DialTimeout  int // seconds
	LogLevel     string
	// Optional metrics path; empty = disabled.
	MetricsPath string
}

// EnvVar is the environment variable name for a config entry, to document them.
const (
	EnvListen      = "VOIDSWITCH_AGENT_LISTEN"
	EnvToken       = "VOIDSWITCH_AGENT_TOKEN"
	EnvTLSCert     = "VOIDSWITCH_AGENT_TLS_CERT"
	EnvTLSKey      = "VOIDSWITCH_AGENT_TLS_KEY"
	EnvMode        = "VOIDSWITCH_AGENT_MODE"
	EnvProxy       = "VOIDSWITCH_AGENT_UPSTREAM_PROXY"
	EnvBind        = "VOIDSWITCH_AGENT_BIND_ADDRESS"
	EnvAllowlist   = "VOIDSWITCH_AGENT_ALLOWLIST_IPS"
	EnvIdleTimeout = "VOIDSWITCH_AGENT_IDLE_TIMEOUT"
	EnvMaxStreams  = "VOIDSWITCH_AGENT_MAX_STREAMS"
	EnvDialTimeout = "VOIDSWITCH_AGENT_DIAL_TIMEOUT"
	EnvLogLevel    = "VOIDSWITCH_AGENT_LOG_LEVEL"
	EnvMetrics     = "VOIDSWITCH_AGENT_METRICS_PATH"
)

func env(key, def string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v, ok := os.LookupEnv(key); ok {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

// UpstreamTargetHeader is the custom header carrying the real upstream URL.
const UpstreamTargetHeader = "X-VS-Upstream-URL"

// Parse builds a Config from the command line, environment, then defaults.
func Parse(args []string) (*Config, error) {
	fs := flag.NewFlagSet("voidswitch-agent", flag.ContinueOnError)
	fs.Usage = func() {
		fmt.Fprintf(fs.Output(), "voidswitch-agent — a minimal VS-native outbound relay.\n\n")
		fs.PrintDefaults()
	}

	var (
		listen   = fs.String("listen", env(EnvListen, ":8443"), "listen address")
		token    = fs.String("token", env(EnvToken, ""), "preshared auth token")
		tlsCert  = fs.String("tls-cert", env(EnvTLSCert, ""), "TLS certificate file (optional)")
		tlsKey   = fs.String("tls-key", env(EnvTLSKey, ""), "TLS private key file (optional)")
		mode     = fs.String("mode", env(EnvMode, "relay"), "relay | connect")
		proxy    = fs.String("upstream-proxy", env(EnvProxy, ""), "chain egress through this proxy")
		bind     = fs.String("bind-address", env(EnvBind, ""), "bind outbound to this source IP")
		allow    = fs.String("allowlist-ips", env(EnvAllowlist, ""), "comma-separated CIDR allowlist")
		idle     = fs.Int("idle-timeout", envInt(EnvIdleTimeout, 120), "idle/stream seconds")
		maxStr   = fs.Int("max-streams", envInt(EnvMaxStreams, 0), "max concurrent H2 streams")
		dialT    = fs.Int("dial-timeout", envInt(EnvDialTimeout, 15), "dial seconds")
		logLvl   = fs.String("log-level", env(EnvLogLevel, "info"), "debug|info|warn|error")
		metrics  = fs.String("metrics-path", env(EnvMetrics, "/metrics"), "metrics endpoint (empty=off)")
	)

	// Parse returns flag.ErrHelp on -h; map it to our sentinel.
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil, ErrHelp
		}
		return nil, err
	}

	if strings.TrimSpace(*token) == "" {
		return nil, fmt.Errorf("a --token (or %s) is required", EnvToken)
	}
	if *idle <= 0 {
		*idle = 120
	}
	m := strings.ToLower(strings.TrimSpace(*mode))
	if m != "relay" && m != "connect" {
		return nil, fmt.Errorf("mode must be 'relay' or 'connect'")
	}
	allowlist := splitCsv(*allow)
	return &Config{
		Listen:        strings.TrimSpace(*listen),
		Token:         strings.TrimSpace(*token),
		TLSCert:       strings.TrimSpace(*tlsCert),
		TLSKey:        strings.TrimSpace(*tlsKey),
		Mode:          m,
		UpstreamProxy: strings.TrimSpace(*proxy),
		BindAddress:   strings.TrimSpace(*bind),
		AllowlistIPs:  allowlist,
		IdleTimeout:   *idle,
		MaxStreams:    *maxStr,
		DialTimeout:   *dialT,
		LogLevel:      strings.ToLower(strings.TrimSpace(*logLvl)),
		MetricsPath:   strings.TrimSpace(*metrics),
	}, nil
}

func splitCsv(s string) []string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	var out []string
	for _, p := range strings.Split(s, ",") {
		if t := strings.TrimSpace(p); t != "" {
			out = append(out, t)
		}
	}
	return out
}
