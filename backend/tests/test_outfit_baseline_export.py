import json
from openpyxl import load_workbook
import pytest
from tools.evaluation.export_outfit_baseline import export_snapshot, origin_key
from test_outfit_library import setup, run_all


def test_export_preserves_scores_reasons_and_versions_without_mutating(setup,tmp_path):
    uid,top,bottom,lib,p=setup
    lib.build(uid,top.id);run_all(lib)
    rows=lib.store.evaluations(uid)
    r=rows[0]
    r['payload']['evaluation'].update(aesthetic_score=None,aesthetic_reason='=HYPERLINK("bad")',structurally_wearable='no')
    with lib.store.db() as db:
        db.execute('update outfits set data=? where id=?',(json.dumps(r),r['id']))
    before=lib.store.evaluations(uid)
    out=tmp_path/'export'
    meta=export_snapshot(lib.repository,lib.store,uid,lib.config.generation_key,lib.config.evaluator_key,out,final=True)
    assert meta['final'] and meta['queue_drained']
    assert lib.store.evaluations(uid)==before
    raw=json.loads((out/'snapshot.json').read_text())
    assert raw['records'][0]['payload']['evaluation']['aesthetic_score'] is None
    assert 'lease_token' not in raw['jobs'][0]
    book=load_workbook(out/'outfit_baseline.xlsx')
    sheet=book['Outfit evaluations']
    assert sheet.cell(2,7).value is None
    assert sheet.cell(2,9).value.startswith('=HYPERLINK') and sheet.cell(2,9).data_type=='s'
    assert sheet.cell(2,14).value is True
    assert origin_key(r)==lib.config.generation_key


def test_final_export_refuses_unfinished_target_version(setup,tmp_path):
    uid,top,bottom,lib,p=setup
    lib.build(uid,top.id)
    with pytest.raises(ValueError,match='pending'):
        export_snapshot(lib.repository,lib.store,uid,lib.config.generation_key,lib.config.evaluator_key,tmp_path/'final',final=True)
    assert not (tmp_path/'final'/'snapshot.json').exists()
