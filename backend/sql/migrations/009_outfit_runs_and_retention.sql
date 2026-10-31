-- Apply after 008. No historical records are deleted or assigned invented usage.
begin;
create table if not exists public.outfit_runs (
 id uuid primary key,
 user_id uuid not null references auth.users(id) on delete cascade,
 algorithm text not null,
 generation_key text not null,
 evaluator_key text not null,
 generation_model text not null,
 evaluation_model text not null,
 generation_prompt_hash text not null,
 evaluation_prompt_hash text not null,
 config jsonb not null,
 pinned boolean not null default false,
 pin_reason text,
 created_at timestamptz not null default now(),
 unique(id,user_id)
);
create index if not exists outfit_runs_owner_created on public.outfit_runs(user_id,created_at desc,id);
alter table public.outfit_build_jobs add column if not exists run_id uuid references public.outfit_runs(id);
create index if not exists outfit_jobs_run_status on public.outfit_build_jobs(run_id,status);
create table if not exists public.outfit_model_calls (
 id uuid primary key,
 run_id uuid not null,
 job_id text not null references public.outfit_build_jobs(id),
 user_id uuid not null references auth.users(id) on delete cascade,
 attempt integer not null check(attempt>0),
 lease_token uuid,
 stage text not null check(stage in ('generation','evaluation')),
 model text not null,
 status text not null check(status in ('running','succeeded','failed','unknown')),
 input_tokens bigint check(input_tokens>=0),
 cached_input_tokens bigint check(cached_input_tokens>=0),
 output_tokens bigint check(output_tokens>=0),
 estimated_cost_usd numeric(24,12) check(estimated_cost_usd>=0),
 pricing jsonb,
 raw_usage jsonb,
 error_type text,
 duration_ms bigint check(duration_ms>=0),
 created_at timestamptz not null default now(),
 finished_at timestamptz,
 compacted_at timestamptz,
 foreign key(run_id,user_id) references public.outfit_runs(id,user_id) on delete cascade,
 check(cached_input_tokens is null or input_tokens is null or cached_input_tokens<=input_tokens)
);
create index if not exists outfit_calls_run_stage on public.outfit_model_calls(run_id,stage,status);
create index if not exists outfit_calls_unfinished on public.outfit_model_calls(job_id,lease_token) where status='running';
create index if not exists outfit_calls_retention on public.outfit_model_calls(finished_at) where raw_usage is not null;
create table if not exists public.outfit_run_results (
 run_id uuid not null references public.outfit_runs(id) on delete cascade,
 outfit_id uuid not null references public.outfits(id) on delete cascade,
 user_id uuid not null references auth.users(id) on delete cascade,
 cached boolean not null,
 primary key(run_id,outfit_id)
);
create index if not exists outfit_result_reverse on public.outfit_run_results(outfit_id);

create or replace function public.outfit_review_status(p jsonb) returns text language sql immutable as $$
 select case when p is null or p='null'::jsonb then 'unreviewed'
 when exists(select 1 from unnest(array['wearability','thermal','color_pattern','occasion']) k where p->k->>'verdict'='fail') then 'failed'
 when exists(select 1 from unnest(array['wearability','thermal','color_pattern','occasion']) k where (p->k->>'verdict') is distinct from 'pass') then 'uncertain'
 else 'passed' end;
$$;
alter table public.outfits add column if not exists run_id uuid references public.outfit_runs(id);
alter table public.outfits add column if not exists core_review_status text generated always as (public.outfit_review_status(payload->'visual_review'->'core')) stored;
alter table public.outfits add column if not exists full_review_status text generated always as (public.outfit_review_status(payload->'visual_review'->'full')) stored;
alter table public.outfits add column if not exists optional_layer_verdict text generated always as (coalesce(payload->'visual_review'->'optional_layering'->>'verdict','unreviewed')) stored;
create index if not exists outfits_owner_core_review on public.outfits(user_id,core_review_status,created_at desc);
create index if not exists outfits_run on public.outfits(run_id);
alter table public.current_outfits add column if not exists review_status text generated always as (coalesce(payload->>'visual_review_status','pending')) stored;
alter table public.current_outfit_layers add column if not exists review_status text generated always as (coalesce(payload->>'visual_review_status','pending')) stored;
create index if not exists current_outfits_owner_review on public.current_outfits(user_id,review_status,id);
-- Currentness lives in the current projection, not an independently mutable flag.
create table if not exists public.outfit_projection_sources (
 current_outfit_id uuid not null references public.current_outfits(id) on delete cascade,
 evaluation_id uuid not null references public.outfits(id),
 user_id uuid not null references auth.users(id) on delete cascade,
 primary key(current_outfit_id,evaluation_id)
);
create index if not exists outfit_projection_evaluation on public.outfit_projection_sources(evaluation_id);
create or replace view public.outfit_evaluation_index with (security_invoker=true) as
 select o.id,o.user_id,o.run_id,o.signature,o.revision,o.evaluator_key,o.core_review_status,o.full_review_status,o.optional_layer_verdict,o.created_at,
 exists(select 1 from outfit_projection_sources s where s.evaluation_id=o.id) as is_current
 from outfits o;

create or replace function public.freeze_outfit_run() returns trigger language plpgsql as $$
begin
 if to_jsonb(NEW)-array['pinned','pin_reason'] is distinct from to_jsonb(OLD)-array['pinned','pin_reason'] then
  raise exception 'Run manifests are immutable; create a new run'; end if;
 return NEW;
end $$;
drop trigger if exists freeze_outfit_run on outfit_runs;
create trigger freeze_outfit_run before update on outfit_runs for each row execute function freeze_outfit_run();
create or replace function public.set_outfit_run_reference() returns trigger language plpgsql as $$
begin
 NEW.run_id:=nullif(NEW.payload->>'run_id','')::uuid;
 if NEW.run_id is not null and not exists(select 1 from outfit_runs r where r.id=NEW.run_id and r.user_id=NEW.user_id) then raise exception 'Outfit run owner mismatch'; end if;
 return NEW;
end $$;
drop trigger if exists set_outfit_run_reference on outfits;
create trigger set_outfit_run_reference before insert or update of payload on outfits for each row execute function set_outfit_run_reference();

create or replace function public.enqueue_outfit_run(p_run jsonb,p_jobs jsonb) returns integer
language plpgsql security definer set search_path=public as $$
declare r outfit_runs; j jsonb; added integer:=0; n integer;
begin
 -- Serialize enqueue for this user: overlapping uploads cannot create empty runs.
 perform pg_advisory_xact_lock(hashtextextended(p_run->>'user_id',901));
 if not exists(select 1 from jsonb_array_elements(p_jobs) x where not exists(select 1 from outfit_build_jobs b where b.id=x->>'id')) then return 0; end if;
 insert into outfit_runs(id,user_id,algorithm,generation_key,evaluator_key,generation_model,evaluation_model,generation_prompt_hash,evaluation_prompt_hash,config)
 values((p_run->>'id')::uuid,(p_run->>'user_id')::uuid,p_run->>'algorithm',p_run->>'generation_key',p_run->>'evaluator_key',p_run->>'generation_model',p_run->>'evaluation_model',p_run->>'generation_prompt_hash',p_run->>'evaluation_prompt_hash',p_run->'config') on conflict(id) do nothing;
 select * into r from outfit_runs where id=(p_run->>'id')::uuid;
 if r.user_id<>(p_run->>'user_id')::uuid or r.config<>p_run->'config' then raise exception 'Run manifest conflict'; end if;
 for j in select value from jsonb_array_elements(p_jobs) loop
  if j->>'user_id'<>r.user_id::text or j->>'generation_key'<>r.generation_key or not exists(select 1 from clothing_items where id=(j->>'anchor_item_id')::uuid and user_id=r.user_id) then raise exception 'Job/run mismatch'; end if;
  insert into outfit_build_jobs(id,user_id,anchor_item_id,revision,generation_key,run_id)
  values(j->>'id',r.user_id,(j->>'anchor_item_id')::uuid,j->>'revision',r.generation_key,r.id) on conflict(id) do nothing;
  get diagnostics n=row_count;added:=added+n;
 end loop;
 return added;
end $$;
create or replace function public.attach_outfit_job_run(p_job_id text,p_run jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
declare j outfit_build_jobs; r outfit_runs;
begin
 select * into j from outfit_build_jobs where id=p_job_id for update;
 if not found or j.user_id::text<>p_run->>'user_id' or j.generation_key<>p_run->>'generation_key' then raise exception 'Job/run mismatch'; end if;
 if j.run_id is null then
  insert into outfit_runs(id,user_id,algorithm,generation_key,evaluator_key,generation_model,evaluation_model,generation_prompt_hash,evaluation_prompt_hash,config)
  values((p_run->>'id')::uuid,j.user_id,p_run->>'algorithm',j.generation_key,p_run->>'evaluator_key',p_run->>'generation_model',p_run->>'evaluation_model',p_run->>'generation_prompt_hash',p_run->>'evaluation_prompt_hash',p_run->'config') on conflict(id) do nothing;
  update outfit_build_jobs set run_id=(p_run->>'id')::uuid where id=j.id returning * into j;
 end if;
 select * into r from outfit_runs where id=j.run_id and user_id=j.user_id;
 if not found then raise exception 'Run owner mismatch'; end if;
 return to_jsonb(r);
end $$;
create or replace function public.guard_outfit_job_run() returns trigger language plpgsql set search_path=public as $$
begin
 if NEW.run_id is not null then
  perform 1 from outfit_runs where id=NEW.run_id and user_id=NEW.user_id for key share;
  if not found then raise exception 'Job run owner mismatch'; end if;
 end if;
 return NEW;
end $$;
drop trigger if exists guard_outfit_job_run on outfit_build_jobs;
create trigger guard_outfit_job_run before insert or update of run_id,status on outfit_build_jobs for each row execute function guard_outfit_job_run();

create or replace function public.validate_outfit_call() returns trigger language plpgsql as $$
begin
 perform 1 from outfit_runs where id=NEW.run_id for key share;
 if not exists(select 1 from outfit_build_jobs j where j.id=NEW.job_id and j.run_id=NEW.run_id and j.user_id=NEW.user_id
  and j.status='processing' and j.lease_token=NEW.lease_token and j.lease_until>now()) then raise exception 'Call requires current job lease'; end if;
 return NEW;
end $$;
drop trigger if exists validate_outfit_call on outfit_model_calls;
create trigger validate_outfit_call before insert on outfit_model_calls for each row execute function validate_outfit_call();
create or replace function public.link_outfit_run_result(p_run uuid,p_outfit uuid,p_cached boolean) returns void
language plpgsql security definer set search_path=public as $$
declare u uuid;
begin
 select user_id into u from outfit_runs where id=p_run;
 if u is null or not exists(select 1 from outfits where id=p_outfit and user_id=u) then raise exception 'Result owner mismatch'; end if;
 insert into outfit_run_results(run_id,outfit_id,user_id,cached) values(p_run,p_outfit,u,p_cached)
 on conflict(run_id,outfit_id) do update set cached=outfit_run_results.cached and excluded.cached;
end $$;
create or replace function public.recover_outfit_calls() returns integer language plpgsql security definer set search_path=public as $$
declare n integer;
begin
 update outfit_model_calls c set status='unknown',error_type='WorkerInterrupted',finished_at=now()
 where status='running' and not exists(select 1 from outfit_build_jobs j where j.id=c.job_id and j.status='processing' and j.lease_token=c.lease_token and j.lease_until>now());
 get diagnostics n=row_count;return n;
end $$;

create or replace view public.outfit_run_summary with (security_invoker=true) as
 select r.id,r.user_id,r.algorithm,r.generation_key,r.evaluator_key,r.generation_model,r.evaluation_model,r.generation_prompt_hash,r.evaluation_prompt_hash,r.pinned,r.created_at,
 coalesce(j.total_jobs,0) total_jobs,coalesce(j.job_counts,'{}'::jsonb) job_counts,
 case when coalesce(j.processing,0)>0 then 'running' when coalesce(j.queued,0)>0 then 'queued' when coalesce(j.failed,0)>0 then 'failed' when coalesce(j.complete,0)=0 and coalesce(j.obsolete,0)>0 then 'obsolete' else 'complete' end status,
 coalesce(c.call_count,0) call_count,coalesce(c.input_tokens,0) input_tokens,coalesce(c.output_tokens,0) output_tokens,
 coalesce(c.unknown_cost_calls,0) unknown_cost_calls,coalesce(c.known_estimated_cost_usd,0) known_estimated_cost_usd,
 case when coalesce(c.unknown_cost_calls,0)=0 then coalesce(c.known_estimated_cost_usd,0) else null end estimated_cost_usd,
 coalesce(res.unique_results,0) unique_results,coalesce(res.cached_results,0) cached_results
 from outfit_runs r
 left join lateral (select sum(n) total_jobs,jsonb_object_agg(status,n) job_counts,
  sum(n) filter(where status='processing') processing,sum(n) filter(where status='queued') queued,
  sum(n) filter(where status='failed') failed,sum(n) filter(where status='complete') complete,sum(n) filter(where status='obsolete') obsolete
  from(select status,count(*) n from outfit_build_jobs where run_id=r.id group by status) q) j on true
 left join lateral (select count(*) call_count,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens,
  count(*) filter(where estimated_cost_usd is null) unknown_cost_calls,sum(estimated_cost_usd) known_estimated_cost_usd
  from outfit_model_calls where run_id=r.id) c on true
 left join lateral (select count(*) unique_results,count(*) filter(where cached) cached_results from outfit_run_results where run_id=r.id) res on true;

create table if not exists public.data_retention_policies (
 dataset text primary key,
 retention_days integer check(retention_days is null or retention_days>=30),
 action text not null check(action in ('keep','compact_raw_usage')),
 description text not null
);
insert into data_retention_policies values
 ('outfit_model_calls.raw_usage',180,'compact_raw_usage','Keep typed token/cost counters and call identity; compact raw usage only for unpinned terminal runs.'),
 ('outfit_runs',null,'keep','Immutable reproducibility manifests; pinned experiment runs are protected.'),
 ('outfits',null,'keep','Audit evaluations and detailed review evidence. No automatic deletion.'),
 ('recognition_records',null,'keep','Recognition history; no automatic deletion or invented historical cost.'),
 ('item_edit_events',null,'keep','User feedback and learning labels; no automatic deletion.'),
 ('item_feature_snapshots',null,'keep','Versioned feature history; preserve until dataset export/retention is explicitly defined.')
 on conflict(dataset) do nothing;
create table if not exists public.history_maintenance_runs (
 id uuid primary key default gen_random_uuid(),user_id uuid not null references auth.users(id) on delete cascade,
 action text not null,dry_run boolean not null,affected_rows integer not null,created_at timestamptz not null default now()
);
create or replace function public.compact_outfit_usage(p_user uuid,p_apply boolean default false,p_limit integer default 1000) returns integer
language plpgsql security definer set search_path=public as $$
declare n integer; days integer; ids uuid[];
begin
 select retention_days into days from data_retention_policies where dataset='outfit_model_calls.raw_usage' and action='compact_raw_usage';
 if days is null then return 0; end if;
 -- Lock each selected run so pinning/retry cannot race retention decisions.
 perform 1 from outfit_runs where user_id=p_user order by id for update;
 select array_agg(id) into ids from (select c.id from outfit_model_calls c join outfit_runs r on r.id=c.run_id
  where c.user_id=p_user and not r.pinned and c.status in ('succeeded','failed','unknown') and c.raw_usage is not null
  and c.finished_at<now()-make_interval(days=>days)
  and not exists(select 1 from outfit_build_jobs j where j.run_id=r.id and j.status in ('queued','processing'))
  order by c.finished_at,c.id limit least(greatest(p_limit,1),10000)) q;
 n:=coalesce(cardinality(ids),0);
 if p_apply then update outfit_model_calls set raw_usage=null,compacted_at=now() where id=any(ids); end if;
 insert into history_maintenance_runs(user_id,action,dry_run,affected_rows) values(p_user,'compact_raw_usage',not p_apply,n);
 return n;
end $$;

-- All mutations are service-role only. Owners may inspect their own telemetry.
do $$
declare t text;
begin
 foreach t in array array['outfit_runs','outfit_model_calls','outfit_run_results','outfit_projection_sources','history_maintenance_runs'] loop
  execute format('alter table %I enable row level security',t);
  execute format('drop policy if exists owner_read on %I',t);
  execute format('create policy owner_read on %I for select using(auth.uid()=user_id)',t);
 end loop;
end $$;
alter table data_retention_policies enable row level security;
revoke all on function enqueue_outfit_run(jsonb,jsonb),attach_outfit_job_run(text,jsonb),link_outfit_run_result(uuid,uuid,boolean),recover_outfit_calls(),compact_outfit_usage(uuid,boolean,integer) from public,anon,authenticated;
grant execute on function enqueue_outfit_run(jsonb,jsonb),attach_outfit_job_run(text,jsonb),link_outfit_run_result(uuid,uuid,boolean),recover_outfit_calls(),compact_outfit_usage(uuid,boolean,integer) to service_role;
create or replace function public.publish_current_outfits(p_user_id uuid,p_version bigint,p_key text,p_rows jsonb)
returns boolean language plpgsql security definer set search_path=public as $$
declare state outfit_refresh_requests; r jsonb; v jsonb;
begin
 select * into state from outfit_refresh_requests where user_id=p_user_id for update;
 if not found or state.source_version<>p_version then return false; end if;
 delete from current_outfits where user_id=p_user_id;
 for r in select value from jsonb_array_elements(p_rows) loop
  if exists(select 1 from jsonb_array_elements(r->'items') x where not exists(
    select 1 from clothing_items i where i.id=(x->>'id')::uuid and i.user_id=p_user_id)) then raise exception 'Projection owner mismatch'; end if;
  insert into current_outfits(id,user_id,core_item_ids,payload) values((r->>'id')::uuid,p_user_id,
   array(select (x->>'id')::uuid from jsonb_array_elements(r->'items') x),r-array['optional_additions','source_evaluation_ids']);
  if exists(select 1 from jsonb_array_elements_text(coalesce(r->'source_evaluation_ids','[]'::jsonb)) x
    where not exists(select 1 from outfits o where o.id=x::uuid and o.user_id=p_user_id)) then raise exception 'Evaluation owner mismatch'; end if;
  insert into outfit_projection_sources(current_outfit_id,evaluation_id,user_id)
    select (r->>'id')::uuid,x::uuid,p_user_id from jsonb_array_elements_text(coalesce(r->'source_evaluation_ids','[]'::jsonb)) x on conflict do nothing;
  for v in select value from jsonb_array_elements(r->'optional_additions') loop
   if exists(select 1 from jsonb_array_elements(v->'items') x where not exists(
    select 1 from clothing_items i where i.id=(x->>'id')::uuid and i.user_id=p_user_id)) then raise exception 'Projection owner mismatch'; end if;
   insert into current_outfit_layers(outfit_id,id,user_id,item_ids,payload) values((r->>'id')::uuid,v->>'id',p_user_id,
    array(select (x->>'id')::uuid from jsonb_array_elements(v->'items') x),v);
  end loop;
 end loop;
 update outfit_refresh_requests set projected_version=p_version,projection_key=p_key,updated_at=now() where user_id=p_user_id;
 return true;
end $$;


-- Rebuild provenance once without making any model calls.
update outfit_refresh_requests r set projected_version=0,projection_key=null
where exists(select 1 from current_outfits c where c.user_id=r.user_id and not exists(select 1 from outfit_projection_sources s where s.current_outfit_id=c.id));
commit;
notify pgrst,'reload schema';
