package config

import (
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"gopkg.in/yaml.v3"
)

type ServerSettings struct {
	Host              string   `yaml:"host" env:"VOIDSWITCH_SERVER__HOST"`
	Port              int      `yaml:"port" env:"VOIDSWITCH_SERVER__PORT"`
	BaseURL           string   `yaml:"base_url" env:"VOIDSWITCH_SERVER__BASE_URL"`
	FrontendURL       string   `yaml:"frontend_url" env:"VOIDSWITCH_SERVER__FRONTEND_URL"`
	CorsOrigins       []string `yaml:"cors_origins" env:"VOIDSWITCH_SERVER__CORS_ORIGINS"`
	SecretKey         string   `yaml:"secret_key" env:"VOIDSWITCH_SERVER__SECRET_KEY"`
	SessionTTLMinutes int      `yaml:"session_ttl_minutes" env:"VOIDSWITCH_SERVER__SESSION_TTL_MINUTES"`
	LogLevel          string   `yaml:"log_level" env:"VOIDSWITCH_SERVER__LOG_LEVEL"`
	LogConsole        bool     `yaml:"log_console" env:"VOIDSWITCH_SERVER__LOG_CONSOLE"`
	Debug             bool     `yaml:"debug" env:"VOIDSWITCH_SERVER__DEBUG"`
	DevMode           bool     `yaml:"dev_mode" env:"VOIDSWITCH_SERVER__DEV_MODE"`
	DocsDir           string   `yaml:"docs_dir" env:"VOIDSWITCH_SERVER__DOCS_DIR"`
}

type DatabaseSettings struct {
	URL  string `yaml:"url" env:"VOIDSWITCH_DATABASE__URL"`
	Echo bool   `yaml:"echo" env:"VOIDSWITCH_DATABASE__ECHO"`
}

type PrismSettings struct {
	Issuer       string   `yaml:"issuer" env:"VOIDSWITCH_PRISM__ISSUER"`
	ClientID     string   `yaml:"client_id" env:"VOIDSWITCH_PRISM__CLIENT_ID"`
	ClientSecret string   `yaml:"client_secret" env:"VOIDSWITCH_PRISM__CLIENT_SECRET"`
	RedirectURI  string   `yaml:"redirect_uri" env:"VOIDSWITCH_PRISM__REDIRECT_URI"`
	Scopes       []string `yaml:"scopes" env:"VOIDSWITCH_PRISM__SCOPES"`
}

func (p PrismSettings) AuthorizeURL() string {
	return fmt.Sprintf("%s/api/oauth/authorize", strings.TrimRight(p.Issuer, "/"))
}

func (p PrismSettings) TokenURL() string {
	return fmt.Sprintf("%s/api/oauth/token", strings.TrimRight(p.Issuer, "/"))
}

func (p PrismSettings) UserinfoURL() string {
	return fmt.Sprintf("%s/api/oauth/userinfo", strings.TrimRight(p.Issuer, "/"))
}

func (p PrismSettings) JwksURL() string {
	return fmt.Sprintf("%s/.well-known/jwks.json", strings.TrimRight(p.Issuer, "/"))
}

type AdminSettings struct {
	OwnerSubs           []string `yaml:"owner_subs" env:"VOIDSWITCH_ADMIN__OWNER_SUBS"`
	OwnerEmails         []string `yaml:"owner_emails" env:"VOIDSWITCH_ADMIN__OWNER_EMAILS"`
	TrustPrismAdmin     bool     `yaml:"trust_prism_admin" env:"VOIDSWITCH_ADMIN__TRUST_PRISM_ADMIN"`
	BootstrapFirstUser  bool     `yaml:"bootstrap_first_user" env:"VOIDSWITCH_ADMIN__BOOTSTRAP_FIRST_USER"`
}

type Settings struct {
	Server   ServerSettings   `yaml:"server"`
	Database DatabaseSettings `yaml:"database"`
	Prism    PrismSettings    `yaml:"prism"`
	Admin    AdminSettings    `yaml:"admin"`
}

var (
	cfg  *Settings
	once sync.Once
)

func Load() *Settings {
	once.Do(func() {
		cfg = loadConfig()
	})
	return cfg
}

func loadConfig() *Settings {
	root := projectRoot()
	s := defaults()

	yamlPath := configPath(root)
	if data, err := os.ReadFile(yamlPath); err == nil {
		var yamlCfg Settings
		if err := yaml.Unmarshal(data, &yamlCfg); err == nil {
			mergeYaml(s, &yamlCfg)
		}
	}

	applyEnvOverrides(s)

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
			FrontendURL:       "",
			CorsOrigins:       []string{"http://localhost:5173"},
			SecretKey:         "",
			SessionTTLMinutes: 720,
			LogLevel:          "INFO",
			LogConsole:        true,
			Debug:             false,
			DevMode:           false,
		},
		Database: DatabaseSettings{
			URL:  "voidswitch.db",
			Echo: false,
		},
		Prism: PrismSettings{
			Issuer:       "https://prism.siiway.org",
			ClientID:     "",
			ClientSecret: "",
			RedirectURI:  "",
			Scopes:       []string{"openid", "profile", "email"},
		},
		Admin: AdminSettings{
			OwnerSubs:          nil,
			OwnerEmails:        nil,
			TrustPrismAdmin:    true,
			BootstrapFirstUser: true,
		},
	}
}

func mergeYaml(target *Settings, source *Settings) {
	mergeServer(&target.Server, &source.Server)
	mergeDatabase(&target.Database, &source.Database)
	mergePrism(&target.Prism, &source.Prism)
	mergeAdmin(&target.Admin, &source.Admin)
}

func mergeServer(target *ServerSettings, source *ServerSettings) {
	if source.Host != "" {
		target.Host = source.Host
	}
	if source.Port != 0 {
		target.Port = source.Port
	}
	if source.BaseURL != "" {
		target.BaseURL = source.BaseURL
	}
	if source.FrontendURL != "" {
		target.FrontendURL = source.FrontendURL
	}
	if source.CorsOrigins != nil {
		target.CorsOrigins = source.CorsOrigins
	}
	if source.SecretKey != "" {
		target.SecretKey = source.SecretKey
	}
	if source.SessionTTLMinutes != 0 {
		target.SessionTTLMinutes = source.SessionTTLMinutes
	}
	if source.LogLevel != "" {
		target.LogLevel = source.LogLevel
	}
	if source.LogConsole {
		target.LogConsole = source.LogConsole
	}
	if source.Debug {
		target.Debug = source.Debug
	}
	if source.DevMode {
		target.DevMode = source.DevMode
	}
}

func mergeDatabase(target *DatabaseSettings, source *DatabaseSettings) {
	if source.URL != "" {
		target.URL = source.URL
	}
	if source.Echo {
		target.Echo = source.Echo
	}
}

func mergePrism(target *PrismSettings, source *PrismSettings) {
	if source.Issuer != "" {
		target.Issuer = source.Issuer
	}
	if source.ClientID != "" {
		target.ClientID = source.ClientID
	}
	if source.ClientSecret != "" {
		target.ClientSecret = source.ClientSecret
	}
	if source.RedirectURI != "" {
		target.RedirectURI = source.RedirectURI
	}
	if source.Scopes != nil {
		target.Scopes = source.Scopes
	}
}

func mergeAdmin(target *AdminSettings, source *AdminSettings) {
	if source.OwnerSubs != nil {
		target.OwnerSubs = source.OwnerSubs
	}
	if source.OwnerEmails != nil {
		target.OwnerEmails = source.OwnerEmails
	}
	if source.TrustPrismAdmin {
		target.TrustPrismAdmin = source.TrustPrismAdmin
	}
	if source.BootstrapFirstUser {
		target.BootstrapFirstUser = source.BootstrapFirstUser
	}
}

func applyEnvOverrides(s *Settings) {
	envVars := map[string]func(string){
		"VOIDSWITCH_SERVER__HOST":                  func(v string) { s.Server.Host = v },
		"VOIDSWITCH_SERVER__PORT":                  func(v string) { s.Server.Port = parseInt(v) },
		"VOIDSWITCH_SERVER__BASE_URL":              func(v string) { s.Server.BaseURL = v },
		"VOIDSWITCH_SERVER__FRONTEND_URL":          func(v string) { s.Server.FrontendURL = v },
		"VOIDSWITCH_SERVER__CORS_ORIGINS":          func(v string) { s.Server.CorsOrigins = splitCSV(v) },
		"VOIDSWITCH_SERVER__SECRET_KEY":            func(v string) { s.Server.SecretKey = v },
		"VOIDSWITCH_SERVER__SESSION_TTL_MINUTES":   func(v string) { s.Server.SessionTTLMinutes = parseInt(v) },
		"VOIDSWITCH_SERVER__LOG_LEVEL":             func(v string) { s.Server.LogLevel = v },
		"VOIDSWITCH_SERVER__LOG_CONSOLE":           func(v string) { s.Server.LogConsole = parseBool(v) },
		"VOIDSWITCH_SERVER__DEBUG":                 func(v string) { s.Server.Debug = parseBool(v) },
		"VOIDSWITCH_SERVER__DEV_MODE":              func(v string) { s.Server.DevMode = parseBool(v) },
		"VOIDSWITCH_DATABASE__URL":                 func(v string) { s.Database.URL = v },
		"VOIDSWITCH_DATABASE__ECHO":                func(v string) { s.Database.Echo = parseBool(v) },
		"VOIDSWITCH_PRISM__ISSUER":                 func(v string) { s.Prism.Issuer = v },
		"VOIDSWITCH_PRISM__CLIENT_ID":              func(v string) { s.Prism.ClientID = v },
		"VOIDSWITCH_PRISM__CLIENT_SECRET":          func(v string) { s.Prism.ClientSecret = v },
		"VOIDSWITCH_PRISM__REDIRECT_URI":           func(v string) { s.Prism.RedirectURI = v },
		"VOIDSWITCH_PRISM__SCOPES":                 func(v string) { s.Prism.Scopes = splitCSV(v) },
		"VOIDSWITCH_ADMIN__OWNER_SUBS":             func(v string) { s.Admin.OwnerSubs = splitCSV(v) },
		"VOIDSWITCH_ADMIN__OWNER_EMAILS":           func(v string) { s.Admin.OwnerEmails = splitCSV(v) },
		"VOIDSWITCH_ADMIN__TRUST_PRISM_ADMIN":      func(v string) { s.Admin.TrustPrismAdmin = parseBool(v) },
		"VOIDSWITCH_ADMIN__BOOTSTRAP_FIRST_USER":   func(v string) { s.Admin.BootstrapFirstUser = parseBool(v) },
	}

	for _, e := range os.Environ() {
		parts := strings.SplitN(e, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key, val := parts[0], parts[1]
		if setter, ok := envVars[key]; ok {
			setter(val)
		}
	}
}

func splitCSV(s string) []string {
	if s == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			result = append(result, p)
		}
	}
	return result
}

func parseInt(s string) int {
	var n int
	fmt.Sscanf(s, "%d", &n)
	return n
}

func parseBool(s string) bool {
	switch strings.ToLower(s) {
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
	return fmt.Sprintf("%s/api/auth/callback", strings.TrimRight(s.Server.BaseURL, "/"))
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
		key := strings.TrimSpace(string(data))
		if key != "" {
			return key
		}
	}
	key := make([]byte, 48)
	if _, err := rand.Read(key); err != nil {
		b := make([]byte, 48)
		for i := range b {
			b[i] = byte(i ^ 0x55)
		}
		key = b
	}
	encoded := base64.URLEncoding.EncodeToString(key)
	_ = os.WriteFile(path, []byte(encoded), 0600)
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
			break
		}
		dir = parent
	}
	return "."
}

func configPath(root string) string {
	if env := os.Getenv("VOIDSWITCH_CONFIG"); env != "" {
		return env
	}
	return filepath.Join(root, "config.yaml")
}

func ResetForTesting() {
	once = sync.Once{}
	cfg = nil
}
