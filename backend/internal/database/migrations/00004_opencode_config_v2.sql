-- +goose Up
-- Per-version OpenCode model config. `opencode_config` keeps the V1 shape; this
-- column carries the V2 (OpenCode 2.x) overrides, so a V2-shaped block can
-- never be rejected for holding V1-only fields.
ALTER TABLE exposed_models
    ADD COLUMN opencode_config_v2 json DEFAULT '{}'::json NOT NULL;

-- +goose Down
ALTER TABLE exposed_models
    DROP COLUMN opencode_config_v2;
