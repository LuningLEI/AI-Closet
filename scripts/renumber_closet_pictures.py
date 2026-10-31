"""Renumber local images without changing image bytes or historical evaluation workbooks."""
import csv
import hashlib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]/'closet_picture'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def natural(value):return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)',value)]

def main():
    files=[p for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in {'.jpg','.jpeg','.png','.heic','.webp'}]
    files.sort(key=lambda p:(0,int(p.stem[1:])) if re.fullmatch(r'I\d+',p.stem) else (1,natural(p.name)))
    old=json.loads((ROOT/'filename_mapping.json').read_text())['files']
    by_name={x['new_name']:x for x in old};by_hash=defaultdict(list)
    for x in old:
        if x.get('sha256'):by_hash[x['sha256']].append(x)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=ROOT/'.renaming_history'/stamp;backup.mkdir(parents=True)
    for name in ['filename_mapping.csv','filename_mapping.json','README.md']:
        if (ROOT/name).exists():shutil.copy2(ROOT/name,backup/name)
    rows=[];hash_groups=defaultdict(list)
    for i,p in enumerate(files,1):
        checksum=sha(p);entry=by_name.get(p.name)
        match=entry if entry and entry.get('sha256')==checksum else None
        candidates=by_hash[checksum]
        ids={x.get('item_id') for x in candidates if x.get('item_id')}
        item_id=match.get('item_id','') if match else next(iter(ids)) if len(ids)==1 else ''
        rows.append({'code':f'I{i:03d}','item_id':item_id,'previous_name':p.name,
                     'previous_code':entry['code'] if entry else '',
                     'original_name':entry.get('original_name',p.name) if entry else p.name,
                     'new_name':f'I{i:03d}{p.suffix.upper()}',
                     'sha256':checksum,'action':'renamed' if p.name!=f'I{i:03d}{p.suffix.upper()}' else 'unchanged',
                     'match_method':'Existing mapping + SHA256' if match else 'Unique historical item hash' if item_id else 'Unlinked; backend identity not verified',
                     'historical_matching_codes':[x['code'] for x in candidates],
                     'duplicate_of':'',
                     'temporary_name':f'.renumber-{uuid4().hex}{p.suffix}'})
        hash_groups[checksum].append(rows[-1])
    for group in hash_groups.values():
        for r in group[1:]:r['duplicate_of']=group[0]['code']
    plan={'status':'planned','mapping_version':stamp,'files':rows}
    (backup/'rename_plan.json').write_text(json.dumps(plan,indent=2))
    moved=[];finished=[]
    try:
        for row in rows:
            src=ROOT/row['previous_name'];tmp=ROOT/row['temporary_name']
            assert sha(src)==row['sha256']
            src.rename(tmp);moved.append(row)
        for row in rows:
            dest=ROOT/row['new_name']
            if dest.exists():raise FileExistsError(dest)
            (ROOT/row['temporary_name']).rename(dest);finished.append(row)
        for row in rows:assert sha(ROOT/row['new_name'])==row['sha256']
        assert {p.stem for p in ROOT.iterdir() if p.suffix.lower() in {'.jpg','.jpeg','.png','.heic','.webp'}}=={f'I{i:03d}' for i in range(1,len(rows)+1)}
    except BaseException:
        for row in finished:(ROOT/row['new_name']).rename(ROOT/row['temporary_name'])
        for row in moved:(ROOT/row['temporary_name']).rename(ROOT/row['previous_name'])
        raise
    for row in rows:row.pop('temporary_name')
    result={'status':'complete','mapping_version':stamp,'total_images':len(rows),'files':rows}
    (ROOT/'filename_mapping.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    with (ROOT/'filename_mapping.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader()
        for row in rows:writer.writerow({**row,'historical_matching_codes':' | '.join(row['historical_matching_codes'])})
    shutil.copy2(ROOT/'filename_mapping.csv',backup/'new_mapping.csv')
    (backup/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    (ROOT/'README.md').write_text(f'''# Local closet image numbering

Mapping version: {stamp}. {len(rows)} images continuously numbered I001–I{len(rows):03d}.
Existing numbered images were ordered numerically, then unnumbered images by natural filename order.
Image bytes are unchanged; exact duplicates are preserved and marked in duplicate_of.

These are LOCAL display codes, not database identity. Empty item_id means the backend association
has not been verified; it does not prove that a garment has never been uploaded.
Existing verified backend UUID associations are preserved using image checksums.

Historical evaluation workbooks and their manifests retain their ORIGINAL codes and were not edited.
Use previous_code / previous_name in filename_mapping.csv to translate old codes into this local version.
Never interpret old Excel item codes as current filenames without that translation.
Historical hash matches are listed separately; identical photographs can have different database items.

Previous mapping and a reversible rename journal are archived in .renaming_history/{stamp}/.
Future renumbering archives each version; chain mappings for older historical codes.
''')
    print(json.dumps({'images':len(rows),'linked':sum(bool(r['item_id']) for r in rows),'unlinked':sum(not r['item_id'] for r in rows),'duplicates_preserved':sum(bool(r['duplicate_of']) for r in rows),'backup':str(backup)},indent=2))

if __name__=='__main__':main()
