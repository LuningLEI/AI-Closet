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
