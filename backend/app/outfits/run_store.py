"""Run persistence adapters. Historical rows without run_id remain readable."""
import json
from collections import Counter
from decimal import Decimal
from datetime import datetime, timezone


def timestamp():return datetime.now(timezone.utc).isoformat()


class SupabaseRunStore:
    def enqueue_run(self, run, jobs):
        return self.client.rpc('enqueue_outfit_run',{'p_run':run,'p_jobs':jobs}).execute().data

    def ensure_job_run(self, job, manifest):
        return self.client.rpc('attach_outfit_job_run',{'p_job_id':job['id'],'p_run':manifest}).execute().data

    def start_call(self, call):self.client.table('outfit_model_calls').insert(call).execute()
    def finish_call(self, cid, changes):
        self.client.table('outfit_model_calls').update(changes).eq('id',cid).in_('status',['running','unknown']).execute()
    def link_result(self, run_id, record_id, cached):
        self.client.rpc('link_outfit_run_result',{'p_run':run_id,'p_outfit':record_id,'p_cached':cached}).execute()
    def recover_calls(self):self.client.rpc('recover_outfit_calls',{}).execute()
    def pin_run(self, uid, rid, reason):
        return bool(self.client.table('outfit_runs').update({'pinned':True,'pin_reason':reason}).eq('user_id',uid).eq('id',rid).execute().data)
    def compact_usage(self, uid, apply=False):
        return self.client.rpc('compact_outfit_usage',{'p_user':uid,'p_apply':apply}).execute().data
    def run_report(self, uid):
        rows=[]
        while True:
            page=self.client.table('outfit_run_summary').select('*').eq('user_id',uid).order('created_at',desc=True).order('id').range(len(rows),len(rows)+499).execute().data or []
            rows.extend(page)
            if len(page)<500:return rows


class LocalRunStore:
    def init_runs(self, db):
        db.execute('create table if not exists outfit_runs(id text primary key,user_id text not null,data text not null)')
        db.execute('create table if not exists outfit_model_calls(id text primary key,run_id text not null,data text not null)')
        db.execute('create table if not exists outfit_run_results(run_id text not null,outfit_id text not null,cached integer not null,primary key(run_id,outfit_id))')
        db.execute('create index if not exists local_call_run on outfit_model_calls(run_id)')
    def enqueue_run(self, run, jobs):
        with self.db() as db:
            fresh=[j for j in jobs if not db.execute('select 1 from jobs where id=?',(j['id'],)).fetchone()]
            if not fresh:return 0
            row={'created_at':timestamp(),**run}
            db.execute('insert or ignore into outfit_runs values (?,?,?)',(row['id'],row['user_id'],json.dumps(row)))
            for j in fresh:
                j={'created_at':timestamp(),'status':'queued','attempts':0,'retry_at':timestamp(),**j,'run_id':run['id']}
                db.execute('insert into jobs values (?,?,?)',(j['id'],j['user_id'],json.dumps(j)))
            return len(fresh)
    def ensure_job_run(self, job, manifest):
        with self.db() as db:
            current=json.loads(db.execute('select data from jobs where id=?',(job['id'],)).fetchone()[0])
            rid=current.get('run_id')
            if not rid:
                rid=manifest['id'];current['run_id']=rid
                manifest={'created_at':timestamp(),**manifest}
                db.execute('insert or ignore into outfit_runs values (?,?,?)',(rid,job['user_id'],json.dumps(manifest)))
                db.execute('update jobs set data=? where id=?',(json.dumps(current),job['id']))
            return json.loads(db.execute('select data from outfit_runs where id=?',(rid,)).fetchone()[0])
    def start_call(self, call):
        with self.db() as db:db.execute('insert into outfit_model_calls values (?,?,?)',(call['id'],call['run_id'],json.dumps({'created_at':timestamp(),**call})))
    def finish_call(self, cid, changes):
        with self.db() as db:
            row=json.loads(db.execute('select data from outfit_model_calls where id=?',(cid,)).fetchone()[0])
            if row['status'] in {'running','unknown'}:
                row.update(changes);db.execute('update outfit_model_calls set data=? where id=?',(json.dumps(row),cid))
    def link_result(self, run_id, record_id, cached):
        with self.db() as db:db.execute('insert into outfit_run_results values (?,?,?) on conflict(run_id,outfit_id) do update set cached=min(cached,excluded.cached)',(run_id,record_id,int(cached)))
    def recover_calls(self):
        with self.db() as db:
            for cid,raw in db.execute('select id,data from outfit_model_calls').fetchall():
                call=json.loads(raw)
                if call['status']!='running':continue
                data=db.execute('select data from jobs where id=?',(call['job_id'],)).fetchone()
                job=json.loads(data[0]) if data else {}
                if job.get('status')!='processing' or job.get('lease_token')!=call.get('lease_token') or (job.get('lease_until') or '')<timestamp():
                    call.update(status='unknown',error_type='WorkerInterrupted',finished_at=timestamp())
                    db.execute('update outfit_model_calls set data=? where id=?',(json.dumps(call),cid))
    def pin_run(self, uid, rid, reason):
        with self.db() as db:
            row=db.execute('select data from outfit_runs where id=? and user_id=?',(rid,uid)).fetchone()
            if not row:return False
            run=json.loads(row[0]);run.update(pinned=True,pin_reason=reason)
            db.execute('update outfit_runs set data=? where id=?',(json.dumps(run),rid));return True
    def compact_usage(self, uid, apply=False):
        from datetime import timedelta
        cutoff=(datetime.now(timezone.utc)-timedelta(days=180)).isoformat()
        with self.db() as db:
            runs={rid:json.loads(data) for rid,data in db.execute('select id,data from outfit_runs where user_id=?',(uid,))}
            active={json.loads(r[0]).get('run_id') for r in db.execute('select data from jobs') if json.loads(r[0])['status'] in {'queued','processing'}}
            affected=0
            for cid,raw in db.execute('select id,data from outfit_model_calls').fetchall():
                c=json.loads(raw);r=runs.get(c['run_id'])
                if r and not r['pinned'] and r['id'] not in active and c['status']!='running' and c.get('finished_at','9999')<cutoff and c.get('raw_usage') is not None:
                    affected+=1
                    if apply:
                        c.update(raw_usage=None,compacted_at=timestamp());db.execute('update outfit_model_calls set data=? where id=?',(json.dumps(c),cid))
            return affected
    def run_report(self, uid):
        with self.db() as db:
            runs=[json.loads(r[0]) for r in db.execute('select data from outfit_runs where user_id=?',(uid,))]
            jobs=[json.loads(r[0]) for r in db.execute('select data from jobs where user_id=?',(uid,))]
            for run in runs:
                counts=Counter(j['status'] for j in jobs if j.get('run_id')==run['id'])
                calls=[json.loads(r[0]) for r in db.execute('select data from outfit_model_calls where run_id=?',(run['id'],))]
                run['job_counts']=dict(counts);run['total_jobs']=sum(counts.values())
                run['status']='running' if counts['processing'] else 'queued' if counts['queued'] else 'failed' if counts['failed'] else 'complete'
                run['call_count']=len(calls);run['unknown_cost_calls']=sum(c.get('estimated_cost_usd') is None for c in calls)
                run['known_estimated_cost_usd']=str(sum((Decimal(c['estimated_cost_usd']) for c in calls if c.get('estimated_cost_usd') is not None),Decimal(0)))
                run['estimated_cost_usd']=run['known_estimated_cost_usd'] if run['unknown_cost_calls']==0 else None
                run['input_tokens']=sum(c.get('input_tokens') or 0 for c in calls);run['output_tokens']=sum(c.get('output_tokens') or 0 for c in calls)
                run['unique_results']=db.execute('select count(*) from outfit_run_results where run_id=?',(run['id'],)).fetchone()[0]
            return runs
