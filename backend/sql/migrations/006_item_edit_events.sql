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

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'item_edit_events_user_id_fkey'
    ) then
        alter table public.item_edit_events
            add constraint item_edit_events_user_id_fkey
            foreign key (user_id) references auth.users(id) on delete cascade not valid;
    end if;
end $$;

alter table public.item_edit_events enable row level security;

drop policy if exists item_edit_events_owner_access on public.item_edit_events;
create policy item_edit_events_owner_access
    on public.item_edit_events
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

notify pgrst, 'reload schema';
