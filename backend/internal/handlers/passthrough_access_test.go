package handlers

import "testing"

// Passthrough access control mirrors a regular model: staff always pass, a
// model with no groups selected is staff-only, and a member passes only through
// one of the listed groups.
func TestPassthroughAllowedForGroups(t *testing.T) {
	tests := []struct {
		name       string
		roleGroups []int
		groupIDs   []int
		isStaff    bool
		want       bool
	}{
		{"staff with no groups", nil, nil, true, true},
		{"staff with groups", []int{1}, []int{1}, true, true},
		{"member no groups selected", nil, []int{1, 2}, false, false},
		{"empty list is staff-only", []int{}, []int{1}, false, false},
		{"member in a listed group", []int{1, 2}, []int{2}, false, true},
		{"member outside the list", []int{1, 2}, []int{3}, false, false},
		{"member with no memberships", []int{1}, nil, false, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := passthroughAllowedForGroups(tt.roleGroups, tt.groupIDs, tt.isStaff); got != tt.want {
				t.Fatalf("passthroughAllowedForGroups(%v, %v, %v) = %v, want %v",
					tt.roleGroups, tt.groupIDs, tt.isStaff, got, tt.want)
			}
		})
	}
}
