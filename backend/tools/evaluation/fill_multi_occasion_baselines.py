"""Refresh only the two garment occasion baseline columns, preserving other XLSX parts."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from openpyxl import load_workbook
from tools.evaluation.baseline_eval import DirectVisionBaseline
from app.core.config import settings
from tools.evaluation.fill_human_eval_baselines import _download_images, _contact_sheets, _data_url, _response, _cosine
from app.repositories.factory import build_closet_repository
from app.services.embedding_service import EmbeddingService
from app.services.occasion_support import select_scored_occasions
from app.services.taxonomy import OCCASIONS

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def write_cells(source, output, cells):
    # Patch only cell XML: keep drawings, images, styles, human labels and all other sheets byte-identical.
    import re
    with ZipFile(source) as original:
        book = ET.fromstring(original.read('xl/workbook.xml'))
        sheet = next(s for s in book.find(f'{{{NS}}}sheets') if s.attrib['name'] == 'Garment Labels')
        rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
        rels = ET.fromstring(original.read('xl/_rels/workbook.xml.rels'))
        target = next(r.attrib['Target'] for r in rels if r.attrib['Id'] == rid)
        member = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        xml = original.read(member).decode()
        for address, value in cells.items():
            from xml.sax.saxutils import escape
            replacement = f'<c r="{address}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            pattern = rf'<c\b(?=[^>]*\br="{address}")[^>]*(?:/>|>.*?</c>)'
            match = re.search(pattern, xml, flags=re.DOTALL)
            if not match:
                raise ValueError(f'Missing existing baseline cell {address}')
            style = re.search(r'\bs="([^"]+)"', match.group())
            if style:
                replacement = replacement.replace(' t="inlineStr"', f' s="{style.group(1)}" t="inlineStr"')
            xml = xml[:match.start()] + replacement + xml[match.end():]
        with ZipFile(output, 'w') as updated:
            for info in original.infolist():
                updated.writestr(info, xml.encode() if info.filename == member else original.read(info.filename))
    before, after = load_workbook(source), load_workbook(output)
    for old in before:
        new = after[old.title]
        for row in old:
            for cell in row:
                if old.title == 'Garment Labels' and cell.coordinate in cells:
                    assert new[cell.coordinate].value == cells[cell.coordinate]
                else:
                    assert new[cell.coordinate].value == cell.value, (old.title, cell.coordinate)
    with ZipFile(source) as a, ZipFile(output) as b:
        assert all(a.read(n) == b.read(n) for n in a.namelist() if n != member)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook', required=True, type=Path)
    parser.add_argument('--user-id', required=True)
    args = parser.parse_args()
    output = args.workbook.with_name(args.workbook.stem + '_multi_occasion.xlsx')
    report_path = output.with_suffix('.json')
    workbook = load_workbook(args.workbook)
    sheet = workbook['Garment Labels']
    rows = [(r, sheet.cell(r, 2).value, sheet.cell(r, 3).value) for r in range(3, sheet.max_row+1) if sheet.cell(r,2).value]
    repository = build_closet_repository()
    items = {i.id:i for i in repository.list_items_for_recommendation(args.user_id)}
    assert all(i in items for _,_,i in rows), 'Missing workbook garments in current closet'
    assert all(items[i].semantic_vector for _,_,i in rows), 'Missing stored vectors'
    report = {'vision_model':settings.openai_vision_model, 'embedding_model':settings.openai_embedding_model,
              'threshold':0.8, 'fallback':'highest score; taxonomy order breaks ties',
              'vector_method':'raw cosine against a garment appropriate for {occasion}; not calibrated probability',
              'source':str(args.workbook.resolve()), 'picture':{}, 'vector':{}, 'usage':[]}
    def save():
        report_path.write_text(json.dumps(report,indent=2))
    if report_path.exists():
        previous = json.loads(report_path.read_text())
        if previous['source'] != report['source']:
            raise ValueError('Checkpoint belongs to another workbook')
        report = previous
    candidates = DirectVisionBaseline().candidates_for_items([items[i] for _,_,i in rows], max_images=0)
    urls = {c.item_id:c.image_url for c in candidates}
    assert all(i in urls for _,_,i in rows), 'Missing image URLs'
    with TemporaryDirectory(prefix='occasion-eval-') as directory:
        for start in range(0,len(rows),12):
            batch = rows[start:start+12]
            codes = [c for _,c,_ in batch]
            if all(c in report['picture'] for c in codes):
                continue
            images = _download_images({c:urls[i] for _,c,i in batch})
            sheets = _contact_sheets(images,Path(directory)/str(start))
            scores_schema = {'type':'object','additionalProperties':False,'properties':{o:{'type':'number','minimum':0,'maximum':1} for o in OCCASIONS},'required':OCCASIONS}
            schema = {'type':'object','additionalProperties':False,'properties':{c:scores_schema for c in codes},'required':codes}
            prompt = 'Inspect each code-labelled garment photo. Score its suitability independently for EVERY occasion from 0 to 1. Multiple occasions can score highly; scores do not sum to 1. 0 means unsuitable and 1 means strongly suitable. Use only visual evidence, not imagined outfit additions. Return all ten scores for every supplied garment code.'
            result, usage = _response([{'type':'input_text','text':prompt}] + [{'type':'input_image','image_url':_data_url(p),'detail':'high'} for p in sheets],schema)
            assert set(result) == set(codes)
            for code, scores in result.items():
                assert set(scores)==set(OCCASIONS)
                assert all(isinstance(s,(int,float)) and not isinstance(s,bool) and math.isfinite(s) and 0<=s<=1 for s in scores.values())
                report['picture'][code] = {'scores':scores,'selected':select_scored_occasions(scores,0.8)}
            report['usage'].append(usage)
            save()
            print(f'Picture: {min(start+12,len(rows))}/{len(rows)}',flush=True)
    if not report['vector']:
        prototypes = {}
        for label in OCCASIONS:
            vector, usage = EmbeddingService().create_embedding_with_usage(f'a garment appropriate for {label}')
            if not vector:
                raise RuntimeError(f'Embedding failed: {label}')
            prototypes[label] = vector
            report['usage'].append(usage)
        for _, code, item_id in rows:
            vector = items[item_id].semantic_vector
            assert all(len(v)==len(vector) for v in prototypes.values()), 'Vector dimension mismatch'
            scores = {label:_cosine(vector,v) for label,v in prototypes.items()}
            report['vector'][code] = {'item_id':item_id,'scores':scores,'selected':select_scored_occasions(scores,0.8)}
        save()
    cells = {}
    for row, code, item_id in rows:
        for column,method in [('G','picture'),('H','vector')]:
            cells[f'{column}{row}'] = ', '.join(report[method][code]['selected'])
    write_cells(args.workbook,output,cells)
    report['verified'] = {'garments':len(rows),'baseline_cells':len(cells),'all_other_cell_values_preserved':True,'other_xlsx_parts_byte_identical':True}
    save()
    print(json.dumps({'output':str(output.resolve()),'verified':report['verified'],'multi_label_counts':{m:sum(len(v['selected'])>1 for v in report[m].values()) for m in ['picture','vector']}},indent=2),flush=True)

if __name__ == '__main__':
    main()
