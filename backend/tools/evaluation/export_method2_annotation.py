"""Watch a fixed outfit generation version and append two annotation sheets, read-only on DB."""
import argparse
from collections import Counter
from copy import copy, deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time
from types import SimpleNamespace

import httpx
from PIL import Image as PILImage, ImageOps
from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.formula.translate import Translator
from openpyxl.utils.units import pixels_to_EMU

from app.outfits.config import load_config
from app.outfits.service import OutfitLibrary, record_revision_matches, signature
from app.outfits.compatibility import core_items
from app.outfits.store import build_store
from app.repositories.factory import build_closet_repository
from app.services.storage_service import StorageService

NAMES = ('Method 2 Outfits', 'Method 2 Evaluation')


def dump(path, data):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str))
    temp.replace(path)


def capture(repo, store, uid, config, directory):
    items=repo.list_items_for_outfits(uid)
    records=store.evaluations(uid)
    jobs=store.jobs(uid)
    frozen_repo=SimpleNamespace(list_items_for_outfits=lambda _:items)
    frozen_store=SimpleNamespace(evaluations=lambda _:records, jobs=lambda _:jobs,enrolled=lambda _:True)
    signer=SimpleNamespace(items=lambda values,_:values)
    result=OutfitLibrary(frozen_repo,frozen_store,config).list(uid,signer,'',limit=1000000)
    # Select the same latest core review used by the frontend, not a score from another outfit.
    by_id={i.id:i for i in items}
    reviews={}
    for rec in sorted(records,key=lambda r:r['payload'].get('evaluated_at','')):
        p=rec['payload']
        if rec['evaluator_key']!=config.evaluator_key or not p.get('visual_review'):continue
        if any(i not in by_id or not record_revision_matches(p,by_id[i]) for i in p['item_ids']):continue
        reviews[signature(core_items([by_id[i] for i in p['item_ids']]))]=rec
    outfits=[]
    for outfit in result.outfits:
        value=outfit.model_dump(mode='json')
        value['review_record']=reviews.get(signature(outfit.items))
        outfits.append(value)
    data={'captured_at':datetime.now(timezone.utc).isoformat(),'user_id':uid,'config':config.snapshot(),
          'generation_key':config.generation_key,'evaluator_key':config.evaluator_key,
          'job_counts':dict(Counter(j['status'] for j in jobs if j['generation_key']==config.generation_key)),
          'outfits':outfits,'records':records,'jobs':jobs}
    dump(directory/'snapshot.json',data)
    return data


def prepare_images(data, directory):
    cache=directory/'images';cache.mkdir(exist_ok=True)
    storage=StorageService();paths={}
    for outfit in data['outfits']:
        for item in outfit['items']:
            path=item['image_path']
            if path in paths:continue
            target=cache/(hashlib.sha256(path.encode()).hexdigest()+'.img')
            if not target.exists():
                url=storage.signed_image_url(path)
                if not url:raise RuntimeError('Image signing failed; export will retry')
                if url.startswith('/'):
                    content=(storage.uploads_dir/Path(path).name).read_bytes()
                else:
                    response=httpx.get(url,timeout=60,follow_redirects=True);response.raise_for_status();content=response.content
                target.write_bytes(content)
            # Validate before changing the workbook; failures never produce silent blank previews.
            Image(target)
            preview=target.with_suffix('.preview.jpg')
            if not preview.exists():
                with PILImage.open(target) as original:
                    thumb=ImageOps.exif_transpose(original).convert('RGB')
                    thumb.thumbnail((480,640))
                    thumb.save(preview,format='JPEG',quality=85)
            paths[path]=preview
    return paths


def fresh_sheet(book, source, name, count):
    sheet=book.copy_worksheet(book[source]);sheet.title=name;sheet.sheet_state='visible'
    sheet.data_validations=deepcopy(book[source].data_validations)
    sheet.conditional_formatting=deepcopy(book[source].conditional_formatting)
    prototypes=[copy(c) for c in sheet[5]]
    for row in sheet.iter_rows(min_row=5):
        for cell in row:cell.value=None
    if sheet.max_row>4:sheet.delete_rows(5,sheet.max_row-4)
    for r in range(5,count+5):
        sheet.row_dimensions[r].height=book[source].row_dimensions[5].height
        for c,proto in enumerate(prototypes,1):
            cell=sheet.cell(r,c);cell._style=copy(proto._style)
            if proto.data_type=='f':
                cell.value=Translator(proto.value,origin=proto.coordinate).translate_formula(cell.coordinate).replace("'Outfit Annotation'!",f"'{NAMES[0]}'!")
    last=max(5,count+4)
    sheet.auto_filter.ref=f'A4:{sheet.cell(4,sheet.max_column).column_letter}{last}'
    sheet.print_area=f'A1:{sheet.cell(4,sheet.max_column).column_letter}{last}'
    for dv in sheet.data_validations.dataValidation:
        dv.sqref=' '.join(f'{x.min_col and sheet.cell(1,x.min_col).column_letter}5:{sheet.cell(1,x.max_col).column_letter}{last}' for x in list(dv.sqref.ranges))
    # Extend conditional formatting beyond the old V1 row count.
    old_rules=list(sheet.conditional_formatting._cf_rules.items());sheet.conditional_formatting._cf_rules.clear()
    for cf,rules in old_rules:
        for area in cf.sqref.ranges:
            for rule in rules:sheet.conditional_formatting.add(f'{sheet.cell(1,area.min_col).column_letter}5:{sheet.cell(1,area.max_col).column_letter}{last}',rule)
    return sheet


def append_workbook(workbook, data, image_paths, directory):
    if workbook.with_name('~$'+workbook.name).exists():
        raise RuntimeError('Close Excel workbook before automatic append')
    before=hashlib.sha256(workbook.read_bytes()).hexdigest()
    book=load_workbook(workbook)
    if any(name in book.sheetnames for name in NAMES):
        raise FileExistsError('Method 2 sheets already exist; refusing to overwrite annotations')
    count=len(data['outfits'])
    main=fresh_sheet(book,'Outfit Annotation',NAMES[0],count)
    model=fresh_sheet(book,'Model Evaluation',NAMES[1],count)
    main['A1']='Method 2 · Outfit Annotation'
    model['A1']='Method 2 · Model Evaluation'
    counts=data['job_counts'];summary=f'{count} frontend base outfits. Job status: {json.dumps(counts)}. Optional layers excluded from image rows.'
    main['A2']=summary
    model['A2']=summary+' No numerical aesthetic rating is produced by this method; blank scores are intentional.'
    old_manifest=json.loads(workbook.with_name('outfit_annotation_en_manifest.json').read_text())
    codes={i['id']:i['code'] for o in old_manifest['outfits'] for i in o['items']}
    old_split={book['Outfit Annotation'].cell(r,3).value:book['Model Evaluation'].cell(r,3).value for r in range(5,book['Outfit Annotation'].max_row+1)}
    split_by_set={tuple(sorted(k.split(' | '))):v for k,v in old_split.items() if k}
    provenance=[]
    for index,outfit in enumerate(data['outfits']):
        r=index+5;oid=f'M2-{index+1:04d}'
        item_codes=[codes.get(i['id'],i['id']) for i in outfit['items']]
        main.cell(r,1,oid);main.cell(r,3,' | '.join(item_codes))
        width=min(200,440/max(1,len(outfit['items'])))
        for pos,item in enumerate(outfit['items']):
            image=Image(image_paths[item['image_path']]);scale=min(width/image.width,205/image.height)
            image.width*=scale;image.height*=scale
            image.anchor=OneCellAnchor(_from=AnchorMarker(col=1,row=r-1,colOff=pixels_to_EMU(pos*width)),ext=XDRPositiveSize2D(pixels_to_EMU(image.width),pixels_to_EMU(image.height)))
            main.add_image(image)
        rec=outfit.get('review_record');p=rec['payload'] if rec else {};review=p.get('visual_review',{}).get('core')
        config=data['config']
        split=split_by_set.get(tuple(sorted(item_codes))) or ('Holdout' if int(hashlib.sha256('|'.join(sorted(item_codes)).encode()).hexdigest(),16)%10<3 else 'Development')
        values={1:oid,2:'Frontend outfit library · base outfit (optional additions excluded)',3:split,
                4:f"V2 · {config['generation_model']} / {config['evaluation_model']} · {data['generation_key'][:12]}",8:'Yes',11:p.get('evaluated_at')}
        if review:
            values[5]={'pass':'Yes','fail':'No','uncertain':'Cannot judge'}[review['wearability']['verdict']]
            values[9]=review['wearability']['reason']
            values[10]='\n'.join(f"{key}: {review[key]['verdict']} — {review[key]['reason']}" for key in ['thermal','color_pattern','occasion'])
        else:values[9]='No current matching core visual review; scores left blank.'
        for c,value in values.items():
            cell=model.cell(r,c,value)
            if isinstance(value,str):cell.data_type='s'
        main.cell(r,3).data_type='s'
        provenance.append({'annotation_id':oid,'outfit_id':outfit['id'],'review_record_id':rec['id'] if rec else None,'item_ids':[i['id'] for i in outfit['items']]})
    backup=directory/'before_append.xlsx'
    if not backup.exists():shutil.copy2(workbook,backup)
    temp=workbook.with_name('.method2_pending.xlsx')
    book.save(temp)
    check=load_workbook(temp)
    assert len(check[NAMES[0]]._images)==sum(len(o['items']) for o in data['outfits'])
    for name in book.sheetnames:
        if name in NAMES:continue
        assert [[c.value for c in row] for row in check[name]]==[[c.value for c in row] for row in book[name]]
        assert len(check[name]._images)==len(book[name]._images)
    if hashlib.sha256(workbook.read_bytes()).hexdigest()!=before or workbook.with_name('~$'+workbook.name).exists():
        temp.unlink();raise RuntimeError('Workbook changed or opened during export; retrying safely')
    temp.replace(workbook)
    dump(directory/'provenance.json',provenance)
    return count


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id',required=True);parser.add_argument('--workbook',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--watch',action='store_true')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    if (args.out/'complete.json').exists():print('Already exported');return
    config=load_config();repo=build_closet_repository();store=build_store(repo)
    config_path=args.out/'config.json'
    if config_path.exists():
        from app.outfits.config import OutfitConfig
        config=OutfitConfig.model_validate(json.loads(config_path.read_text()))
    else:dump(config_path,config.snapshot())
    stable=0
    while True:
        try:
            snapshot=args.out/'snapshot.json'
            if snapshot.exists():data=json.loads(snapshot.read_text())
            else:
                jobs=[j for j in store.jobs(args.user_id) if j['generation_key']==config.generation_key]
                counts=dict(Counter(j['status'] for j in jobs))
                ready=bool(jobs) and not any(j['status'] in {'queued','processing'} for j in jobs)
                stable=stable+1 if ready else 0
                status={'state':'waiting_for_jobs','job_counts':counts,'generation_key':config.generation_key}
                dump(args.out/'status.json',status);print(json.dumps(status),flush=True)
                if stable<(2 if args.watch else 1):
                    if not args.watch:return
                    time.sleep(30);continue
                data=capture(repo,store,args.user_id,config,args.out)
            images=prepare_images(data,args.out)
            count=append_workbook(args.workbook,data,images,args.out)
            status={'state':'complete','outfits':count,'workbook':str(args.workbook),'job_counts':data['job_counts']}
            dump(args.out/'complete.json',status);dump(args.out/'status.json',status);print(json.dumps(status),flush=True);return
        except FileExistsError:
            raise
        except Exception as error:
            status={'state':'retrying_export','error':type(error).__name__,'reason':str(error) if isinstance(error,RuntimeError) else 'Read/download/write failed; will retry'}
            dump(args.out/'status.json',status);print(json.dumps(status),flush=True)
            if not args.watch:raise
        time.sleep(30)


if __name__=='__main__':main()
