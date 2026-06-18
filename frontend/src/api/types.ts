// Types mirroring the backend Pydantic schemas.

export type Role = "owner" | "co-owner" | "admin" | "member";

export interface User {
  id: number;
  sub: string;
  username?: string | null;
  email?: string | null;
  name?: string | null;
  picture?: string | null;
  role: Role;
  prism_role?: string | null;
  enabled: boolean;
  last_login_at?: string | null;
  created_at: string;
}

export interface Provider {
  id: number;
  uuid?: string | null;
  name: string;
  type: string;
  base_url: string;
  enabled: boolean;
  priority: number;
  weight: number;
  models: string[];
  model_map: Record<string, string>;
  balance_url?: string | null;
  extra_headers: Record<string, string>;
  timeout_seconds: number;
  drop_opencode_identity_block: boolean;
  proxy_mode: ProxyMode;
  proxy_ids: number[];
  model_routes: ModelRoute[];
  created_at: string;
  updated_at: string;
  key_count: number;
  active_key_count: number;
  supports_balance: boolean;
  added_by?: number | null;
  added_by_name?: string | null;
  key_api_enabled: boolean;
  key_api_token_preview?: string | null;
}

// Per-provider key-management API credential (owner-only).
export interface ProviderKeyApi {
  provider_id: number;
  provider_uuid?: string | null;
  enabled: boolean;
  token_preview?: string | null;
  // Present only on enable / rotate / reveal.
  token?: string;
}

export type ProxyMode = "all" | "direct" | "selected";

export interface ModelRoute {
  alias: string;
  upstream: string;
  pool: string;
}

export interface ApiKey {
  id: number;
  provider_id: number;
  key_preview: string;
  pool: string;
  status: string;
  failed_count: number;
  weight: number;
  note?: string | null;
  balance: Record<string, unknown>;
  disabled_reason?: string | null;
  total_requests: number;
  last_used_at?: string | null;
  last_checked_at?: string | null;
  created_at: string;
  disabled_since?: string | null;
  added_by?: number | null;
  added_by_name?: string | null;
}

export interface Proxy {
  id: number;
  url: string;
  local_address?: string | null;
  enabled: boolean;
  status: string;
  failed_count: number;
  weight: number;
  latency_ms?: number | null;
  note?: string | null;
  disabled_reason?: string | null;
  last_used_at?: string | null;
  last_checked_at?: string | null;
  created_at: string;
}

export interface VoidToken {
  id: number;
  user_id: number;
  username?: string | null;
  name: string;
  token_prefix: string;
  enabled: boolean;
  allowed_models: string[];
  rpm_limit: number;
  daily_quota: number;
  total_requests: number;
  total_tokens: number;
  last_used_at?: string | null;
  expires_at?: string | null;
  created_at: string;
}

export interface VoidTokenWithSecret extends VoidToken {
  token: string;
}

export interface ModelEntry {
  id: number | null;
  model_id: string;
  mapped_id?: string | null;
  public_id: string;
  display_name?: string | null;
  description?: string | null;
  opencode_config: Record<string, unknown>;
  enabled: boolean;
  providers: string[];
  served: boolean;
  registered: boolean;
  added_by_name?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ModelSyncResult {
  added: number;
  total: number;
}

export interface Stats {
  providers: number;
  active_keys: number;
  total_keys: number;
  active_proxies: number;
  total_proxies: number;
  tokens: number;
  requests_24h: number;
  success_24h: number;
  failures_24h: number;
  tokens_24h: number;
}

export interface AuditLog {
  id: number;
  ts: string;
  actor_sub?: string | null;
  actor_name?: string | null;
  action: string;
  // "admin" (management surface) or "self" (a user's own account/tokens).
  scope: string;
  target_type?: string | null;
  target_id?: string | null;
  detail: Record<string, unknown>;
  ip?: string | null;
  has_sensitive?: boolean;
}

export interface RequestLog {
  id: number;
  ts: string;
  user_sub?: string | null;
  user_name?: string | null;
  token_id?: number | null;
  token_name?: string | null;
  provider_name?: string | null;
  model?: string | null;
  inbound_style?: string | null;
  upstream_style?: string | null;
  status_code?: number | null;
  success: boolean;
  latency_ms?: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  stream: boolean;
  attempts: number;
  error?: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface UsageTotals {
  requests: number;
  success: number;
  failures: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface UsageBucket extends UsageTotals {
  period: string;
}

export interface UsageGroupRow extends UsageTotals {
  key: string;
  label: string;
  sublabel?: string | null;
}

export interface UsageAnalytics {
  // "all" (staff, platform-wide) or "self" (member, own traffic only).
  scope: "all" | "self";
  totals: UsageTotals;
  daily: UsageBucket[];
  weekly: UsageBucket[];
  monthly: UsageBucket[];
  yearly: UsageBucket[];
  by_user: UsageGroupRow[];
  by_token: UsageGroupRow[];
  by_model: UsageGroupRow[];
}

export interface AdapterMeta {
  type: string;
  style: string;
  default_base_url: string;
  default_models: string[];
  supports_balance: boolean;
}

export interface SystemInfo {
  version: string;
  adapters: AdapterMeta[];
  tasks: TaskStatus[];
}

export interface TaskStatus {
  name: string;
  interval_seconds: number;
  enabled: boolean;
  runs: number;
  last_run?: string | null;
  last_error?: string | null;
}
