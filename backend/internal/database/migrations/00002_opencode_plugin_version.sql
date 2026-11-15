-- +goose Up
-- Record which VoidSwitch OpenCode plugin generation served a request.
--
-- The boolean is_opencode only said "the plugin was involved". With two plugin
-- generations (V1 on @opencode-ai/plugin, V2 on @opencode/plugin) the dashboard
-- needs to say which one, so the log carries the version instead: 'v1', 'v2',
-- or NULL when the request did not come through the plugin at all.
--
-- Existing rows are backfilled from is_opencode: any request that was flagged as
-- plugin traffic predates the V2 plugin, so it is V1.
ALTER TABLE request_logs ADD COLUMN opencode_plugin character varying(8);

UPDATE request_logs SET opencode_plugin = 'v1' WHERE is_opencode;

-- +goose Down
ALTER TABLE request_logs DROP COLUMN opencode_plugin;
