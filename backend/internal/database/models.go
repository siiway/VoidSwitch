// Package database defines the GORM models that mirror the Python SQLAlchemy
// schema EXACTLY (table names, column names, types) so the existing production
// PostgreSQL database can be reused without transformation.
//
// These structs are read/write mappings only — the schema is owned by the goose
// migrations in ./migrations. `AutoMigrate` is never used.
package database

import (
	"database/sql/driver"
	"encoding/json"
	"fmt"
	"time"

	"gorm.io/gorm"
)

// JSON is a GORM field type for PostgreSQL `json` columns. It round-trips
// arbitrary JSON and marshals nil as SQL NULL when Nullable.
type JSON json.RawMessage

func (j JSON) Value() (driver.Value, error) {
	if len(j) == 0 {
		return nil, nil
	}
	return []byte(j), nil
}

func (j *JSON) Scan(value any) error {
	if value == nil {
		*j = nil
		return nil
	}
	switch v := value.(type) {
	case []byte:
		*j = append((*j)[:0], v...)
	case string:
		*j = append((*j)[:0], v...)
	default:
		return fmt.Errorf("database.JSON: cannot scan %T", value)
	}
	return nil
}

func (j JSON) MarshalJSON() ([]byte, error) {
	if len(j) == 0 {
		return []byte("null"), nil
	}
	return j, nil
}

func (j *JSON) UnmarshalJSON(b []byte) error {
	*j = append((*j)[:0], b...)
	return nil
}

// JSONOf encodes a Go value into a JSON column value.
func JSONOf(v any) JSON {
	b, err := json.Marshal(v)
	if err != nil {
		return JSON("null")
	}
	return JSON(b)
}

// DecodeJSON unmarshals a JSON column into dst, tolerating NULL/empty.
func DecodeJSON[T any](j JSON, dst *T) {
	if len(j) == 0 || string(j) == "null" {
		return
	}
	_ = json.Unmarshal(j, dst)
}

// RawOrNull maps to a nullable json column.
func NullableJSON(j JSON) JSON {
	if len(j) == 0 {
		return nil
	}
	return j
}

// Timestamps are plain time.Time columns; the DB supplies defaults (now()).
type Timestamped struct {
	CreatedAt time.Time `gorm:"column:created_at;autoCreateTime"`
	UpdatedAt time.Time `gorm:"column:updated_at;autoUpdateTime"`
}

// ---- users ----------------------------------------------------------------

type User struct {
	Timestamped
	ID                      int        `gorm:"column:id;primaryKey;autoIncrement"`
	Sub                     string     `gorm:"column:sub;type:varchar(255);uniqueIndex;not null"`
	Username                *string    `gorm:"column:username;type:varchar(255)"`
	Email                   *string    `gorm:"column:email;type:varchar(320);index"`
	Name                    *string    `gorm:"column:name;type:varchar(255)"`
	Picture                 *string    `gorm:"column:picture;type:text"`
	Role                    string     `gorm:"column:role;type:varchar(32);not null"`
	PrismRole               *string    `gorm:"column:prism_role;type:varchar(32)"`
	TeamIDs                 JSON       `gorm:"column:team_ids;type:json;not null"`
	Enabled                 bool       `gorm:"column:enabled;not null"`
	LastLoginAt             *time.Time `gorm:"column:last_login_at;type:timestamptz"`
	SessionEpoch            int        `gorm:"column:session_epoch;not null"`
	LoginTokenHash          *string    `gorm:"column:login_token_hash;type:varchar(64);uniqueIndex"`
	LoginTokenPrefix        *string    `gorm:"column:login_token_prefix;type:varchar(32)"`
	VoidTokensAdminDisabled bool       `gorm:"column:void_tokens_admin_disabled;not null"`

	// Not persisted; eagerly loaded where needed.
	GroupMemberships []RoleGroupMembership `gorm:"foreignKey:UserID"`
	GroupAdminships  []RoleGroupAdminship  `gorm:"foreignKey:UserID"`
}

func (User) TableName() string { return "users" }

// ---- void_tokens ----------------------------------------------------------

type VoidToken struct {
	Timestamped
	ID            int        `gorm:"column:id;primaryKey;autoIncrement"`
	UserID        int        `gorm:"column:user_id;index;not null"`
	Name          string     `gorm:"column:name;type:varchar(120);not null"`
	TokenHash     string     `gorm:"column:token_hash;type:varchar(64);uniqueIndex;not null"`
	TokenPrefix   string     `gorm:"column:token_prefix;type:varchar(32);not null"`
	Enabled       bool       `gorm:"column:enabled;not null"`
	AutoDisabled  bool       `gorm:"column:auto_disabled;not null"`
	Deleted       bool       `gorm:"column:deleted;index;not null"`
	DeletedAt     *time.Time `gorm:"column:deleted_at;type:timestamptz"`
	AllowedModels JSON       `gorm:"column:allowed_models;type:json;not null"`
	RPMLimit      int        `gorm:"column:rpm_limit;not null"`
	DailyQuota    int        `gorm:"column:daily_quota;not null"`
	TotalRequests int64      `gorm:"column:total_requests;not null"`
	TotalTokens   int64      `gorm:"column:total_tokens;not null"`
	LastUsedAt    *time.Time `gorm:"column:last_used_at;type:timestamptz"`
	ExpiresAt     *time.Time `gorm:"column:expires_at;type:timestamptz"`
	DebugEnabled  bool       `gorm:"column:debug_enabled;not null"`

	User *User `gorm:"foreignKey:UserID"`
}

func (VoidToken) TableName() string { return "void_tokens" }

// ---- model_categories -----------------------------------------------------

type ModelCategory struct {
	Timestamped
	ID       int    `gorm:"column:id;primaryKey;autoIncrement"`
	Name     string `gorm:"column:name;type:varchar(120);uniqueIndex;not null"`
	Slug     string `gorm:"column:slug;type:varchar(120);uniqueIndex;not null"`
	Position int    `gorm:"column:position;not null"`
}

func (ModelCategory) TableName() string { return "model_categories" }

// ---- exposed_models -------------------------------------------------------

type ExposedModel struct {
	Timestamped
	ID                  int        `gorm:"column:id;primaryKey;autoIncrement"`
	ModelID             string     `gorm:"column:model_id;type:varchar(255);uniqueIndex;not null"`
	DisplayName         *string    `gorm:"column:display_name;type:varchar(255)"`
	Description         *string    `gorm:"column:description;type:text"`
	OpenCodeConfig      JSON       `gorm:"column:opencode_config;type:json;not null"`
	Enabled             bool       `gorm:"column:enabled;not null"`
	AllowedRoleGroupIDs JSON       `gorm:"column:allowed_role_group_ids;type:json;not null"`
	LimitContext        *int       `gorm:"column:limit_context"`
	LimitInput          *int       `gorm:"column:limit_input"`
	LimitOutput         *int       `gorm:"column:limit_output"`
	Reasoning           *bool      `gorm:"column:reasoning"`
	Capabilities        JSON       `gorm:"column:capabilities;type:json;not null"`
	Modalities          JSON       `gorm:"column:modalities;type:json;not null"`
	ModelsDevID         *string    `gorm:"column:models_dev_id;type:varchar(255);index"`
	ModelsDevSyncedAt   *time.Time `gorm:"column:models_dev_synced_at;type:timestamptz"`
	Brand               *string    `gorm:"column:brand;type:varchar(64)"`
	AddedBy             *int       `gorm:"column:added_by;index"`
	AddedByName         *string    `gorm:"column:added_by_name;type:varchar(255)"`
	CategoryID          *int       `gorm:"column:category_id;index"`

	Route    *Route         `gorm:"foreignKey:ExposedModelID"`
	Category *ModelCategory `gorm:"foreignKey:CategoryID"`
}

func (ExposedModel) TableName() string { return "exposed_models" }

// ---- routes ---------------------------------------------------------------

type Route struct {
	Timestamped
	ID                        int    `gorm:"column:id;primaryKey;autoIncrement"`
	ExposedModelID            int    `gorm:"column:exposed_model_id;uniqueIndex;not null"`
	UpstreamSelectMode        string `gorm:"column:upstream_select_mode;type:varchar(32);not null"`
	UpstreamRankAlgorithm     string `gorm:"column:upstream_rank_algorithm;type:varchar(32);not null"`
	MaxUpstreamAttempts       int    `gorm:"column:max_upstream_attempts;not null"`
	UpstreamAllCooledBehavior string `gorm:"column:upstream_all_cooled_behavior;type:varchar(32);not null"`

	ExposedModel *ExposedModel   `gorm:"foreignKey:ExposedModelID"`
	Upstreams    []RouteUpstream `gorm:"foreignKey:RouteID"`
}

func (Route) TableName() string { return "routes" }

// ---- route_upstreams ------------------------------------------------------

type RouteUpstream struct {
	ID                  int    `gorm:"column:id;primaryKey;autoIncrement"`
	RouteID             int    `gorm:"column:route_id;index;not null"`
	ProviderID          *int   `gorm:"column:provider_id;index"`
	UpstreamModel       string `gorm:"column:upstream_model;type:varchar(255);not null"`
	GroupPosition       int    `gorm:"column:group_position;not null"`
	Position            int    `gorm:"column:position;not null"`
	Weight              int    `gorm:"column:weight;not null"`
	Enabled             bool   `gorm:"column:enabled;not null"`
	KeyPool             string `gorm:"column:key_pool;type:varchar(64);not null"`
	CooldownStatusCodes JSON   `gorm:"column:cooldown_status_codes;type:json;not null"`
	CooldownSeconds     int    `gorm:"column:cooldown_seconds;not null"`

	Provider *Provider `gorm:"foreignKey:ProviderID"`
}

func (RouteUpstream) TableName() string { return "route_upstreams" }

// ---- upstream_cooldowns ---------------------------------------------------

type UpstreamCooldown struct {
	Timestamped
	ID               int        `gorm:"column:id;primaryKey;autoIncrement"`
	ProviderID       int        `gorm:"column:provider_id;index;not null"`
	UpstreamModel    string     `gorm:"column:upstream_model;type:varchar(255);not null"`
	KeyPool          string     `gorm:"column:key_pool;type:varchar(64);not null"`
	Until            time.Time  `gorm:"column:until;type:timestamptz;index;not null"`
	Reason           *string    `gorm:"column:reason;type:varchar(255)"`
	TriggerStatus    int        `gorm:"column:trigger_status;not null"`
	TriggerSource    string     `gorm:"column:trigger_source;type:varchar(32);not null"`
	TriggeredAt      time.Time  `gorm:"column:triggered_at;type:timestamptz;not null"`
	ConsecutiveTrips int        `gorm:"column:consecutive_trips;not null"`
	LastSuccessAt    *time.Time `gorm:"column:last_success_at;type:timestamptz"`
}

func (UpstreamCooldown) TableName() string { return "upstream_cooldowns" }

// ---- providers ------------------------------------------------------------

type Provider struct {
	Timestamped
	ID                             int     `gorm:"column:id;primaryKey;autoIncrement"`
	UUID                           string  `gorm:"column:uuid;type:varchar(36);uniqueIndex;not null"`
	Name                           string  `gorm:"column:name;type:varchar(120);uniqueIndex;not null"`
	Slug                           string  `gorm:"column:slug;type:varchar(120);uniqueIndex;not null"`
	NodeGroupID                    *int    `gorm:"column:node_group_id;index"`
	Type                           string  `gorm:"column:type;type:varchar(64);not null"`
	BaseURL                        string  `gorm:"column:base_url;type:varchar(512);not null"`
	Enabled                        bool    `gorm:"column:enabled;not null"`
	Priority                       int     `gorm:"column:priority;not null"`
	Weight                         int     `gorm:"column:weight;not null"`
	Models                         JSON    `gorm:"column:models;type:json;not null"`
	ModelMap                       JSON    `gorm:"column:model_map;type:json;not null"`
	ModelRoutes                    JSON    `gorm:"column:model_routes;type:json;not null"`
	BalanceURL                     *string `gorm:"column:balance_url;type:varchar(512)"`
	ExtraHeaders                   JSON    `gorm:"column:extra_headers;type:json;not null"`
	TimeoutSeconds                 int     `gorm:"column:timeout_seconds;not null"`
	RetryOnZeroToken               bool    `gorm:"column:retry_on_zero_token;not null"`
	DropOpenCodeIdentityBlock      bool    `gorm:"column:drop_opencode_identity_block;not null"`
	NormalizeDeveloperRoleToSystem bool    `gorm:"column:normalize_developer_role_to_system;not null"`
	KeySelectMode                  string  `gorm:"column:key_select_mode;type:varchar(32);not null"`
	RateLimitCooldownSeconds       int     `gorm:"column:rate_limit_cooldown_seconds;not null"`
	AddedBy                        *int    `gorm:"column:added_by;index"`
	AddedByName                    *string `gorm:"column:added_by_name;type:varchar(255)"`
	KeyAPIEnabled                  bool    `gorm:"column:key_api_enabled;not null"`
	KeyAPITokenHash                *string `gorm:"column:key_api_token_hash;type:varchar(64);uniqueIndex"`
	KeyAPITokenCiphertext          *string `gorm:"column:key_api_token_ciphertext;type:text"`
	KeyAPITokenPreview             *string `gorm:"column:key_api_token_preview;type:varchar(48)"`
	PassthroughEnabled             bool    `gorm:"column:passthrough_enabled;not null"`
	PassthroughModels              JSON    `gorm:"column:passthrough_models;type:json;not null"`
	UpstreamCooldownSeconds        int     `gorm:"column:upstream_cooldown_seconds;not null"`
	UpstreamCooldownStatusCodes    JSON    `gorm:"column:upstream_cooldown_status_codes;type:json;not null"`
	UpstreamRetryAfterHeaders      JSON    `gorm:"column:upstream_retry_after_headers;type:json;not null"`
	UpstreamMaxKeysPerAttempt      int     `gorm:"column:upstream_max_keys_per_attempt;not null"`
	NewAPIMode                     string  `gorm:"column:new_api_mode;type:varchar(16);not null"`
	ProtectedErrorRetryEnabled     bool    `gorm:"column:protected_error_retry_enabled;not null"`
	SelectiveIgnoreRules           JSON    `gorm:"column:selective_ignore_rules;type:json;not null"`

	Keys []ApiKey `gorm:"foreignKey:ProviderID"`
}

func (Provider) TableName() string { return "providers" }

// ---- api_keys -------------------------------------------------------------

type ApiKey struct {
	Timestamped
	ID             int        `gorm:"column:id;primaryKey;autoIncrement"`
	ProviderID     int        `gorm:"column:provider_id;index;not null"`
	KeyCiphertext  string     `gorm:"column:key_ciphertext;type:text;not null"`
	KeyHash        string     `gorm:"column:key_hash;type:varchar(64);index;not null"`
	KeyPreview     string     `gorm:"column:key_preview;type:varchar(32);not null"`
	Pool           string     `gorm:"column:pool;type:varchar(64);index;not null"`
	SortOrder      int        `gorm:"column:sort_order;index;not null"`
	Status         string     `gorm:"column:status;type:varchar(32);index;not null"`
	FailedCount    int        `gorm:"column:failed_count;not null"`
	Weight         int        `gorm:"column:weight;not null"`
	Note           *string    `gorm:"column:note;type:varchar(255)"`
	Balance        JSON       `gorm:"column:balance;type:json;not null"`
	DisabledReason *string    `gorm:"column:disabled_reason;type:varchar(255)"`
	DisabledSince  *time.Time `gorm:"column:disabled_since;type:timestamptz"`
	RateLimitUntil *time.Time `gorm:"column:rate_limit_until;type:timestamptz"`
	TotalRequests  int64      `gorm:"column:total_requests;not null"`
	LastUsedAt     *time.Time `gorm:"column:last_used_at;type:timestamptz"`
	LastCheckedAt  *time.Time `gorm:"column:last_checked_at;type:timestamptz"`
	AddedBy        *int       `gorm:"column:added_by;index"`
	AddedByName    *string    `gorm:"column:added_by_name;type:varchar(255)"`
}

func (ApiKey) TableName() string { return "api_keys" }

// ---- nodes ----------------------------------------------------------------

type Node struct {
	Timestamped
	ID              int        `gorm:"column:id;primaryKey;autoIncrement"`
	URL             string     `gorm:"column:url;type:varchar(512);uniqueIndex;not null"`
	Type            string     `gorm:"column:type;type:varchar(16);not null"`
	TokenCiphertext *string    `gorm:"column:token_ciphertext;type:text"`
	LocalAddress    *string    `gorm:"column:local_address;type:varchar(64)"`
	Enabled         bool       `gorm:"column:enabled;not null"`
	Status          string     `gorm:"column:status;type:varchar(32);index;not null"`
	FailedCount     int        `gorm:"column:failed_count;not null"`
	Weight          int        `gorm:"column:weight;not null"`
	LatencyMs       *float64   `gorm:"column:latency_ms"`
	LatencyEWMA     *float64   `gorm:"column:latency_ewma"`
	Note            *string    `gorm:"column:note;type:varchar(255)"`
	DisabledReason  *string    `gorm:"column:disabled_reason;type:varchar(255)"`
	LastUsedAt      *time.Time `gorm:"column:last_used_at;type:timestamptz"`
	LastCheckedAt   *time.Time `gorm:"column:last_checked_at;type:timestamptz"`
}

func (Node) TableName() string { return "nodes" }

// ---- node_health_samples --------------------------------------------------

type NodeHealthSample struct {
	ID         int       `gorm:"column:id;primaryKey;autoIncrement"`
	NodeID     int       `gorm:"column:node_id;index;not null"`
	TS         time.Time `gorm:"column:ts;type:timestamptz;index;not null"`
	Source     string    `gorm:"column:source;type:varchar(16);not null"`
	Success    bool      `gorm:"column:success;not null"`
	LatencyMs  *float64  `gorm:"column:latency_ms"`
	StatusCode *int      `gorm:"column:status_code"`
	Error      *string   `gorm:"column:error;type:varchar(255)"`
}

func (NodeHealthSample) TableName() string { return "node_health_samples" }

// ---- node_groups ----------------------------------------------------------

type NodeGroup struct {
	Timestamped
	ID                   int     `gorm:"column:id;primaryKey;autoIncrement"`
	Slug                 *string `gorm:"column:slug;type:varchar(64);uniqueIndex"`
	Name                 string  `gorm:"column:name;type:varchar(120);uniqueIndex;not null"`
	Description          *string `gorm:"column:description;type:text"`
	ProbeURL             *string `gorm:"column:probe_url;type:varchar(512)"`
	ProbeIntervalSeconds int     `gorm:"column:probe_interval_seconds;not null"`
	IsSystem             bool    `gorm:"column:is_system;not null"`

	Members []NodeGroupMember `gorm:"foreignKey:GroupID"`
}

func (NodeGroup) TableName() string { return "node_groups" }

// ---- node_group_members ---------------------------------------------------

type NodeGroupMember struct {
	ID            int  `gorm:"column:id;primaryKey;autoIncrement"`
	GroupID       int  `gorm:"column:group_id;index;not null"`
	NodeID        *int `gorm:"column:node_id;index"`
	SourceGroupID *int `gorm:"column:source_group_id;index"`
	Pinned        bool `gorm:"column:pinned;not null"`
	Weight        int  `gorm:"column:weight;not null"`

	Node        *Node      `gorm:"foreignKey:NodeID"`
	SourceGroup *NodeGroup `gorm:"foreignKey:SourceGroupID"`
}

func (NodeGroupMember) TableName() string { return "node_group_members" }

// ---- settings -------------------------------------------------------------

type Setting struct {
	Key       string    `gorm:"column:key;type:varchar(120);primaryKey"`
	Value     JSON      `gorm:"column:value;type:json;not null"`
	UpdatedAt time.Time `gorm:"column:updated_at;autoUpdateTime"`
}

func (Setting) TableName() string { return "settings" }

// ---- models_dev_cache -----------------------------------------------------

type ModelsDevCache struct {
	ID        string    `gorm:"column:id;type:varchar(255);primaryKey"`
	Data      JSON      `gorm:"column:data;type:json;not null"`
	UpdatedAt time.Time `gorm:"column:updated_at;autoUpdateTime"`
}

func (ModelsDevCache) TableName() string { return "models_dev_cache" }

// ---- role_groups ----------------------------------------------------------

type RoleGroup struct {
	Timestamped
	ID                         int     `gorm:"column:id;primaryKey;autoIncrement"`
	Slug                       *string `gorm:"column:slug;type:varchar(64);uniqueIndex"`
	Name                       string  `gorm:"column:name;type:varchar(120);uniqueIndex;not null"`
	Description                *string `gorm:"column:description;type:text"`
	Builtin                    bool    `gorm:"column:builtin;not null"`
	CallRateLimitWindowSeconds int     `gorm:"column:call_rate_limit_window_seconds;not null"`
	CallRateLimitMaxRequests   int     `gorm:"column:call_rate_limit_max_requests;not null"`

	Mappings    []RoleGroupMapping    `gorm:"foreignKey:RoleGroupID"`
	Memberships []RoleGroupMembership `gorm:"foreignKey:RoleGroupID"`
	Adminships  []RoleGroupAdminship  `gorm:"foreignKey:RoleGroupID"`
}

func (RoleGroup) TableName() string { return "role_groups" }

// ---- role_group_mappings --------------------------------------------------

type RoleGroupMapping struct {
	ID          int       `gorm:"column:id;primaryKey;autoIncrement"`
	RoleGroupID int       `gorm:"column:role_group_id;index;not null"`
	TeamID      string    `gorm:"column:team_id;type:varchar(120);index;not null"`
	MinRole     string    `gorm:"column:min_role;type:varchar(32);not null"`
	Grants      string    `gorm:"column:grants;type:varchar(16);not null"`
	CreatedAt   time.Time `gorm:"column:created_at;autoCreateTime"`
}

func (RoleGroupMapping) TableName() string { return "role_group_mappings" }

// ---- role_group_memberships ----------------------------------------------

type RoleGroupMembership struct {
	ID          int       `gorm:"column:id;primaryKey;autoIncrement"`
	UserID      int       `gorm:"column:user_id;index;not null"`
	RoleGroupID int       `gorm:"column:role_group_id;index;not null"`
	Source      string    `gorm:"column:source;type:varchar(16);not null"`
	CreatedAt   time.Time `gorm:"column:created_at;autoCreateTime"`

	Group *RoleGroup `gorm:"foreignKey:RoleGroupID"`
}

func (RoleGroupMembership) TableName() string { return "role_group_memberships" }

// ---- role_group_adminships -----------------------------------------------

type RoleGroupAdminship struct {
	ID          int       `gorm:"column:id;primaryKey;autoIncrement"`
	UserID      int       `gorm:"column:user_id;index;not null"`
	RoleGroupID int       `gorm:"column:role_group_id;index;not null"`
	Source      string    `gorm:"column:source;type:varchar(16);not null"`
	CreatedAt   time.Time `gorm:"column:created_at;autoCreateTime"`

	Group *RoleGroup `gorm:"foreignKey:RoleGroupID"`
}

func (RoleGroupAdminship) TableName() string { return "role_group_adminships" }

// ---- announcements --------------------------------------------------------

type Announcement struct {
	Timestamped
	ID                 int     `gorm:"column:id;primaryKey;autoIncrement"`
	Title              string  `gorm:"column:title;type:varchar(255);not null"`
	Body               string  `gorm:"column:body;type:text;not null"`
	CreatedBy          *int    `gorm:"column:created_by;index"`
	CreatedByName      *string `gorm:"column:created_by_name;type:varchar(255)"`
	CreatedByRole      string  `gorm:"column:created_by_role;type:varchar(32);not null"`
	Edited             bool    `gorm:"column:edited;not null"`
	TargetRoleGroupIDs JSON    `gorm:"column:target_role_group_ids;type:json;not null"`
}

func (Announcement) TableName() string { return "announcements" }

// ---- audit_logs -----------------------------------------------------------

type AuditLog struct {
	ID                  int       `gorm:"column:id;primaryKey;autoIncrement"`
	TS                  time.Time `gorm:"column:ts;type:timestamptz;index;not null"`
	ActorSub            *string   `gorm:"column:actor_sub;type:varchar(255);index"`
	ActorName           *string   `gorm:"column:actor_name;type:varchar(255)"`
	Action              string    `gorm:"column:action;type:varchar(120);not null"`
	Scope               string    `gorm:"column:scope;type:varchar(16);index;not null"`
	TargetType          *string   `gorm:"column:target_type;type:varchar(64)"`
	TargetID            *string   `gorm:"column:target_id;type:varchar(64)"`
	Detail              JSON      `gorm:"column:detail;type:json;not null"`
	IP                  *string   `gorm:"column:ip;type:varchar(64)"`
	UserAgent           *string   `gorm:"column:user_agent;type:varchar(512)"`
	SensitiveCiphertext *string   `gorm:"column:sensitive_ciphertext;type:text"`
}

func (AuditLog) TableName() string { return "audit_logs" }

// BeforeCreate stamps TS server-side if zero.
func (a *AuditLog) BeforeCreate(*gorm.DB) error {
	if a.TS.IsZero() {
		a.TS = time.Now().UTC()
	}
	return nil
}

// ---- request_logs ---------------------------------------------------------

type RequestLog struct {
	ID               int        `gorm:"column:id;primaryKey;autoIncrement"`
	TS               time.Time  `gorm:"column:ts;type:timestamptz;index;not null"`
	StartedAt        *time.Time `gorm:"column:started_at;type:timestamptz"`
	FinishedAt       *time.Time `gorm:"column:finished_at;type:timestamptz"`
	FirstTokenMs     *float64   `gorm:"column:first_token_ms"`
	ReqStatus        *string    `gorm:"column:req_status;type:varchar(32);index"`
	ClientIP         *string    `gorm:"column:client_ip;type:varchar(64)"`
	TokenID          *int       `gorm:"column:token_id;index"`
	UserSub          *string    `gorm:"column:user_sub;type:varchar(255);index"`
	SessionID        *string    `gorm:"column:session_id;type:varchar(255);index"`
	ProviderID       *int       `gorm:"column:provider_id"`
	ProviderName     *string    `gorm:"column:provider_name;type:varchar(120)"`
	KeyID            *int       `gorm:"column:key_id"`
	ProxyID          *int       `gorm:"column:proxy_id"`
	Model            *string    `gorm:"column:model;type:varchar(120);index"`
	UpstreamModel    *string    `gorm:"column:upstream_model;type:varchar(120)"`
	InboundStyle     *string    `gorm:"column:inbound_style;type:varchar(32)"`
	UpstreamStyle    *string    `gorm:"column:upstream_style;type:varchar(32)"`
	StatusCode       *int       `gorm:"column:status_code"`
	Success          bool       `gorm:"column:success;index;not null"`
	LatencyMs        *float64   `gorm:"column:latency_ms"`
	PromptTokens     int64      `gorm:"column:prompt_tokens;not null"`
	CompletionTokens int64      `gorm:"column:completion_tokens;not null"`
	TotalTokens      int64      `gorm:"column:total_tokens;not null"`
	Stream           bool       `gorm:"column:stream;not null"`
	Attempts         int        `gorm:"column:attempts;not null"`
	ProviderAttempts int        `gorm:"column:provider_attempts;not null"`
	NetworkAttempts  int        `gorm:"column:network_attempts;not null"`
	Error            *string    `gorm:"column:error;type:text"`
	UserAgent        *string    `gorm:"column:user_agent;type:varchar(512)"`
	ClientType       *string    `gorm:"column:client_type;type:varchar(64)"`
	IsOpenCode       bool       `gorm:"column:is_opencode;not null"`
	Debug            bool       `gorm:"column:debug;index;not null"`
	ReqMethod        *string    `gorm:"column:req_method;type:varchar(16)"`
	ReqHeaders       JSON       `gorm:"column:req_headers;type:json"`
	ReqBody          JSON       `gorm:"column:req_body;type:json"`
	RespHeaders      JSON       `gorm:"column:resp_headers;type:json"`
	RespBody         JSON       `gorm:"column:resp_body;type:json"`
	DebugAttempts    JSON       `gorm:"column:debug_attempts;type:json"`
	AttemptsSummary  JSON       `gorm:"column:attempts_summary;type:json"`
	UpstreamURL      *string    `gorm:"column:upstream_url;type:varchar(1024)"`
	ProxyURL         *string    `gorm:"column:proxy_url;type:varchar(512)"`
}

func (RequestLog) TableName() string { return "request_logs" }

// ---- usage_daily ----------------------------------------------------------

type UsageDaily struct {
	ID        int       `gorm:"column:id;primaryKey;autoIncrement"`
	UserSub   string    `gorm:"column:user_sub;type:varchar(255);index;not null"`
	Day       string    `gorm:"column:day;type:varchar(10);index;not null"`
	Tokens    int64     `gorm:"column:tokens;not null"`
	Requests  int64     `gorm:"column:requests;not null"`
	UpdatedAt time.Time `gorm:"column:updated_at;autoUpdateTime"`
}

func (UsageDaily) TableName() string { return "usage_daily" }

// ---- session_spans --------------------------------------------------------

type SessionSpan struct {
	ID         int       `gorm:"column:id;primaryKey;autoIncrement"`
	SessionKey string    `gorm:"column:session_key;type:varchar(255);uniqueIndex;not null"`
	UserSub    string    `gorm:"column:user_sub;type:varchar(255);index;not null"`
	StartedAt  time.Time `gorm:"column:started_at;type:timestamptz;not null"`
	LastAt     time.Time `gorm:"column:last_at;type:timestamptz;index;not null"`
	Requests   int64     `gorm:"column:requests;not null"`
	UpdatedAt  time.Time `gorm:"column:updated_at;autoUpdateTime"`
}

func (SessionSpan) TableName() string { return "session_spans" }

// AllModels returns every persisted model (used by tests / schema checks).
func AllModels() []any {
	return []any{
		&User{}, &VoidToken{}, &ModelCategory{}, &ExposedModel{}, &Route{},
		&RouteUpstream{}, &UpstreamCooldown{}, &Provider{}, &ApiKey{}, &Node{},
		&NodeHealthSample{}, &NodeGroup{}, &NodeGroupMember{}, &Setting{},
		&ModelsDevCache{}, &RoleGroup{}, &RoleGroupMapping{}, &RoleGroupMembership{},
		&RoleGroupAdminship{}, &Announcement{}, &AuditLog{}, &RequestLog{},
		&UsageDaily{}, &SessionSpan{},
	}
}
