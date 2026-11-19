-- +goose Up
-- scopes_granted_at was written on create/rotate but never read: scopes are
-- narrowed per request from the owner's current role, so a grant timestamp adds
-- nothing. platform_key.update already records scope changes in the audit log.
ALTER TABLE public.platform_api_keys DROP COLUMN scopes_granted_at;

-- +goose Down
ALTER TABLE public.platform_api_keys ADD COLUMN scopes_granted_at timestamp with time zone;
