begin;

alter table public.outfit_feedback_events
    drop constraint if exists outfit_feedback_events_action_check;
alter table public.user_outfit_feedback_state
    drop constraint if exists user_outfit_feedback_state_state_check;

update public.outfit_feedback_events set action='liked' where action='adopted';
update public.user_outfit_feedback_state set state='liked' where state='adopted';

alter table public.outfit_feedback_events
    add constraint outfit_feedback_events_action_check check(action in ('liked','disliked'));
alter table public.user_outfit_feedback_state
    add constraint user_outfit_feedback_state_state_check check(state in ('liked','disliked'));

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

revoke all on function public.record_outfit_feedback(jsonb) from public,anon,authenticated;
grant execute on function public.record_outfit_feedback(jsonb) to service_role;

commit;
notify pgrst,'reload schema';
