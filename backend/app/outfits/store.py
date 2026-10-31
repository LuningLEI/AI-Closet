from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from app.core.config import settings
from app.outfits.run_store import SupabaseRunStore, LocalRunStore


def now():
    return datetime.now(timezone.utc).isoformat()

class SupabaseOutfitStore(SupabaseRunStore):
    def __init__(self, client): self.client = client
    def rows(self, table, user_id=None):
        rows = []
        for offset in range(0, 10000000, 500):
            query = self.client.table(table).select('*').order('created_at').order('user_id' if table == 'outfit_libraries' else 'id')
            if user_id is not None: query = query.eq('user_id', user_id)
            batch = query.range(offset, offset+499).execute().data or []
            rows.extend(batch)
            if len(batch) < 500: return rows
        raise RuntimeError('Outfit listing exceeded safe pagination limit')
    def users(self):
        users=[]
        while True:
            batch=self.client.table('outfit_refresh_requests').select('user_id').order('user_id').range(len(users),len(users)+499).execute().data or []
            users.extend(r['user_id'] for r in batch)
            if len(batch)<500:return users

    def projection_state(self, uid):
        self.client.table('outfit_refresh_requests').upsert({'user_id':uid},on_conflict='user_id',ignore_duplicates=True).execute()
        return self.client.table('outfit_refresh_requests').select('*').eq('user_id',uid).single().execute().data

    def publish_projection(self, uid, version, key, rows):
        return self.client.rpc('publish_current_outfits',{'p_user_id':uid,'p_version':version,'p_key':key,'p_rows':rows}).execute().data

    def projected_page(self, uid, key, generation_key, anchor, offset, limit):
        return self.client.rpc('read_current_outfits',{'p_user_id':uid,'p_key':key,'p_generation_key':generation_key,
            'p_anchor':anchor,'p_offset':offset,'p_limit':limit}).execute().data

    def enrolled(self, uid):
        return bool(self.client.table('outfit_libraries').select('user_id').eq('user_id',uid).execute().data)
    def enroll(self, uid):
        self.client.table('outfit_libraries').upsert({'user_id':uid}, on_conflict='user_id', ignore_duplicates=True).execute()
    def jobs(self, uid): return self.rows('outfit_build_jobs',uid)
    def enqueue(self, job):
        self.client.table('outfit_build_jobs').upsert(job,on_conflict='id',ignore_duplicates=True).execute()
    def retry(self, uid):
        self.client.table('outfit_build_jobs').update({'status':'queued','attempts':0,'error':None,'retry_at':now()}).eq('user_id',uid).eq('status','failed').execute()
    def claim(self, config):
        result=self.client.rpc('claim_outfit_job',{'p_max_attempts':config.max_attempts,'p_lease_seconds':config.lease_seconds}).execute().data
        return result[0] if result else None
    def finish(self, job, status, stats=None, error=None):
        values={'status':status,'stats':stats or {},'error':error,'lease_until':None,'retry_at':(datetime.now(timezone.utc)+timedelta(seconds=30*job['attempts'])).isoformat()}
        self.client.table('outfit_build_jobs').update(values).eq('id',job['id']).eq('status','processing').eq('lease_token',job['lease_token']).execute()
    def evaluations(self, uid):
        rows=self.rows('outfits',uid)
        ids={r.get('payload',{}).get('run_id') for r in rows}-{None}
        configs={}
        ids=list(ids)
        for start in range(0,len(ids),100):
            for r in self.client.table('outfit_runs').select('id,config').in_('id',ids[start:start+100]).execute().data or []:configs[r['id']]=r['config']
        for row in rows:
            if row['payload'].get('run_id') in configs:row['payload']['config']=configs[row['payload']['run_id']]
        return rows
    def save_checked(self, record, job, items):
        from app.repositories.item_transactions import expected_item
        return self.client.rpc('save_outfit_evaluation_checked',{'p_record':record,
            'p_item_ids':record['payload']['item_ids'],'p_job':job,
            'p_expected_items':[expected_item(item) for item in items]}).execute().data

    def save(self, record):
        self.client.rpc('save_outfit_evaluation',{'p_record':record,'p_item_ids':record['payload']['item_ids']}).execute()

class LocalOutfitStore(LocalRunStore):
    """SQLite provides durable dedupe and atomic claims across local API/worker processes."""
    def __init__(self, path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            self.init_runs(db)
            db.execute('create table if not exists libraries (user_id text primary key)')
            db.execute('create table if not exists jobs (id text primary key,user_id text not null,data text not null)')
            db.execute('create table if not exists outfits (id text primary key,user_id text not null,data text not null)')
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            db.execute('begin immediate')
            yield db
            db.commit()
        except Exception:
            db.rollback();raise
        finally:db.close()
    def users(self):
        with self.db() as db:return [r[0] for r in db.execute('select user_id from libraries')]
    def enrolled(self, uid): return uid in self.users()
    def enroll(self, uid):
        with self.db() as db:db.execute('insert or ignore into libraries values (?)',(uid,))
    def jobs(self, uid):
        with self.db() as db:return [json.loads(r[0]) for r in db.execute('select data from jobs where user_id=?',(uid,))]
    def enqueue(self, job):
        row={'created_at':now(),'status':'queued','attempts':0,'retry_at':now(),**job}
        with self.db() as db:db.execute('insert or ignore into jobs values (?,?,?)',(job['id'],job['user_id'],json.dumps(row)))
    def retry(self, uid):
        with self.db() as db:
            for row in db.execute('select data from jobs where user_id=?',(uid,)).fetchall():
                job=json.loads(row[0])
                if job['status']=='failed':
                    job.update(status='queued',attempts=0,error=None,retry_at=now())
                    db.execute('update jobs set data=? where id=?',(json.dumps(job),job['id']))
    def claim(self, config):
        with self.db() as db:
            jobs=[json.loads(r[0]) for r in db.execute('select data from jobs')]
            for job in sorted(jobs,key=lambda j:j['created_at']):
                expired=job['status']=='processing' and job.get('lease_until','')<now()
                if expired and job['attempts']>=config.max_attempts:
                    job.update(status='failed',error='Worker lease expired; retry limit reached')
                    db.execute('update jobs set data=? where id=?',(json.dumps(job),job['id']))
                    continue
                if (job['status']=='queued' and job['retry_at']<=now() or expired) and job['attempts']<config.max_attempts:
                    job.update(status='processing',attempts=job['attempts']+1,lease_token=str(uuid4()),lease_until=(datetime.now(timezone.utc)+timedelta(seconds=config.lease_seconds)).isoformat())
                    db.execute('update jobs set data=? where id=?',(json.dumps(job),job['id']))
                    return job
        return None
    def finish(self, job, status, stats=None, error=None):
        with self.db() as db:
            data=db.execute('select data from jobs where id=?',(job['id'],)).fetchone()
            if not data:return
            row=json.loads(data[0])
            if row.get('lease_token')!=job['lease_token'] or row['status']!='processing':return
            row.update(status=status,stats=stats or {},error=error,lease_until=None,retry_at=(datetime.now(timezone.utc)+timedelta(seconds=30*job['attempts'])).isoformat())
            db.execute('update jobs set data=? where id=?',(json.dumps(row),job['id']))
    def evaluations(self, uid):
        with self.db() as db:
            rows=[json.loads(r[0]) for r in db.execute('select data from outfits where user_id=?',(uid,))]
            configs={r[0]:json.loads(r[1])['config'] for r in db.execute('select id,data from outfit_runs where user_id=?',(uid,))}
            for row in rows:
                if row['payload'].get('run_id') in configs:row['payload']['config']=configs[row['payload']['run_id']]
            return rows
    def save(self, record):
        with self.db() as db:db.execute('insert or ignore into outfits values (?,?,?)',(record['id'],record['user_id'],json.dumps(record)))

def build_store(repository):
    if hasattr(repository,'client'):return SupabaseOutfitStore(repository.client)
    return LocalOutfitStore(settings.data_dir/'outfit_library.sqlite3')
