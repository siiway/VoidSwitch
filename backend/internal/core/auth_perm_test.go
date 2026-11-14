package core

import "testing"

func TestRoleGroupAdminPredicate(t *testing.T) {
	member := &UserView{Role: "member"}
	if member.IsStaff() || member.IsRoleGroupAdmin() {
		t.Fatal("plain member must be neither staff nor rg-admin")
	}
	rgAdmin := &UserView{Role: "member", AdminGroupIDs: []int{3}}
	if rgAdmin.IsStaff() {
		t.Fatal("rg-admin is not staff")
	}
	if !rgAdmin.IsRoleGroupAdmin() {
		t.Fatal("rg-admin with managed groups must be role-group admin")
	}
	staff := &UserView{Role: "admin"}
	if !staff.IsStaff() {
		t.Fatal("admin is staff")
	}
}
