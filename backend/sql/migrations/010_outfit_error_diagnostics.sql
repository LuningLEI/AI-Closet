-- Safe structured diagnostics; no response bodies, image URLs or credentials.
alter table public.outfit_model_calls add column if not exists diagnostics jsonb not null default '{}'::jsonb;
notify pgrst, 'reload schema';
