-- Personal outfits remain independent of generated evaluation history/projection.
begin;
create table if not exists public.personal_outfits (
 id uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
 item_ids uuid[] not null, title text not null default 'My outfit',
 created_at timestamptz not null default now(),
 check(cardinality(item_ids) between 1 and 12)
);
create index if not exists personal_outfits_owner on public.personal_outfits(user_id,id);
create index if not exists personal_outfits_members on public.personal_outfits using gin(item_ids);
create table if not exists public.outfit_wear_events (
 id uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
 item_ids uuid[] not null, worn_at timestamptz not null,
 created_at timestamptz not null default now(),
 check(cardinality(item_ids) between 1 and 12)
);
create index if not exists outfit_wear_owner_date on public.outfit_wear_events(user_id,worn_at desc);
alter table personal_outfits enable row level security;
alter table outfit_wear_events enable row level security;
drop policy if exists personal_outfits_read on personal_outfits;
create policy personal_outfits_read on personal_outfits for select using(auth.uid()=user_id);
drop policy if exists outfit_wear_read on outfit_wear_events;
create policy outfit_wear_read on outfit_wear_events for select using(auth.uid()=user_id);

create or replace function public.save_personal_outfit(p_id uuid,p_user uuid,p_items uuid[],p_title text)
returns jsonb language plpgsql security definer set search_path=public as $$
declare result personal_outfits; n integer;
begin
 perform id from clothing_items where user_id=p_user and id=any(p_items) for share;
 select count(*) into n from clothing_items where user_id=p_user and id=any(p_items);
 if n<>cardinality(p_items) or n<1 or n>12 then raise exception 'Invalid outfit members'; end if;
 insert into personal_outfits(id,user_id,item_ids,title) values(p_id,p_user,p_items,left(p_title,120))
 on conflict(id) do nothing;
 select * into result from personal_outfits where id=p_id and user_id=p_user and item_ids=p_items;
 if result is null then raise exception 'Outfit identity conflict'; end if;
 return to_jsonb(result);
end $$;

create or replace function public.record_outfit_wear(p_id uuid,p_user uuid,p_items uuid[],p_worn_at timestamptz)
returns jsonb language plpgsql security definer set search_path=public as $$
declare result outfit_wear_events; n integer;
begin
 perform id from clothing_items where user_id=p_user and id=any(p_items) for share;
 select count(*) into n from clothing_items where user_id=p_user and id=any(p_items);
 if n<>cardinality(p_items) or n<1 or n>12 or p_worn_at>now()+interval '1 minute' then raise exception 'Invalid wear event'; end if;
 insert into outfit_wear_events(id,user_id,item_ids,worn_at) values(p_id,p_user,p_items,p_worn_at) on conflict(id) do nothing;
 select * into result from outfit_wear_events where id=p_id and user_id=p_user and item_ids=p_items and worn_at=p_worn_at;
 if result is null then raise exception 'Wear event identity conflict'; end if;
 return to_jsonb(result);
end $$;
revoke all on function save_personal_outfit(uuid,uuid,uuid[],text),record_outfit_wear(uuid,uuid,uuid[],timestamptz) from public,anon,authenticated;
grant execute on function save_personal_outfit(uuid,uuid,uuid[],text),record_outfit_wear(uuid,uuid,uuid[],timestamptz) to service_role;
create or replace function public.read_current_outfits(p_user_id uuid,p_key text,p_generation_key text,p_anchor uuid default null,p_offset int default 0,p_limit int default 30)
returns jsonb language sql stable security definer set search_path=public as $$
 with matching as (
  select c.id,c.payload,c.core_item_ids from current_outfits c join outfit_refresh_requests s on s.user_id=c.user_id
  where c.user_id=p_user_id and s.projection_key=p_key and
   (p_anchor is null or c.core_item_ids @> array[p_anchor] or exists(select 1 from current_outfit_layers l where l.outfit_id=c.id and l.item_ids @> array[p_anchor]))
 ), personal as (
 select p.id,p.item_ids as core_item_ids,jsonb_build_object('id',p.id,'items',
  (select jsonb_agg(to_jsonb(i)-array['semantic_vector','feature_vector'] order by i.id) from clothing_items i where i.user_id=p_user_id and i.id=any(p.item_ids)),
  'optional_additions','[]'::jsonb,'aesthetic_score',null,'structural_reason','Saved by you','aesthetic_reason',p.title,
  'source','personal','visual_review_status','pending') as payload
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
