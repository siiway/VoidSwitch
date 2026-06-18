package models

import "time"

// Auth

type LoginStart struct {
	AuthorizeURL string `json:"authorize_url"`
	State        string `json:"state"`
}

type UserOut struct {
	ID          int        `json:"id"`
	Sub         string     `json:"sub"`
	Username    *string    `json:"username"`
	Email       *string    `json:"email"`
	Name        *string    `json:"name"`
	Picture     *string    `json:"picture"`
	Role        string     `json:"role"`
	PrismRole   *string    `json:"prism_role"`
	Enabled     bool       `json:"enabled"`
	LastLoginAt *time.Time `json:"last_login_at"`
	CreatedAt   time.Time  `json:"created_at"`
}

type SessionOut struct {
	AccessToken string  `json:"access_token"`
	TokenType   string  `json:"token_type"`
	ExpiresIn   int     `json:"expires_in"`
	User        UserOut `json:"user"`
}

// ModelRoute

type ModelRoute struct {
	Alias    string `json:"alias"`
	Upstream string `json:"upstream"`
	Pool     string `json:"pool"`
}

// Providers

type ProviderCreate struct {
	Name                      string            `json:"name"`
	Type                      string            `json:"type"`
	BaseURL                   string            `json:"base_url"`
	Enabled                   *bool             `json:"enabled"`
	Priority                  int               `json:"priority"`
	Weight                    int               `json:"weight"`
	Models                    []string          `json:"models"`
	ModelMap                  map[string]string `json:"model_map"`
	BalanceURL                *string           `json:"balance_url"`
	ExtraHeaders              map[string]string `json:"extra_headers"`
	TimeoutSeconds            int               `json:"timeout_seconds"`
	DropOpenCodeIdentityBlock *bool             `json:"drop_opencode_identity_block"`
	ProxyMode                 string            `json:"proxy_mode"`
	ProxyIDs                  []int             `json:"proxy_ids"`
	ModelRoutes               []ModelRoute      `json:"model_routes"`
}

type ProviderUpdate struct {
	Name                      *string            `json:"name,omitempty"`
	Type                      *string            `json:"type,omitempty"`
	BaseURL                   *string            `json:"base_url,omitempty"`
	Enabled                   *bool              `json:"enabled,omitempty"`
	Priority                  *int               `json:"priority,omitempty"`
	Weight                    *int               `json:"weight,omitempty"`
	Models                    *[]string          `json:"models,omitempty"`
	ModelMap                  *map[string]string `json:"model_map,omitempty"`
	BalanceURL                *string            `json:"balance_url,omitempty"`
	ExtraHeaders              *map[string]string `json:"extra_headers,omitempty"`
	TimeoutSeconds            *int               `json:"timeout_seconds,omitempty"`
	DropOpenCodeIdentityBlock *bool              `json:"drop_opencode_identity_block,omitempty"`
	ProxyMode                 *string            `json:"proxy_mode,omitempty"`
	ProxyIDs                  *[]int             `json:"proxy_ids,omitempty"`
	ModelRoutes               *[]ModelRoute      `json:"model_routes,omitempty"`
}

type ProviderOut struct {
	ID                      int               `json:"id"`
	Name                    string            `json:"name"`
	Type                    string            `json:"type"`
	BaseURL                 string            `json:"base_url"`
	Enabled                 bool              `json:"enabled"`
	Priority                int               `json:"priority"`
	Weight                  int               `json:"weight"`
	Models                  []string          `json:"models"`
	ModelMap                map[string]string `json:"model_map"`
	BalanceURL              *string           `json:"balance_url"`
	ExtraHeaders            map[string]string `json:"extra_headers"`
	TimeoutSeconds          int               `json:"timeout_seconds"`
	DropOpenCodeIdentityBlock bool            `json:"drop_opencode_identity_block"`
	ProxyMode               string            `json:"proxy_mode"`
	ProxyIDs                []int             `json:"proxy_ids"`
	ModelRoutes             []ModelRoute      `json:"model_routes"`
	KeyCount                int               `json:"key_count"`
	ActiveKeyCount          int               `json:"active_key_count"`
	SupportsBalance         bool              `json:"supports_balance"`
	AddedBy                 *int              `json:"added_by"`
	AddedByName             *string           `json:"added_by_name"`
	CreatedAt               time.Time         `json:"created_at"`
	UpdatedAt               time.Time         `json:"updated_at"`
}

// Models

type ModelOut struct {
	ID            *int      `json:"id"`
	ModelID       string    `json:"model_id"`
	MappedID      *string   `json:"mapped_id"`
	PublicID      string    `json:"public_id"`
	DisplayName   *string   `json:"display_name"`
	Description   *string   `json:"description"`
	OpenCodeConfig map[string]any `json:"opencode_config"`
	Enabled       bool      `json:"enabled"`
	Providers     []string  `json:"providers"`
	Served        bool      `json:"served"`
	Registered    bool      `json:"registered"`
	AddedByName   *string   `json:"added_by_name"`
	CreatedAt     *time.Time `json:"created_at"`
	UpdatedAt     *time.Time `json:"updated_at"`
}

type ModelUpsert struct {
	ModelID       string          `json:"model_id"`
	MappedID      *string         `json:"mapped_id,omitempty"`
	DisplayName   *string         `json:"display_name,omitempty"`
	Description   *string         `json:"description,omitempty"`
	OpenCodeConfig *map[string]any `json:"opencode_config,omitempty"`
	Enabled       *bool           `json:"enabled,omitempty"`
}

type ModelBatchUpdate struct {
	ModelIDs       []string        `json:"model_ids"`
	Description    *string         `json:"description,omitempty"`
	OpenCodeConfig *map[string]any `json:"opencode_config,omitempty"`
	Enabled        *bool           `json:"enabled,omitempty"`
}

type ModelBatchResult struct {
	Updated int `json:"updated"`
}

type ModelSyncResult struct {
	Added int `json:"added"`
	Total int `json:"total"`
}

type ModelCleanResult struct {
	Deleted  int      `json:"deleted"`
	ModelIDs []string `json:"model_ids"`
}

// API Keys

type ApiKeyCreate struct {
	Keys   []string `json:"keys"`
	Weight int      `json:"weight"`
	Note   *string  `json:"note"`
	Pool   string   `json:"pool"`
}

type ApiKeyUpdate struct {
	Key          *string  `json:"key,omitempty"`
	Status       *string  `json:"status,omitempty"`
	Weight       *int     `json:"weight,omitempty"`
	Note         *string  `json:"note,omitempty"`
	Pool         *string  `json:"pool,omitempty"`
	Enabled      *bool    `json:"enabled,omitempty"`
	AccessToken  *string  `json:"access_token,omitempty"`
	RefreshToken *string  `json:"refresh_token,omitempty"`
	ExpiresAt    *float64 `json:"expires_at,omitempty"`
}

type ApiKeyOut struct {
	ID             int            `json:"id"`
	ProviderID     int            `json:"provider_id"`
	KeyPreview     string         `json:"key_preview"`
	Pool           string         `json:"pool"`
	Status         string         `json:"status"`
	FailedCount    int            `json:"failed_count"`
	Weight         int            `json:"weight"`
	Note           *string        `json:"note"`
	Balance        map[string]any `json:"balance"`
	DisabledReason *string        `json:"disabled_reason"`
	TotalRequests  int            `json:"total_requests"`
	LastUsedAt     *time.Time     `json:"last_used_at"`
	LastCheckedAt  *time.Time     `json:"last_checked_at"`
	CreatedAt      time.Time      `json:"created_at"`
	DisabledSince  *time.Time     `json:"disabled_since"`
	AddedBy        *int           `json:"added_by"`
	AddedByName    *string        `json:"added_by_name"`
}

type ApiKeyCleanup struct {
	Target  string `json:"target"`
	MinDays int    `json:"min_days"`
}

type ApiKeyCleanupResult struct {
	Deleted int `json:"deleted"`
}

// Claude Code OAuth

type ClaudeOAuthStart struct {
	AuthorizeURL string `json:"authorize_url"`
	State        string `json:"state"`
}

type ClaudeOAuthComplete struct {
	Code  string  `json:"code"`
	State string  `json:"state"`
	Note  *string `json:"note"`
}

// Proxies

type ProxyCreate struct {
	URLs         []string `json:"urls"`
	LocalAddress *string  `json:"local_address"`
	Weight       int      `json:"weight"`
	Note         *string  `json:"note"`
}

type ProxyUpdate struct {
	URL          *string `json:"url,omitempty"`
	LocalAddress *string `json:"local_address,omitempty"`
	Enabled      *bool   `json:"enabled,omitempty"`
	Status       *string `json:"status,omitempty"`
	Weight       *int    `json:"weight,omitempty"`
	Note         *string `json:"note,omitempty"`
}

type ProxyOut struct {
	ID             int        `json:"id"`
	URL            string     `json:"url"`
	LocalAddress   *string    `json:"local_address"`
	Enabled        bool       `json:"enabled"`
	Status         string     `json:"status"`
	FailedCount    int        `json:"failed_count"`
	Weight         int        `json:"weight"`
	LatencyMs      *float64   `json:"latency_ms"`
	Note           *string    `json:"note"`
	DisabledReason *string    `json:"disabled_reason"`
	LastUsedAt     *time.Time `json:"last_used_at"`
	LastCheckedAt  *time.Time `json:"last_checked_at"`
	CreatedAt      time.Time  `json:"created_at"`
}

// Void Tokens

type VoidTokenCreate struct {
	Name          string     `json:"name"`
	AllowedModels []string   `json:"allowed_models"`
	RPMLimit      int        `json:"rpm_limit"`
	DailyQuota    int        `json:"daily_quota"`
	ExpiresAt     *time.Time `json:"expires_at"`
	UserID        *int       `json:"user_id"`
}

type VoidTokenUpdate struct {
	Name          *string    `json:"name,omitempty"`
	Enabled       *bool      `json:"enabled,omitempty"`
	AllowedModels *[]string  `json:"allowed_models,omitempty"`
	RPMLimit      *int       `json:"rpm_limit,omitempty"`
	DailyQuota    *int       `json:"daily_quota,omitempty"`
	ExpiresAt     *time.Time `json:"expires_at,omitempty"`
}

type VoidTokenOut struct {
	ID            int        `json:"id"`
	UserID        int        `json:"user_id"`
	Username      *string    `json:"username"`
	Name          string     `json:"name"`
	TokenPrefix   string     `json:"token_prefix"`
	Enabled       bool       `json:"enabled"`
	AllowedModels []string   `json:"allowed_models"`
	RPMLimit      int        `json:"rpm_limit"`
	DailyQuota    int        `json:"daily_quota"`
	TotalRequests int        `json:"total_requests"`
	TotalTokens   int        `json:"total_tokens"`
	LastUsedAt    *time.Time `json:"last_used_at"`
	ExpiresAt     *time.Time `json:"expires_at"`
	CreatedAt     time.Time  `json:"created_at"`
}

type VoidTokenWithSecret struct {
	VoidTokenOut
	Token string `json:"token"`
}

// Settings & logs

type SettingsOut struct {
	Values map[string]any `json:"values"`
}

type SettingsUpdate struct {
	Values map[string]any `json:"values"`
}

type AuditLogOut struct {
	ID           int            `json:"id"`
	TS           time.Time      `json:"ts"`
	ActorSub     *string        `json:"actor_sub"`
	ActorName    *string        `json:"actor_name"`
	Action       string         `json:"action"`
	Scope        string         `json:"scope"`
	TargetType   *string        `json:"target_type"`
	TargetID     *string        `json:"target_id"`
	Detail       map[string]any `json:"detail"`
	IP           *string        `json:"ip"`
	HasSensitive bool           `json:"has_sensitive"`
}

type RequestLogOut struct {
	ID              int       `json:"id"`
	TS              time.Time `json:"ts"`
	UserSub         *string   `json:"user_sub"`
	UserName        *string   `json:"user_name"`
	TokenID         *int      `json:"token_id"`
	TokenName       *string   `json:"token_name"`
	ProviderName    *string   `json:"provider_name"`
	Model           *string   `json:"model"`
	InboundStyle    *string   `json:"inbound_style"`
	UpstreamStyle   *string   `json:"upstream_style"`
	StatusCode      *int      `json:"status_code"`
	Success         bool      `json:"success"`
	LatencyMs       *float64  `json:"latency_ms"`
	PromptTokens    int       `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	TotalTokens     int       `json:"total_tokens"`
	Stream          bool      `json:"stream"`
	Attempts        int       `json:"attempts"`
	Error           *string   `json:"error"`
}

type StatsOut struct {
	Providers     int `json:"providers"`
	ActiveKeys    int `json:"active_keys"`
	TotalKeys     int `json:"total_keys"`
	ActiveProxies int `json:"active_proxies"`
	TotalProxies  int `json:"total_proxies"`
	Tokens        int `json:"tokens"`
	Requests24h   int `json:"requests_24h"`
	Success24h    int `json:"success_24h"`
	Failures24h   int `json:"failures_24h"`
	Tokens24h     int `json:"tokens_24h"`
}

type Page[T any] struct {
	Items  []T `json:"items"`
	Total  int  `json:"total"`
	Limit  int  `json:"limit"`
	Offset int  `json:"offset"`
}

// Usage analytics

type UsageTotals struct {
	Requests         int `json:"requests"`
	Success          int `json:"success"`
	Failures         int `json:"failures"`
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

type UsageBucket struct {
	UsageTotals
	Period string `json:"period"`
}

type UsageGroupRow struct {
	UsageTotals
	Key      string  `json:"key"`
	Label    string  `json:"label"`
	SubLabel *string `json:"sublabel"`
}

type UsageAnalyticsOut struct {
	Scope   string           `json:"scope"`
	Totals  UsageTotals      `json:"totals"`
	Daily   []UsageBucket    `json:"daily"`
	Weekly  []UsageBucket    `json:"weekly"`
	Monthly []UsageBucket    `json:"monthly"`
	Yearly  []UsageBucket    `json:"yearly"`
	ByUser  []UsageGroupRow  `json:"by_user"`
	ByToken []UsageGroupRow  `json:"by_token"`
	ByModel []UsageGroupRow  `json:"by_model"`
}

// Announcements

type AnnouncementCreate struct {
	Title              string `json:"title"`
	Body               string `json:"body"`
	TargetRoleGroupIDs []int  `json:"target_role_group_ids"`
}

type AnnouncementUpdate struct {
	Title              *string `json:"title,omitempty"`
	Body               *string `json:"body,omitempty"`
	TargetRoleGroupIDs *[]int  `json:"target_role_group_ids,omitempty"`
}

type AnnouncementOut struct {
	ID                 int       `json:"id"`
	CreatedAt          time.Time `json:"created_at"`
	UpdatedAt          time.Time `json:"updated_at"`
	Title              string    `json:"title"`
	Body               string    `json:"body"`
	CreatedBy          int       `json:"created_by"`
	CreatedByName      string    `json:"created_by_name"`
	CreatedByRole      string    `json:"created_by_role"`
	Edited             bool      `json:"edited"`
	CanManage          bool      `json:"can_manage"`
	TargetRoleGroupIDs []int     `json:"target_role_group_ids"`
}

// Role Groups

type RoleGroupMappingIn struct {
	TeamID  string `json:"team_id"`
	MinRole string `json:"min_role"`
}

type RoleGroupMappingOut struct {
	ID     int    `json:"id"`
	TeamID string `json:"team_id"`
	MinRole string `json:"min_role"`
}

type RoleGroupCreate struct {
	Name        string              `json:"name"`
	Description *string             `json:"description"`
	Mappings    []RoleGroupMappingIn `json:"mappings"`
}

type RoleGroupUpdate struct {
	Name        *string              `json:"name,omitempty"`
	Description *string              `json:"description,omitempty"`
	Mappings    *[]RoleGroupMappingIn `json:"mappings,omitempty"`
}

type RoleGroupOut struct {
	ID          int                 `json:"id"`
	Slug        string              `json:"slug"`
	Name        string              `json:"name"`
	Description *string             `json:"description"`
	Builtin     bool                `json:"builtin"`
	MemberCount int                 `json:"member_count"`
	Mappings    []RoleGroupMappingOut `json:"mappings"`
	CreatedAt   time.Time           `json:"created_at"`
	UpdatedAt   time.Time           `json:"updated_at"`
}

type RoleGroupMemberOut struct {
	UserID  int     `json:"user_id"`
	Name    string  `json:"name"`
	Email   *string `json:"email"`
	Role    string  `json:"role"`
	Source  string  `json:"source"`
	Enabled bool    `json:"enabled"`
}

// Provider Key API

type ProviderKeyAPISecret struct {
	Token string `json:"token"`
}

type LogCleanupResult struct {
	DeletedRequestLogs int `json:"deleted_request_logs"`
	DeletedAuditLogs   int `json:"deleted_audit_logs"`
	StrippedDebugLogs  int `json:"stripped_debug_logs"`
}
