// Code generated from the Python backend DEFAULT_SETTINGS; do not edit by hand.
// Regenerate with scripts/gen-default-settings.py if the Python defaults change.
package constants

import "encoding/json"

// DefaultSettingsJSON is the canonical map of runtime-tunable settings seeded
// into the settings table on first boot (matches Python DEFAULT_SETTINGS).
var DefaultSettingsJSON = map[string]json.RawMessage{
	"announcements_home_count": json.RawMessage("3"),
	"audit_log_retention_days": json.RawMessage("0"),
	"auto_disable_zero_balance": json.RawMessage("true"),
	"balance_probe_enabled": json.RawMessage("true"),
	"balance_probe_interval_seconds": json.RawMessage("1800"),
	"balance_rescan_enabled": json.RawMessage("true"),
	"balance_rescan_interval_seconds": json.RawMessage("86400"),
	"balance_scan_rate_per_second": json.RawMessage("5"),
	"chat_preset_questions": json.RawMessage("[\"Explain async/await in Python with a short example\", \"Write a regex to validate an email address\", \"Summarize the CAP theorem in three bullets\", \"Refactor this loop into a list comprehension\"]"),
	"connect_timeout_seconds": json.RawMessage("15"),
	"debug_log_retention_days": json.RawMessage("0"),
	"heatmap_retention_days": json.RawMessage("365"),
	"log_cleanup_enabled": json.RawMessage("true"),
	"log_cleanup_interval_seconds": json.RawMessage("86400"),
	"logs_page_size": json.RawMessage("50"),
	"max_connections": json.RawMessage("400"),
	"max_keepalive_connections": json.RawMessage("150"),
	"max_key_failures": json.RawMessage("3"),
	"max_provider_attempts": json.RawMessage("6"),
	"max_proxy_failures": json.RawMessage("3"),
	"model_health_recent_request_count": json.RawMessage("50"),
	"models_dev_sync_interval_minutes": json.RawMessage("1440"),
	"network_max_attempts": json.RawMessage("3"),
	"node_default_probe_url": json.RawMessage("\"https://api.openai.com/v1/models\""),
	"node_health_history_retention_days": json.RawMessage("7"),
	"node_probe_interval_seconds": json.RawMessage("120"),
	"node_rank_alpha": json.RawMessage("1.0"),
	"node_rank_beta": json.RawMessage("100.0"),
	"node_rank_ewma_half_life_seconds": json.RawMessage("300"),
	"node_rank_gamma": json.RawMessage("1000.0"),
	"opencode_default_model": json.RawMessage("\"claude-opus-4-8\""),
	"opencode_small_model": json.RawMessage("\"claude-haiku-4-5-20251001\""),
	"proxy_health_check_enabled": json.RawMessage("true"),
	"proxy_probe_interval_seconds": json.RawMessage("120"),
	"proxy_switching_enabled": json.RawMessage("true"),
	"rate_limit_max_cooldown_seconds": json.RawMessage("3600"),
	"rate_limit_recovery_seconds": json.RawMessage("180"),
	"request_log_retention_days": json.RawMessage("0"),
	"request_timeout_seconds": json.RawMessage("300"),
	"response_timeout_seconds": json.RawMessage("3600"),
	"session_ttl_minutes": json.RawMessage("0"),
	"sse_max_connections_per_user": json.RawMessage("2"),
	"static_proxy_url": json.RawMessage("\"\""),
	"stream_idle_timeout_seconds": json.RawMessage("120"),
	"upstream_all_cooled_behavior": json.RawMessage("\"ignore_cooldown\""),
	"upstream_balance_tolerance": json.RawMessage("0.2"),
	"upstream_cooldown_backoff_cap": json.RawMessage("3"),
	"upstream_cooldown_seconds": json.RawMessage("180"),
	"upstream_cooldown_status_codes": json.RawMessage("[0, 429, 500, 502, 503, 504]"),
	"upstream_ewma_half_life_seconds": json.RawMessage("600"),
	"upstream_max_keys_per_attempt": json.RawMessage("2"),
	"upstream_min_samples": json.RawMessage("10"),
	"upstream_pin_jitter": json.RawMessage("0.15"),
	"upstream_rank_algorithm": json.RawMessage("\"weighted\""),
	"upstream_rank_alpha": json.RawMessage("100.0"),
	"upstream_rank_beta": json.RawMessage("1.0"),
	"upstream_rank_gamma": json.RawMessage("10.0"),
	"upstream_retry_after_headers": json.RawMessage("[\"retry-after\", \"x-ratelimit-reset-after\", \"ratelimit-reset\", \"x-ratelimit-reset-requests\"]"),
	"upstream_select_mode": json.RawMessage("\"best\""),
	"upstream_tier_healthy_threshold": json.RawMessage("0.9"),
}

// DefaultSettings decodes DefaultSettingsJSON into a plain map.
func DefaultSettings() map[string]any {
	out := make(map[string]any, len(DefaultSettingsJSON))
	for k, raw := range DefaultSettingsJSON {
		var v any
		if err := json.Unmarshal(raw, &v); err == nil {
			out[k] = v
		}
	}
	return out
}
