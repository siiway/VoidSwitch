package services

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
)

const maxSessionIDChars = 120

// SessionKey derives a stable per-session identifier for a request, used for the
// per-session pinned key-select modes and the session_spans rollup. Precedence:
//  1. explicit client session id (x-voidswitch-session / OpenCode sessionID)
//  2. Anthropic metadata.user_id
//  3. hash of the conversation prefix (system/instructions + first message)
//
// Always namespaced by the calling token so two tokens never share a pin.
func SessionKey(tokenID int, explicitSessionID string, payload map[string]any) string {
	if explicitSessionID != "" {
		return fmt.Sprintf("t%d:sid:%s", tokenID, truncateStr(explicitSessionID, maxSessionIDChars))
	}
	if meta, ok := payload["metadata"].(map[string]any); ok {
		if uid, ok := meta["user_id"].(string); ok && uid != "" {
			return fmt.Sprintf("t%d:u:%s", tokenID, truncateStr(uid, maxSessionIDChars))
		}
	}
	var parts []string
	system := payload["system"]
	if system == nil {
		system = payload["instructions"]
	}
	if system != nil {
		parts = append(parts, stringifyAny(system))
	}
	if msgs, ok := payload["messages"].([]any); ok && len(msgs) > 0 {
		parts = append(parts, stringifyAny(msgs[0]))
	} else if rawInput, ok := payload["input"]; ok {
		switch v := rawInput.(type) {
		case string:
			if v != "" {
				parts = append(parts, v)
			}
		case []any:
			if len(v) > 0 {
				parts = append(parts, stringifyAny(v[0]))
			}
		}
	}
	sum := sha256.Sum256([]byte(strings.Join(parts, "\x00")))
	return fmt.Sprintf("t%d:s:%s", tokenID, hex.EncodeToString(sum[:])[:16])
}

func stringifyAny(v any) string {
	switch t := v.(type) {
	case string:
		return t
	default:
		b, _ := json.Marshal(t)
		return string(b)
	}
}

func truncateStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
