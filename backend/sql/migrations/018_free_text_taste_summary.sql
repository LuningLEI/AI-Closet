-- Low-frequency, model-assisted summaries of optional per-user feedback notes.
begin;

alter table public.user_taste_profiles
  add column if not exists summarized_free_text_count integer not null default 0 check(summarized_free_text_count>=0),
  add column if not exists free_text_summary jsonb not null default '{}'::jsonb,
  add column if not exists free_text_summary_updated_at timestamptz;

create table if not exists public.taste_summary_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  profile_version bigint not null,
  previous_summarized_count integer not null check(previous_summarized_count>=0),
  processed_count integer not null check(processed_count>0),
  model text not null,
  usage jsonb not null default '{}'::jsonb,
  published boolean not null,
  created_at timestamptz not null default now()
);

create index if not exists taste_summary_runs_user_created_idx
  on public.taste_summary_runs(user_id,created_at desc);
alter table public.taste_summary_runs enable row level security;
drop policy if exists taste_summary_runs_owner_read on public.taste_summary_runs;
create policy taste_summary_runs_owner_read on public.taste_summary_runs
  for select using(auth.uid()=user_id);

create or replace function public.reset_taste_profile(p_user uuid)
returns jsonb language plpgsql security definer set search_path=public as $$
declare saved user_taste_profiles;
begin
 insert into user_taste_profiles(user_id,learning_reset_at,updated_at) values(p_user,now(),now())
 on conflict(user_id) do update set profile_version=user_taste_profiles.profile_version+1,
 projected_version=user_taste_profiles.source_version,feature_weights='{}',feature_evidence='{}',positive_centroid=null,
 negative_centroid=null,generation_memory='{}',new_free_text_count=0,summarized_free_text_count=0,
 free_text_summary='{}',free_text_summary_updated_at=null,learning_reset_at=now(),updated_at=now();
 select * into saved from user_taste_profiles where user_id=p_user; return to_jsonb(saved);
end $$;

create or replace function public.publish_free_text_taste_summary(
  p_user uuid,p_profile_version bigint,p_expected_summarized_count integer,
  p_summary jsonb,p_processed_count integer,p_model text,p_usage jsonb
) returns boolean language plpgsql security definer set search_path=public as $$
declare changed integer;
begin
  if p_processed_count<1 or p_summary is null or jsonb_typeof(p_summary)<>'object' then
    raise exception 'Invalid taste summary publication';
  end if;
  update user_taste_profiles set
    profile_version=profile_version+1,free_text_summary=p_summary,
    summarized_free_text_count=summarized_free_text_count+p_processed_count,
    new_free_text_count=greatest(0,new_free_text_count-p_processed_count),
    free_text_summary_updated_at=now(),updated_at=now()
  where user_id=p_user and profile_version=p_profile_version
    and summarized_free_text_count=p_expected_summarized_count;
  get diagnostics changed=row_count;
  insert into taste_summary_runs(user_id,profile_version,previous_summarized_count,
    processed_count,model,usage,published) values(p_user,p_profile_version,p_expected_summarized_count,
    p_processed_count,p_model,coalesce(p_usage,'{}'::jsonb),changed=1);
  return changed=1;
end $$;

revoke all on function public.publish_free_text_taste_summary(uuid,bigint,integer,jsonb,integer,text,jsonb)
  from public,anon,authenticated;
revoke all on function public.reset_taste_profile(uuid) from public,anon,authenticated;
grant execute on function public.publish_free_text_taste_summary(uuid,bigint,integer,jsonb,integer,text,jsonb),
  public.reset_taste_profile(uuid)
  to service_role;

commit;
notify pgrst,'reload schema';
