package services

import (
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

// ResolveAccessToken is a hook assigned by oauth_tokens to resolve a key's
// usable upstream credential (refreshing OAuth bundles as needed).
var ResolveAccessToken func(db *gorm.DB, key *database.ApiKey, secretKey string, forceRefresh bool) (string, error)

// ActiveProxies returns enabled, active nodes. Retained for the OAuth flow which
// prefers the pooled egress path before falling back to direct.
func ActiveProxies(db *gorm.DB) ([]database.Node, error) {
	var nodes []database.Node
	err := db.Where("enabled = ? AND status = ?", true, string(constants.NodeStatusActive)).Find(&nodes).Error
	return nodes, err
}

// EnsureSeededNodeGroups makes sure the "default" node group exists. There is
// no built-in "system" group any more: system-origin requests (OAuth, models.dev
// pulls) always go direct and only use the process HTTP(S)_PROXY env vars if
// configured — they are never routed through the node pool. Any legacy "system"
// group is removed on boot.
func EnsureSeededNodeGroups(db *gorm.DB) error {
	var existing database.NodeGroup
	err := db.Where("slug = ?", "default").First(&existing).Error
	if err == gorm.ErrRecordNotFound {
		slug := "default"
		group := database.NodeGroup{Slug: &slug, Name: "Default", ProbeIntervalSeconds: 0}
		if err := db.Create(&group).Error; err != nil {
			return err
		}
	} else if err != nil {
		return err
	}

	// Drop the obsolete "system" group (and its members) if it exists.
	var legacySystem database.NodeGroup
	if err := db.Where("slug = ? OR is_system = ?", "system", true).First(&legacySystem).Error; err == nil {
		db.Where("group_id = ?", legacySystem.ID).Delete(&database.NodeGroupMember{})
		db.Delete(&legacySystem)
	}
	return nil
}

// DefaultNodeGroupID returns the id of the "default" node group (0 if absent).
func DefaultNodeGroupID(db *gorm.DB) int {
	var g database.NodeGroup
	if err := db.Where("slug = ?", "default").First(&g).Error; err != nil {
		return 0
	}
	return g.ID
}
