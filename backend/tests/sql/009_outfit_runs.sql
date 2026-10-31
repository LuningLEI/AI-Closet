-- Isolated integration assertions, run after 007/008/009; leaves no application data.
begin;
do $$
declare u uuid:=gen_random_uuid(); a uuid:=gen_random_uuid(); b uuid:=gen_random_uuid(); rid uuid:=gen_random_uuid();
 oid uuid:=gen_random_uuid(); visible uuid:=gen_random_uuid(); cid uuid:=gen_random_uuid(); manifest jsonb; jobs jsonb;
 job outfit_build_jobs; checks jsonb; record jsonb; report jsonb; version bigint;
begin
 insert into auth.users(id) values(u);
 insert into clothing_items(id,user_id,image_url,category) values(a,u,'a','Tops'),(b,u,'b','Bottoms');
 manifest:=jsonb_build_object('id',rid,'user_id',u,'algorithm','vision_then_visual','generation_key','gen','evaluator_key','eval',
 'generation_model','model','evaluation_model','model','generation_prompt_hash','gp','evaluation_prompt_hash','ep','config','{"pricing":{}}'::jsonb);
 jobs:=jsonb_build_array(jsonb_build_object('id',rid::text,'user_id',u,'anchor_item_id',a,'revision','rev','generation_key','gen'));
 assert enqueue_outfit_run(manifest,jobs)=1;
 assert enqueue_outfit_run(manifest,jobs)=0,'duplicate jobs/run';
 assert (select count(*)=1 from outfit_runs where user_id=u);
 begin
  update outfit_runs set algorithm='changed' where id=rid;
  raise exception 'Mutable run manifest';
 exception when raise_exception then if SQLERRM='Mutable run manifest' then raise; end if; end;
 select * into job from claim_outfit_job(3,1800);
 assert job.run_id=rid;
 insert into outfit_model_calls(id,run_id,job_id,user_id,attempt,lease_token,stage,model,status)
 values(cid,rid,job.id,u,job.attempts,job.lease_token,'generation','model','running');
 update outfit_model_calls set status='succeeded',input_tokens=100,output_tokens=20,estimated_cost_usd=0.001,raw_usage='{"input_tokens":100}',finished_at=now()-interval '200 days' where id=cid;
 checks:='{"wearability":{"verdict":"pass"},"thermal":{"verdict":"pass"},"color_pattern":{"verdict":"pass"},"occasion":{"verdict":"pass"}}';
 record:=jsonb_build_object('id',oid,'user_id',u,'signature','sig','revision','rev','evaluator_key','eval',
  'payload',jsonb_build_object('run_id',rid,'item_ids',jsonb_build_array(a,b),'visual_review',jsonb_build_object('core',checks,'full',checks)));
 perform save_outfit_evaluation(record,array[a,b]);
 perform link_outfit_run_result(rid,oid,false);
 perform link_outfit_run_result(rid,oid,true);
 assert (select core_review_status='passed' and full_review_status='passed' and run_id=rid from outfits where id=oid);
 assert (select not cached from outfit_run_results where run_id=rid),'cache overwrote generation provenance';
 select to_jsonb(s) into report from outfit_run_summary s where id=rid;
 assert (report->>'call_count')::int=1 and (report->>'unique_results')::int=1;
 assert (report->>'estimated_cost_usd')::numeric=0.001,'cost counted per outfit instead of per call';
 select source_version into version from outfit_refresh_requests where user_id=u;
 assert publish_current_outfits(u,version,'key',jsonb_build_array(jsonb_build_object('id',visible,'items',jsonb_build_array(jsonb_build_object('id',a),jsonb_build_object('id',b)),
  'optional_additions','[]'::jsonb,'source_evaluation_ids',jsonb_build_array(oid),'visual_review_status','passed')));
 assert (select is_current from outfit_evaluation_index where id=oid),'missing current provenance';
 update clothing_items set color='Blue' where id=a;
 assert not (select is_current from outfit_evaluation_index where id=oid),'stale current flag';
 update outfit_build_jobs set status='complete',lease_until=null where id=job.id;
 assert compact_outfit_usage(u,false)=1;
 assert (select raw_usage is not null from outfit_model_calls where id=cid),'preview mutated data';
 update outfit_runs set pinned=true,pin_reason='Evaluation dataset' where id=rid;
 assert compact_outfit_usage(u,true)=0,'pinned experiment compacted';
 update outfit_runs set pinned=false where id=rid;
 assert compact_outfit_usage(u,true)=1;
 assert (select raw_usage is null and input_tokens=100 and estimated_cost_usd=0.001 from outfit_model_calls where id=cid),'lost accounting counters';
 assert (select count(*)=1 from outfits where id=oid),'deleted audit history';
 assert not has_function_privilege('authenticated','enqueue_outfit_run(jsonb,jsonb)','execute');
 raise notice '009 batch dedup, immutable manifests, accounting, statuses, currentness and retention assertions passed';
end $$;
rollback;
