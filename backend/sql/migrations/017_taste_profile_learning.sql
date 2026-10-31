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
  execute format('create trigger mark_taste_profile_dirty after insert or delete on public.%I for each row execute function public.mark_taste_profile_dirty()',table_name);
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
