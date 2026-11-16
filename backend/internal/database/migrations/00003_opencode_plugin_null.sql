-- +goose Up
-- Normalise "no OpenCode plugin" request-log rows to NULL.
--
-- The first cut of 00002 wrote an empty string when a request did not come
-- through the plugin, so the dashboard's `?? "—"` fallback never fired and the
-- field rendered blank instead. Absent values are NULL.
UPDATE request_logs SET opencode_plugin = NULL WHERE opencode_plugin = '';

-- +goose Down
-- No-op: the pre-00003 state (empty string vs NULL) carried no meaning.
SELECT 1;
