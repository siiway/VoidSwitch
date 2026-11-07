package services

import (
	"encoding/json"
	"time"

	"github.com/siiway/voidswitch/internal/database"
)

// ---- user view -------------------------------------------------------------

type UserView struct {
	ID                  int        `json:"id"`
	Sub                 string     `json:"sub"`
	Username            *string    `json:"username"`
	Email               *string    `json:"email"`
	Name                *string    `json:"name"`
	Picture             *string    `json:"picture"`
	Role                string     `json:"role"`
	PrismRole           *string    `json:"prism_role"`
	TeamIDs             []string   `json:"team_ids"`
	Enabled             bool       `json:"enabled"`
	LastLoginAt         *time.Time `json:"last_login_at"`
	CreatedAt           time.Time  `json:"created_at"`
	RoleGroupNames      []string   `json:"role_group_names,omitempty"`
	ManagedGroupIDs     []int      `json:"managed_group_ids,omitempty"`
	ManagedGroupNames   []string   `json:"managed_group_names,omitempty"`
	VisibleViaGroupIDs  []int      `json:"visible_via_group_ids,omitempty"`
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
	ID                  *int            `json:"id"`
	ModelID             string          `json:"model_id"`
	DisplayName         *string         `json:"display_name"`
	Description         *string         `json:"description"`
	OpenCodeConfig      any             `json:"opencode_config"`
	Enabled             bool            `json:"enabled"`
	AllowedRoleGroupIDs []int           `json:"allowed_role_group_ids"`
	LimitContext        *int            `json:"limit_context"`
	LimitInput          *int            `json:"limit_input"`
	LimitOutput         *int            `json:"limit_output"`
	Reasoning           *bool           `json:"reasoning"`
	Capabilities        any             `json:"capabilities"`
	Modalities          any             `json:"modalities"`
	ModelsDevID         *string         `json:"models_dev_id"`
	ModelsDevSyncedAt   *time.Time      `json:"models_dev_synced_at"`
	Brand               *string         `json:"brand"`
	Upstreams           []string        `json:"upstreams"`
	AddedByName         *string         `json:"added_by_name"`
	CreatedAt           *time.Time      `json:"created_at"`
	UpdatedAt           *time.Time      `json:"updated_at"`
	CategoryID          *int            `json:"category_id"`
	CategoryName        *string         `json:"category_name"`
	CategorySlug        *string         `json:"category_slug"`
	Provider            bool            `json:"provider"`
	Unserved            bool            `json:"unserved"`
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
