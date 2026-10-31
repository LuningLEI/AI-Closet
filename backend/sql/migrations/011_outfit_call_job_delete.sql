-- Keep usage/cost history when deleting a garment cascades to its build jobs.
-- Apply after 009 (010 is independent). No clothing or job rows are deleted here.
begin;
alter table public.outfit_model_calls alter column job_id drop not null;
alter table public.outfit_model_calls drop constraint if exists outfit_model_calls_job_id_fkey;
alter table public.outfit_model_calls add constraint outfit_model_calls_job_id_fkey
 foreign key (job_id) references public.outfit_build_jobs(id) on delete set null;
commit;
notify pgrst, 'reload schema';
