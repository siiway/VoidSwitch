package services

import (
	"encoding/json"
	"fmt"
	"time"

	"github.com/siiway/voidswitch/internal/database"
)

// ---- user view -------------------------------------------------------------

type UserView struct {
	ID                 int        `json:"id"`
	Sub                string     `json:"sub"`
	Username           *string    `json:"username"`
	Email              *string    `json:"email"`
	Name               *string    `json:"name"`
	Picture            *string    `json:"picture"`
	Role               string     `json:"role"`
	PrismRole          *string    `json:"prism_role"`
	TeamIDs            []string   `json:"team_ids"`
	Enabled            bool       `json:"enabled"`
	LastLoginAt        *time.Time `json:"last_login_at"`
	CreatedAt          time.Time  `json:"created_at"`
	RoleGroupNames     []string   `json:"role_group_names,omitempty"`
	ManagedGroupIDs    []int      `json:"managed_group_ids,omitempty"`
	ManagedGroupNames  []string   `json:"managed_group_names,omitempty"`
	VisibleViaGroupIDs []int      `json:"visible_via_group_ids,omitempty"`
}

// BuildUserView maps a DB user to the API view.
func BuildUserView(u *database.User) UserView {
	var teamIDs []string
	database.DecodeJSON(u.TeamIDs, &teamIDs)
	if teamIDs == nil {
		teamIDs = []string{}
	}
	return UserView{
		ID:          u.ID,
		Sub:         u.Sub,
		Username:    u.Username,
		Email:       u.Email,
		Name:        u.Name,
		Picture:     u.Picture,
		Role:        u.Role,
		PrismRole:   u.PrismRole,
		TeamIDs:     teamIDs,
		Enabled:     u.Enabled,
		LastLoginAt: u.LastLoginAt,
		CreatedAt:   u.CreatedAt,
	}
}

// ---- announcement view ----------------------------------------------------

type AnnouncementView struct {
	ID                 int       `json:"id"`
	Title              string    `json:"title"`
	Body               string    `json:"body"`
	CreatedBy          *int      `json:"created_by"`
	CreatedByName      *string   `json:"created_by_name"`
	CreatedByRole      string    `json:"created_by_role"`
	Edited             bool      `json:"edited"`
	TargetRoleGroupIDs []int     `json:"target_role_group_ids"`
	CreatedAt          time.Time `json:"created_at"`
	UpdatedAt          time.Time `json:"updated_at"`
	CanManage          bool      `json:"can_manage"`
}

// ---- model view -----------------------------------------------------------

type ModelEntryView struct {
	ID                  *int       `json:"id"`
	ModelID             string     `json:"model_id"`
	DisplayName         *string    `json:"display_name"`
	Description         *string    `json:"description"`
	OpenCodeConfig      any        `json:"opencode_config"`
	Enabled             bool       `json:"enabled"`
	AllowedRoleGroupIDs []int      `json:"allowed_role_group_ids"`
	LimitContext        *int       `json:"limit_context"`
	LimitInput          *int       `json:"limit_input"`
	LimitOutput         *int       `json:"limit_output"`
	Reasoning           *bool      `json:"reasoning"`
	Capabilities        any        `json:"capabilities"`
	Modalities          any        `json:"modalities"`
	ModelsDevID         *string    `json:"models_dev_id"`
	ModelsDevSyncedAt   *time.Time `json:"models_dev_synced_at"`
	Brand               *string    `json:"brand"`
	Upstreams           []string   `json:"upstreams"`
	AddedByName         *string    `json:"added_by_name"`
	CreatedAt           *time.Time `json:"created_at"`
	UpdatedAt           *time.Time `json:"updated_at"`
	CategoryID          *int       `json:"category_id"`
	CategoryName        *string    `json:"category_name"`
	CategorySlug        *string    `json:"category_slug"`
	Provider            bool       `json:"provider"`
	Unserved            bool       `json:"unserved"`
}

// BuildModelEntryView maps an exposed model + its reachable upstream refs.
func BuildModelEntryView(m *database.ExposedModel, upstreams []string) ModelEntryView {
	var oc, caps, mods, allowed any
	_ = decodeAny(m.OpenCodeConfig, &oc)
	_ = decodeAny(m.Capabilities, &caps)
	_ = decodeAny(m.Modalities, &mods)
	var allowedIDs []int
	database.DecodeJSON(m.AllowedRoleGroupIDs, &allowedIDs)
	_ = allowed
	if upstreams == nil {
		upstreams = []string{}
	}
	if oc == nil {
		oc = map[string]any{}
	}
	if caps == nil {
		caps = map[string]any{}
	}
	if mods == nil {
		mods = map[string]any{}
	}
	createdAt := m.CreatedAt
	updatedAt := m.UpdatedAt
	return ModelEntryView{
		ID:                  &m.ID,
		ModelID:             m.ModelID,
		DisplayName:         m.DisplayName,
		Description:         m.Description,
		OpenCodeConfig:      oc,
		Enabled:             m.Enabled,
		AllowedRoleGroupIDs: allowedIDs,
		LimitContext:        m.LimitContext,
		LimitInput:          m.LimitInput,
		LimitOutput:         m.LimitOutput,
		Reasoning:           m.Reasoning,
		Capabilities:        caps,
		Modalities:          mods,
		ModelsDevID:         m.ModelsDevID,
		ModelsDevSyncedAt:   m.ModelsDevSyncedAt,
		Brand:               m.Brand,
		Upstreams:           upstreams,
		AddedByName:         m.AddedByName,
		CreatedAt:           &createdAt,
		UpdatedAt:           &updatedAt,
		CategoryID:          m.CategoryID,
		Unserved:            len(upstreams) == 0,
	}
}

func decodeAny(j database.JSON, dst *any) error {
	if len(j) == 0 {
		return nil
	}
	return json.Unmarshal(j, dst)
}

// ProviderView is the admin provider payload (matches the frontend Provider type).
type ProviderView struct {
	ID                             int               `json:"id"`
	UUID                           string            `json:"uuid"`
	Name                           string            `json:"name"`
	Slug                           string            `json:"slug"`
	Type                           string            `json:"type"`
	BaseURL                        string            `json:"base_url"`
	Enabled                        bool              `json:"enabled"`
	Priority                       int               `json:"priority"`
	Weight                         int               `json:"weight"`
	Models                         []string          `json:"models"`
	BalanceURL                     *string           `json:"balance_url"`
	ExtraHeaders                   map[string]string `json:"extra_headers"`
	TimeoutSeconds                 int               `json:"timeout_seconds"`
	RetryOnZeroToken               bool              `json:"retry_on_zero_token"`
	DropOpenCodeIdentityBlock      bool              `json:"drop_opencode_identity_block"`
	NormalizeDeveloperRoleToSystem bool              `json:"normalize_developer_role_to_system"`
	NodeGroupID                    *int              `json:"node_group_id"`
	KeySelectMode                  string            `json:"key_select_mode"`
	RateLimitCooldownSeconds       int               `json:"rate_limit_cooldown_seconds"`
	CreatedAt                      time.Time         `json:"created_at"`
	UpdatedAt                      time.Time         `json:"updated_at"`
	KeyCount                       int               `json:"key_count"`
	ActiveKeyCount                 int               `json:"active_key_count"`
	SupportsBalance                bool              `json:"supports_balance"`
	SupportsImport                 bool              `json:"supports_import"`
	SupportsRefresh                bool              `json:"supports_refresh"`
	SupportsOAuth                  bool              `json:"supports_oauth"`
	AddedBy                        *int              `json:"added_by"`
	AddedByName                    *string           `json:"added_by_name"`
	KeyAPIEnabled                  bool              `json:"key_api_enabled"`
	KeyAPITokenPreview             *string           `json:"key_api_token_preview"`
	PassthroughEnabled             bool              `json:"passthrough_enabled"`
	PassthroughModels              []string          `json:"passthrough_models"`
	NewAPIMode                     string            `json:"new_api_mode"`
	ProtectedErrorRetryEnabled     bool              `json:"protected_error_retry_enabled"`
	SelectiveIgnoreRules           any               `json:"selective_ignore_rules"`
}

// BuildProviderView maps a provider row to the admin payload.
func BuildProviderView(p *database.Provider, keys []database.ApiKey) ProviderView {
	var models, ptModels, rules []string
	database.DecodeJSON(p.Models, &models)
	database.DecodeJSON(p.PassthroughModels, &ptModels)
	if models == nil {
		models = []string{}
	}
	if ptModels == nil {
		ptModels = []string{}
	}
	var hdrs map[string]any
	database.DecodeJSON(p.ExtraHeaders, &hdrs)
	extra := map[string]string{}
	for k, v := range hdrs {
		extra[k] = fmt.Sprint(v)
	}
	var ignoreRules any
	if len(p.SelectiveIgnoreRules) > 0 {
		_ = json.Unmarshal(p.SelectiveIgnoreRules, &ignoreRules)
	}
	if ignoreRules == nil {
		ignoreRules = []any{}
	}
	_ = rules

	keyCount := len(keys)
	active := 0
	for _, k := range keys {
		if k.Status == "active" {
			active++
		}
	}

	var balURL *string = p.BalanceURL
	return ProviderView{
		ID: p.ID, UUID: p.UUID, Name: p.Name, Slug: p.Slug, Type: p.Type,
		BaseURL: p.BaseURL, Enabled: p.Enabled, Priority: p.Priority, Weight: p.Weight,
		Models: models, BalanceURL: balURL, ExtraHeaders: extra,
		TimeoutSeconds: p.TimeoutSeconds, RetryOnZeroToken: p.RetryOnZeroToken,
		DropOpenCodeIdentityBlock:      p.DropOpenCodeIdentityBlock,
		NormalizeDeveloperRoleToSystem: p.NormalizeDeveloperRoleToSystem,
		NodeGroupID:                    p.NodeGroupID, KeySelectMode: p.KeySelectMode,
		RateLimitCooldownSeconds: p.RateLimitCooldownSeconds,
		CreatedAt:                p.CreatedAt, UpdatedAt: p.UpdatedAt,
		KeyCount: keyCount, ActiveKeyCount: active,
		AddedBy: p.AddedBy, AddedByName: p.AddedByName,
		KeyAPIEnabled: p.KeyAPIEnabled, KeyAPITokenPreview: p.KeyAPITokenPreview,
		PassthroughEnabled: p.PassthroughEnabled, PassthroughModels: ptModels,
		NewAPIMode: p.NewAPIMode, ProtectedErrorRetryEnabled: p.ProtectedErrorRetryEnabled,
		SelectiveIgnoreRules: ignoreRules,
	}
}
