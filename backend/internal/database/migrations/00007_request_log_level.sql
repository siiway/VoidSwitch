-- +goose Up
-- Record how much detail a request row kept, so the access policy can decide who
-- may read each group. 0 means "written before this policy existed" and is read
-- as the old fixed behaviour (headers for staff, bodies for owners).
ALTER TABLE public.request_logs ADD COLUMN log_level smallint NOT NULL DEFAULT 0;

-- +goose Down
ALTER TABLE public.request_logs DROP COLUMN log_level;