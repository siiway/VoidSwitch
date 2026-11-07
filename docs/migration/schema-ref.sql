--
-- PostgreSQL database dump
--

\restrict T1o5t0K7KIZNZTzbXVCmdqg3DpdeLMrea4kYtxg4eiohLYDqms3rbW742yODy1z

-- Dumped from database version 17.7 (Ubuntu 17.7-0ubuntu0.25.04.1)
-- Dumped by pg_dump version 17.7 (Ubuntu 17.7-0ubuntu0.25.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: announcements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.announcements (
    id integer NOT NULL,
    title character varying(255) NOT NULL,
    body text NOT NULL,
    created_by integer,
    created_by_name character varying(255),
    created_by_role character varying(32) NOT NULL,
    edited boolean NOT NULL,
    target_role_group_ids json NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: announcements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.announcements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: announcements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.announcements_id_seq OWNED BY public.announcements.id;


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id integer NOT NULL,
    provider_id integer NOT NULL,
    key_ciphertext text NOT NULL,
    key_hash character varying(64) NOT NULL,
    key_preview character varying(32) NOT NULL,
    pool character varying(64) NOT NULL,
    sort_order integer NOT NULL,
    status character varying(32) NOT NULL,
    failed_count integer NOT NULL,
    weight integer NOT NULL,
    note character varying(255),
    balance json NOT NULL,
    disabled_reason character varying(255),
    disabled_since timestamp with time zone,
    rate_limit_until timestamp with time zone,
    total_requests bigint NOT NULL,
    last_used_at timestamp with time zone,
    last_checked_at timestamp with time zone,
    added_by integer,
    added_by_name character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    actor_sub character varying(255),
    actor_name character varying(255),
    action character varying(120) NOT NULL,
    scope character varying(16) NOT NULL,
    target_type character varying(64),
    target_id character varying(64),
    detail json NOT NULL,
    ip character varying(64),
    user_agent character varying(512),
    sensitive_ciphertext text
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: exposed_models; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.exposed_models (
    id integer NOT NULL,
    model_id character varying(255) NOT NULL,
    display_name character varying(255),
    description text,
    opencode_config json NOT NULL,
    enabled boolean NOT NULL,
    allowed_role_group_ids json NOT NULL,
    limit_context integer,
    limit_input integer,
    limit_output integer,
    reasoning boolean,
    capabilities json DEFAULT '{}'::json NOT NULL,
    modalities json DEFAULT '{}'::json NOT NULL,
    models_dev_id character varying(255),
    models_dev_synced_at timestamp with time zone,
    brand character varying(64),
    added_by integer,
    added_by_name character varying(255),
    category_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: exposed_models_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.exposed_models_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: exposed_models_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.exposed_models_id_seq OWNED BY public.exposed_models.id;


--
-- Name: model_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_categories (
    id integer NOT NULL,
    name character varying(120) NOT NULL,
    slug character varying(120) NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: model_categories_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.model_categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: model_categories_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.model_categories_id_seq OWNED BY public.model_categories.id;


--
-- Name: models_dev_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.models_dev_cache (
    id character varying(255) NOT NULL,
    data json NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: node_group_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.node_group_members (
    id integer NOT NULL,
    group_id integer NOT NULL,
    node_id integer,
    source_group_id integer,
    pinned boolean DEFAULT false NOT NULL,
    weight integer NOT NULL
);


--
-- Name: node_group_members_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.node_group_members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: node_group_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.node_group_members_id_seq OWNED BY public.node_group_members.id;


--
-- Name: node_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.node_groups (
    id integer NOT NULL,
    slug character varying(64),
    name character varying(120) NOT NULL,
    description text,
    probe_url character varying(512),
    probe_interval_seconds integer NOT NULL,
    is_system boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: node_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.node_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: node_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.node_groups_id_seq OWNED BY public.node_groups.id;


--
-- Name: node_health_samples; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.node_health_samples (
    id integer NOT NULL,
    node_id integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    source character varying(16) NOT NULL,
    success boolean NOT NULL,
    latency_ms double precision,
    status_code integer,
    error character varying(255)
);


--
-- Name: node_health_samples_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.node_health_samples_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: node_health_samples_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.node_health_samples_id_seq OWNED BY public.node_health_samples.id;


--
-- Name: nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nodes (
    id integer NOT NULL,
    url character varying(512) NOT NULL,
    type character varying(16) NOT NULL,
    token_ciphertext text,
    local_address character varying(64),
    enabled boolean NOT NULL,
    status character varying(32) NOT NULL,
    failed_count integer NOT NULL,
    weight integer NOT NULL,
    latency_ms double precision,
    latency_ewma double precision,
    note character varying(255),
    disabled_reason character varying(255),
    last_used_at timestamp with time zone,
    last_checked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: nodes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.nodes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nodes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.nodes_id_seq OWNED BY public.nodes.id;


--
-- Name: providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.providers (
    id integer NOT NULL,
    uuid character varying(36) NOT NULL,
    name character varying(120) NOT NULL,
    slug character varying(120) NOT NULL,
    node_group_id integer,
    type character varying(64) NOT NULL,
    base_url character varying(512) NOT NULL,
    enabled boolean NOT NULL,
    priority integer NOT NULL,
    weight integer NOT NULL,
    models json NOT NULL,
    model_map json NOT NULL,
    model_routes json NOT NULL,
    balance_url character varying(512),
    extra_headers json NOT NULL,
    timeout_seconds integer NOT NULL,
    retry_on_zero_token boolean NOT NULL,
    drop_opencode_identity_block boolean NOT NULL,
    normalize_developer_role_to_system boolean DEFAULT true NOT NULL,
    key_select_mode character varying(32) NOT NULL,
    rate_limit_cooldown_seconds integer NOT NULL,
    added_by integer,
    added_by_name character varying(255),
    key_api_enabled boolean NOT NULL,
    key_api_token_hash character varying(64),
    key_api_token_ciphertext text,
    key_api_token_preview character varying(48),
    passthrough_enabled boolean NOT NULL,
    passthrough_models json NOT NULL,
    upstream_cooldown_seconds integer DEFAULT 0 NOT NULL,
    upstream_cooldown_status_codes json DEFAULT '[]'::json NOT NULL,
    upstream_retry_after_headers json DEFAULT '[]'::json NOT NULL,
    upstream_max_keys_per_attempt integer DEFAULT 0 NOT NULL,
    new_api_mode character varying(16) DEFAULT 'auto'::character varying NOT NULL,
    protected_error_retry_enabled boolean DEFAULT false NOT NULL,
    selective_ignore_rules json DEFAULT '[]'::json NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: providers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.providers_id_seq OWNED BY public.providers.id;


--
-- Name: request_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.request_logs (
    id integer NOT NULL,
    ts timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    first_token_ms double precision,
    req_status character varying(32),
    client_ip character varying(64),
    token_id integer,
    user_sub character varying(255),
    session_id character varying(255),
    provider_id integer,
    provider_name character varying(120),
    key_id integer,
    proxy_id integer,
    model character varying(120),
    upstream_model character varying(120),
    inbound_style character varying(32),
    upstream_style character varying(32),
    status_code integer,
    success boolean NOT NULL,
    latency_ms double precision,
    prompt_tokens bigint NOT NULL,
    completion_tokens bigint NOT NULL,
    total_tokens bigint NOT NULL,
    stream boolean NOT NULL,
    attempts integer NOT NULL,
    provider_attempts integer DEFAULT 1 NOT NULL,
    network_attempts integer DEFAULT 1 NOT NULL,
    error text,
    user_agent character varying(512),
    client_type character varying(64),
    is_opencode boolean NOT NULL,
    debug boolean NOT NULL,
    req_method character varying(16),
    req_headers json,
    req_body json,
    resp_headers json,
    resp_body json,
    debug_attempts json,
    attempts_summary json,
    upstream_url character varying(1024),
    proxy_url character varying(512)
);


--
-- Name: request_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.request_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: request_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.request_logs_id_seq OWNED BY public.request_logs.id;


--
-- Name: role_group_adminships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_group_adminships (
    id integer NOT NULL,
    user_id integer NOT NULL,
    role_group_id integer NOT NULL,
    source character varying(16) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: role_group_adminships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.role_group_adminships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_group_adminships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.role_group_adminships_id_seq OWNED BY public.role_group_adminships.id;


--
-- Name: role_group_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_group_mappings (
    id integer NOT NULL,
    role_group_id integer NOT NULL,
    team_id character varying(120) NOT NULL,
    min_role character varying(32) NOT NULL,
    grants character varying(16) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: role_group_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.role_group_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_group_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.role_group_mappings_id_seq OWNED BY public.role_group_mappings.id;


--
-- Name: role_group_memberships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_group_memberships (
    id integer NOT NULL,
    user_id integer NOT NULL,
    role_group_id integer NOT NULL,
    source character varying(16) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: role_group_memberships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.role_group_memberships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_group_memberships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.role_group_memberships_id_seq OWNED BY public.role_group_memberships.id;


--
-- Name: role_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role_groups (
    id integer NOT NULL,
    slug character varying(64),
    name character varying(120) NOT NULL,
    description text,
    builtin boolean NOT NULL,
    call_rate_limit_window_seconds integer DEFAULT 30 NOT NULL,
    call_rate_limit_max_requests integer DEFAULT 30 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: role_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.role_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.role_groups_id_seq OWNED BY public.role_groups.id;


--
-- Name: route_upstreams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.route_upstreams (
    id integer NOT NULL,
    route_id integer NOT NULL,
    provider_id integer,
    upstream_model character varying(255) NOT NULL,
    group_position integer DEFAULT 0 NOT NULL,
    "position" integer NOT NULL,
    weight integer NOT NULL,
    enabled boolean NOT NULL,
    key_pool character varying(64) NOT NULL,
    cooldown_status_codes json DEFAULT '[]'::json NOT NULL,
    cooldown_seconds integer DEFAULT 0 NOT NULL
);


--
-- Name: route_upstreams_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.route_upstreams_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: route_upstreams_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.route_upstreams_id_seq OWNED BY public.route_upstreams.id;


--
-- Name: routes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.routes (
    id integer NOT NULL,
    exposed_model_id integer NOT NULL,
    upstream_select_mode character varying(32) DEFAULT ''::character varying NOT NULL,
    upstream_rank_algorithm character varying(32) DEFAULT ''::character varying NOT NULL,
    max_upstream_attempts integer DEFAULT 0 NOT NULL,
    upstream_all_cooled_behavior character varying(32) DEFAULT ''::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: routes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.routes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: routes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.routes_id_seq OWNED BY public.routes.id;


--
-- Name: session_spans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_spans (
    id integer NOT NULL,
    session_key character varying(255) NOT NULL,
    user_sub character varying(255) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    last_at timestamp with time zone NOT NULL,
    requests bigint NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: session_spans_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.session_spans_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_spans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.session_spans_id_seq OWNED BY public.session_spans.id;


--
-- Name: settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.settings (
    key character varying(120) NOT NULL,
    value json NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: upstream_cooldowns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.upstream_cooldowns (
    id integer NOT NULL,
    provider_id integer NOT NULL,
    upstream_model character varying(255) NOT NULL,
    key_pool character varying(64) NOT NULL,
    until timestamp with time zone NOT NULL,
    reason character varying(255),
    trigger_status integer NOT NULL,
    trigger_source character varying(32) NOT NULL,
    triggered_at timestamp with time zone NOT NULL,
    consecutive_trips integer NOT NULL,
    last_success_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: upstream_cooldowns_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.upstream_cooldowns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: upstream_cooldowns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.upstream_cooldowns_id_seq OWNED BY public.upstream_cooldowns.id;


--
-- Name: usage_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_daily (
    id integer NOT NULL,
    user_sub character varying(255) NOT NULL,
    day character varying(10) NOT NULL,
    tokens bigint NOT NULL,
    requests bigint NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: usage_daily_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.usage_daily_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: usage_daily_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.usage_daily_id_seq OWNED BY public.usage_daily.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    sub character varying(255) NOT NULL,
    username character varying(255),
    email character varying(320),
    name character varying(255),
    picture text,
    role character varying(32) NOT NULL,
    prism_role character varying(32),
    team_ids json NOT NULL,
    enabled boolean NOT NULL,
    last_login_at timestamp with time zone,
    session_epoch integer NOT NULL,
    login_token_hash character varying(64),
    login_token_prefix character varying(32),
    void_tokens_admin_disabled boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: void_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.void_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(120) NOT NULL,
    token_hash character varying(64) NOT NULL,
    token_prefix character varying(32) NOT NULL,
    enabled boolean NOT NULL,
    auto_disabled boolean NOT NULL,
    deleted boolean NOT NULL,
    deleted_at timestamp with time zone,
    allowed_models json NOT NULL,
    rpm_limit integer NOT NULL,
    daily_quota integer NOT NULL,
    total_requests bigint NOT NULL,
    total_tokens bigint NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    debug_enabled boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: void_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.void_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: void_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.void_tokens_id_seq OWNED BY public.void_tokens.id;


--
-- Name: announcements id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.announcements ALTER COLUMN id SET DEFAULT nextval('public.announcements_id_seq'::regclass);


--
-- Name: api_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: exposed_models id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exposed_models ALTER COLUMN id SET DEFAULT nextval('public.exposed_models_id_seq'::regclass);


--
-- Name: model_categories id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_categories ALTER COLUMN id SET DEFAULT nextval('public.model_categories_id_seq'::regclass);


--
-- Name: node_group_members id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_group_members ALTER COLUMN id SET DEFAULT nextval('public.node_group_members_id_seq'::regclass);


--
-- Name: node_groups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_groups ALTER COLUMN id SET DEFAULT nextval('public.node_groups_id_seq'::regclass);


--
-- Name: node_health_samples id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_health_samples ALTER COLUMN id SET DEFAULT nextval('public.node_health_samples_id_seq'::regclass);


--
-- Name: nodes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes ALTER COLUMN id SET DEFAULT nextval('public.nodes_id_seq'::regclass);


--
-- Name: providers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers ALTER COLUMN id SET DEFAULT nextval('public.providers_id_seq'::regclass);


--
-- Name: request_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.request_logs ALTER COLUMN id SET DEFAULT nextval('public.request_logs_id_seq'::regclass);


--
-- Name: role_group_adminships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_adminships ALTER COLUMN id SET DEFAULT nextval('public.role_group_adminships_id_seq'::regclass);


--
-- Name: role_group_mappings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_mappings ALTER COLUMN id SET DEFAULT nextval('public.role_group_mappings_id_seq'::regclass);


--
-- Name: role_group_memberships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_memberships ALTER COLUMN id SET DEFAULT nextval('public.role_group_memberships_id_seq'::regclass);


--
-- Name: role_groups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_groups ALTER COLUMN id SET DEFAULT nextval('public.role_groups_id_seq'::regclass);


--
-- Name: route_upstreams id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_upstreams ALTER COLUMN id SET DEFAULT nextval('public.route_upstreams_id_seq'::regclass);


--
-- Name: routes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routes ALTER COLUMN id SET DEFAULT nextval('public.routes_id_seq'::regclass);


--
-- Name: session_spans id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_spans ALTER COLUMN id SET DEFAULT nextval('public.session_spans_id_seq'::regclass);


--
-- Name: upstream_cooldowns id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upstream_cooldowns ALTER COLUMN id SET DEFAULT nextval('public.upstream_cooldowns_id_seq'::regclass);


--
-- Name: usage_daily id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_daily ALTER COLUMN id SET DEFAULT nextval('public.usage_daily_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: void_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.void_tokens ALTER COLUMN id SET DEFAULT nextval('public.void_tokens_id_seq'::regclass);


--
-- Name: announcements announcements_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.announcements
    ADD CONSTRAINT announcements_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: exposed_models exposed_models_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exposed_models
    ADD CONSTRAINT exposed_models_pkey PRIMARY KEY (id);


--
-- Name: model_categories model_categories_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_categories
    ADD CONSTRAINT model_categories_name_key UNIQUE (name);


--
-- Name: model_categories model_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_categories
    ADD CONSTRAINT model_categories_pkey PRIMARY KEY (id);


--
-- Name: models_dev_cache models_dev_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.models_dev_cache
    ADD CONSTRAINT models_dev_cache_pkey PRIMARY KEY (id);


--
-- Name: node_group_members node_group_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_group_members
    ADD CONSTRAINT node_group_members_pkey PRIMARY KEY (id);


--
-- Name: node_groups node_groups_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_groups
    ADD CONSTRAINT node_groups_name_key UNIQUE (name);


--
-- Name: node_groups node_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_groups
    ADD CONSTRAINT node_groups_pkey PRIMARY KEY (id);


--
-- Name: node_groups node_groups_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_groups
    ADD CONSTRAINT node_groups_slug_key UNIQUE (slug);


--
-- Name: node_health_samples node_health_samples_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_health_samples
    ADD CONSTRAINT node_health_samples_pkey PRIMARY KEY (id);


--
-- Name: nodes nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_pkey PRIMARY KEY (id);


--
-- Name: nodes nodes_url_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_url_key UNIQUE (url);


--
-- Name: providers providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_pkey PRIMARY KEY (id);


--
-- Name: request_logs request_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.request_logs
    ADD CONSTRAINT request_logs_pkey PRIMARY KEY (id);


--
-- Name: role_group_adminships role_group_adminships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_adminships
    ADD CONSTRAINT role_group_adminships_pkey PRIMARY KEY (id);


--
-- Name: role_group_mappings role_group_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_mappings
    ADD CONSTRAINT role_group_mappings_pkey PRIMARY KEY (id);


--
-- Name: role_group_memberships role_group_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_memberships
    ADD CONSTRAINT role_group_memberships_pkey PRIMARY KEY (id);


--
-- Name: role_groups role_groups_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_groups
    ADD CONSTRAINT role_groups_name_key UNIQUE (name);


--
-- Name: role_groups role_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_groups
    ADD CONSTRAINT role_groups_pkey PRIMARY KEY (id);


--
-- Name: role_groups role_groups_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_groups
    ADD CONSTRAINT role_groups_slug_key UNIQUE (slug);


--
-- Name: route_upstreams route_upstreams_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_upstreams
    ADD CONSTRAINT route_upstreams_pkey PRIMARY KEY (id);


--
-- Name: routes routes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routes
    ADD CONSTRAINT routes_pkey PRIMARY KEY (id);


--
-- Name: session_spans session_spans_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_spans
    ADD CONSTRAINT session_spans_pkey PRIMARY KEY (id);


--
-- Name: settings settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_pkey PRIMARY KEY (key);


--
-- Name: upstream_cooldowns upstream_cooldowns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upstream_cooldowns
    ADD CONSTRAINT upstream_cooldowns_pkey PRIMARY KEY (id);


--
-- Name: node_group_members uq_group_node; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_group_members
    ADD CONSTRAINT uq_group_node UNIQUE (group_id, node_id);


--
-- Name: node_group_members uq_group_source_group; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_group_members
    ADD CONSTRAINT uq_group_source_group UNIQUE (group_id, source_group_id);


--
-- Name: role_group_mappings uq_group_team_role_grants; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_mappings
    ADD CONSTRAINT uq_group_team_role_grants UNIQUE (role_group_id, team_id, min_role, grants);


--
-- Name: api_keys uq_provider_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT uq_provider_key UNIQUE (provider_id, key_hash);


--
-- Name: route_upstreams uq_route_upstream; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_upstreams
    ADD CONSTRAINT uq_route_upstream UNIQUE (route_id, group_position, provider_id, upstream_model, key_pool);


--
-- Name: upstream_cooldowns uq_upstream_cooldown; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upstream_cooldowns
    ADD CONSTRAINT uq_upstream_cooldown UNIQUE (provider_id, upstream_model, key_pool);


--
-- Name: usage_daily uq_usage_daily_user_day; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_daily
    ADD CONSTRAINT uq_usage_daily_user_day UNIQUE (user_sub, day);


--
-- Name: role_group_memberships uq_user_group; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_memberships
    ADD CONSTRAINT uq_user_group UNIQUE (user_id, role_group_id);


--
-- Name: role_group_adminships uq_user_group_admin; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_adminships
    ADD CONSTRAINT uq_user_group_admin UNIQUE (user_id, role_group_id);


--
-- Name: usage_daily usage_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_daily
    ADD CONSTRAINT usage_daily_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: void_tokens void_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.void_tokens
    ADD CONSTRAINT void_tokens_pkey PRIMARY KEY (id);


--
-- Name: ix_announcements_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_announcements_created_by ON public.announcements USING btree (created_by);


--
-- Name: ix_api_keys_added_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_added_by ON public.api_keys USING btree (added_by);


--
-- Name: ix_api_keys_key_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_key_hash ON public.api_keys USING btree (key_hash);


--
-- Name: ix_api_keys_pool; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_pool ON public.api_keys USING btree (pool);


--
-- Name: ix_api_keys_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_provider_id ON public.api_keys USING btree (provider_id);


--
-- Name: ix_api_keys_sort_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_sort_order ON public.api_keys USING btree (sort_order);


--
-- Name: ix_api_keys_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_status ON public.api_keys USING btree (status);


--
-- Name: ix_audit_logs_action_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_action_id ON public.audit_logs USING btree (action, id);


--
-- Name: ix_audit_logs_actor_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_actor_sub ON public.audit_logs USING btree (actor_sub);


--
-- Name: ix_audit_logs_actor_sub_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_actor_sub_id ON public.audit_logs USING btree (actor_sub, id);


--
-- Name: ix_audit_logs_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_scope ON public.audit_logs USING btree (scope);


--
-- Name: ix_audit_logs_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_scope_id ON public.audit_logs USING btree (scope, id);


--
-- Name: ix_audit_logs_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_ts ON public.audit_logs USING btree (ts);


--
-- Name: ix_exposed_models_added_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exposed_models_added_by ON public.exposed_models USING btree (added_by);


--
-- Name: ix_exposed_models_category_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exposed_models_category_id ON public.exposed_models USING btree (category_id);


--
-- Name: ix_exposed_models_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_exposed_models_model_id ON public.exposed_models USING btree (model_id);


--
-- Name: ix_exposed_models_models_dev_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_exposed_models_models_dev_id ON public.exposed_models USING btree (models_dev_id);


--
-- Name: ix_model_categories_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_model_categories_slug ON public.model_categories USING btree (slug);


--
-- Name: ix_node_group_members_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_node_group_members_group_id ON public.node_group_members USING btree (group_id);


--
-- Name: ix_node_group_members_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_node_group_members_node_id ON public.node_group_members USING btree (node_id);


--
-- Name: ix_node_group_members_source_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_node_group_members_source_group_id ON public.node_group_members USING btree (source_group_id);


--
-- Name: ix_node_health_samples_node_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_node_health_samples_node_id ON public.node_health_samples USING btree (node_id);


--
-- Name: ix_node_health_samples_node_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_node_health_samples_node_ts ON public.node_health_samples USING btree (node_id, ts);


--
-- Name: ix_node_health_samples_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_node_health_samples_ts ON public.node_health_samples USING btree (ts);


--
-- Name: ix_nodes_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_nodes_status ON public.nodes USING btree (status);


--
-- Name: ix_providers_added_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_providers_added_by ON public.providers USING btree (added_by);


--
-- Name: ix_providers_key_api_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_providers_key_api_token_hash ON public.providers USING btree (key_api_token_hash);


--
-- Name: ix_providers_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_providers_name ON public.providers USING btree (name);


--
-- Name: ix_providers_node_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_providers_node_group_id ON public.providers USING btree (node_group_id);


--
-- Name: ix_providers_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_providers_slug ON public.providers USING btree (slug);


--
-- Name: ix_providers_uuid; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_providers_uuid ON public.providers USING btree (uuid);


--
-- Name: ix_request_logs_debug; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_debug ON public.request_logs USING btree (debug);


--
-- Name: ix_request_logs_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_model ON public.request_logs USING btree (model);


--
-- Name: ix_request_logs_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_model_id ON public.request_logs USING btree (model, id);


--
-- Name: ix_request_logs_provider_name_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_provider_name_id ON public.request_logs USING btree (provider_name, id);


--
-- Name: ix_request_logs_req_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_req_status ON public.request_logs USING btree (req_status);


--
-- Name: ix_request_logs_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_session_id ON public.request_logs USING btree (session_id);


--
-- Name: ix_request_logs_success; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_success ON public.request_logs USING btree (success);


--
-- Name: ix_request_logs_success_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_success_id ON public.request_logs USING btree (success, id);


--
-- Name: ix_request_logs_token_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_token_id ON public.request_logs USING btree (token_id);


--
-- Name: ix_request_logs_token_id_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_token_id_id ON public.request_logs USING btree (token_id, id);


--
-- Name: ix_request_logs_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_ts ON public.request_logs USING btree (ts);


--
-- Name: ix_request_logs_user_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_user_sub ON public.request_logs USING btree (user_sub);


--
-- Name: ix_request_logs_user_sub_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_request_logs_user_sub_id ON public.request_logs USING btree (user_sub, id);


--
-- Name: ix_role_group_adminships_role_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_group_adminships_role_group_id ON public.role_group_adminships USING btree (role_group_id);


--
-- Name: ix_role_group_adminships_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_group_adminships_user_id ON public.role_group_adminships USING btree (user_id);


--
-- Name: ix_role_group_mappings_role_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_group_mappings_role_group_id ON public.role_group_mappings USING btree (role_group_id);


--
-- Name: ix_role_group_mappings_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_group_mappings_team_id ON public.role_group_mappings USING btree (team_id);


--
-- Name: ix_role_group_memberships_role_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_group_memberships_role_group_id ON public.role_group_memberships USING btree (role_group_id);


--
-- Name: ix_role_group_memberships_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_role_group_memberships_user_id ON public.role_group_memberships USING btree (user_id);


--
-- Name: ix_route_upstreams_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_route_upstreams_provider_id ON public.route_upstreams USING btree (provider_id);


--
-- Name: ix_route_upstreams_route_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_route_upstreams_route_id ON public.route_upstreams USING btree (route_id);


--
-- Name: ix_routes_exposed_model_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_routes_exposed_model_id ON public.routes USING btree (exposed_model_id);


--
-- Name: ix_session_spans_last_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_spans_last_at ON public.session_spans USING btree (last_at);


--
-- Name: ix_session_spans_session_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_session_spans_session_key ON public.session_spans USING btree (session_key);


--
-- Name: ix_session_spans_user_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_session_spans_user_sub ON public.session_spans USING btree (user_sub);


--
-- Name: ix_upstream_cooldowns_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_upstream_cooldowns_provider_id ON public.upstream_cooldowns USING btree (provider_id);


--
-- Name: ix_upstream_cooldowns_until; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_upstream_cooldowns_until ON public.upstream_cooldowns USING btree (until);


--
-- Name: ix_usage_daily_day; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_daily_day ON public.usage_daily USING btree (day);


--
-- Name: ix_usage_daily_user_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_daily_user_sub ON public.usage_daily USING btree (user_sub);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_login_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_login_token_hash ON public.users USING btree (login_token_hash);


--
-- Name: ix_users_sub; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_sub ON public.users USING btree (sub);


--
-- Name: ix_void_tokens_deleted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_void_tokens_deleted ON public.void_tokens USING btree (deleted);


--
-- Name: ix_void_tokens_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_void_tokens_token_hash ON public.void_tokens USING btree (token_hash);


--
-- Name: ix_void_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_void_tokens_user_id ON public.void_tokens USING btree (user_id);


--
-- Name: api_keys api_keys_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.providers(id) ON DELETE CASCADE;


--
-- Name: exposed_models exposed_models_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.exposed_models
    ADD CONSTRAINT exposed_models_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.model_categories(id) ON DELETE SET NULL;


--
-- Name: providers fk_providers_node_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT fk_providers_node_group_id FOREIGN KEY (node_group_id) REFERENCES public.node_groups(id) ON DELETE SET NULL;


--
-- Name: node_group_members node_group_members_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_group_members
    ADD CONSTRAINT node_group_members_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.node_groups(id) ON DELETE CASCADE;


--
-- Name: node_group_members node_group_members_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_group_members
    ADD CONSTRAINT node_group_members_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(id) ON DELETE CASCADE;


--
-- Name: node_group_members node_group_members_source_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_group_members
    ADD CONSTRAINT node_group_members_source_group_id_fkey FOREIGN KEY (source_group_id) REFERENCES public.node_groups(id) ON DELETE CASCADE;


--
-- Name: node_health_samples node_health_samples_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.node_health_samples
    ADD CONSTRAINT node_health_samples_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(id) ON DELETE CASCADE;


--
-- Name: providers providers_node_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_node_group_id_fkey FOREIGN KEY (node_group_id) REFERENCES public.node_groups(id) ON DELETE SET NULL;


--
-- Name: role_group_adminships role_group_adminships_role_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_adminships
    ADD CONSTRAINT role_group_adminships_role_group_id_fkey FOREIGN KEY (role_group_id) REFERENCES public.role_groups(id) ON DELETE CASCADE;


--
-- Name: role_group_adminships role_group_adminships_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_adminships
    ADD CONSTRAINT role_group_adminships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: role_group_mappings role_group_mappings_role_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_mappings
    ADD CONSTRAINT role_group_mappings_role_group_id_fkey FOREIGN KEY (role_group_id) REFERENCES public.role_groups(id) ON DELETE CASCADE;


--
-- Name: role_group_memberships role_group_memberships_role_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_memberships
    ADD CONSTRAINT role_group_memberships_role_group_id_fkey FOREIGN KEY (role_group_id) REFERENCES public.role_groups(id) ON DELETE CASCADE;


--
-- Name: role_group_memberships role_group_memberships_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role_group_memberships
    ADD CONSTRAINT role_group_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: route_upstreams route_upstreams_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_upstreams
    ADD CONSTRAINT route_upstreams_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.providers(id) ON DELETE SET NULL;


--
-- Name: route_upstreams route_upstreams_route_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_upstreams
    ADD CONSTRAINT route_upstreams_route_id_fkey FOREIGN KEY (route_id) REFERENCES public.routes(id) ON DELETE CASCADE;


--
-- Name: routes routes_exposed_model_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.routes
    ADD CONSTRAINT routes_exposed_model_id_fkey FOREIGN KEY (exposed_model_id) REFERENCES public.exposed_models(id) ON DELETE CASCADE;


--
-- Name: upstream_cooldowns upstream_cooldowns_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upstream_cooldowns
    ADD CONSTRAINT upstream_cooldowns_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.providers(id) ON DELETE CASCADE;


--
-- Name: void_tokens void_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.void_tokens
    ADD CONSTRAINT void_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict T1o5t0K7KIZNZTzbXVCmdqg3DpdeLMrea4kYtxg4eiohLYDqms3rbW742yODy1z

