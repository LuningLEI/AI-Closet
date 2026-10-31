-- Run on a disposable database after migration 008. Every assertion rolls back.
begin;
do $$
declare u uuid:=gen_random_uuid(); other_user uuid:=gen_random_uuid();
 a uuid:=gen_random_uuid(); b uuid:=gen_random_uuid(); coat uuid:=gen_random_uuid();
 o uuid:=gen_random_uuid(); o2 uuid:=gen_random_uuid(); j uuid:=gen_random_uuid();
 ver bigint; before_ver bigint; e jsonb; r jsonb; rows jsonb; event jsonb; lease timestamptz:=now();
begin
 insert into auth.users(id) values(u),(other_user);
 insert into clothing_items(id,user_id,image_url,category) values(a,u,'a','Tops'),(b,u,'b','Bottoms'),(coat,u,'coat','Outerwear');
 e:=jsonb_build_object('id',a,'user_id',u,'color','Unknown');
 select source_version into before_ver from outfit_refresh_requests where user_id=u;
 event:=jsonb_build_object('id',gen_random_uuid(),'user_id',u,'clothing_item_id',a,'edit_session_id',gen_random_uuid(),
  'event_type','item_attributes_updated','source','ios','changed_fields',jsonb_build_array('color'),'changes','{}'::jsonb,'created_at',now());
 -- A failed audit insert rolls back the item and its outbox event.
 begin
  perform commit_item_change(e,'{"color":"Red"}',null,event||'{"event_type":null}');
  raise exception 'Expected audit constraint failure';
 exception when not_null_violation then null; end;
 assert (select color='Unknown' from clothing_items where id=a),'partial item commit';
 assert (select source_version=before_ver from outfit_refresh_requests where user_id=u),'partial outbox commit';
 r:=commit_item_change(e,'{"color":"Blue"}',null,event);
 assert r->>'color'='Blue';
 assert (select count(*)=1 from item_edit_events where clothing_item_id=a);
 assert commit_item_change(e,'{"color":"Pink"}') is null,'stale writer accepted';
 e:=e||'{"color":"Blue"}';
 -- A replaced worker lease cannot commit or complete a recognition job.
 insert into recognition_jobs(id,user_id,clothing_item_id,filename,image_url,status,attempts,leased_at)
 values(j,u,a,'photo','a','processing',2,lease);
 assert commit_item_change(e,'{"color":"Pink"}',null,null,null,
  jsonb_build_object('id',j,'attempts',1,'leased_at',lease)) is null,'stale lease accepted';
 r:=commit_item_change(e,'{"color":"Green"}',null,null,null,
  jsonb_build_object('id',j,'attempts',2,'leased_at',lease));
 assert r->>'color'='Green' and (select status='complete' from recognition_jobs where id=j);
 select source_version into ver from outfit_refresh_requests where user_id=u;
 rows:=jsonb_build_array(
  jsonb_build_object('id',o,'items',jsonb_build_array(jsonb_build_object('id',a),jsonb_build_object('id',b)),
   'optional_additions',jsonb_build_array(jsonb_build_object('id','layer1','items',jsonb_build_array(jsonb_build_object('id',coat))))),
  jsonb_build_object('id',o2,'items',jsonb_build_array(jsonb_build_object('id',b)),'optional_additions','[]'::jsonb));
 assert not publish_current_outfits(u,ver-1,'key',rows),'stale projection accepted';
 assert publish_current_outfits(u,ver,'key',rows);
 r:=read_current_outfits(u,'key','generation',null,0,1);
 assert (r->>'total')::int=2 and jsonb_array_length(r->'outfits')=1 and (r->>'next_offset')::int=1,'bad page';
 r:=read_current_outfits(u,'key','generation',coat,0,30);
 assert (r->>'total')::int=1 and jsonb_array_length(r->'outfits'->0->'optional_additions')=1,'bad anchor filter';
 assert (read_current_outfits(other_user,'key','generation')->>'total')::int=0,'cross-user read';
 assert (read_current_outfits(u,'new-key','generation')->>'total')::int=0,'stale config visible';
 update clothing_items set material='Wool' where id=coat;
 assert (read_current_outfits(u,'key','generation')->>'total')::int=1,'affected projection not invalidated';
 assert not publish_current_outfits(u,ver,'key',rows),'concurrent mutation lost';
 assert not has_function_privilege('authenticated','commit_item_change(jsonb,jsonb,jsonb,jsonb,jsonb,jsonb)','execute');
 raise notice '008 transaction, fencing, invalidation, pagination, ownership assertions passed';
end $$;
rollback;
