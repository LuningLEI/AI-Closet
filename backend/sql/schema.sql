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
    season text not null default 'All-Season',
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
