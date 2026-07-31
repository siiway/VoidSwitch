package constants

type Role string

const (
	RoleOwner    Role = "owner"
	RoleCoOwner  Role = "co-owner"
	RoleAdmin    Role = "admin"
	RoleMember   Role = "member"
)

type KeyStatus string

const (
	KeyStatusActive             KeyStatus = "active"
	KeyStatusInvalid            KeyStatus = "invalid"
	KeyStatusInsufficientBalance KeyStatus = "insufficient_balance"
	KeyStatusRateLimited        KeyStatus = "rate_limited"
	KeyStatusDisabled           KeyStatus = "disabled"
)

type ProxyStatus string

const (
	ProxyStatusActive   ProxyStatus = "active"
	ProxyStatusDisabled ProxyStatus = "disabled"
)

type ApiStyle string

const (
	ApiStyleOpenAI           ApiStyle = "openai"
	ApiStyleAnthropic        ApiStyle = "anthropic"
	ApiStyleOpenAIResponses  ApiStyle = "openai-responses"
)

type ProxyMode string

const (
	ProxyModeAll      ProxyMode = "all"
	ProxyModeDirect   ProxyMode = "direct"
	ProxyModeSelected ProxyMode = "selected"
)

var DefaultSettings = map[string]any{
	"max_proxy_failures":                 3,
	"max_key_failures":                   3,
	"proxy_probe_interval_seconds":       120,
	"balance_probe_interval_seconds":     1800,
	"balance_rescan_interval_seconds":    86400,
	"rate_limit_recovery_seconds":        180,
	"rate_limit_max_cooldown_seconds":    3600,
	"balance_scan_rate_per_second":       5,
	"request_timeout_seconds":            300,
	"connect_timeout_seconds":            15,
	"max_retries":                        6,
	"stream_idle_timeout_seconds":        120,
	"auto_disable_zero_balance":          true,
	"balance_probe_enabled":              true,
	"balance_rescan_enabled":             true,
	"proxy_switching_enabled":            true,
	"proxy_health_check_enabled":         true,
	"static_proxy_url":                   "",
	"proxy_probe_url":                    "https://api.openai.com/v1/models",
	"opencode_default_model":             "claude-opus-4-8",
	"opencode_small_model":               "claude-haiku-4-5-20251001",
	"audit_log_retention_days":           0,
	"request_log_retention_days":         0,
	"debug_log_retention_days":           0,
	"heatmap_retention_days":             365,
	"log_cleanup_enabled":                true,
	"log_cleanup_interval_seconds":       86400,
	"logs_page_size":                     50,
	"announcements_home_count":           3,
	"operation_rate_limit_window_seconds": 10,
	"operation_rate_limit_max_requests":  0,
	"call_rate_limit_window_seconds":     60,
	"call_rate_limit_max_requests":       0,
}

var OwnerRoles = []Role{RoleOwner, RoleCoOwner}

var StaffRoles = []Role{RoleOwner, RoleCoOwner, RoleAdmin}

const VoidTokenPrefix = "vs-"

const KeyAPITokenPrefix = "vsk-"

const ModeratorGroupSlug = "moderator"

var TeamRoleRank = map[string]int{
	"owner":   4,
	"co-owner": 3,
	"admin":   2,
	"member":  1,
}
