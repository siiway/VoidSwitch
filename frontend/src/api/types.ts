// Types mirroring the backend Pydantic schemas.

export type Role = "owner" | "admin" | "member";

export interface User {
  id: number;
  sub: string;
  username?: string | null;
  email?: string | null;
  name?: string | null;
  picture?: string | null;
  role: Role;
  enabled: boolean;
  last_login_at?: string | null;
  created_at: string;
}

export interface Provider {
  id: number;
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
  target_type?: string | null;
  target_id?: string | null;
  detail: Record<string, unknown>;
  ip?: string | null;
}

export interface RequestLog {
  id: number;
  ts: string;
  user_sub?: string | null;
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
