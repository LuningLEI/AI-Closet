-- Isolated regression, after migrations. Roll back fixture data.
begin;
do $$
declare u uuid:=gen_random_uuid(); a uuid:=gen_random_uuid(); rid uuid:=gen_random_uuid();
 cid uuid:=gen_random_uuid(); pending uuid:=gen_random_uuid(); job outfit_build_jobs; manifest jsonb;
begin
 insert into auth.users(id) values(u);
 insert into clothing_items(id,user_id,image_url,category) values(a,u,'test-image','Tops');
 manifest:=jsonb_build_object('id',rid,'user_id',u,'algorithm','test','generation_key','gen','evaluator_key','eval',
 'generation_model','test','evaluation_model','test','generation_prompt_hash','gp','evaluation_prompt_hash','ep','config','{}'::jsonb);
 perform enqueue_outfit_run(manifest,jsonb_build_array(jsonb_build_object('id',rid::text,'user_id',u,'anchor_item_id',a,'revision','rev','generation_key','gen')));
 update outfit_build_jobs set status='processing',attempts=1,lease_token=gen_random_uuid(),lease_until=now()+interval '1 hour'
 where id=rid::text returning * into job;
 insert into outfit_model_calls(id,run_id,job_id,user_id,attempt,lease_token,stage,model,status)
 values(cid,rid,job.id,u,1,job.lease_token,'generation','test','running'),
 (pending,rid,job.id,u,1,job.lease_token,'evaluation','test','running');
 update outfit_model_calls set status='succeeded',input_tokens=100,estimated_cost_usd=0.01 where id=cid;
 delete from clothing_items where id=a and user_id=u;
 assert not exists(select 1 from outfit_build_jobs where id=job.id),'job did not cascade';
 assert (select job_id is null and status='succeeded' and input_tokens=100 and estimated_cost_usd=0.01 from outfit_model_calls where id=cid),'lost call accounting';
 assert (select job_id is null from outfit_model_calls where id=pending),'pending call blocks deletion';
 perform recover_outfit_calls();
 assert (select status='unknown' and error_type='WorkerInterrupted' from outfit_model_calls where id=pending),'detached call not recovered';
 -- A detached call must not authorize a NEW paid call.
 begin
  insert into outfit_model_calls(id,run_id,job_id,user_id,attempt,stage,model,status)
  values(gen_random_uuid(),rid,null,u,1,'generation','test','running');
  raise exception 'Detached insert allowed';
 exception when raise_exception then
  if SQLERRM='Detached insert allowed' then raise; end if;
 end;
end $$;
rollback;
