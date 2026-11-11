create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists public.clothing_items (
    id uuid primary key,
    user_id uuid not null,
    analysis_version text not null default 'clothing-analysis-v1',
    taxonomy_version text not null default 'taxonomy-v1',
    feature_version text not null default 'item-feature-v1',
    recognition_status text not null default 'complete'
        check (recognition_status in ('queued', 'processing', 'complete', 'failed', 'manual')),
    image_url text not null,
    image_path text,
    category text not null,
    subtype text,
    color text not null default 'Unknown',
    season text not null default 'Spring, Summer, Fall, Winter',
    style text not null default 'Casual',
    occasion text not null default 'Everyday',
    material text,
    pattern text,
    fit text,
    length text,
    sleeve_length text,
    neckline text,
    layering_role text,
    warmth_level integer,
    formality_score integer,
    recognition_source text,
    recognition_summary text,
    recognition_confidence double precision,
    recognition_tags jsonb,
    feature_vector vector(13),
    semantic_vector vector(1536),
    metadata jsonb,
    created_at timestamptz not null default now()
);

alter table public.clothing_items
    add column if not exists semantic_vector vector(1536);

alter table public.clothing_items
    add column if not exists user_id uuid;

alter table public.clothing_items
    add column if not exists analysis_version text not null default 'clothing-analysis-v1';

alter table public.clothing_items
    add column if not exists taxonomy_version text not null default 'taxonomy-v1';

alter table public.clothing_items
    add column if not exists feature_version text not null default 'item-feature-v1';

alter table public.clothing_items
    add column if not exists recognition_status text not null default 'complete';

alter table public.clothing_items
    add column if not exists material text;

alter table public.clothing_items
    add column if not exists pattern text;

alter table public.clothing_items
    add column if not exists fit text;

alter table public.clothing_items
    add column if not exists length text;

alter table public.clothing_items
    add column if not exists sleeve_length text;

alter table public.clothing_items
    add column if not exists neckline text;

alter table public.clothing_items
    add column if not exists layering_role text;

alter table public.clothing_items
    add column if not exists warmth_level integer;

alter table public.clothing_items
    add column if not exists formality_score integer;

alter table public.clothing_items
    alter column user_id drop default;

alter table public.clothing_items
    alter column user_id set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'clothing_items_recognition_status_check'
    ) then
        alter table public.clothing_items
            add constraint clothing_items_recognition_status_check
            check (recognition_status in ('queued', 'processing', 'complete', 'failed', 'manual'));
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'clothing_items_warmth_level_check'
    ) then
        alter table public.clothing_items
            add constraint clothing_items_warmth_level_check
            check (warmth_level is null or (warmth_level >= 1 and warmth_level <= 5));
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'clothing_items_formality_score_check'
    ) then
        alter table public.clothing_items
            add constraint clothing_items_formality_score_check
            check (formality_score is null or (formality_score >= 1 and formality_score <= 5));
    end if;
end $$;

create index if not exists clothing_items_created_at_idx
    on public.clothing_items (created_at desc);

create index if not exists clothing_items_category_idx
    on public.clothing_items (category);

create index if not exists clothing_items_user_created_at_idx
    on public.clothing_items (user_id, created_at desc);

create index if not exists clothing_items_user_category_idx
    on public.clothing_items (user_id, category);

create index if not exists clothing_items_user_recognition_status_idx
    on public.clothing_items (user_id, recognition_status);

create index if not exists clothing_items_user_style_idx
    on public.clothing_items (user_id, style);

create index if not exists clothing_items_user_warmth_level_idx
    on public.clothing_items (user_id, warmth_level);

create index if not exists clothing_items_semantic_vector_idx
    on public.clothing_items
    using ivfflat (semantic_vector vector_cosine_ops)
    with (lists = 100);

create table if not exists public.recognition_records (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    provider text not null,
    model_name text,
    prompt_version text,
    analysis_version text not null default 'clothing-analysis-v1',
    taxonomy_version text not null default 'taxonomy-v1',
    confidence double precision,
    category text,
    subtype text,
    color text,
    seasons text[] not null default array[]::text[],
    style text,
    occasion text,
    material text,
    pattern text,
    fit text,
    length text,
    sleeve_length text,
    neckline text,
    layering_role text,
    warmth_level integer,
    formality_score integer,
    normalized_payload jsonb not null,
    raw_payload jsonb,
    created_at timestamptz not null default now()
);

alter table public.recognition_records
    add column if not exists user_id uuid;

alter table public.recognition_records
    add column if not exists analysis_version text not null default 'clothing-analysis-v1';

alter table public.recognition_records
    add column if not exists taxonomy_version text not null default 'taxonomy-v1';

alter table public.recognition_records
    add column if not exists confidence double precision;

alter table public.recognition_records
    add column if not exists category text;

alter table public.recognition_records
    add column if not exists subtype text;

alter table public.recognition_records
    add column if not exists color text;

alter table public.recognition_records
    add column if not exists seasons text[] not null default array[]::text[];

alter table public.recognition_records
    add column if not exists style text;

alter table public.recognition_records
    add column if not exists occasion text;

alter table public.recognition_records
    add column if not exists material text;

alter table public.recognition_records
    add column if not exists pattern text;

alter table public.recognition_records
    add column if not exists fit text;

alter table public.recognition_records
    add column if not exists length text;

alter table public.recognition_records
    add column if not exists sleeve_length text;

alter table public.recognition_records
    add column if not exists neckline text;

alter table public.recognition_records
    add column if not exists layering_role text;

alter table public.recognition_records
    add column if not exists warmth_level integer;

alter table public.recognition_records
    add column if not exists formality_score integer;

alter table public.recognition_records
    alter column user_id drop default;

alter table public.recognition_records
    alter column user_id set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'recognition_records_warmth_level_check'
    ) then
        alter table public.recognition_records
            add constraint recognition_records_warmth_level_check
            check (warmth_level is null or (warmth_level >= 1 and warmth_level <= 5));
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'recognition_records_formality_score_check'
    ) then
        alter table public.recognition_records
            add constraint recognition_records_formality_score_check
            check (formality_score is null or (formality_score >= 1 and formality_score <= 5));
    end if;
end $$;

create index if not exists recognition_records_user_id_idx
    on public.recognition_records (user_id);

create index if not exists recognition_records_clothing_item_id_idx
    on public.recognition_records (clothing_item_id);

create index if not exists recognition_records_user_provider_idx
    on public.recognition_records (user_id, provider);

create index if not exists recognition_records_user_category_idx
    on public.recognition_records (user_id, category);

create table if not exists public.item_edit_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    edit_session_id uuid not null default gen_random_uuid(),
    event_type text not null,
    source text not null default 'unknown',
    changed_fields text[] not null default array[]::text[],
    changes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists item_edit_events_user_created_at_idx
    on public.item_edit_events (user_id, created_at desc);

create index if not exists item_edit_events_item_created_at_idx
    on public.item_edit_events (clothing_item_id, created_at desc);

create index if not exists item_edit_events_changed_fields_gin_idx
    on public.item_edit_events using gin (changed_fields);

create table if not exists public.item_feature_snapshots (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    feature_version text not null default 'v1',
    feature_vector vector(13),
    extra_features jsonb,
    created_at timestamptz not null default now()
);

alter table public.item_feature_snapshots
    add column if not exists user_id uuid;

alter table public.item_feature_snapshots
    alter column user_id drop default;

alter table public.item_feature_snapshots
    alter column user_id set not null;

create index if not exists item_feature_snapshots_item_id_idx
    on public.item_feature_snapshots (clothing_item_id);

create index if not exists item_feature_snapshots_user_id_idx
    on public.item_feature_snapshots (user_id);

create table if not exists public.recognition_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    filename text not null,
    image_url text not null,
    image_path text,
    status text not null default 'queued'
        check (status in ('queued', 'processing', 'complete', 'failed', 'dead_letter')),
    attempts integer not null default 0,
    last_error text,
    leased_at timestamptz,
    next_run_at timestamptz,
    dead_lettered_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.recognition_jobs
    add column if not exists user_id uuid;

alter table public.recognition_jobs
    alter column user_id drop default;

alter table public.recognition_jobs
    alter column user_id set not null;

alter table public.recognition_jobs
    add column if not exists leased_at timestamptz;

alter table public.recognition_jobs
    add column if not exists next_run_at timestamptz;

alter table public.recognition_jobs
    add column if not exists dead_lettered_at timestamptz;

do $$
begin
    if exists (
        select 1
        from pg_constraint
        where conname = 'recognition_jobs_status_check'
    ) then
        alter table public.recognition_jobs
            drop constraint recognition_jobs_status_check;
    end if;
end $$;

alter table public.recognition_jobs
    add constraint recognition_jobs_status_check
    check (status in ('queued', 'processing', 'complete', 'failed', 'dead_letter'));

create index if not exists recognition_jobs_status_created_at_idx
    on public.recognition_jobs (status, created_at);

create index if not exists recognition_jobs_clothing_item_id_idx
    on public.recognition_jobs (clothing_item_id);

create index if not exists recognition_jobs_user_status_created_at_idx
    on public.recognition_jobs (user_id, status, created_at);

create index if not exists recognition_jobs_status_next_run_at_idx
    on public.recognition_jobs (status, next_run_at);

create table if not exists public.user_preferences (
    user_id uuid primary key,
    profile_version text not null default 'profile-v1',
    taxonomy_version text not null default 'taxonomy-v1',
    style_preference_version text not null default 'style-preference-v1',
    onboarding_completed boolean not null default false,
    nickname text,
    avatar_path text,
    birth_year integer,
    gender_identity text,
    daily_occasions text[] not null default array['Everyday', 'Work']::text[],
    style_preferences text[] not null default array['Casual']::text[],
    selected_categories text[] not null default array[
        'Tops',
        'Bottoms',
        'Dresses',
        'Jumpsuits',
        'Sets',
        'Outerwear',
        'Shoes',
        'Bags',
        'Accessories',
        'Activewear',
        'Swimwear',
        'Intimates',
        'Uncategorized'
    ]::text[],
    custom_categories text[] not null default array[]::text[],
    model_training_consent boolean not null default false,
    profile_features jsonb not null default '{}'::jsonb,
    default_location_label text,
    default_latitude double precision,
    default_longitude double precision,
    temperature_unit text not null default 'F'
        check (temperature_unit in ('F', 'C')),
    preferences jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.user_preferences
    add column if not exists profile_version text not null default 'profile-v1';

alter table public.user_preferences
    add column if not exists taxonomy_version text not null default 'taxonomy-v1';

alter table public.user_preferences
    add column if not exists style_preference_version text not null default 'style-preference-v1';

alter table public.user_preferences
    add column if not exists onboarding_completed boolean not null default false;

alter table public.user_preferences
    add column if not exists nickname text;

alter table public.user_preferences
    add column if not exists avatar_path text;

alter table public.user_preferences
    add column if not exists birth_year integer;

alter table public.user_preferences
    add column if not exists gender_identity text;

alter table public.user_preferences
    add column if not exists daily_occasions text[] not null default array['Everyday', 'Work']::text[];

alter table public.user_preferences
    add column if not exists style_preferences text[] not null default array['Casual']::text[];

alter table public.user_preferences
    add column if not exists selected_categories text[] not null default array[
        'Tops',
        'Bottoms',
        'Dresses',
        'Jumpsuits',
        'Sets',
        'Outerwear',
        'Shoes',
        'Bags',
        'Accessories',
        'Activewear',
        'Swimwear',
        'Intimates',
        'Uncategorized'
    ]::text[];

alter table public.user_preferences
    add column if not exists custom_categories text[] not null default array[]::text[];

alter table public.user_preferences
    add column if not exists model_training_consent boolean not null default false;

alter table public.user_preferences
    add column if not exists profile_features jsonb not null default '{}'::jsonb;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'user_preferences_birth_year_check'
    ) then
        alter table public.user_preferences
            add constraint user_preferences_birth_year_check
            check (birth_year is null or (birth_year >= 1900 and birth_year <= extract(year from now())::integer));
    end if;
end $$;

create index if not exists user_preferences_onboarding_completed_idx
    on public.user_preferences (onboarding_completed);

create index if not exists user_preferences_style_preferences_gin_idx
    on public.user_preferences
    using gin (style_preferences);

create index if not exists user_preferences_selected_categories_gin_idx
    on public.user_preferences
    using gin (selected_categories);

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'clothing_items_user_id_fkey'
    ) then
        alter table public.clothing_items
            add constraint clothing_items_user_id_fkey
            foreign key (user_id) references auth.users(id) on delete cascade not valid;
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'recognition_records_user_id_fkey'
    ) then
        alter table public.recognition_records
            add constraint recognition_records_user_id_fkey
            foreign key (user_id) references auth.users(id) on delete cascade not valid;
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'item_feature_snapshots_user_id_fkey'
    ) then
        alter table public.item_feature_snapshots
            add constraint item_feature_snapshots_user_id_fkey
            foreign key (user_id) references auth.users(id) on delete cascade not valid;
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'item_edit_events_user_id_fkey'
    ) then
        alter table public.item_edit_events
            add constraint item_edit_events_user_id_fkey
            foreign key (user_id) references auth.users(id) on delete cascade not valid;
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'recognition_jobs_user_id_fkey'
    ) then
        alter table public.recognition_jobs
            add constraint recognition_jobs_user_id_fkey
            foreign key (user_id) references auth.users(id) on delete cascade not valid;
    end if;

    if not exists (
        select 1 from pg_constraint where conname = 'user_preferences_user_id_fkey'
    ) then
        alter table public.user_preferences
            add constraint user_preferences_user_id_fkey
            foreign key (user_id) references auth.users(id) on delete cascade not valid;
    end if;
end $$;

alter table public.clothing_items enable row level security;
alter table public.recognition_records enable row level security;
alter table public.item_edit_events enable row level security;
alter table public.item_feature_snapshots enable row level security;
alter table public.recognition_jobs enable row level security;
alter table public.user_preferences enable row level security;

drop policy if exists clothing_items_owner_access on public.clothing_items;
create policy clothing_items_owner_access
    on public.clothing_items
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists recognition_records_owner_access on public.recognition_records;
create policy recognition_records_owner_access
    on public.recognition_records
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists item_edit_events_owner_access on public.item_edit_events;
create policy item_edit_events_owner_access
    on public.item_edit_events
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists item_feature_snapshots_owner_access on public.item_feature_snapshots;
create policy item_feature_snapshots_owner_access
    on public.item_feature_snapshots
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists recognition_jobs_owner_access on public.recognition_jobs;
create policy recognition_jobs_owner_access
    on public.recognition_jobs
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists user_preferences_owner_access on public.user_preferences;
create policy user_preferences_owner_access
    on public.user_preferences
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

update storage.buckets
set public = false
where id = 'closet-images';

drop policy if exists closet_images_owner_select on storage.objects;
create policy closet_images_owner_select
    on storage.objects
    for select
    using (
        bucket_id = 'closet-images'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

drop policy if exists closet_images_owner_insert on storage.objects;
create policy closet_images_owner_insert
    on storage.objects
    for insert
    with check (
        bucket_id = 'closet-images'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

drop policy if exists closet_images_owner_update on storage.objects;
create policy closet_images_owner_update
    on storage.objects
    for update
    using (
        bucket_id = 'closet-images'
        and (storage.foldername(name))[1] = auth.uid()::text
    )
    with check (
        bucket_id = 'closet-images'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

drop policy if exists closet_images_owner_delete on storage.objects;
create policy closet_images_owner_delete
    on storage.objects
    for delete
    using (
        bucket_id = 'closet-images'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

create or replace function public.claim_recognition_jobs(
    batch_limit integer default 3,
    max_attempts integer default 3,
    job_timeout_seconds integer default 120
)
returns setof public.recognition_jobs
language plpgsql
as $$
begin
    update public.recognition_jobs
    set
        status = case
            when attempts >= max_attempts then 'dead_letter'
            else 'failed'
        end,
        last_error = coalesce(last_error, 'Recognition job timed out.'),
        next_run_at = case
            when attempts >= max_attempts then null
            else now() + make_interval(secs => least(300, 10 * power(2, greatest(attempts - 1, 0))::integer))
        end,
        dead_lettered_at = case
            when attempts >= max_attempts then now()
            else dead_lettered_at
        end,
        updated_at = now()
    where status = 'processing'
        and leased_at is not null
        and leased_at < now() - make_interval(secs => job_timeout_seconds);

    update public.recognition_jobs
    set
        status = 'dead_letter',
        dead_lettered_at = coalesce(dead_lettered_at, now()),
        next_run_at = null,
        updated_at = now()
    where status = 'failed'
        and attempts >= max_attempts;

    return query
    update public.recognition_jobs
    set
        status = 'processing',
        attempts = attempts + 1,
        leased_at = now(),
        updated_at = now()
    where id in (
        select id
        from public.recognition_jobs
        where status in ('queued', 'failed')
            and attempts < max_attempts
            and (next_run_at is null or next_run_at <= now())
        order by created_at
        for update skip locked
        limit batch_limit
    )
    returning *;
end;
$$;

-- Optional similarity search example:
-- select id, category, subtype
-- from public.clothing_items
-- order by feature_vector <-> '[1,0,0,0,0,0,1,0,0,0,0,0,0]'
-- limit 5;


-- Outfit library (migration 007)
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

-- Migration 008: current schema additions
-- Apply after 007. Additive: existing outfits remain immutable audit history.
begin;
create table if not exists public.outfit_refresh_requests (
 user_id uuid primary key references auth.users(id) on delete cascade,
 source_version bigint not null default 1,
 projected_version bigint not null default 0,
 projection_key text,
 updated_at timestamptz not null default now()
);
create table if not exists public.current_outfits (
 id uuid primary key,
 user_id uuid not null references auth.users(id) on delete cascade,
 core_item_ids uuid[] not null,
 payload jsonb not null,
 updated_at timestamptz not null default now()
);
create index if not exists current_outfits_owner_page on public.current_outfits(user_id,id);
create index if not exists current_outfits_members on public.current_outfits using gin(core_item_ids);
create table if not exists public.current_outfit_layers (
 outfit_id uuid not null references public.current_outfits(id) on delete cascade,
 id text not null,
 user_id uuid not null references auth.users(id) on delete cascade,
 item_ids uuid[] not null,
 payload jsonb not null,
 primary key(outfit_id,id)
);
create index if not exists current_outfit_layers_members on public.current_outfit_layers using gin(item_ids);
create index if not exists current_outfit_layers_owner on public.current_outfit_layers(user_id,outfit_id);

-- A coalescing transactional outbox. Item writes invalidate affected visible
-- outfits immediately; a worker publishes a new projection only at the same version.
create or replace function public.mark_outfit_refresh() returns trigger language plpgsql security definer set search_path=public as $$
declare owner uuid; item uuid;
begin
 owner:=case when TG_OP='DELETE' then OLD.user_id else NEW.user_id end;
 if not exists(select 1 from auth.users where id=owner) then return case when TG_OP='DELETE' then OLD else NEW end; end if;
 if TG_TABLE_NAME='clothing_items' then
  if TG_OP='UPDATE' and (to_jsonb(OLD)-array['image_url','semantic_vector','feature_vector','metadata']) =
                         (to_jsonb(NEW)-array['image_url','semantic_vector','feature_vector','metadata'])
     and (OLD.metadata->'occasion_overrides') is not distinct from (NEW.metadata->'occasion_overrides')
     and (OLD.metadata->'label_confirmation'->'labels') is not distinct from (NEW.metadata->'label_confirmation'->'labels') then return NEW; end if;
  item:=case when TG_OP='DELETE' then OLD.id else NEW.id end;
 end if;
 insert into outfit_refresh_requests(user_id) values(owner)
 on conflict(user_id) do update set source_version=outfit_refresh_requests.source_version+1,updated_at=now();
 if TG_TABLE_NAME='user_preferences' then delete from current_outfits where user_id=owner; end if;
 if item is not null then
  delete from current_outfits c where c.user_id=owner and
   (c.core_item_ids @> array[item] or exists(select 1 from current_outfit_layers l where l.outfit_id=c.id and l.item_ids @> array[item]));
  if TG_OP in ('UPDATE','DELETE') then
   update outfit_build_jobs set status='obsolete',lease_token=null,lease_until=null
    where user_id=owner and anchor_item_id=item and status<>'obsolete';
  end if;
 end if;
 return case when TG_OP='DELETE' then OLD else NEW end;
end $$;
drop trigger if exists item_outfit_refresh on public.clothing_items;
create trigger item_outfit_refresh after insert or update or delete on public.clothing_items for each row execute function public.mark_outfit_refresh();
drop trigger if exists evaluation_outfit_refresh on public.outfits;
create trigger evaluation_outfit_refresh after insert or update or delete on public.outfits for each row execute function public.mark_outfit_refresh();
drop trigger if exists preference_outfit_refresh on public.user_preferences;
create trigger preference_outfit_refresh after update on public.user_preferences for each row execute function public.mark_outfit_refresh();
-- Legacy development rows can reference a placeholder user absent from Auth.
-- Preserve those rows; only real Auth owners can receive refresh requests.
insert into outfit_refresh_requests(user_id)
 select distinct owners.user_id
 from (
  select user_id from clothing_items
  union select user_id from outfit_libraries
  union select user_id from outfits
 ) owners
 join auth.users u on u.id=owners.user_id
 on conflict do nothing;

-- All database effects of one label/recognition/photo change commit together.
-- The expected snapshot protects manual edits; a job lease fences stale workers.
create or replace function public.commit_item_change(p_expected jsonb,p_updates jsonb,p_recognition jsonb default null,
 p_event jsonb default null,p_feature jsonb default null,p_job jsonb default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare current_row clothing_items; result_row clothing_items; j recognition_jobs; k text; cols text; rowdata jsonb;
begin
 if p_job is not null then
  select * into j from recognition_jobs where id=(p_job->>'id')::uuid for update;
  if not found or j.user_id<>(p_expected->>'user_id')::uuid or j.clothing_item_id<>(p_expected->>'id')::uuid
    or j.status<>'processing' or j.attempts<>(p_job->>'attempts')::int
    or j.leased_at is distinct from (p_job->>'leased_at')::timestamptz then return null; end if;
 end if;
 select * into current_row from clothing_items where id=(p_expected->>'id')::uuid and user_id=(p_expected->>'user_id')::uuid for update;
 if not found then return null; end if;
 for k in select jsonb_object_keys(p_expected) loop
  if (to_jsonb(current_row)->k) is distinct from (p_expected->k) then return null; end if;
 end loop;
 if p_updates ?| array['id','user_id','created_at'] then raise exception 'Immutable item field'; end if;
 for k in select jsonb_object_keys(p_updates) loop
  if not to_jsonb(current_row) ? k then raise exception 'Unknown item field'; end if;
 end loop;
 rowdata:=to_jsonb(current_row)||p_updates;
 select string_agg(quote_ident(key),',') into cols from jsonb_object_keys(p_updates) key;
 if cols is not null then
  execute format('update clothing_items set (%s)=(select %s from jsonb_populate_record(null::clothing_items,$1)) where id=$2 returning *',cols,cols)
   into result_row using rowdata,current_row.id;
 else result_row:=current_row; end if;
 foreach rowdata in array array[p_recognition,p_event,p_feature] loop
  if rowdata is not null and ((rowdata->>'user_id')::uuid<>current_row.user_id or (rowdata->>'clothing_item_id')::uuid<>current_row.id) then raise exception 'Record owner mismatch'; end if;
 end loop;
 if p_recognition is not null then insert into recognition_records select * from jsonb_populate_record(null::recognition_records,p_recognition); end if;
 if p_event is not null then insert into item_edit_events select * from jsonb_populate_record(null::item_edit_events,p_event); end if;
 if p_feature is not null then insert into item_feature_snapshots select * from jsonb_populate_record(null::item_feature_snapshots,p_feature); end if;
 if p_job is not null then update recognition_jobs set status='complete',last_error=null,leased_at=null,next_run_at=null,updated_at=now() where id=j.id; end if;
 return to_jsonb(result_row);
end $$;

create or replace function public.create_item_with_records(p_item jsonb,p_recognition jsonb default null,p_feature jsonb default null,p_job jsonb default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare r jsonb; result clothing_items;
begin
 foreach r in array array[p_recognition,p_feature,p_job] loop
  if r is not null and ((r->>'user_id') is distinct from (p_item->>'user_id') or
                       (r->>'clothing_item_id') is distinct from (p_item->>'id')) then raise exception 'Record owner mismatch'; end if;
 end loop;
 insert into clothing_items select * from jsonb_populate_record(null::clothing_items,p_item) returning * into result;
 if p_recognition is not null then insert into recognition_records select * from jsonb_populate_record(null::recognition_records,p_recognition); end if;
 if p_feature is not null then insert into item_feature_snapshots select * from jsonb_populate_record(null::item_feature_snapshots,p_feature); end if;
 if p_job is not null then insert into recognition_jobs select * from jsonb_populate_record(null::recognition_jobs,p_job); end if;
 return to_jsonb(result);
end $$;
revoke all on function create_item_with_records(jsonb,jsonb,jsonb,jsonb) from public,anon,authenticated;
grant execute on function create_item_with_records(jsonb,jsonb,jsonb,jsonb) to service_role;

-- Model calls stay outside SQL transactions. Recheck lease and garment snapshot
-- at the actual commit boundary, then save audit + membership atomically.
create or replace function public.save_outfit_evaluation_checked(p_record jsonb,p_item_ids uuid[],p_job jsonb,p_expected_items jsonb)
returns boolean language plpgsql security definer set search_path=public as $$
declare j outfit_build_jobs; i clothing_items; expected jsonb; k text;
begin
 select * into j from outfit_build_jobs where id=p_job->>'id' for update;
 if not found or j.user_id<>(p_record->>'user_id')::uuid or j.status<>'processing'
  or j.lease_token is distinct from (p_job->>'lease_token')::uuid or j.lease_until<=now() then return false; end if;
 if jsonb_array_length(p_expected_items)<>cardinality(p_item_ids) then raise exception 'Invalid snapshot'; end if;
 for expected in select value from jsonb_array_elements(p_expected_items) order by value->>'id' loop
  select * into i from clothing_items where id=(expected->>'id')::uuid and user_id=j.user_id for share;
  if not found or not i.id=any(p_item_ids) then return false; end if;
  for k in select jsonb_object_keys(expected) loop
   if (to_jsonb(i)->k) is distinct from (expected->k) then return false; end if;
  end loop;
 end loop;
 perform save_outfit_evaluation(p_record,p_item_ids);
 return true;
end $$;
revoke all on function save_outfit_evaluation_checked(jsonb,uuid[],jsonb,jsonb) from public,anon,authenticated;
grant execute on function save_outfit_evaluation_checked(jsonb,uuid[],jsonb,jsonb) to service_role;

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
   array(select (x->>'id')::uuid from jsonb_array_elements(r->'items') x),r-'optional_additions');
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

create or replace function public.read_current_outfits(p_user_id uuid,p_key text,p_generation_key text,p_anchor uuid default null,p_offset int default 0,p_limit int default 30)
returns jsonb language sql stable security definer set search_path=public as $$
 with matching as (
  select c.* from current_outfits c join outfit_refresh_requests s on s.user_id=c.user_id
  where c.user_id=p_user_id and s.projection_key=p_key and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or exists(select 1 from current_outfit_layers l where l.outfit_id=c.id and l.item_ids @> array[p_anchor]))
 ), page as (select * from matching order by id offset greatest(p_offset,0) limit least(greatest(p_limit,1),100)),
 latest_jobs as (select distinct on (anchor_item_id) status from outfit_build_jobs where user_id=p_user_id and generation_key=p_generation_key and status<>'obsolete' order by anchor_item_id,created_at desc,id),
 counts as (select status,count(*) n from latest_jobs group by status)
 select jsonb_build_object('outfits',coalesce((select jsonb_agg(c.payload||jsonb_build_object('optional_additions',
  coalesce((select jsonb_agg(l.payload order by l.id) from current_outfit_layers l where l.outfit_id=c.id and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or l.item_ids @> array[p_anchor])),'[]'::jsonb)) order by c.id) from page c),'[]'::jsonb),
  'total',(select count(*) from matching),'jobs',coalesce((select jsonb_object_agg(status,n) from counts),'{}'::jsonb),'enrolled',true,
  'next_offset',case when p_offset+p_limit<(select count(*) from matching) then p_offset+p_limit else null end);
$$;

alter table outfit_refresh_requests enable row level security;
alter table current_outfits enable row level security;
alter table current_outfit_layers enable row level security;
drop policy if exists current_outfits_read on current_outfits;
create policy current_outfits_read on current_outfits for select using(auth.uid()=user_id);
drop policy if exists current_outfit_layers_read on current_outfit_layers;
create policy current_outfit_layers_read on current_outfit_layers for select using(auth.uid()=user_id);
drop policy if exists outfit_refresh_read on outfit_refresh_requests;
create policy outfit_refresh_read on outfit_refresh_requests for select using(auth.uid()=user_id);
revoke all on function commit_item_change(jsonb,jsonb,jsonb,jsonb,jsonb,jsonb), publish_current_outfits(uuid,bigint,text,jsonb),read_current_outfits(uuid,text,text,uuid,int,int),mark_outfit_refresh() from public,anon,authenticated;
grant execute on function commit_item_change(jsonb,jsonb,jsonb,jsonb,jsonb,jsonb),publish_current_outfits(uuid,bigint,text,jsonb),read_current_outfits(uuid,text,text,uuid,int,int) to service_role;
commit;
notify pgrst,'reload schema';

-- Migration 009: current schema additions
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

-- Safe structured diagnostics; no response bodies, image URLs or credentials.
alter table public.outfit_model_calls add column if not exists diagnostics jsonb not null default '{}'::jsonb;
notify pgrst, 'reload schema';
-- Keep usage/cost history when deleting a garment cascades to its build jobs.
-- Apply after 009 (010 is independent). No clothing or job rows are deleted here.
begin;
alter table public.outfit_model_calls alter column job_id drop not null;
alter table public.outfit_model_calls drop constraint if exists outfit_model_calls_job_id_fkey;
alter table public.outfit_model_calls add constraint outfit_model_calls_job_id_fkey
 foreign key (job_id) references public.outfit_build_jobs(id) on delete set null;
commit;
notify pgrst, 'reload schema';

-- Personal outfits and wear history (migration 012)
-- Personal outfits remain independent of generated evaluation history/projection.
begin;
create table if not exists public.personal_outfits (
 id uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
 item_ids uuid[] not null, title text not null default 'My outfit',
 source_outfit_id uuid,
 created_at timestamptz not null default now(),
 check(cardinality(item_ids) between 1 and 12)
);
create index if not exists personal_outfits_owner on public.personal_outfits(user_id,id);
create index if not exists personal_outfits_members on public.personal_outfits using gin(item_ids);
create unique index if not exists personal_outfits_source_override on public.personal_outfits(user_id,source_outfit_id) where source_outfit_id is not null;
create table if not exists public.outfit_wear_events (
 id uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
 item_ids uuid[] not null, worn_at timestamptz not null,
 created_at timestamptz not null default now(),
 check(cardinality(item_ids) between 1 and 12)
);
create index if not exists outfit_wear_owner_date on public.outfit_wear_events(user_id,worn_at desc);
alter table personal_outfits enable row level security;
alter table outfit_wear_events enable row level security;
drop policy if exists personal_outfits_read on personal_outfits;
create policy personal_outfits_read on personal_outfits for select using(auth.uid()=user_id);
drop policy if exists outfit_wear_read on outfit_wear_events;
create policy outfit_wear_read on outfit_wear_events for select using(auth.uid()=user_id);

create or replace function public.save_personal_outfit(p_id uuid,p_user uuid,p_items uuid[],p_title text)
returns jsonb language plpgsql security definer set search_path=public as $$
declare result personal_outfits; n integer;
begin
 perform id from clothing_items where user_id=p_user and id=any(p_items) for share;
 select count(*) into n from clothing_items where user_id=p_user and id=any(p_items);
 if n<>cardinality(p_items) or n<1 or n>12 then raise exception 'Invalid outfit members'; end if;
 insert into personal_outfits(id,user_id,item_ids,title) values(p_id,p_user,p_items,left(p_title,120))
 on conflict(id) do nothing;
 select * into result from personal_outfits where id=p_id and user_id=p_user and item_ids=p_items;
 if result is null then raise exception 'Outfit identity conflict'; end if;
 return to_jsonb(result);
end $$;

create or replace function public.record_outfit_wear(p_id uuid,p_user uuid,p_items uuid[],p_worn_at timestamptz)
returns jsonb language plpgsql security definer set search_path=public as $$
declare result outfit_wear_events; n integer;
begin
 perform id from clothing_items where user_id=p_user and id=any(p_items) for share;
 select count(*) into n from clothing_items where user_id=p_user and id=any(p_items);
 if n<>cardinality(p_items) or n<1 or n>12 or p_worn_at>now()+interval '1 minute' then raise exception 'Invalid wear event'; end if;
 insert into outfit_wear_events(id,user_id,item_ids,worn_at) values(p_id,p_user,p_items,p_worn_at) on conflict(id) do nothing;
 select * into result from outfit_wear_events where id=p_id and user_id=p_user and item_ids=p_items and worn_at=p_worn_at;
 if result is null then raise exception 'Wear event identity conflict'; end if;
 return to_jsonb(result);
end $$;
revoke all on function save_personal_outfit(uuid,uuid,uuid[],text),record_outfit_wear(uuid,uuid,uuid[],timestamptz) from public,anon,authenticated;
grant execute on function save_personal_outfit(uuid,uuid,uuid[],text),record_outfit_wear(uuid,uuid,uuid[],timestamptz) to service_role;
create or replace function public.read_current_outfits(p_user_id uuid,p_key text,p_generation_key text,p_anchor uuid default null,p_offset int default 0,p_limit int default 30)
returns jsonb language sql stable security definer set search_path=public as $$
 with matching as (
  select c.id,c.payload,c.core_item_ids from current_outfits c join outfit_refresh_requests s on s.user_id=c.user_id
  where c.user_id=p_user_id and s.projection_key=p_key and
   not exists(select 1 from personal_outfits p where p.user_id=p_user_id and p.source_outfit_id=c.id) and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or exists(select 1 from current_outfit_layers l where l.outfit_id=c.id and l.item_ids @> array[p_anchor]))
 ), personal as (
 select p.id,p.item_ids as core_item_ids,jsonb_build_object('id',p.id,'items',
  (select jsonb_agg(to_jsonb(i)-array['semantic_vector','feature_vector'] order by i.id) from clothing_items i where i.user_id=p_user_id and i.id=any(p.item_ids)),
  'optional_additions','[]'::jsonb,'aesthetic_score',null,'structural_reason','Saved by you','aesthetic_reason',p.title,
  'source','personal','visual_review_status','pending','replaces_outfit_id',p.source_outfit_id) as payload
 from personal_outfits p where p.user_id=p_user_id and (p_anchor is null or p.item_ids @> array[p_anchor])
 and cardinality(p.item_ids)=(select count(*) from clothing_items i where i.user_id=p_user_id and i.id=any(p.item_ids))
 ), combined as (
 select id,payload,core_item_ids from personal
 union all select m.id,m.payload,m.core_item_ids from matching m
 where not exists(select 1 from personal p where p.core_item_ids @> m.core_item_ids and m.core_item_ids @> p.core_item_ids)
 ), page as (select * from combined order by id offset greatest(p_offset,0) limit least(greatest(p_limit,1),100)),
 latest_jobs as (select distinct on (anchor_item_id) status from outfit_build_jobs where user_id=p_user_id and generation_key=p_generation_key and status<>'obsolete' order by anchor_item_id,created_at desc,id),
 counts as (select status,count(*) n from latest_jobs group by status)
 select jsonb_build_object('outfits',coalesce((select jsonb_agg(c.payload||jsonb_build_object('optional_additions',
  coalesce((select jsonb_agg(l.payload order by l.id) from current_outfit_layers l where l.outfit_id=c.id and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or l.item_ids @> array[p_anchor])),'[]'::jsonb)) order by c.id) from page c),'[]'::jsonb),
  'total',(select count(*) from combined),'jobs',coalesce((select jsonb_object_agg(status,n) from counts),'{}'::jsonb),'enrolled',true,
  'next_offset',case when p_offset+p_limit<(select count(*) from combined) then p_offset+p_limit else null end);
$$;
commit;
notify pgrst,'reload schema';

-- Migration 013: personalized outfit feedback
begin;

create table if not exists public.outfit_feedback_events (
    id uuid primary key,
    user_id uuid not null references auth.users(id) on delete cascade,
    outfit_id uuid,
    composition_signature text not null,
    item_ids uuid[] not null,
    action text not null check (action in ('liked','disliked')),
    reason_codes text[] not null default array[]::text[],
    note text check (note is null or length(note) <= 500),
    surface text not null check (surface in ('today','library','recommendations','chat')),
    created_at timestamptz not null default now()
);
create index if not exists outfit_feedback_owner_created
    on public.outfit_feedback_events(user_id,created_at desc);
create index if not exists outfit_feedback_owner_signature
    on public.outfit_feedback_events(user_id,composition_signature);

create table if not exists public.user_outfit_feedback_state (
    user_id uuid not null references auth.users(id) on delete cascade,
    composition_signature text not null,
    state text not null check (state in ('liked','disliked')),
    latest_event_id uuid not null references public.outfit_feedback_events(id) on delete cascade,
    updated_at timestamptz not null default now(),
    primary key(user_id,composition_signature)
);

create table if not exists public.user_taste_profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    profile_version bigint not null default 0,
    algorithm_version text not null default 'taste-profile-v2',
    source_version bigint not null default 0,
    projected_version bigint not null default 0,
    feature_weights jsonb not null default '{}'::jsonb,
    feature_evidence jsonb not null default '{}'::jsonb,
    positive_centroid vector(1536),
    negative_centroid vector(1536),
    generation_memory jsonb not null default '{}'::jsonb,
    new_free_text_count integer not null default 0 check(new_free_text_count>=0),
    summarized_free_text_count integer not null default 0 check(summarized_free_text_count>=0),
    free_text_summary jsonb not null default '{}'::jsonb,
    free_text_summary_updated_at timestamptz,
    updated_at timestamptz not null default now()
);

create or replace function public.record_outfit_feedback(p_event jsonb)
returns jsonb language plpgsql security definer set search_path=public as $$
declare
    event_id uuid := (p_event->>'id')::uuid;
    owner_id uuid := (p_event->>'user_id')::uuid;
    member_ids uuid[] := array(select jsonb_array_elements_text(p_event->'item_ids')::uuid);
    reasons text[] := array(select jsonb_array_elements_text(coalesce(p_event->'reason_codes','[]'::jsonb)));
    saved public.outfit_feedback_events;
begin
    if cardinality(member_ids)<1 or cardinality(member_ids)>12
       or cardinality(member_ids)<>(select count(distinct x) from unnest(member_ids) x)
       or (select count(*) from clothing_items where user_id=owner_id and id=any(member_ids))<>cardinality(member_ids)
       or p_event->>'action' not in ('liked','disliked')
       or p_event->>'surface' not in ('today','library','recommendations','chat') then
        raise exception 'Invalid outfit feedback';
    end if;

    insert into outfit_feedback_events(
        id,user_id,outfit_id,composition_signature,item_ids,action,reason_codes,note,surface,created_at
    ) values (
        event_id,owner_id,nullif(p_event->>'outfit_id','')::uuid,p_event->>'composition_signature',
        member_ids,p_event->>'action',reasons,p_event->>'note',p_event->>'surface',
        coalesce((p_event->>'created_at')::timestamptz,now())
    ) on conflict(id) do nothing;

    select * into saved from outfit_feedback_events where id=event_id;
    if saved.user_id<>owner_id or saved.composition_signature<>p_event->>'composition_signature'
       or saved.item_ids<>member_ids or saved.action<>p_event->>'action'
       or saved.reason_codes<>reasons or saved.surface<>p_event->>'surface'
       or saved.outfit_id is distinct from nullif(p_event->>'outfit_id','')::uuid
       or saved.note is distinct from p_event->>'note' then
        raise exception 'Feedback event identity conflict';
    end if;

    insert into user_outfit_feedback_state(user_id,composition_signature,state,latest_event_id,updated_at)
    values(owner_id,saved.composition_signature,saved.action,saved.id,saved.created_at)
    on conflict(user_id,composition_signature) do update
       set state=excluded.state,latest_event_id=excluded.latest_event_id,updated_at=excluded.updated_at
       where user_outfit_feedback_state.updated_at<=excluded.updated_at;

    insert into user_taste_profiles(user_id,source_version,updated_at)
    values(owner_id,1,now())
    on conflict(user_id) do update
       set source_version=user_taste_profiles.source_version+1,updated_at=now();

    return jsonb_build_object(
        'id',saved.id,'user_id',saved.user_id,'outfit_id',saved.outfit_id,
        'item_ids',saved.item_ids,'action',saved.action,'reason_codes',saved.reason_codes,
        'note',saved.note,'surface',saved.surface,
        'composition_signature',saved.composition_signature,'created_at',saved.created_at
    );
end $$;

alter table public.outfit_feedback_events enable row level security;
alter table public.user_outfit_feedback_state enable row level security;
alter table public.user_taste_profiles enable row level security;

drop policy if exists outfit_feedback_owner_read on public.outfit_feedback_events;
create policy outfit_feedback_owner_read on public.outfit_feedback_events
    for select using(auth.uid()=user_id);
drop policy if exists outfit_feedback_state_owner_read on public.user_outfit_feedback_state;
create policy outfit_feedback_state_owner_read on public.user_outfit_feedback_state
    for select using(auth.uid()=user_id);
drop policy if exists taste_profile_owner_read on public.user_taste_profiles;
create policy taste_profile_owner_read on public.user_taste_profiles
    for select using(auth.uid()=user_id);

revoke all on function public.record_outfit_feedback(jsonb) from public,anon,authenticated;
grant execute on function public.record_outfit_feedback(jsonb) to service_role;

commit;
notify pgrst,'reload schema';
-- Persist one current outfit selection per user-local calendar day while keeping
-- outfit_wear_events as the source of recent-wear history.
begin;

create table if not exists public.outfit_daily_selections (
    user_id uuid not null references auth.users(id) on delete cascade,
    wear_date date not null,
    wear_event_id uuid not null references public.outfit_wear_events(id) on delete cascade,
    updated_at timestamptz not null default now(),
    primary key(user_id,wear_date),
    unique(wear_event_id)
);
create index if not exists outfit_daily_selection_event on public.outfit_daily_selections(wear_event_id);
alter table public.outfit_daily_selections enable row level security;
drop policy if exists outfit_daily_selections_read on public.outfit_daily_selections;
create policy outfit_daily_selections_read on public.outfit_daily_selections
    for select using(auth.uid()=user_id);

create or replace function public.set_today_outfit(
    p_id uuid,p_user uuid,p_items uuid[],p_worn_at timestamptz,p_wear_date date
)
returns jsonb language plpgsql security definer set search_path=public as $$
declare
    result public.outfit_wear_events;
    previous_id uuid;
    n integer;
begin
    perform pg_advisory_xact_lock(hashtextextended(p_user::text||':'||p_wear_date::text,0));
    perform id from public.clothing_items where user_id=p_user and id=any(p_items) for share;
    select count(*) into n from public.clothing_items where user_id=p_user and id=any(p_items);
    if n<>cardinality(p_items) or n<1 or n>12 or p_worn_at>now()+interval '1 minute' then
        raise exception 'Invalid wear event';
    end if;

    select wear_event_id into previous_id
      from public.outfit_daily_selections
     where user_id=p_user and wear_date=p_wear_date
     for update;

    if previous_id is not null and previous_id<>p_id then
        delete from public.outfit_wear_events where id=previous_id and user_id=p_user;
    end if;

    insert into public.outfit_wear_events(id,user_id,item_ids,worn_at)
    values(p_id,p_user,p_items,p_worn_at)
    on conflict(id) do nothing;

    select * into result from public.outfit_wear_events
     where id=p_id and user_id=p_user and item_ids=p_items and worn_at=p_worn_at;
    if result is null then raise exception 'Wear event identity conflict'; end if;

    insert into public.outfit_daily_selections(user_id,wear_date,wear_event_id,updated_at)
    values(p_user,p_wear_date,p_id,now())
    on conflict(user_id,wear_date) do update
       set wear_event_id=excluded.wear_event_id,updated_at=excluded.updated_at;

    return to_jsonb(result)||jsonb_build_object('wear_date',p_wear_date);
end $$;

create or replace function public.cancel_today_outfit(p_id uuid,p_user uuid)
returns void language plpgsql security definer set search_path=public as $$
declare selected_date date;
begin
    select wear_date into selected_date from public.outfit_daily_selections
     where wear_event_id=p_id and user_id=p_user;
    if selected_date is null then return; end if;
    perform pg_advisory_xact_lock(hashtextextended(p_user::text||':'||selected_date::text,0));
    delete from public.outfit_wear_events e
     where e.id=p_id and e.user_id=p_user
       and exists(select 1 from public.outfit_daily_selections s
                   where s.wear_event_id=e.id and s.user_id=p_user);
end $$;

revoke all on function public.set_today_outfit(uuid,uuid,uuid[],timestamptz,date) from public,anon,authenticated;
revoke all on function public.cancel_today_outfit(uuid,uuid) from public,anon,authenticated;
grant execute on function public.set_today_outfit(uuid,uuid,uuid[],timestamptz,date) to service_role;
grant execute on function public.cancel_today_outfit(uuid,uuid) to service_role;

commit;
notify pgrst,'reload schema';

-- Profile/catalog preferences are read live by recommendation ranking and are
-- not inputs to generated outfit compositions.
drop trigger if exists preference_outfit_refresh on public.user_preferences;

-- Migration 017: deterministic per-user taste learning
-- Deterministic per-user taste learning sources and projection lifecycle.
begin;

alter table public.outfit_feedback_events add column if not exists context jsonb not null default '{}'::jsonb;
alter table public.outfit_feedback_events add column if not exists target_item_ids uuid[] not null default array[]::uuid[];
alter table public.outfit_feedback_events add column if not exists feature_snapshot jsonb not null default '{}'::jsonb;
alter table public.personal_outfits add column if not exists feature_snapshot jsonb not null default '{}'::jsonb;
alter table public.outfit_wear_events add column if not exists feature_snapshot jsonb not null default '{}'::jsonb;
alter table public.user_taste_profiles add column if not exists learning_reset_at timestamptz;

create or replace function public.taste_snapshot(p_user uuid,p_items uuid[],p_context jsonb default '{}'::jsonb)
returns jsonb language sql stable security definer set search_path=public as $$
 select jsonb_build_object(
   'items',coalesce(jsonb_agg(to_jsonb(i) order by i.id),'[]'::jsonb),
   'context',coalesce(p_context,'{}'::jsonb),
   'outfit_vector',(select to_jsonb(avg(v.semantic_vector)) from clothing_items v
                    where v.user_id=p_user and v.id=any(p_items) and v.semantic_vector is not null)
 ) from clothing_items i where i.user_id=p_user and i.id=any(p_items);
$$;

create or replace function public.capture_taste_snapshot()
returns trigger language plpgsql security definer set search_path=public as $$
begin
 if new.feature_snapshot='{}'::jsonb then
   new.feature_snapshot=public.taste_snapshot(new.user_id,new.item_ids,
     case when tg_table_name='outfit_feedback_events' then new.context else '{}'::jsonb end);
 end if;
 return new;
end $$;

create or replace function public.mark_taste_profile_dirty()
returns trigger language plpgsql security definer set search_path=public as $$
declare owner uuid;
begin
 owner:=case when tg_op='DELETE' then old.user_id else new.user_id end;
 insert into user_taste_profiles(user_id,source_version,updated_at) values(owner,1,now())
 on conflict(user_id) do update set source_version=user_taste_profiles.source_version+1,updated_at=now();
 if tg_op='DELETE' then return old; end if;
 return new;
end $$;

update outfit_feedback_events e set feature_snapshot=public.taste_snapshot(e.user_id,e.item_ids,e.context)
where e.feature_snapshot='{}'::jsonb;
update personal_outfits p set feature_snapshot=public.taste_snapshot(p.user_id,p.item_ids,'{}'::jsonb)
where p.feature_snapshot='{}'::jsonb;
update outfit_wear_events w set feature_snapshot=public.taste_snapshot(w.user_id,w.item_ids,'{}'::jsonb)
where w.feature_snapshot='{}'::jsonb;
insert into user_taste_profiles(user_id,source_version,updated_at)
select u.user_id,u.n,now() from (
 select user_id,count(*) n from (
  select user_id from outfit_feedback_events union all select user_id from personal_outfits union all select user_id from outfit_wear_events
 ) s group by user_id
) u on conflict(user_id) do update set source_version=greatest(user_taste_profiles.source_version,excluded.source_version),updated_at=now();

do $$ declare table_name text;
begin
 foreach table_name in array array['outfit_feedback_events','personal_outfits','outfit_wear_events'] loop
  execute format('drop trigger if exists %I on public.%I','capture_taste_snapshot',table_name);
  execute format('create trigger capture_taste_snapshot before insert on public.%I for each row execute function public.capture_taste_snapshot()',table_name);
  execute format('drop trigger if exists %I on public.%I','mark_taste_profile_dirty',table_name);
  execute format('create trigger mark_taste_profile_dirty after insert or update or delete on public.%I for each row execute function public.mark_taste_profile_dirty()',table_name);
 end loop;
end $$;

create or replace function public.record_outfit_feedback(p_event jsonb)
returns jsonb language plpgsql security definer set search_path=public as $$
declare
 event_id uuid := (p_event->>'id')::uuid; owner_id uuid := (p_event->>'user_id')::uuid;
 member_ids uuid[] := array(select jsonb_array_elements_text(p_event->'item_ids')::uuid);
 reasons text[] := array(select jsonb_array_elements_text(coalesce(p_event->'reason_codes','[]'::jsonb)));
 targets uuid[] := array(select jsonb_array_elements_text(coalesce(p_event->'target_item_ids','[]'::jsonb))::uuid);
 saved public.outfit_feedback_events;
begin
 if cardinality(member_ids)<1 or cardinality(member_ids)>12
    or cardinality(member_ids)<>(select count(distinct x) from unnest(member_ids) x)
    or (select count(*) from clothing_items where user_id=owner_id and id=any(member_ids))<>cardinality(member_ids)
    or not targets <@ member_ids or p_event->>'action' not in ('liked','disliked')
    or p_event->>'surface' not in ('today','library','recommendations','chat') then
   raise exception 'Invalid outfit feedback';
 end if;
 insert into outfit_feedback_events(id,user_id,outfit_id,composition_signature,item_ids,action,reason_codes,note,surface,
                                    context,target_item_ids,feature_snapshot,created_at)
 values(event_id,owner_id,nullif(p_event->>'outfit_id','')::uuid,p_event->>'composition_signature',member_ids,
        p_event->>'action',reasons,p_event->>'note',p_event->>'surface',coalesce(p_event->'context','{}'::jsonb),targets,
        coalesce(p_event->'feature_snapshot','{}'::jsonb),coalesce((p_event->>'created_at')::timestamptz,now()))
 on conflict(id) do nothing;
 select * into saved from outfit_feedback_events where id=event_id;
 if saved.user_id<>owner_id or saved.composition_signature<>p_event->>'composition_signature'
    or saved.item_ids<>member_ids or saved.action<>p_event->>'action' or saved.reason_codes<>reasons
    or saved.surface<>p_event->>'surface' or saved.target_item_ids<>targets
    or saved.outfit_id is distinct from nullif(p_event->>'outfit_id','')::uuid
    or saved.note is distinct from p_event->>'note' then raise exception 'Feedback event identity conflict'; end if;
 insert into user_outfit_feedback_state(user_id,composition_signature,state,latest_event_id,updated_at)
 values(owner_id,saved.composition_signature,saved.action,saved.id,saved.created_at)
 on conflict(user_id,composition_signature) do update set state=excluded.state,latest_event_id=excluded.latest_event_id,
 updated_at=excluded.updated_at where user_outfit_feedback_state.updated_at<=excluded.updated_at;
 return to_jsonb(saved);
end $$;

create or replace function public.reset_taste_profile(p_user uuid)
returns jsonb language plpgsql security definer set search_path=public as $$
declare saved user_taste_profiles;
begin
 insert into user_taste_profiles(user_id,learning_reset_at,updated_at) values(p_user,now(),now())
 on conflict(user_id) do update set profile_version=user_taste_profiles.profile_version+1,
 projected_version=user_taste_profiles.source_version,feature_weights='{}',feature_evidence='{}',positive_centroid=null,
 negative_centroid=null,generation_memory='{}',new_free_text_count=0,learning_reset_at=now(),updated_at=now();
 select * into saved from user_taste_profiles where user_id=p_user; return to_jsonb(saved);
end $$;

create or replace function public.publish_taste_profile(p_user uuid,p_source_version bigint,p_projection jsonb)
returns boolean language plpgsql security definer set search_path=public as $$
declare changed integer;
begin
 update user_taste_profiles set
   profile_version=profile_version+1,algorithm_version=p_projection->>'algorithm_version',
   projected_version=p_source_version,feature_weights=coalesce(p_projection->'feature_weights','{}'),
   feature_evidence=coalesce(p_projection->'feature_evidence','{}'),
   positive_centroid=case when p_projection->'positive_centroid' is null or p_projection->'positive_centroid'='null'::jsonb then null else (p_projection->>'positive_centroid')::vector end,
   negative_centroid=case when p_projection->'negative_centroid' is null or p_projection->'negative_centroid'='null'::jsonb then null else (p_projection->>'negative_centroid')::vector end,
   generation_memory=coalesce(p_projection->'generation_memory','{}'),
   new_free_text_count=coalesce((p_projection->>'new_free_text_count')::integer,0),updated_at=now()
 where user_id=p_user and source_version=p_source_version;
 get diagnostics changed=row_count; return changed=1;
end $$;

revoke all on function public.taste_snapshot(uuid,uuid[],jsonb),public.reset_taste_profile(uuid),public.publish_taste_profile(uuid,bigint,jsonb) from public,anon,authenticated;
grant execute on function public.reset_taste_profile(uuid),public.publish_taste_profile(uuid,bigint,jsonb) to service_role;

commit;
notify pgrst,'reload schema';


-- 018: low-frequency, model-assisted summaries of optional feedback notes.
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
create index if not exists taste_summary_runs_user_created_idx on public.taste_summary_runs(user_id,created_at desc);
alter table public.taste_summary_runs enable row level security;
drop policy if exists taste_summary_runs_owner_read on public.taste_summary_runs;
create policy taste_summary_runs_owner_read on public.taste_summary_runs for select using(auth.uid()=user_id);

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
  update user_taste_profiles set profile_version=profile_version+1,free_text_summary=p_summary,
    summarized_free_text_count=summarized_free_text_count+p_processed_count,
    new_free_text_count=greatest(0,new_free_text_count-p_processed_count),
    free_text_summary_updated_at=now(),updated_at=now()
  where user_id=p_user and profile_version=p_profile_version
    and summarized_free_text_count=p_expected_summarized_count;
  get diagnostics changed=row_count;
  insert into taste_summary_runs(user_id,profile_version,previous_summarized_count,processed_count,model,usage,published)
  values(p_user,p_profile_version,p_expected_summarized_count,p_processed_count,p_model,coalesce(p_usage,'{}'::jsonb),changed=1);
  return changed=1;
end $$;

revoke all on function public.publish_free_text_taste_summary(uuid,bigint,integer,jsonb,integer,text,jsonb),public.reset_taste_profile(uuid) from public,anon,authenticated;
grant execute on function public.publish_free_text_taste_summary(uuid,bigint,integer,jsonb,integer,text,jsonb),public.reset_taste_profile(uuid) to service_role;

-- Migration 020: persistent user edits shadow immutable generated outfits.
alter table public.personal_outfits add column if not exists source_outfit_id uuid;
create unique index if not exists personal_outfits_source_override
  on public.personal_outfits(user_id,source_outfit_id) where source_outfit_id is not null;

create or replace function public.save_personal_outfit_edit(
  p_id uuid,p_user uuid,p_items uuid[],p_title text,p_source_outfit uuid default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare result personal_outfits; n integer; resolved_source uuid; existing_source uuid;
begin
  perform id from clothing_items where user_id=p_user and id=any(p_items) for share;
  select count(*) into n from clothing_items where user_id=p_user and id=any(p_items);
  if n<>cardinality(p_items) or n<1 or n>12 then raise exception 'Invalid outfit members'; end if;
  resolved_source:=p_source_outfit;
  if p_source_outfit is not null then
    select source_outfit_id into existing_source from personal_outfits where id=p_source_outfit and user_id=p_user;
    if found then resolved_source:=existing_source; end if;
  end if;
  insert into personal_outfits(id,user_id,item_ids,title,source_outfit_id,feature_snapshot)
  values(p_id,p_user,p_items,left(p_title,120),resolved_source,public.taste_snapshot(p_user,p_items,'{}'::jsonb))
  on conflict(id) do update set item_ids=excluded.item_ids,title=excluded.title,
    source_outfit_id=coalesce(personal_outfits.source_outfit_id,excluded.source_outfit_id),
    feature_snapshot=excluded.feature_snapshot where personal_outfits.user_id=p_user;
  select * into result from personal_outfits where id=p_id and user_id=p_user;
  if result is null then raise exception 'Outfit identity conflict'; end if;
  return to_jsonb(result);
end $$;
revoke all on function public.save_personal_outfit_edit(uuid,uuid,uuid[],text,uuid) from public,anon,authenticated;
grant execute on function public.save_personal_outfit_edit(uuid,uuid,uuid[],text,uuid) to service_role;
