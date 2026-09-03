alter table public.clothing_items
    add column if not exists user_id uuid;

alter table public.recognition_records
    add column if not exists user_id uuid;

alter table public.item_feature_snapshots
    add column if not exists user_id uuid;

alter table public.clothing_items
    alter column user_id drop default;

alter table public.recognition_records
    alter column user_id drop default;

alter table public.item_feature_snapshots
    alter column user_id drop default;

create index if not exists clothing_items_user_created_at_idx
    on public.clothing_items (user_id, created_at desc);

create index if not exists clothing_items_user_category_idx
    on public.clothing_items (user_id, category);

create index if not exists recognition_records_user_id_idx
    on public.recognition_records (user_id);

create index if not exists item_feature_snapshots_user_id_idx
    on public.item_feature_snapshots (user_id);

alter table public.clothing_items enable row level security;
alter table public.recognition_records enable row level security;
alter table public.item_feature_snapshots enable row level security;

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
