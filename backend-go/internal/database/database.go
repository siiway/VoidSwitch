package database

import (
	"fmt"
	"strings"
	"time"

	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var db *Database

func InitDatabase(url string, echo bool) (*Database, error) {
	var err error
	db, err = NewDatabase(url, echo)
	return db, err
}

func GetDatabase() *Database {
	if db == nil {
		panic("database not initialised, call InitDatabase first")
	}
	return db
}

type Database struct {
	DB *gorm.DB
}

func NewDatabase(url string, echo bool) (*Database, error) {
	// Accept Python-style SQLite URLs: "sqlite+aiosqlite:///./voidswitch.db"
	url = strings.TrimPrefix(url, "sqlite+")
	url = strings.TrimPrefix(url, "aiosqlite://")
	url = strings.TrimPrefix(url, "///") // Python relative path: sqlite:///./foo → ./foo

	logLevel := logger.Silent
	if echo {
		logLevel = logger.Info
	}

	gdb, err := gorm.Open(sqlite.Open(url), &gorm.Config{
		Logger: logger.Default.LogMode(logLevel),
	})
	if err != nil {
		return nil, fmt.Errorf("open database: %w", err)
	}

	if err := gdb.Exec("PRAGMA journal_mode=WAL").Error; err != nil {
		return nil, fmt.Errorf("set WAL mode: %w", err)
	}
	if err := gdb.Exec("PRAGMA foreign_keys=ON").Error; err != nil {
		return nil, fmt.Errorf("enable foreign keys: %w", err)
	}

	return &Database{DB: gdb}, nil
}

func (d *Database) Close() error {
	sqlDB, err := d.DB.DB()
	if err != nil {
		return err
	}
	return sqlDB.Close()
}

func (d *Database) AutoMigrate(models ...interface{}) error {
	if len(models) == 0 {
		models = []interface{}{
			&User{},
			&VoidToken{},
			&ModelEntry{},
			&Provider{},
			&ApiKey{},
			&Proxy{},
			&Setting{},
			&AuditLog{},
			&RequestLog{},
			&Announcement{},
			&RoleGroup{},
			&RoleGroupMapping{},
			&RoleGroupMembership{},
		}
	}
	if err := d.DB.AutoMigrate(models...); err != nil {
		return err
	}
	return addMissingColumns(d.DB)
}

type TimestampMixin struct {
	CreatedAt time.Time `gorm:"autoCreateTime"`
	UpdatedAt time.Time `gorm:"autoUpdateTime"`
}

type User struct {
	TimestampMixin
	ID          int        `gorm:"primaryKey;autoIncrement"`
	Sub         string     `gorm:"type:varchar(255);uniqueIndex;not null"`
	Username    *string    `gorm:"type:varchar(255)"`
	Email       *string    `gorm:"type:varchar(320);index"`
	Name        *string    `gorm:"type:varchar(255)"`
	Picture     *string    `gorm:"type:text"`
	Role        string     `gorm:"type:varchar(32);default:member;not null"`
	PrismRole   *string    `gorm:"type:varchar(32)"`
	Enabled     bool       `gorm:"default:true;not null"`
	LastLoginAt *time.Time `gorm:"type:datetime"`
	SessionEpoch int      `gorm:"column:session_epoch;default:0"`
}

func (User) TableName() string { return "users" }

type VoidToken struct {
	TimestampMixin
	ID            int        `gorm:"primaryKey;autoIncrement"`
	UserID        int        `gorm:"index;not null"`
	User          *User      `gorm:"foreignKey:UserID;constraint:OnDelete:CASCADE"`
	Name          string     `gorm:"type:varchar(120);default:default"`
	TokenHash     string     `gorm:"type:varchar(64);uniqueIndex;not null"`
	TokenPrefix   string     `gorm:"type:varchar(32);default:''"`
	Enabled       bool       `gorm:"default:true;not null"`
	AllowedModels []string   `gorm:"type:text;serializer:json"`
	RpmLimit      int        `gorm:"default:0"`
	DailyQuota    int        `gorm:"default:0"`
	TotalRequests int        `gorm:"default:0"`
	TotalTokens   int        `gorm:"default:0"`
	LastUsedAt    *time.Time `gorm:"type:datetime"`
	ExpiresAt     *time.Time `gorm:"type:datetime"`
}

func (VoidToken) TableName() string { return "void_tokens" }

type ModelEntry struct {
	TimestampMixin
	ID                  int            `gorm:"primaryKey;autoIncrement"`
	ModelID             string         `gorm:"column:model_id;type:varchar(255);uniqueIndex;not null"`
	MappedID            *string        `gorm:"column:mapped_id;type:varchar(255);index"`
	DisplayName         *string        `gorm:"column:display_name;type:varchar(255)"`
	Description         *string        `gorm:"type:text"`
	OpenCodeConfig      map[string]any `gorm:"column:opencode_config;type:text;serializer:json"`
	Enabled             bool           `gorm:"default:true;not null"`
	AllowedRoleGroupIDs []int          `gorm:"column:allowed_role_group_ids;type:text;serializer:json"`
	AddedBy             *int           `gorm:"index"`
	AddedByName         *string        `gorm:"type:varchar(255)"`
}

func (ModelEntry) TableName() string { return "models" }

type Provider struct {
	TimestampMixin
	ID                          int            `gorm:"primaryKey;autoIncrement"`
	Name                        string         `gorm:"type:varchar(120);uniqueIndex;not null"`
	Type                        string         `gorm:"type:varchar(64);default:openai"`
	BaseURL                     string         `gorm:"column:base_url;type:varchar(512);default:''"`
	Enabled                     bool           `gorm:"default:true;not null"`
	Priority                    int            `gorm:"default:100"`
	Weight                      int            `gorm:"default:1"`
	Models                      []string       `gorm:"type:text;serializer:json"`
	ModelMap                    map[string]any `gorm:"column:model_map;type:text;serializer:json"`
	ModelRoutes                 []any          `gorm:"column:model_routes;type:text;serializer:json"`
	BalanceURL                  *string        `gorm:"column:balance_url;type:varchar(512)"`
	ExtraHeaders                map[string]any `gorm:"column:extra_headers;type:text;serializer:json"`
	TimeoutSeconds              int            `gorm:"column:timeout_seconds;default:0"`
	DropOpenCodeIdentityBlock   bool           `gorm:"column:drop_opencode_identity_block;default:false;not null"`
	ProxyMode                   string         `gorm:"column:proxy_mode;type:varchar(16);default:all;not null"`
	ProxyIDs                    []any          `gorm:"column:proxy_ids;type:text;serializer:json"`
	AddedBy                     *int           `gorm:"index"`
	AddedByName                 *string        `gorm:"type:varchar(255)"`
	KeyAPIEnabled               bool           `gorm:"column:key_api_enabled;default:false;not null"`
	KeyAPITokenHash             *string        `gorm:"column:key_api_token_hash;type:varchar(64);index"`
	KeyAPITokenPreview          *string        `gorm:"column:key_api_token_preview;type:varchar(48)"`
}

func (Provider) TableName() string { return "providers" }

type ApiKey struct {
	TimestampMixin
	ID              int            `gorm:"primaryKey;autoIncrement"`
	ProviderID      int            `gorm:"column:provider_id;index;not null;uniqueIndex:uq_provider_key"`
	Provider        *Provider      `gorm:"foreignKey:ProviderID;constraint:OnDelete:CASCADE"`
	KeyCiphertext   string         `gorm:"column:key_ciphertext;type:text;not null"`
	KeyHash         string         `gorm:"column:key_hash;type:varchar(64);index;not null;uniqueIndex:uq_provider_key"`
	KeyPreview      string         `gorm:"column:key_preview;type:varchar(32);default:''"`
	Pool            string         `gorm:"type:varchar(64);default:'';index"`
	Status          string         `gorm:"type:varchar(32);default:active;index"`
	FailedCount     int            `gorm:"column:failed_count;default:0"`
	Weight          int            `gorm:"default:1"`
	Note            *string        `gorm:"type:varchar(255)"`
	Balance         map[string]any `gorm:"type:text;serializer:json"`
	DisabledReason  *string        `gorm:"column:disabled_reason;type:varchar(255)"`
	DisabledSince   *time.Time     `gorm:"column:disabled_since;type:datetime"`
	TotalRequests   int            `gorm:"column:total_requests;default:0"`
	LastUsedAt      *time.Time     `gorm:"column:last_used_at;type:datetime"`
	LastCheckedAt   *time.Time     `gorm:"column:last_checked_at;type:datetime"`
	AddedBy         *int           `gorm:"index"`
	AddedByName     *string        `gorm:"type:varchar(255)"`
}

func (ApiKey) TableName() string { return "api_keys" }

type Proxy struct {
	TimestampMixin
	ID             int        `gorm:"primaryKey;autoIncrement"`
	URL            string     `gorm:"type:varchar(512);default:'';uniqueIndex"`
	LocalAddress   *string    `gorm:"column:local_address;type:varchar(64)"`
	Enabled        bool       `gorm:"default:true;not null"`
	Status         string     `gorm:"type:varchar(32);default:active;index"`
	FailedCount    int        `gorm:"column:failed_count;default:0"`
	Weight         int        `gorm:"default:1"`
	LatencyMs      *float64   `gorm:"column:latency_ms;type:float"`
	Note           *string    `gorm:"type:varchar(255)"`
	DisabledReason *string    `gorm:"column:disabled_reason;type:varchar(255)"`
	LastUsedAt     *time.Time `gorm:"column:last_used_at;type:datetime"`
	LastCheckedAt  *time.Time `gorm:"column:last_checked_at;type:datetime"`
}

func (Proxy) TableName() string { return "proxies" }

type Setting struct {
	Key       string         `gorm:"type:varchar(120);primaryKey"`
	Value     any            `gorm:"type:text;serializer:json"`
	UpdatedAt time.Time      `gorm:"autoUpdateTime"`
}

func (Setting) TableName() string { return "settings" }

type AuditLog struct {
	ID                  int            `gorm:"primaryKey;autoIncrement"`
	Ts                  time.Time      `gorm:"autoCreateTime;index"`
	ActorSub            *string        `gorm:"column:actor_sub;type:varchar(255);index"`
	ActorName           *string        `gorm:"column:actor_name;type:varchar(255)"`
	Action              string         `gorm:"type:varchar(120);default:''"`
	Scope               string         `gorm:"type:varchar(16);default:admin;index;not null"`
	TargetType          *string        `gorm:"column:target_type;type:varchar(64)"`
	TargetID            *string        `gorm:"column:target_id;type:varchar(64)"`
	Detail              map[string]any `gorm:"type:text;serializer:json"`
	IP                  *string        `gorm:"type:varchar(64)"`
	SensitiveCiphertext *string        `gorm:"column:sensitive_ciphertext;type:text"`
}

func (AuditLog) TableName() string { return "audit_logs" }

type RequestLog struct {
	ID               int        `gorm:"primaryKey;autoIncrement"`
	Ts               time.Time  `gorm:"autoCreateTime;index"`
	TokenID          *int       `gorm:"column:token_id;index"`
	TokenName        *string    `gorm:"column:token_name;type:varchar(120)"`
	UserSub          *string    `gorm:"column:user_sub;type:varchar(255);index"`
	UserName         *string    `gorm:"column:user_name;type:varchar(255)"`
	ProviderID       *int       `gorm:"column:provider_id"`
	ProviderName     *string    `gorm:"column:provider_name;type:varchar(120)"`
	KeyID            *int       `gorm:"column:key_id"`
	ProxyID          *int       `gorm:"column:proxy_id"`
	Model            *string    `gorm:"type:varchar(120);index"`
	InboundStyle     *string    `gorm:"column:inbound_style;type:varchar(32)"`
	UpstreamStyle    *string    `gorm:"column:upstream_style;type:varchar(32)"`
	StatusCode       *int       `gorm:"column:status_code"`
	Success          bool       `gorm:"default:false;index;not null"`
	LatencyMs        *float64   `gorm:"column:latency_ms;type:float"`
	PromptTokens     int        `gorm:"column:prompt_tokens;default:0"`
	CompletionTokens int        `gorm:"column:completion_tokens;default:0"`
	TotalTokens      int        `gorm:"column:total_tokens;default:0"`
	Stream           bool       `gorm:"default:false;not null"`
	Attempts         int        `gorm:"default:1"`
	Error            *string    `gorm:"type:text"`
	Debug            bool       `gorm:"default:false;not null"`
	ReqHeaders       *string    `gorm:"column:req_headers;type:text"`
	ReqBody          *string    `gorm:"column:req_body;type:text"`
	RespHeaders      *string    `gorm:"column:resp_headers;type:text"`
	RespBody         *string    `gorm:"column:resp_body;type:text"`
	UpstreamURL      *string    `gorm:"column:upstream_url;type:text"`
	ProxyURL         *string    `gorm:"column:proxy_url;type:varchar(512)"`
}

func (RequestLog) TableName() string { return "request_logs" }

type Announcement struct {
	ID                  int        `gorm:"primaryKey;autoIncrement"`
	CreatedAt           time.Time  `gorm:"autoCreateTime"`
	UpdatedAt           time.Time  `gorm:"autoUpdateTime"`
	Title               string     `gorm:"type:varchar(255);not null"`
	Body                string     `gorm:"type:text;default:''"`
	CreatedBy           int        `gorm:"index;not null"`
	CreatedByName       string     `gorm:"type:varchar(255)"`
	CreatedByRole       string     `gorm:"type:varchar(32)"`
	Edited              bool       `gorm:"default:false"`
	TargetRoleGroupIDs  []int      `gorm:"column:target_role_group_ids;type:text;serializer:json"`
}

func (Announcement) TableName() string { return "announcements" }

type RoleGroup struct {
	ID          int               `gorm:"primaryKey;autoIncrement"`
	CreatedAt   time.Time         `gorm:"autoCreateTime"`
	UpdatedAt   time.Time         `gorm:"autoUpdateTime"`
	Slug        string            `gorm:"type:varchar(120);uniqueIndex;not null"`
	Name        string            `gorm:"type:varchar(120);uniqueIndex;not null"`
	Description *string           `gorm:"type:text"`
	Builtin     bool              `gorm:"default:false;not null"`
	Mappings    []RoleGroupMapping `gorm:"foreignKey:RoleGroupID;constraint:OnDelete:CASCADE"`
}

func (RoleGroup) TableName() string { return "role_groups" }

type RoleGroupMapping struct {
	ID          int    `gorm:"primaryKey;autoIncrement"`
	RoleGroupID int    `gorm:"index;not null"`
	TeamID      string `gorm:"type:varchar(255);not null"`
	MinRole     string `gorm:"type:varchar(32);not null"`
}

func (RoleGroupMapping) TableName() string { return "role_group_mappings" }

type RoleGroupMembership struct {
	ID          int    `gorm:"primaryKey;autoIncrement"`
	UserID      int    `gorm:"index;not null;uniqueIndex:idx_user_group"`
	RoleGroupID int    `gorm:"index;not null;uniqueIndex:idx_user_group"`
	Source      string `gorm:"type:varchar(16);default:auto;not null"`
}

func (RoleGroupMembership) TableName() string { return "role_group_memberships" }

type addedColumn struct {
	Table  string
	Column string
	DDL    string
}

var addedColumns = []addedColumn{
	{"providers", "drop_opencode_identity_block", "BOOLEAN NOT NULL DEFAULT 0"},
	{"providers", "proxy_mode", "VARCHAR(16) NOT NULL DEFAULT 'all'"},
	{"providers", "proxy_ids", "JSON NOT NULL DEFAULT '[]'"},
	{"providers", "model_routes", "JSON NOT NULL DEFAULT '[]'"},
	{"providers", "added_by", "INTEGER"},
	{"providers", "added_by_name", "VARCHAR(255)"},
	{"providers", "key_api_enabled", "BOOLEAN NOT NULL DEFAULT 0"},
	{"providers", "key_api_token_hash", "VARCHAR(64)"},
	{"providers", "key_api_token_preview", "VARCHAR(48)"},
	{"api_keys", "pool", "VARCHAR(64) NOT NULL DEFAULT ''"},
	{"api_keys", "added_by", "INTEGER"},
	{"api_keys", "added_by_name", "VARCHAR(255)"},
	{"api_keys", "disabled_since", "DATETIME"},
	{"audit_logs", "sensitive_ciphertext", "TEXT"},
	{"audit_logs", "scope", "VARCHAR(16) NOT NULL DEFAULT 'admin'"},
	{"models", "mapped_id", "VARCHAR(255)"},
	{"models", "display_name", "VARCHAR(255)"},
	{"request_logs", "debug", "BOOLEAN NOT NULL DEFAULT 0"},
	{"request_logs", "token_name", "VARCHAR(255)"},
	{"request_logs", "user_name", "VARCHAR(255)"},
	{"request_logs", "req_headers", "TEXT"},
	{"request_logs", "req_body", "TEXT"},
	{"request_logs", "resp_headers", "TEXT"},
	{"request_logs", "resp_body", "TEXT"},
	{"request_logs", "upstream_url", "TEXT"},
	{"request_logs", "proxy_url", "VARCHAR(512)"},
	{"users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"},
}

func addMissingColumns(gdb *gorm.DB) error {
	var tableNames []string
	gdb.Raw("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").Scan(&tableNames)

	tableSet := make(map[string]bool, len(tableNames))
	for _, t := range tableNames {
		tableSet[t] = true
	}

	for _, ac := range addedColumns {
		if !tableSet[ac.Table] {
			continue
		}

		var cols []struct{ Name string }
		gdb.Raw(fmt.Sprintf("PRAGMA table_info(%s)", ac.Table)).Scan(&cols)

		exists := false
		for _, c := range cols {
			if c.Name == ac.Column {
				exists = true
				break
			}
		}
		if exists {
			continue
		}

		sql := fmt.Sprintf("ALTER TABLE %s ADD COLUMN %s %s", ac.Table, ac.Column, ac.DDL)
		if err := gdb.Exec(sql).Error; err != nil {
			return fmt.Errorf("add column %s.%s: %w", ac.Table, ac.Column, err)
		}
	}

	return nil
}


