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

create index if not exists clothing_items_user_recognition_status_idx
    on public.clothing_items (user_id, recognition_status);

create index if not exists clothing_items_user_style_idx
    on public.clothing_items (user_id, style);

create index if not exists clothing_items_user_warmth_level_idx
    on public.clothing_items (user_id, warmth_level);

create index if not exists recognition_records_user_provider_idx
    on public.recognition_records (user_id, provider);

create index if not exists recognition_records_user_category_idx
    on public.recognition_records (user_id, category);

notify pgrst, 'reload schema';
