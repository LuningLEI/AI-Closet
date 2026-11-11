-- Persist Replace Items edits without mutating immutable model evaluation history.
-- A personal row shadows its generated source outfit in all library reads.
begin;

alter table public.personal_outfits
  add column if not exists source_outfit_id uuid;

create unique index if not exists personal_outfits_source_override
  on public.personal_outfits(user_id,source_outfit_id)
  where source_outfit_id is not null;

create or replace function public.save_personal_outfit_edit(
  p_id uuid,p_user uuid,p_items uuid[],p_title text,p_source_outfit uuid default null
) returns jsonb language plpgsql security definer set search_path=public as $$
declare result personal_outfits; n integer; resolved_source uuid; existing_source uuid;
begin
  perform id from clothing_items where user_id=p_user and id=any(p_items) for share;
  select count(*) into n from clothing_items where user_id=p_user and id=any(p_items);
  if n<>cardinality(p_items) or n<1 or n>12 then raise exception 'Invalid outfit members'; end if;

  resolved_source:=p_source_outfit;
  if p_source_outfit is not null then
    select source_outfit_id into existing_source
      from personal_outfits where id=p_source_outfit and user_id=p_user;
    if found then resolved_source:=existing_source; end if;
  end if;

  insert into personal_outfits(id,user_id,item_ids,title,source_outfit_id,feature_snapshot)
  values(p_id,p_user,p_items,left(p_title,120),resolved_source,
         public.taste_snapshot(p_user,p_items,'{}'::jsonb))
  on conflict(id) do update set
    item_ids=excluded.item_ids,
    title=excluded.title,
    source_outfit_id=coalesce(personal_outfits.source_outfit_id,excluded.source_outfit_id),
    feature_snapshot=excluded.feature_snapshot
  where personal_outfits.user_id=p_user;

  select * into result from personal_outfits where id=p_id and user_id=p_user;
  if result is null then raise exception 'Outfit identity conflict'; end if;
  return to_jsonb(result);
end $$;

revoke all on function public.save_personal_outfit_edit(uuid,uuid,uuid[],text,uuid)
  from public,anon,authenticated;
grant execute on function public.save_personal_outfit_edit(uuid,uuid,uuid[],text,uuid)
  to service_role;

drop trigger if exists mark_taste_profile_dirty on public.personal_outfits;
create trigger mark_taste_profile_dirty
  after insert or update or delete on public.personal_outfits
  for each row execute function public.mark_taste_profile_dirty();

create or replace function public.read_current_outfits(
  p_user_id uuid,p_key text,p_generation_key text,p_anchor uuid default null,
  p_offset int default 0,p_limit int default 30
) returns jsonb language sql stable security definer set search_path=public as $$
 with matching as (
  select c.id,c.payload,c.core_item_ids from current_outfits c join outfit_refresh_requests s on s.user_id=c.user_id
  where c.user_id=p_user_id and s.projection_key=p_key
   and not exists(select 1 from personal_outfits p where p.user_id=p_user_id and p.source_outfit_id=c.id)
   and (p_anchor is null or c.core_item_ids @> array[p_anchor] or exists(select 1 from current_outfit_layers l where l.outfit_id=c.id and l.item_ids @> array[p_anchor]))
 ), personal as (
 select p.id,p.item_ids as core_item_ids,jsonb_build_object('id',p.id,'items',
  (select jsonb_agg(to_jsonb(i)-array['semantic_vector','feature_vector'] order by i.id) from clothing_items i where i.user_id=p_user_id and i.id=any(p.item_ids)),
  'optional_additions','[]'::jsonb,'aesthetic_score',null,'structural_reason','Saved by you','aesthetic_reason',p.title,
  'source','personal','visual_review_status','pending','replaces_outfit_id',p.source_outfit_id) as payload
 from personal_outfits p where p.user_id=p_user_id and (p_anchor is null or p.item_ids @> array[p_anchor])
 and cardinality(p.item_ids)=(select count(*) from clothing_items i where i.user_id=p_user_id and i.id=any(p.item_ids))
 ), combined as (
 select id,payload,core_item_ids from personal
 union all select m.id,m.payload,m.core_item_ids from matching m
 where not exists(select 1 from personal p where p.core_item_ids @> m.core_item_ids and m.core_item_ids @> p.core_item_ids)
 ), page as (select * from combined order by id offset greatest(p_offset,0) limit least(greatest(p_limit,1),100)),
 latest_jobs as (select distinct on (anchor_item_id) status from outfit_build_jobs where user_id=p_user_id and generation_key=p_generation_key and status<>'obsolete' order by anchor_item_id,created_at desc,id),
 counts as (select status,count(*) n from latest_jobs group by status)
 select jsonb_build_object('outfits',coalesce((select jsonb_agg(c.payload||jsonb_build_object('optional_additions',
  coalesce((select jsonb_agg(l.payload order by l.id) from current_outfit_layers l where l.outfit_id=c.id and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or l.item_ids @> array[p_anchor])),'[]'::jsonb)) order by c.id) from page c),'[]'::jsonb),
  'total',(select count(*) from combined),'jobs',coalesce((select jsonb_object_agg(status,n) from counts),'{}'::jsonb),'enrolled',true,
  'next_offset',case when p_offset+p_limit<(select count(*) from combined) then p_offset+p_limit else null end);
$$;

commit;
notify pgrst,'reload schema';
