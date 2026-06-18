package services

import (
	"strings"

	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/database"
)

var RoleGroupRank = constants.TeamRoleRank

func NormaliseTeamRole(value string) string {
	if value == "" {
		return ""
	}
	key := strings.ToLower(strings.TrimSpace(value))
	key = strings.NewReplacer("-", "", "_", "", " ", "").Replace(key)
	if key == "coowner" {
		return "co-owner"
	}
	aliases := map[string]string{
		"owner": "owner", "admin": "admin", "member": "member",
	}
	if v, ok := aliases[key]; ok {
		return v
	}
	return ""
}

func TeamRoleRank(value string) int {
	canonical := NormaliseTeamRole(value)
	if canonical == "" {
		return 0
	}
	return constants.TeamRoleRank[canonical]
}

func EnsureModeratorGroup(db *gorm.DB) (*database.RoleGroup, error) {
	var group database.RoleGroup
	if err := db.Where("slug = ?", constants.ModeratorGroupSlug).First(&group).Error; err != nil {
		desc := "Owner / co-owner / admin. Always allowed to call every model. Built-in — cannot be deleted or restricted."
		group = database.RoleGroup{
			Slug:        constants.ModeratorGroupSlug,
			Name:        "Moderator",
			Description: &desc,
			Builtin:     true,
		}
		if err := db.Create(&group).Error; err != nil {
			return nil, err
		}
	}
	return &group, nil
}

func EvaluateAutoGroupIDs(db *gorm.DB, teams []map[string]any) ([]int, error) {
	var groups []database.RoleGroup
	if err := db.Where("builtin = ?", false).Find(&groups).Error; err != nil {
		return nil, err
	}

	var granted []int
	for _, group := range groups {
		for _, mapping := range group.Mappings {
			userRank := TeamRoleRank(effectiveTeamRole(teams, mapping.TeamID))
			if userRank <= 0 {
				continue
			}
			if userRank >= TeamRoleRank(mapping.MinRole) {
				granted = append(granted, group.ID)
				break
			}
		}
	}
	return granted, nil
}

func SyncAutoMemberships(db *gorm.DB, userID int, autoGroupIDs []int) error {
	desired := make(map[int]bool)
	for _, gid := range autoGroupIDs {
		desired[gid] = true
	}

	var memberships []database.RoleGroupMembership
	if err := db.Where("user_id = ?", userID).Find(&memberships).Error; err != nil {
		return err
	}

	existing := make(map[int]database.RoleGroupMembership)
	for _, m := range memberships {
		existing[m.RoleGroupID] = m
	}

	for gid, membership := range existing {
		if membership.Source == "auto" && !desired[gid] {
			db.Delete(&membership)
		}
	}

	for gid := range desired {
		if _, ok := existing[gid]; !ok {
			db.Create(&database.RoleGroupMembership{
				UserID:      userID,
				RoleGroupID: gid,
				Source:      "auto",
			})
		} else {
			m := existing[gid]
			if m.Source != "manual" {
				db.Model(&m).Update("source", "auto")
			}
		}
	}

	return nil
}

func UserGroupIDs(db *gorm.DB, userID int) ([]int, error) {
	var ids []int
	if err := db.Model(&database.RoleGroupMembership{}).
		Where("user_id = ?", userID).
		Pluck("role_group_id", &ids).Error; err != nil {
		return nil, err
	}
	return ids, nil
}

func ModelAllowedForGroups(entry *database.ModelEntry, groupIDs []int, isMod bool) bool {
	if isMod {
		return true
	}
	if entry == nil {
		return false
	}
	allowed := entry.AllowedRoleGroupIDs
	if len(allowed) == 0 {
		return false
	}
	groupSet := make(map[int]bool)
	for _, id := range groupIDs {
		groupSet[id] = true
	}
	for _, id := range allowed {
		if groupSet[id] {
			return true
		}
	}
	return false
}

func effectiveTeamRole(teams []map[string]any, teamID string) string {
	if teamID == "" {
		return ""
	}
	bestRank := 0
	bestRole := ""
	for _, entry := range teams {
		id, _ := entry["id"].(string)
		if id != teamID {
			continue
		}
		role, _ := entry["role"].(string)
		canonical := NormaliseTeamRole(role)
		rank := TeamRoleRank(canonical)
		if rank > bestRank {
			bestRank = rank
			bestRole = canonical
		}
	}
	return bestRole
}
