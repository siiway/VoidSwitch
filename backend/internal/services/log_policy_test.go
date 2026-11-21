package services

import "testing"

// TestCapturePolicyLevelSelection pins the source → level resolution: a debug
// token wins over the outcome, a failure uses the error mapping, and the rest use
// the success mapping. A zero policy behaves like the pre-policy defaults.
func TestCapturePolicyLevelSelection(t *testing.T) {
	p := CapturePolicy{Success: LogLevelNone, Debug: LogLevelBodies, Error: LogLevelError}
	cases := []struct {
		debug  bool
		failed bool
		want   int
	}{
		{false, false, LogLevelNone},
		{false, true, LogLevelError},
		{true, false, LogLevelBodies},
		{true, true, LogLevelBodies},
	}
	for _, tc := range cases {
		if got := p.LevelFor(tc.debug, tc.failed); got != tc.want {
			t.Fatalf("LevelFor(%v, %v) = %d, want %d", tc.debug, tc.failed, got, tc.want)
		}
	}

	zero := CapturePolicy{}
	if got := zero.LevelFor(true, false); got != LogLevelBodies {
		t.Fatalf("zero policy debug = %d, want %d", got, LogLevelBodies)
	}
	if got := zero.LevelFor(false, true); got != LogLevelError {
		t.Fatalf("zero policy error = %d, want %d", got, LogLevelError)
	}
	if got := zero.LevelFor(false, false); got != LogLevelNone {
		t.Fatalf("zero policy success = %d, want %d", got, LogLevelNone)
	}

	// A single mapped key is enough to stop the zero-value fallback.
	partial := CapturePolicy{Success: LogLevelHeaders}
	if got := partial.LevelFor(false, false); got != LogLevelHeaders {
		t.Fatalf("partial policy success = %d, want %d", got, LogLevelHeaders)
	}
}

func TestClampLogLevel(t *testing.T) {
	for in, want := range map[int]int{-3: 1, 0: 1, 1: 1, 2: 2, 3: 3, 4: 4, 9: 4} {
		if got := ClampLogLevel(in); got != want {
			t.Fatalf("ClampLogLevel(%d) = %d, want %d", in, got, want)
		}
	}
}

func TestLogAccessRank(t *testing.T) {
	order := []string{LogAccessUser, LogAccessRoleGroupAdmin, LogAccessAdmin, LogAccessOwner}
	for i := 1; i < len(order); i++ {
		if LogAccessRank(order[i]) <= LogAccessRank(order[i-1]) {
			t.Fatalf("%s should outrank %s", order[i], order[i-1])
		}
	}
	if LogAccessRank("nonsense") != 1 {
		t.Fatal("an unknown tier should rank as the narrowest viewer")
	}
}

// TestDefaultAccessPerLevel documents the fallbacks used when the setting is
// absent: headers reach admins, bodies reach owners, error bodies reach admins.
func TestDefaultAccessPerLevel(t *testing.T) {
	cases := map[int]string{
		LogLevelNone:    LogAccessUser,
		LogLevelHeaders: LogAccessAdmin,
		LogLevelBodies:  LogAccessOwner,
		LogLevelError:   LogAccessAdmin,
	}
	for level, want := range cases {
		if got := LogAccessTier(level); got != want {
			t.Fatalf("LogAccessTier(%d) = %q, want %q", level, got, want)
		}
	}
}
