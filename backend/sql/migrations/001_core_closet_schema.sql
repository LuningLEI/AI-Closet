create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists public.clothing_items (
    id uuid primary key,
    image_url text not null,
    image_path text,
    category text not null,
    subtype text,
    color text not null default 'Unknown',
    season text not null default 'All-Season',
    style text not null default 'Casual',
    occasion text not null default 'Everyday',
    recognition_source text,
    recognition_summary text,
    recognition_confidence double precision,
    recognition_tags jsonb,
    feature_vector vector(13),
    semantic_vector vector(1536),
    metadata jsonb,
    created_at timestamptz not null default now()
);

create index if not exists clothing_items_created_at_idx
    on public.clothing_items (created_at desc);

create index if not exists clothing_items_category_idx
    on public.clothing_items (category);

create index if not exists clothing_items_semantic_vector_idx
    on public.clothing_items
    using ivfflat (semantic_vector vector_cosine_ops)
    with (lists = 100);

create table if not exists public.recognition_records (
    id uuid primary key default gen_random_uuid(),
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    provider text not null,
    model_name text,
    prompt_version text,
    normalized_payload jsonb not null,
    raw_payload jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.item_feature_snapshots (
    id uuid primary key default gen_random_uuid(),
    clothing_item_id uuid not null references public.clothing_items(id) on delete cascade,
    feature_version text not null default 'v1',
    feature_vector vector(13),
    extra_features jsonb,
    created_at timestamptz not null default now()
);

create index if not exists recognition_records_clothing_item_id_idx
    on public.recognition_records (clothing_item_id);

create index if not exists item_feature_snapshots_item_id_idx
    on public.item_feature_snapshots (clothing_item_id);
