-- Anchor-driven outfit library. Model calls are made only by the separate outfit worker.
create table if not exists public.outfit_libraries (
    user_id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);
create table if not exists public.outfit_build_jobs (
    id text primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    anchor_item_id uuid not null references public.clothing_items(id) on delete cascade,
    revision text not null,
    generation_key text not null,
    status text not null default 'queued' check (status in ('queued','processing','complete','failed','obsolete')),
    attempts integer not null default 0,
    lease_token uuid,
    lease_until timestamptz,
    retry_at timestamptz not null default now(),
    error text,
    stats jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists outfit_jobs_queue_idx on public.outfit_build_jobs(status,retry_at,created_at);
create index if not exists outfit_jobs_user_idx on public.outfit_build_jobs(user_id);
create table if not exists public.outfits (
    id uuid primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    signature text not null,
    revision text not null,
    evaluator_key text not null,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    unique(user_id,signature,revision,evaluator_key)
);
create index if not exists outfits_user_idx on public.outfits(user_id);
create table if not exists public.outfit_items (
    outfit_id uuid not null references public.outfits(id) on delete cascade,
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    primary key(outfit_id,clothing_item_id)
);
create index if not exists outfit_items_lookup_idx on public.outfit_items(user_id,clothing_item_id);

create or replace function public.claim_outfit_job(p_max_attempts integer, p_lease_seconds integer)
returns setof public.outfit_build_jobs language plpgsql security definer set search_path=public as $$
begin
    update outfit_build_jobs set status='failed',error='Worker lease expired; retry limit reached'
      where status='processing' and lease_until < now() and attempts >= p_max_attempts;
    return query
    with candidate as (
        select id from outfit_build_jobs
        where ((status='queued' and retry_at <= now()) or (status='processing' and lease_until < now()))
          and attempts < p_max_attempts
        order by created_at,id for update skip locked limit 1
    )
    update outfit_build_jobs j set status='processing',attempts=j.attempts+1,
      lease_token=gen_random_uuid(),lease_until=now()+make_interval(secs=>p_lease_seconds),error=null
    from candidate c where j.id=c.id returning j.*;
end $$;

create or replace function public.save_outfit_evaluation(p_record jsonb, p_item_ids uuid[])
returns void language plpgsql security definer set search_path=public as $$
declare owner_id uuid := (p_record->>'user_id')::uuid;
        outfit_id uuid := (p_record->>'id')::uuid;
begin
    if cardinality(p_item_ids) < 1 or cardinality(p_item_ids) <> (select count(distinct x) from unnest(p_item_ids) x) then
        raise exception 'Invalid outfit members';
    end if;
    perform id from clothing_items where id=any(p_item_ids) and user_id=owner_id for key share;
    if (select count(*) from clothing_items where id=any(p_item_ids) and user_id=owner_id) <> cardinality(p_item_ids) then
        raise exception 'Outfit items unavailable or owned by another user';
    end if;
    insert into outfits(id,user_id,signature,revision,evaluator_key,payload)
    values(outfit_id,owner_id,p_record->>'signature',p_record->>'revision',p_record->>'evaluator_key',p_record->'payload')
    on conflict (user_id,signature,revision,evaluator_key) do nothing;
    insert into outfit_items(outfit_id,clothing_item_id,user_id)
      select outfit_id,x,owner_id from unnest(p_item_ids) x on conflict do nothing;
end $$;

-- RLS allows owners to read; generated scores and queue state are backend-controlled.
alter table public.outfit_libraries enable row level security;
alter table public.outfit_build_jobs enable row level security;
alter table public.outfits enable row level security;
alter table public.outfit_items enable row level security;
drop policy if exists outfit_libraries_read on public.outfit_libraries;
create policy outfit_libraries_read on public.outfit_libraries for select using(auth.uid()=user_id);
drop policy if exists outfit_jobs_read on public.outfit_build_jobs;
create policy outfit_jobs_read on public.outfit_build_jobs for select using(auth.uid()=user_id);
drop policy if exists outfits_read on public.outfits;
create policy outfits_read on public.outfits for select using(auth.uid()=user_id);
drop policy if exists outfit_items_read on public.outfit_items;
create policy outfit_items_read on public.outfit_items for select using(auth.uid()=user_id);
revoke all on function public.claim_outfit_job(integer,integer) from public,anon,authenticated;
revoke all on function public.save_outfit_evaluation(jsonb,uuid[]) from public,anon,authenticated;
grant execute on function public.claim_outfit_job(integer,integer) to service_role;
grant execute on function public.save_outfit_evaluation(jsonb,uuid[]) to service_role;
notify pgrst, 'reload schema';
