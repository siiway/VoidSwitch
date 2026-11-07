package config

import "testing"

func TestValidateRejectsBypassInProduction(t *testing.T) {
	s := &Settings{Environment: "production", DevOnlyAuthBypass: true}
	if err := s.Validate(); err == nil {
		t.Fatal("expected production + bypass to be rejected")
	}
	if s.DevAuthBypassActive() {
		t.Fatal("bypass must not be active in production")
	}
}

func TestValidateAllowsBypassInDevelopment(t *testing.T) {
	s := &Settings{Environment: "development", DevOnlyAuthBypass: true}
	if err := s.Validate(); err != nil {
		t.Fatalf("development + bypass should be allowed: %v", err)
	}
	if !s.DevAuthBypassActive() {
		t.Fatal("bypass should be active in development")
	}
}

func TestBypassRequiresExplicitDevelopment(t *testing.T) {
	// Flag set but env empty/other → Validate should reject (not silently allow).
	s := &Settings{Environment: "staging", DevOnlyAuthBypass: true}
	if err := s.Validate(); err == nil {
		t.Fatal("bypass outside development must be rejected")
	}
	if s.DevAuthBypassActive() {
		t.Fatal("bypass must not be active outside development")
	}
}

func TestBypassDisabledByDefault(t *testing.T) {
	s := &Settings{Environment: "development"}
	if s.DevAuthBypassActive() {
		t.Fatal("bypass must be off by default")
	}
}
