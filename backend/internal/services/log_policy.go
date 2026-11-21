package services

import (
	"strconv"
	"strings"
)

// Log capture levels. A level describes how much of one request is stored; the
// settings map each source (a successful call, a debug-enabled token, a failed
// call) onto one of them, and each level onto the minimum viewer it is shown to.
const (
	LogLevelNone    = 1 // routing chain only
	LogLevelHeaders = 2 // chain + redacted request/response headers
	LogLevelBodies  = 3 // chain + headers + request body + response body (SSE included)
	LogLevelError   = 4 // chain + non-SSE response body + the error message
)

// Viewer tiers, ordered by increasing privilege.
const (
	LogAccessUser           = "A" // the row's own user
	LogAccessRoleGroupAdmin = "B"
	LogAccessAdmin          = "C"
	LogAccessOwner          = "D"
)

// CapturePolicy is the source → level mapping.
type CapturePolicy struct {
	Success int
	Debug   int
	Error   int
}

// LevelFor returns the capture level for one request. A debug-enabled token wins
// over the outcome: the operator asked for those bodies explicitly.
//
// A zero-value policy (settings not loaded yet, or a caller that never set one)
// behaves like the pre-policy defaults rather than capturing nothing.
func (p CapturePolicy) LevelFor(debugEnabled, failed bool) int {
	if p.isZero() {
		p = CapturePolicy{Success: LogLevelNone, Debug: LogLevelBodies, Error: LogLevelError}
	}
	switch {
	case debugEnabled:
		return ClampLogLevel(p.Debug)
	case failed:
		return ClampLogLevel(p.Error)
	default:
		return ClampLogLevel(p.Success)
	}
}

func (p CapturePolicy) isZero() bool {
	return p.Success == 0 && p.Debug == 0 && p.Error == 0
}

// ClampLogLevel keeps a stored/configured level inside the supported range.
func ClampLogLevel(level int) int {
	if level < LogLevelNone {
		return LogLevelNone
	}
	if level > LogLevelError {
		return LogLevelError
	}
	return level
}

// CapturePolicyFromSettings reads the source → level mapping, falling back to the
// behaviour the backend had before the mapping existed: successful requests keep
// only the chain, debug tokens keep everything, failures keep the error body.
func CapturePolicyFromSettings() CapturePolicy {
	p := CapturePolicy{Success: LogLevelNone, Debug: LogLevelBodies, Error: LogLevelError}
	if m, ok := GetSetting("log_capture_policy").(map[string]any); ok {
		p.Success = intFromAny(m["success"], p.Success)
		p.Debug = intFromAny(m["debug"], p.Debug)
		p.Error = intFromAny(m["error"], p.Error)
	}
	return p
}

// LogAccessTier returns the minimum viewer tier for a capture level.
func LogAccessTier(level int) string {
	def := defaultAccessFor(level)
	m, ok := GetSetting("log_access_policy").(map[string]any)
	if !ok {
		return def
	}
	raw, ok := m[levelKey(level)]
	if !ok {
		return def
	}
	s, ok := raw.(string)
	if !ok {
		return def
	}
	s = strings.ToUpper(strings.TrimSpace(s))
	switch s {
	case LogAccessUser, LogAccessRoleGroupAdmin, LogAccessAdmin, LogAccessOwner:
		return s
	}
	return def
}

func defaultAccessFor(level int) string {
	switch level {
	case LogLevelHeaders:
		return LogAccessAdmin
	case LogLevelBodies:
		return LogAccessOwner
	case LogLevelError:
		return LogAccessAdmin
	default:
		return LogAccessUser
	}
}

// LogAccessRank orders the tiers; higher may see everything a lower tier may.
func LogAccessRank(tier string) int {
	switch tier {
	case LogAccessOwner:
		return 4
	case LogAccessAdmin:
		return 3
	case LogAccessRoleGroupAdmin:
		return 2
	default:
		return 1
	}
}

func levelKey(level int) string {
	switch level {
	case LogLevelHeaders:
		return "2"
	case LogLevelBodies:
		return "3"
	case LogLevelError:
		return "4"
	default:
		return "1"
	}
}

func intFromAny(v any, def int) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case string:
		if i, err := strconv.Atoi(strings.TrimSpace(n)); err == nil {
			return i
		}
	}
	return def
}
