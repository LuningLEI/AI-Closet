begin;
insert into auth.users(id) values ('00000000-0000-4000-8000-000000000012'),('00000000-0000-4000-8000-000000000013');
insert into clothing_items(id,user_id,image_url,category) values
 ('10000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000012','x','Tops'),
 ('20000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000012','y','Bottoms');
select save_personal_outfit('30000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000012',array['10000000-0000-4000-8000-000000000012','20000000-0000-4000-8000-000000000012']::uuid[],'Mine');
select save_personal_outfit('30000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000012',array['10000000-0000-4000-8000-000000000012','20000000-0000-4000-8000-000000000012']::uuid[],'Mine');
do $$declare result jsonb; begin
 result:=read_current_outfits('00000000-0000-4000-8000-000000000012','unbuilt','unbuilt','10000000-0000-4000-8000-000000000012',0,30);
 assert (result->>'total')::int=1,'Personal outfit must appear before any worker build';
 assert result->'outfits'->0->>'source'='personal';
 assert jsonb_array_length(result->'outfits'->0->'items')=2;
 result:=read_current_outfits('00000000-0000-4000-8000-000000000013','unbuilt','unbuilt',null,0,30);
 assert (result->>'total')::int=0,'No cross-account outfits';
 begin
  perform save_personal_outfit('40000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000013',array['10000000-0000-4000-8000-000000000012']::uuid[],'foreign');
  raise exception 'Foreign item was accepted' using errcode='ZX001';
 exception when raise_exception then null; end;
end $$;
select record_outfit_wear('50000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000012',array['10000000-0000-4000-8000-000000000012']::uuid[],'2026-01-01T00:00:00Z');
select record_outfit_wear('50000000-0000-4000-8000-000000000012','00000000-0000-4000-8000-000000000012',array['10000000-0000-4000-8000-000000000012']::uuid[],'2026-01-01T00:00:00Z');
do $$begin assert (select count(*) from outfit_wear_events where user_id='00000000-0000-4000-8000-000000000012')=1;end $$;
delete from clothing_items where id='10000000-0000-4000-8000-000000000012';
do $$declare result jsonb;begin
 result:=read_current_outfits('00000000-0000-4000-8000-000000000012','unbuilt','unbuilt',null,0,30);
 assert (result->>'total')::int=0,'Deleted members must hide personal outfits';
 assert (select count(*) from outfit_wear_events where user_id='00000000-0000-4000-8000-000000000012')=1,'Retain wear history';
end $$;
rollback;
