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

// EnsureSeededNodeGroups makes sure the special "default" and "system" node
// groups exist, matching Python's routing.ensure_seeded_groups.
func EnsureSeededNodeGroups(db *gorm.DB) error {
	seeds := []struct {
		slug string
		name string
		sys  bool
	}{
		{"default", "Default", false},
		{"system", "System", true},
	}
	for _, s := range seeds {
		var existing database.NodeGroup
		err := db.Where("slug = ?", s.slug).First(&existing).Error
		if err == nil {
			continue
		}
		if err != gorm.ErrRecordNotFound {
			return err
		}
		slug := s.slug
		group := database.NodeGroup{
			Slug:        &slug,
			Name:        s.name,
			IsSystem:    s.sys,
			ProbeIntervalSeconds: 0,
		}
		if err := db.Create(&group).Error; err != nil {
			return err
		}
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
