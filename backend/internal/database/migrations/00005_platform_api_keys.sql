-- +goose Up
-- Platform API Keys (vsapi-…) let a staff member's automation reach the
-- platform API (/api/v1) and the MCP endpoint (/api/v1/mcp) on their behalf.
-- They replace the per-provider key-management token (vsk-), so that one
-- credential covers every provider surface through a provider-key:<slug> scope
-- instead of one token minted per provider.
CREATE TABLE public.platform_api_keys (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(120) NOT NULL,
    key_hash character varying(64) NOT NULL,
    key_prefix character varying(32) NOT NULL,
    scopes json DEFAULT '[]'::json NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    disabled_reason character varying(64),
    expires_at timestamp with time zone,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE SEQUENCE public.platform_api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.platform_api_keys_id_seq OWNED BY public.platform_api_keys.id;

ALTER TABLE ONLY public.platform_api_keys ALTER COLUMN id SET DEFAULT nextval('public.platform_api_keys_id_seq'::regclass);

ALTER TABLE ONLY public.platform_api_keys
    ADD CONSTRAINT platform_api_keys_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.platform_api_keys
    ADD CONSTRAINT platform_api_keys_key_hash_key UNIQUE (key_hash);

CREATE INDEX ix_platform_api_keys_user_id ON public.platform_api_keys (user_id);

ALTER TABLE ONLY public.platform_api_keys
    ADD CONSTRAINT platform_api_keys_user_id_fkey FOREIGN KEY (user_id)
    REFERENCES public.users(id) ON DELETE CASCADE;

-- Audit rows now name the credential that performed an action, so "who" and
-- "which key" are both answerable from one row.
ALTER TABLE public.audit_logs ADD COLUMN credential character varying(64);

-- Retire the per-provider key-management credential. The capability moves to
-- platform API keys with a provider-key:<slug> scope.
ALTER TABLE public.providers DROP COLUMN key_api_enabled;
ALTER TABLE public.providers DROP COLUMN key_api_token_hash;
ALTER TABLE public.providers DROP COLUMN key_api_token_ciphertext;
ALTER TABLE public.providers DROP COLUMN key_api_token_preview;

-- +goose Down
ALTER TABLE public.providers ADD COLUMN key_api_enabled boolean DEFAULT false NOT NULL;
ALTER TABLE public.providers ADD COLUMN key_api_token_hash character varying(64);
ALTER TABLE public.providers ADD COLUMN key_api_token_ciphertext text;
ALTER TABLE public.providers ADD COLUMN key_api_token_preview character varying(48);

-- The baseline carried a unique index on the token hash; dropping the column
-- dropped it too, so rolling back has to recreate it.
CREATE UNIQUE INDEX ix_providers_key_api_token_hash ON public.providers (key_api_token_hash);

ALTER TABLE public.audit_logs DROP COLUMN credential;

-- Dropping the table also drops the sequence it owns.
DROP TABLE public.platform_api_keys;
