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
        'Tops', 'Bottoms', 'Dresses', 'Jumpsuits', 'Sets', 'Outerwear',
        'Shoes', 'Bags', 'Accessories', 'Activewear', 'Swimwear',
        'Intimates', 'Uncategorized'
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
        'Tops', 'Bottoms', 'Dresses', 'Jumpsuits', 'Sets', 'Outerwear',
        'Shoes', 'Bags', 'Accessories', 'Activewear', 'Swimwear',
        'Intimates', 'Uncategorized'
    ]::text[];

alter table public.user_preferences
    add column if not exists custom_categories text[] not null default array[]::text[];

alter table public.user_preferences
    add column if not exists model_training_consent boolean not null default false;

alter table public.user_preferences
    add column if not exists profile_features jsonb not null default '{}'::jsonb;

create index if not exists user_preferences_onboarding_completed_idx
    on public.user_preferences (onboarding_completed);

create index if not exists user_preferences_style_preferences_gin_idx
    on public.user_preferences
    using gin (style_preferences);

create index if not exists user_preferences_selected_categories_gin_idx
    on public.user_preferences
    using gin (selected_categories);

alter table public.user_preferences enable row level security;

drop policy if exists user_preferences_owner_access on public.user_preferences;
create policy user_preferences_owner_access
    on public.user_preferences
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
