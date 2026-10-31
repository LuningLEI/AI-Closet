-- Apply after 007. Additive: existing outfits remain immutable audit history.
begin;
create table if not exists public.outfit_refresh_requests (
 user_id uuid primary key references auth.users(id) on delete cascade,
 source_version bigint not null default 1,
 projected_version bigint not null default 0,
 projection_key text,
 updated_at timestamptz not null default now()
);
create table if not exists public.current_outfits (
 id uuid primary key,
 user_id uuid not null references auth.users(id) on delete cascade,
 core_item_ids uuid[] not null,
 payload jsonb not null,
 updated_at timestamptz not null default now()
);
create index if not exists current_outfits_owner_page on public.current_outfits(user_id,id);
create index if not exists current_outfits_members on public.current_outfits using gin(core_item_ids);
create table if not exists public.current_outfit_layers (
 outfit_id uuid not null references public.current_outfits(id) on delete cascade,
 id text not null,
 user_id uuid not null references auth.users(id) on delete cascade,
 item_ids uuid[] not null,
 payload jsonb not null,
 primary key(outfit_id,id)
);
create index if not exists current_outfit_layers_members on public.current_outfit_layers using gin(item_ids);
create index if not exists current_outfit_layers_owner on public.current_outfit_layers(user_id,outfit_id);

-- A coalescing transactional outbox. Item writes invalidate affected visible
-- outfits immediately; a worker publishes a new projection only at the same version.
create or replace function public.mark_outfit_refresh() returns trigger language plpgsql security definer set search_path=public as $$
declare owner uuid; item uuid;
begin
 owner:=case when TG_OP='DELETE' then OLD.user_id else NEW.user_id end;
 if not exists(select 1 from auth.users where id=owner) then return case when TG_OP='DELETE' then OLD else NEW end; end if;
 if TG_TABLE_NAME='clothing_items' then
  if TG_OP='UPDATE' and (to_jsonb(OLD)-array['image_url','semantic_vector','feature_vector','metadata']) =
                         (to_jsonb(NEW)-array['image_url','semantic_vector','feature_vector','metadata'])
     and (OLD.metadata->'occasion_overrides') is not distinct from (NEW.metadata->'occasion_overrides')
     and (OLD.metadata->'label_confirmation'->'labels') is not distinct from (NEW.metadata->'label_confirmation'->'labels') then return NEW; end if;
  item:=case when TG_OP='DELETE' then OLD.id else NEW.id end;
 end if;
 insert into outfit_refresh_requests(user_id) values(owner)
 on conflict(user_id) do update set source_version=outfit_refresh_requests.source_version+1,updated_at=now();
 if TG_TABLE_NAME='user_preferences' then delete from current_outfits where user_id=owner; end if;
 if item is not null then
  delete from current_outfits c where c.user_id=owner and
   (c.core_item_ids @> array[item] or exists(select 1 from current_outfit_layers l where l.outfit_id=c.id and l.item_ids @> array[item]));
  if TG_OP in ('UPDATE','DELETE') then
   update outfit_build_jobs set status='obsolete',lease_token=null,lease_until=null
    where user_id=owner and anchor_item_id=item and status<>'obsolete';
  end if;
 end if;
 return case when TG_OP='DELETE' then OLD else NEW end;
end $$;
drop trigger if exists item_outfit_refresh on public.clothing_items;
create trigger item_outfit_refresh after insert or update or delete on public.clothing_items for each row execute function public.mark_outfit_refresh();
drop trigger if exists evaluation_outfit_refresh on public.outfits;
create trigger evaluation_outfit_refresh after insert or update or delete on public.outfits for each row execute function public.mark_outfit_refresh();
drop trigger if exists preference_outfit_refresh on public.user_preferences;
create trigger preference_outfit_refresh after update on public.user_preferences for each row execute function public.mark_outfit_refresh();
-- Legacy development rows can reference a placeholder user absent from Auth.
-- Preserve those rows; only real Auth owners can receive refresh requests.
insert into outfit_refresh_requests(user_id)
 select distinct owners.user_id
 from (
  select user_id from clothing_items
  union select user_id from outfit_libraries
  union select user_id from outfits
 ) owners
 join auth.users u on u.id=owners.user_id
 on conflict do nothing;

-- All database effects of one label/recognition/photo change commit together.
-- The expected snapshot protects manual edits; a job lease fences stale workers.
create or replace function public.commit_item_change(p_expected jsonb,p_updates jsonb,p_recognition jsonb default null,
 p_event jsonb default null,p_feature jsonb default null,p_job jsonb default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare current_row clothing_items; result_row clothing_items; j recognition_jobs; k text; cols text; rowdata jsonb;
begin
 if p_job is not null then
  select * into j from recognition_jobs where id=(p_job->>'id')::uuid for update;
  if not found or j.user_id<>(p_expected->>'user_id')::uuid or j.clothing_item_id<>(p_expected->>'id')::uuid
    or j.status<>'processing' or j.attempts<>(p_job->>'attempts')::int
    or j.leased_at is distinct from (p_job->>'leased_at')::timestamptz then return null; end if;
 end if;
 select * into current_row from clothing_items where id=(p_expected->>'id')::uuid and user_id=(p_expected->>'user_id')::uuid for update;
 if not found then return null; end if;
 for k in select jsonb_object_keys(p_expected) loop
  if (to_jsonb(current_row)->k) is distinct from (p_expected->k) then return null; end if;
 end loop;
 if p_updates ?| array['id','user_id','created_at'] then raise exception 'Immutable item field'; end if;
 for k in select jsonb_object_keys(p_updates) loop
  if not to_jsonb(current_row) ? k then raise exception 'Unknown item field'; end if;
 end loop;
 rowdata:=to_jsonb(current_row)||p_updates;
 select string_agg(quote_ident(key),',') into cols from jsonb_object_keys(p_updates) key;
 if cols is not null then
  execute format('update clothing_items set (%s)=(select %s from jsonb_populate_record(null::clothing_items,$1)) where id=$2 returning *',cols,cols)
   into result_row using rowdata,current_row.id;
 else result_row:=current_row; end if;
 foreach rowdata in array array[p_recognition,p_event,p_feature] loop
  if rowdata is not null and ((rowdata->>'user_id')::uuid<>current_row.user_id or (rowdata->>'clothing_item_id')::uuid<>current_row.id) then raise exception 'Record owner mismatch'; end if;
 end loop;
 if p_recognition is not null then insert into recognition_records select * from jsonb_populate_record(null::recognition_records,p_recognition); end if;
 if p_event is not null then insert into item_edit_events select * from jsonb_populate_record(null::item_edit_events,p_event); end if;
 if p_feature is not null then insert into item_feature_snapshots select * from jsonb_populate_record(null::item_feature_snapshots,p_feature); end if;
 if p_job is not null then update recognition_jobs set status='complete',last_error=null,leased_at=null,next_run_at=null,updated_at=now() where id=j.id; end if;
 return to_jsonb(result_row);
end $$;

create or replace function public.create_item_with_records(p_item jsonb,p_recognition jsonb default null,p_feature jsonb default null,p_job jsonb default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare r jsonb; result clothing_items;
begin
 foreach r in array array[p_recognition,p_feature,p_job] loop
  if r is not null and ((r->>'user_id') is distinct from (p_item->>'user_id') or
                       (r->>'clothing_item_id') is distinct from (p_item->>'id')) then raise exception 'Record owner mismatch'; end if;
 end loop;
 insert into clothing_items select * from jsonb_populate_record(null::clothing_items,p_item) returning * into result;
 if p_recognition is not null then insert into recognition_records select * from jsonb_populate_record(null::recognition_records,p_recognition); end if;
 if p_feature is not null then insert into item_feature_snapshots select * from jsonb_populate_record(null::item_feature_snapshots,p_feature); end if;
 if p_job is not null then insert into recognition_jobs select * from jsonb_populate_record(null::recognition_jobs,p_job); end if;
 return to_jsonb(result);
end $$;
revoke all on function create_item_with_records(jsonb,jsonb,jsonb,jsonb) from public,anon,authenticated;
grant execute on function create_item_with_records(jsonb,jsonb,jsonb,jsonb) to service_role;

-- Model calls stay outside SQL transactions. Recheck lease and garment snapshot
-- at the actual commit boundary, then save audit + membership atomically.
create or replace function public.save_outfit_evaluation_checked(p_record jsonb,p_item_ids uuid[],p_job jsonb,p_expected_items jsonb)
returns boolean language plpgsql security definer set search_path=public as $$
declare j outfit_build_jobs; i clothing_items; expected jsonb; k text;
begin
 select * into j from outfit_build_jobs where id=p_job->>'id' for update;
 if not found or j.user_id<>(p_record->>'user_id')::uuid or j.status<>'processing'
  or j.lease_token is distinct from (p_job->>'lease_token')::uuid or j.lease_until<=now() then return false; end if;
 if jsonb_array_length(p_expected_items)<>cardinality(p_item_ids) then raise exception 'Invalid snapshot'; end if;
 for expected in select value from jsonb_array_elements(p_expected_items) order by value->>'id' loop
  select * into i from clothing_items where id=(expected->>'id')::uuid and user_id=j.user_id for share;
  if not found or not i.id=any(p_item_ids) then return false; end if;
  for k in select jsonb_object_keys(expected) loop
   if (to_jsonb(i)->k) is distinct from (expected->k) then return false; end if;
  end loop;
 end loop;
 perform save_outfit_evaluation(p_record,p_item_ids);
 return true;
end $$;
revoke all on function save_outfit_evaluation_checked(jsonb,uuid[],jsonb,jsonb) from public,anon,authenticated;
grant execute on function save_outfit_evaluation_checked(jsonb,uuid[],jsonb,jsonb) to service_role;

create or replace function public.publish_current_outfits(p_user_id uuid,p_version bigint,p_key text,p_rows jsonb)
returns boolean language plpgsql security definer set search_path=public as $$
declare state outfit_refresh_requests; r jsonb; v jsonb;
begin
 select * into state from outfit_refresh_requests where user_id=p_user_id for update;
 if not found or state.source_version<>p_version then return false; end if;
 delete from current_outfits where user_id=p_user_id;
 for r in select value from jsonb_array_elements(p_rows) loop
  if exists(select 1 from jsonb_array_elements(r->'items') x where not exists(
    select 1 from clothing_items i where i.id=(x->>'id')::uuid and i.user_id=p_user_id)) then raise exception 'Projection owner mismatch'; end if;
  insert into current_outfits(id,user_id,core_item_ids,payload) values((r->>'id')::uuid,p_user_id,
   array(select (x->>'id')::uuid from jsonb_array_elements(r->'items') x),r-'optional_additions');
  for v in select value from jsonb_array_elements(r->'optional_additions') loop
   if exists(select 1 from jsonb_array_elements(v->'items') x where not exists(
    select 1 from clothing_items i where i.id=(x->>'id')::uuid and i.user_id=p_user_id)) then raise exception 'Projection owner mismatch'; end if;
   insert into current_outfit_layers(outfit_id,id,user_id,item_ids,payload) values((r->>'id')::uuid,v->>'id',p_user_id,
    array(select (x->>'id')::uuid from jsonb_array_elements(v->'items') x),v);
  end loop;
 end loop;
 update outfit_refresh_requests set projected_version=p_version,projection_key=p_key,updated_at=now() where user_id=p_user_id;
 return true;
end $$;

create or replace function public.read_current_outfits(p_user_id uuid,p_key text,p_generation_key text,p_anchor uuid default null,p_offset int default 0,p_limit int default 30)
returns jsonb language sql stable security definer set search_path=public as $$
 with matching as (
  select c.* from current_outfits c join outfit_refresh_requests s on s.user_id=c.user_id
  where c.user_id=p_user_id and s.projection_key=p_key and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or exists(select 1 from current_outfit_layers l where l.outfit_id=c.id and l.item_ids @> array[p_anchor]))
 ), page as (select * from matching order by id offset greatest(p_offset,0) limit least(greatest(p_limit,1),100)),
 latest_jobs as (select distinct on (anchor_item_id) status from outfit_build_jobs where user_id=p_user_id and generation_key=p_generation_key and status<>'obsolete' order by anchor_item_id,created_at desc,id),
 counts as (select status,count(*) n from latest_jobs group by status)
 select jsonb_build_object('outfits',coalesce((select jsonb_agg(c.payload||jsonb_build_object('optional_additions',
  coalesce((select jsonb_agg(l.payload order by l.id) from current_outfit_layers l where l.outfit_id=c.id and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or l.item_ids @> array[p_anchor])),'[]'::jsonb)) order by c.id) from page c),'[]'::jsonb),
  'total',(select count(*) from matching),'jobs',coalesce((select jsonb_object_agg(status,n) from counts),'{}'::jsonb),'enrolled',true,
  'next_offset',case when p_offset+p_limit<(select count(*) from matching) then p_offset+p_limit else null end);
$$;

alter table outfit_refresh_requests enable row level security;
alter table current_outfits enable row level security;
alter table current_outfit_layers enable row level security;
drop policy if exists current_outfits_read on current_outfits;
create policy current_outfits_read on current_outfits for select using(auth.uid()=user_id);
drop policy if exists current_outfit_layers_read on current_outfit_layers;
create policy current_outfit_layers_read on current_outfit_layers for select using(auth.uid()=user_id);
drop policy if exists outfit_refresh_read on outfit_refresh_requests;
create policy outfit_refresh_read on outfit_refresh_requests for select using(auth.uid()=user_id);
revoke all on function commit_item_change(jsonb,jsonb,jsonb,jsonb,jsonb,jsonb), publish_current_outfits(uuid,bigint,text,jsonb),read_current_outfits(uuid,text,text,uuid,int,int),mark_outfit_refresh() from public,anon,authenticated;
grant execute on function commit_item_change(jsonb,jsonb,jsonb,jsonb,jsonb,jsonb),publish_current_outfits(uuid,bigint,text,jsonb),read_current_outfits(uuid,text,text,uuid,int,int) to service_role;
commit;
notify pgrst,'reload schema';
