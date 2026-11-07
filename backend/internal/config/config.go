// Package config loads VoidSwitch configuration from a YAML file and
// VOIDSWITCH_* environment variables (with "__" as the nesting separator),
// matching the Python backend's precedence: env > YAML > defaults.
package config

import (
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

type ServerSettings struct {
	Host              string   `yaml:"host"`
	Port              int      `yaml:"port"`
	BaseURL           string   `yaml:"base_url"`
	FrontendURL       string   `yaml:"frontend_url"`
	CorsOrigins       []string `yaml:"cors_origins"`
	SecretKey         string   `yaml:"secret_key"`
	SessionTTLMinutes int      `yaml:"session_ttl_minutes"`
	LogLevel          string   `yaml:"log_level"`
	LogConsole        bool     `yaml:"log_console"`
	Debug             bool     `yaml:"debug"`
	DevMode           bool     `yaml:"dev_mode"`
	DocsDir           string   `yaml:"docs_dir"`
}

type DatabaseSettings struct {
	URL  string `yaml:"url"`
	Echo bool   `yaml:"echo"`
}

type RedisSettings struct {
	URL            string  `yaml:"url"`
	KeyPrefix      string  `yaml:"key_prefix"`
	MaxConnections int     `yaml:"max_connections"`
	ConnectTimeout float64 `yaml:"connect_timeout"`
	SocketTimeout  float64 `yaml:"socket_timeout"`
}

type PrismSettings struct {
	Issuer       string   `yaml:"issuer"`
	ClientID     string   `yaml:"client_id"`
	ClientSecret string   `yaml:"client_secret"`
	RedirectURI  string   `yaml:"redirect_uri"`
	Scopes       []string `yaml:"scopes"`
}

func (p PrismSettings) AuthorizeURL() string {
	return strings.TrimRight(p.Issuer, "/") + "/api/oauth/authorize"
}
func (p PrismSettings) TokenURL() string {
	return strings.TrimRight(p.Issuer, "/") + "/api/oauth/token"
}
func (p PrismSettings) UserinfoURL() string {
	return strings.TrimRight(p.Issuer, "/") + "/api/oauth/userinfo"
}
func (p PrismSettings) JwksURL() string {
	return strings.TrimRight(p.Issuer, "/") + "/.well-known/jwks.json"
}

type AdminSettings struct {
	OwnerSubs          []string `yaml:"owner_subs"`
	OwnerEmails        []string `yaml:"owner_emails"`
	BootstrapFirstUser bool     `yaml:"bootstrap_first_user"`
	MainTeamID         string   `yaml:"main_team_id"`
}

type Settings struct {
	Server   ServerSettings   `yaml:"server"`
	Database DatabaseSettings `yaml:"database"`
	Redis    RedisSettings    `yaml:"redis"`
	Prism    PrismSettings    `yaml:"prism"`
	Admin    AdminSettings    `yaml:"admin"`

	// DevOnlyAuthBypass mirrors VOIDSWITCH_DEV_SKIP_AUTH. It is only honoured
	// when Environment == "development"; production refuses to start with it set.
	DevOnlyAuthBypass bool
	Environment       string
}

var (
	cfg  *Settings
	once sync.Once
)

func Load() *Settings {
	once.Do(func() { cfg = loadConfig() })
	return cfg
}

func ResetForTesting() { once = sync.Once{}; cfg = nil }

func loadConfig() *Settings {
	root := projectRoot()
	s := defaults()

	if data, err := os.ReadFile(configPath(root)); err == nil {
		var yamlCfg Settings
		if err := yaml.Unmarshal(data, &yamlCfg); err == nil {
			mergeYAML(s, &yamlCfg)
		}
	}

	applyEnv(s)

	s.Prism.RedirectURI = finalizeRedirectURI(s)
	s.Server.SecretKey = finalizeSecretKey(root, s.Server.SecretKey)
	s.Server.FrontendURL = finalizeFrontendURL(s)

	return s
}

func defaults() *Settings {
	return &Settings{
		Server: ServerSettings{
			Host:              "0.0.0.0",
			Port:              8080,
			BaseURL:           "http://localhost:8080",
			CorsOrigins:       []string{"http://localhost:5173", "http://localhost:4173"},
			SessionTTLMinutes: 720,
			LogLevel:          "INFO",
			LogConsole:        true,
		},
		Database: DatabaseSettings{
			URL: "postgres://localhost:5432/voidswitch?sslmode=disable",
		},
		Redis: RedisSettings{
			URL:            "redis://localhost:6379/0",
			KeyPrefix:      "voidswitch",
			MaxConnections: 50,
			ConnectTimeout: 2.0,
			SocketTimeout:  2.0,
		},
		Prism: PrismSettings{
			Issuer: "https://prism.siiway.org",
			Scopes: []string{"openid", "profile", "email", "teams:read"},
		},
		Admin: AdminSettings{
			BootstrapFirstUser: true,
		},
		Environment: envOr("VOIDSWITCH_ENV", "production"),
	}
}

func mergeYAML(target, src *Settings) {
	if src.Server.Host != "" {
		target.Server.Host = src.Server.Host
	}
	if src.Server.Port != 0 {
		target.Server.Port = src.Server.Port
	}
	if src.Server.BaseURL != "" {
		target.Server.BaseURL = src.Server.BaseURL
	}
	if src.Server.FrontendURL != "" {
		target.Server.FrontendURL = src.Server.FrontendURL
	}
	if src.Server.CorsOrigins != nil {
		target.Server.CorsOrigins = src.Server.CorsOrigins
	}
	if src.Server.SecretKey != "" {
		target.Server.SecretKey = src.Server.SecretKey
	}
	if src.Server.SessionTTLMinutes != 0 {
		target.Server.SessionTTLMinutes = src.Server.SessionTTLMinutes
	}
	if src.Server.LogLevel != "" {
		target.Server.LogLevel = src.Server.LogLevel
	}
	if src.Server.LogConsole {
		target.Server.LogConsole = true
	}
	if src.Server.Debug {
		target.Server.Debug = true
	}
	if src.Server.DevMode {
		target.Server.DevMode = true
	}
	if src.Server.DocsDir != "" {
		target.Server.DocsDir = src.Server.DocsDir
	}
	if src.Database.URL != "" {
		target.Database.URL = src.Database.URL
	}
	if src.Database.Echo {
		target.Database.Echo = true
	}
	if src.Redis.URL != "" {
		target.Redis.URL = src.Redis.URL
	}
	if src.Redis.KeyPrefix != "" {
		target.Redis.KeyPrefix = src.Redis.KeyPrefix
	}
	if src.Redis.MaxConnections != 0 {
		target.Redis.MaxConnections = src.Redis.MaxConnections
	}
	if src.Prism.Issuer != "" {
		target.Prism.Issuer = src.Prism.Issuer
	}
	if src.Prism.ClientID != "" {
		target.Prism.ClientID = src.Prism.ClientID
	}
	if src.Prism.ClientSecret != "" {
		target.Prism.ClientSecret = src.Prism.ClientSecret
	}
	if src.Prism.RedirectURI != "" {
		target.Prism.RedirectURI = src.Prism.RedirectURI
	}
	if src.Prism.Scopes != nil {
		target.Prism.Scopes = src.Prism.Scopes
	}
	if src.Admin.OwnerSubs != nil {
		target.Admin.OwnerSubs = src.Admin.OwnerSubs
	}
	if src.Admin.OwnerEmails != nil {
		target.Admin.OwnerEmails = src.Admin.OwnerEmails
	}
	if src.Admin.MainTeamID != "" {
		target.Admin.MainTeamID = src.Admin.MainTeamID
	}
}

// applyEnv reads VOIDSWITCH_* overrides. Empty values are ignored.
func applyEnv(s *Settings) {
	for k, v := range envMap() {
		if v == "" {
			continue
		}
		switch k {
		case "VOIDSWITCH_SERVER__HOST":
			s.Server.Host = v
		case "VOIDSWITCH_SERVER__PORT":
			s.Server.Port = atoi(v)
		case "VOIDSWITCH_SERVER__BASE_URL":
			s.Server.BaseURL = v
		case "VOIDSWITCH_SERVER__FRONTEND_URL":
			s.Server.FrontendURL = v
		case "VOIDSWITCH_SERVER__CORS_ORIGINS":
			s.Server.CorsOrigins = splitCSV(v)
		case "VOIDSWITCH_SERVER__SECRET_KEY":
			s.Server.SecretKey = v
		case "VOIDSWITCH_SERVER__SESSION_TTL_MINUTES":
			s.Server.SessionTTLMinutes = atoi(v)
		case "VOIDSWITCH_SERVER__LOG_LEVEL":
			s.Server.LogLevel = v
		case "VOIDSWITCH_SERVER__LOG_CONSOLE":
			s.Server.LogConsole = atob(v)
		case "VOIDSWITCH_SERVER__DEBUG":
			s.Server.Debug = atob(v)
		case "VOIDSWITCH_SERVER__DEV_MODE":
			s.Server.DevMode = atob(v)
		case "VOIDSWITCH_SERVER__DOCS_DIR":
			s.Server.DocsDir = v
		case "VOIDSWITCH_DATABASE__URL":
			s.Database.URL = v
		case "VOIDSWITCH_DATABASE__ECHO":
			s.Database.Echo = atob(v)
		case "VOIDSWITCH_REDIS__URL":
			s.Redis.URL = v
		case "VOIDSWITCH_REDIS__KEY_PREFIX":
			s.Redis.KeyPrefix = v
		case "VOIDSWITCH_REDIS__MAX_CONNECTIONS":
			s.Redis.MaxConnections = atoi(v)
		case "VOIDSWITCH_PRISM__ISSUER":
			s.Prism.Issuer = v
		case "VOIDSWITCH_PRISM__CLIENT_ID":
			s.Prism.ClientID = v
		case "VOIDSWITCH_PRISM__CLIENT_SECRET":
			s.Prism.ClientSecret = v
		case "VOIDSWITCH_PRISM__REDIRECT_URI":
			s.Prism.RedirectURI = v
		case "VOIDSWITCH_PRISM__SCOPES":
			s.Prism.Scopes = splitCSV(v)
		case "VOIDSWITCH_ADMIN__OWNER_SUBS":
			s.Admin.OwnerSubs = splitCSV(v)
		case "VOIDSWITCH_ADMIN__OWNER_EMAILS":
			s.Admin.OwnerEmails = splitCSV(v)
		case "VOIDSWITCH_ADMIN__BOOTSTRAP_FIRST_USER":
			s.Admin.BootstrapFirstUser = atob(v)
		case "VOIDSWITCH_ADMIN__MAIN_TEAM_ID":
			s.Admin.MainTeamID = v
		case "VOIDSWITCH_DEV_SKIP_AUTH":
			s.DevOnlyAuthBypass = atob(v)
		case "VOIDSWITCH_ENV":
			s.Environment = v
		}
	}
}

func envMap() map[string]string {
	out := map[string]string{}
	for _, e := range os.Environ() {
		i := strings.IndexByte(e, '=')
		if i <= 0 {
			continue
		}
		out[e[:i]] = e[i+1:]
	}
	return out
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func splitCSV(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func atoi(s string) int { n, _ := strconv.Atoi(strings.TrimSpace(s)); return n }

func atob(s string) bool {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

func finalizeRedirectURI(s *Settings) string {
	if s.Prism.RedirectURI != "" {
		return s.Prism.RedirectURI
	}
	return strings.TrimRight(s.Server.BaseURL, "/") + "/api/auth/callback"
}

func finalizeFrontendURL(s *Settings) string {
	if s.Server.FrontendURL != "" {
		return s.Server.FrontendURL
	}
	if len(s.Server.CorsOrigins) > 0 {
		return s.Server.CorsOrigins[0]
	}
	return ""
}

func finalizeSecretKey(root, current string) string {
	if current != "" {
		return current
	}
	return loadOrCreateSecret(root)
}

func loadOrCreateSecret(root string) string {
	path := filepath.Join(root, ".secret_key")
	if data, err := os.ReadFile(path); err == nil {
		if k := strings.TrimSpace(string(data)); k != "" {
			return k
		}
	}
	key := make([]byte, 48)
	_, _ = rand.Read(key)
	encoded := base64.URLEncoding.EncodeToString(key)
	_ = os.WriteFile(path, []byte(encoded), 0o600)
	return encoded
}

func projectRoot() string {
	if root := os.Getenv("VOIDSWITCH_ROOT"); root != "" {
		return root
	}
	dir, err := os.Getwd()
	if err != nil {
		return "."
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "."
		}
		dir = parent
	}
}

func configPath(root string) string {
	if env := os.Getenv("VOIDSWITCH_CONFIG"); env != "" {
		return env
	}
	return filepath.Join(root, "config.yaml")
}

// Validate enforces the dev-bypass safety rules. Called at startup.
func (s *Settings) Validate() error {
	prod := strings.EqualFold(s.Environment, "production")
	if s.DevOnlyAuthBypass {
		if prod {
			return fmt.Errorf("VOIDSWITCH_DEV_SKIP_AUTH cannot be enabled in production (VOIDSWITCH_ENV=%s)", s.Environment)
		}
		if !strings.EqualFold(s.Environment, "development") && !strings.EqualFold(s.Environment, "dev") {
			return fmt.Errorf("VOIDSWITCH_DEV_SKIP_AUTH requires VOIDSWITCH_ENV=development, got %q", s.Environment)
		}
	}
	return nil
}

// DevAuthBypassActive reports whether the login bypass is actually in effect:
// the flag is set AND the environment is explicitly development.
func (s *Settings) DevAuthBypassActive() bool {
	if !s.DevOnlyAuthBypass {
		return false
	}
	return strings.EqualFold(s.Environment, "development") || strings.EqualFold(s.Environment, "dev")
}
