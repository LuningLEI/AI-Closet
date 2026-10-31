"""Read-only versioned outfit export; optional watcher never starts model jobs."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from openpyxl import Workbook
from app.outfits.config import OutfitConfig, digest
from app.outfits.store import build_store
from app.repositories.factory import build_closet_repository


def origin_key(row):
    recorded = row['payload'].get('generation_key')
    if recorded:
        return recorded
    values = row['payload'].get('config', {})
    try:
        return OutfitConfig.model_validate(values).generation_key
    except (ValueError, TypeError):
        return 'unknown'


def write_sheet(book, name, headers, rows):
    sheet = book.create_sheet(name)
    sheet.append(headers)
    for row in rows:
        sheet.append([json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in row])
    # Model/user text must never become spreadsheet formulas.
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(60, max(18, len(str(column[0].value)) + 3))
    return sheet


def export_snapshot(repo, store, uid, generation_key, evaluator_key, destination, final=False):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    jobs = [{k:v for k,v in j.items() if k != 'lease_token'} for j in store.jobs(uid) if j['generation_key'] == generation_key]
    if not jobs:
        raise ValueError('No jobs found for the requested user and generation version')
    records = [r for r in store.evaluations(uid) if r['evaluator_key'] == evaluator_key]
    counts = dict(Counter(j['status'] for j in jobs))
    if final and (counts.get('queued', 0) or counts.get('processing', 0)):
        raise ValueError('Target version still has pending work')
    ids = {i for r in records for i in r['payload']['item_ids']}
    fields = ['id','category','subtype','color','style','occasion','season','material','pattern',
              'fit','length','sleeve_length','layering_role','warmth_level','formality_score','image_path']
    items = [{k:getattr(i,k,None) for k in fields} for i in repo.list_items_for_outfits(uid) if i.user_id == uid and i.id in ids]
    stamp = datetime.now(timezone.utc).isoformat()
    metadata = {'exported_at_utc':stamp, 'user_id':uid, 'generation_key':generation_key,
                'evaluator_key':evaluator_key, 'queue_drained':not(counts.get('queued',0) or counts.get('processing',0)),
                'final':final, 'job_counts':counts, 'stored_variant_count':len(records),
                'scope':'All retained variants for this evaluator; generation origin is reported separately. Cached results can originate in earlier generation passes.',
                'limitations':'Not raw proposals: invalid proposals discarded before evaluation cannot be recovered. Current item metadata is not historical metadata. Jobs have no exact per-result linkage. Counts are full variants, not UI base outfit totals. Reads are sequential, not a database transaction.'}
    payload = {'metadata':metadata,'jobs':jobs,'items':items,'records':records}
    raw_path = destination/'snapshot.json'
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    book = Workbook();book.remove(book.active)
    write_sheet(book,'Summary',['Field','Value'],list(metadata.items()))
    configs = {}
    outfit_rows = []
    for r in sorted(records,key=lambda x:(x['signature'],x['id'])):
        p=r['payload'];e=p['evaluation'];config=p.get('config',{});config_id=digest(config)
        configs[config_id]=config
        origin=origin_key(r)
        outfit_rows.append([r['id'],r['signature'],p['item_ids'],len(p['item_ids']),p.get('evaluated_at'),
            e.get('structurally_wearable'),e.get('aesthetic_score'),e.get('structural_reason'),e.get('aesthetic_reason'),e.get('issues'),
            p.get('generation_reason'),p.get('anchor_item_id'),origin,origin==generation_key,r['revision'],p.get('item_revisions'),
            config_id,config.get('generation_model'),config.get('evaluation_model'),config.get('image_detail'),
            config.get('evaluation_filter_enabled'),config.get('aesthetic_threshold'),p.get('generation_usage'),p.get('evaluation_usage'),p.get('visual_review')])
    write_sheet(book,'Outfit evaluations',['Record ID','Full combination signature','Item IDs','Piece count','Evaluated at UTC',
        'Structurally wearable','Aesthetic score (1-5)','Structural reason','Aesthetic reason','Issues','Generation reason',
        'Origin anchor ID','Origin generation key','Origin matches target','Member revision hash','Item revisions','Config ID',
        'Generation model','Evaluation model','Image detail','Legacy score filter enabled','Legacy score threshold',
        'Generation usage (shared per anchor; do not sum)','Evaluation usage','Visual review'],outfit_rows)
    write_sheet(book,'Current items',fields,[[i[k] for k in fields] for i in items])
    write_sheet(book,'Jobs',['ID','Anchor item ID','Status','Attempts','Created at','Retry at','Stats','Error'],
        [[j.get(k) for k in ['id','anchor_item_id','status','attempts','created_at','retry_at','stats','error']] for j in jobs])
    write_sheet(book,'Configurations',['Config ID','Configuration JSON'],list(configs.items()))
    book.save(destination/'outfit_baseline.xlsx')
    (destination/'README.md').write_text(
        '# Outfit baseline export\n\n'+metadata['scope']+'\n\n'+metadata['limitations']+
        '\n\nScores and reasons are original saved model outputs, including low scores and rejections. Null scores remain blank, never zero. '+
        'Configuration JSON includes full prompts. Use sorted item IDs to match full combinations across versions. '+
        'Use member revisions to distinguish changed garments. Do not sum repeated generation usage across outfits. '+
        'Failed or obsolete jobs are disclosed and are not successful completions. No image downloads, model calls or database writes are performed.\n')
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id',required=True)
    parser.add_argument('--generation-key',required=True)
    parser.add_argument('--evaluator-key',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--poll-seconds',type=int,default=30)
    args=parser.parse_args()
    if args.poll_seconds < 5:parser.error('poll-seconds must be at least 5')
    repo=build_closet_repository();store=build_store(repo)
    result=export_snapshot(repo,store,args.user_id,args.generation_key,args.evaluator_key,args.out/'initial')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if not args.watch:return
    stable=0
    while True:
        try:
            jobs=[j for j in store.jobs(args.user_id) if j['generation_key']==args.generation_key]
            counts=dict(Counter(j['status'] for j in jobs))
            pending=counts.get('queued',0)+counts.get('processing',0)
            print(json.dumps({'job_counts':counts,'pending':pending}),flush=True)
            stable=stable+1 if jobs and not pending else 0
            if stable>=2:
                result=export_snapshot(repo,store,args.user_id,args.generation_key,args.evaluator_key,args.out/'final',final=True)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                return
        except Exception as error:
            stable=0
            print(f'Export watcher will retry: {type(error).__name__}',flush=True)
        time.sleep(args.poll_seconds)


if __name__=='__main__':main()
