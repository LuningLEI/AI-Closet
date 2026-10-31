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
    algorithm_version text not null default 'taste-profile-v1',
    source_version bigint not null default 0,
    projected_version bigint not null default 0,
    feature_weights jsonb not null default '{}'::jsonb,
    feature_evidence jsonb not null default '{}'::jsonb,
    positive_centroid vector(1536),
    negative_centroid vector(1536),
    generation_memory jsonb not null default '{}'::jsonb,
    new_free_text_count integer not null default 0 check(new_free_text_count>=0),
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
