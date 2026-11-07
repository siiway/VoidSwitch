package database

import (
	"context"
	"database/sql"
	"fmt"
	"sort"
	"strings"
)

// requiredColumns lists a representative subset of columns per table that are
// essential for the Go backend to operate. It is deliberately not exhaustive:
// it is a compatibility gate to refuse booting against an old/incompatible
// schema, not a substitute for goose migrations. Every table the Go code writes
// must appear here with its identity/time/status columns.
var requiredColumns = map[string][]string{
	"users":                  {"id", "sub", "role", "enabled", "session_epoch", "team_ids", "void_tokens_admin_disabled"},
	"void_tokens":            {"id", "user_id", "token_hash", "enabled", "deleted", "allowed_models", "rpm_limit", "daily_quota", "debug_enabled", "auto_disabled"},
	"providers":              {"id", "uuid", "name", "slug", "type", "base_url", "models", "model_map", "model_routes", "passthrough_enabled", "new_api_mode", "selective_ignore_rules", "normalize_developer_role_to_system"},
	"api_keys":               {"id", "provider_id", "key_ciphertext", "key_hash", "pool", "sort_order", "status", "rate_limit_until"},
	"exposed_models":         {"id", "model_id", "opencode_config", "allowed_role_group_ids", "capabilities", "modalities", "brand", "category_id"},
	"routes":                 {"id", "exposed_model_id", "upstream_select_mode", "upstream_rank_algorithm", "max_upstream_attempts", "upstream_all_cooled_behavior"},
	"route_upstreams":        {"id", "route_id", "provider_id", "upstream_model", "group_position", "position", "key_pool", "cooldown_status_codes", "cooldown_seconds"},
	"upstream_cooldowns":     {"id", "provider_id", "upstream_model", "key_pool", "until", "triggered_at"},
	"nodes":                  {"id", "url", "type", "status", "latency_ewma", "token_ciphertext"},
	"node_groups":            {"id", "slug", "name", "is_system", "probe_interval_seconds"},
	"node_group_members":     {"id", "group_id", "node_id", "source_group_id", "pinned"},
	"node_health_samples":    {"id", "node_id", "ts", "success", "source"},
	"role_groups":            {"id", "slug", "name", "builtin", "call_rate_limit_window_seconds", "call_rate_limit_max_requests"},
	"role_group_mappings":    {"id", "role_group_id", "team_id", "min_role", "grants"},
	"role_group_memberships": {"id", "user_id", "role_group_id", "source"},
	"role_group_adminships":  {"id", "user_id", "role_group_id", "source"},
	"announcements":          {"id", "title", "body", "created_by", "target_role_group_ids"},
	"audit_logs":             {"id", "ts", "actor_sub", "action", "scope", "detail", "sensitive_ciphertext"},
	"request_logs":           {"id", "ts", "user_sub", "model", "success", "prompt_tokens", "completion_tokens", "total_tokens", "debug", "attempts_summary"},
	"usage_daily":            {"id", "user_sub", "day", "tokens", "requests"},
	"session_spans":          {"id", "session_key", "user_sub", "started_at", "last_at"},
	"settings":               {"key", "value", "updated_at"},
	"models_dev_cache":       {"id", "data", "updated_at"},
	"model_categories":       {"id", "name", "slug", "position"},
}

// requiredUniqueKeys asserts column sets that MUST be unique. Checked by columns
// (not index name) so the validator is robust to SQLAlchemy vs goose naming.
var requiredUniqueKeys = [][]string{
	{"users", "sub"},
	{"void_tokens", "token_hash"},
	{"providers", "name"},
	{"providers", "slug"},
	{"providers", "uuid"},
	{"exposed_models", "model_id"},
	{"routes", "exposed_model_id"},
	{"role_groups", "slug"},
	{"role_groups", "name"},
	{"session_spans", "session_key"},
	{"api_keys", "provider_id", "key_hash"},
	{"role_group_mappings", "role_group_id", "team_id", "min_role", "grants"},
	{"role_group_memberships", "user_id", "role_group_id"},
	{"role_group_adminships", "user_id", "role_group_id"},
	{"node_group_members", "group_id", "node_id"},
	{"node_group_members", "group_id", "source_group_id"},
}

// ValidateSchema verifies an existing database matches the expected structure.
// Returns a descriptive error listing every missing piece so operators can act.
func ValidateSchema(ctx context.Context, db *sql.DB) error {
	var problems []string

	cols, err := loadColumns(ctx, db)
	if err != nil {
		return fmt.Errorf("load columns: %w", err)
	}
	for table, want := range requiredColumns {
		have, ok := cols[table]
		if !ok {
			problems = append(problems, fmt.Sprintf("missing table %q", table))
			continue
		}
		for _, c := range want {
			if !have[c] {
				problems = append(problems, fmt.Sprintf("table %q missing column %q", table, c))
			}
		}
	}

	uniq, err := loadUniqueColumnSets(ctx, db)
	if err != nil {
		return fmt.Errorf("load unique constraints: %w", err)
	}
	for _, key := range requiredUniqueKeys {
		table := key[0]
		want := canonicalSet(key[1:])
		if !uniq[table][want] {
			problems = append(problems, fmt.Sprintf(
				"table %q missing UNIQUE constraint on (%s)", table, strings.Join(key[1:], ", ")))
		}
	}

	if len(problems) > 0 {
		sort.Strings(problems)
		return fmt.Errorf("schema validation failed:\n  - %s", strings.Join(problems, "\n  - "))
	}
	return nil
}

func canonicalSet(cols []string) string {
	c := append([]string(nil), cols...)
	sort.Strings(c)
	return strings.Join(c, ",")
}

func loadColumns(ctx context.Context, db *sql.DB) (map[string]map[string]bool, error) {
	rows, err := db.QueryContext(ctx,
		`SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public'`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[string]map[string]bool{}
	for rows.Next() {
		var t, c string
		if err := rows.Scan(&t, &c); err != nil {
			return nil, err
		}
		if out[t] == nil {
			out[t] = map[string]bool{}
		}
		out[t][c] = true
	}
	return out, rows.Err()
}

// loadUniqueColumnSets returns, per table, the set of canonical column lists
// that have a UNIQUE index/constraint (in any column order).
func loadUniqueColumnSets(ctx context.Context, db *sql.DB) (map[string]map[string]bool, error) {
	// Fetch index → column membership per row, then group in Go. This avoids
	// array-type scan quirks across drivers.
	rows, err := db.QueryContext(ctx, `
		SELECT t.relname AS table_name,
		       i.indexrelid::regclass::text AS index_name,
		       a.attname AS column_name
		FROM pg_index i
		JOIN pg_class t ON t.oid = i.indrelid
		JOIN pg_namespace n ON n.oid = t.relnamespace
		JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
		WHERE n.nspname = 'public'
		  AND i.indisunique
		  AND i.indisvalid
		  AND t.relkind = 'r'
		ORDER BY t.relname, index_name, a.attname`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	type idxKey struct{ table, index string }
	groups := map[idxKey][]string{}
	for rows.Next() {
		var table, index, col string
		if err := rows.Scan(&table, &index, &col); err != nil {
			return nil, err
		}
		k := idxKey{table, index}
		groups[k] = append(groups[k], col)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	out := map[string]map[string]bool{}
	for k, cols := range groups {
		if out[k.table] == nil {
			out[k.table] = map[string]bool{}
		}
		out[k.table][canonicalSet(cols)] = true
	}
	return out, nil
}
