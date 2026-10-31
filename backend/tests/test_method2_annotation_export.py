import json
from pathlib import Path
from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image
from PIL import Image as PILImage
from tools.evaluation.export_method2_annotation import append_workbook, NAMES


def test_append_preserves_first_method_and_links_second(tmp_path):
    image=tmp_path/'image.png';PILImage.new('RGB',(20,30),'blue').save(image)
    path=tmp_path/'outfit_annotation_en.xlsx'
    book=Workbook();a=book.active;a.title='Outfit Annotation';m=book.create_sheet('Model Evaluation')
    for c in range(1,18):a.cell(4,c,f'column {c}')
    for c in range(1,17):m.cell(4,c,f'column {c}')
    a.cell(5,1,'P001');a.cell(5,3,'I001');a.cell(5,4,'No');a.cell(5,7,'Preserve my notes')
    a.cell(5,17,'=COUNTA(D5:F5)');a.add_image(Image(image),'B5')
    m.cell(5,3,'Holdout');m.cell(5,12,'=IF(\'Outfit Annotation\'!D5="","",\'Outfit Annotation\'!D5)')
    book.save(path)
    path.with_name('outfit_annotation_en_manifest.json').write_text(json.dumps({'outfits':[{'items':[{'id':'one','code':'I001'}]}]}))
    check={'verdict':'pass','reason':'Looks fine'}
    data={'outfits':[{'id':'outfit','items':[{'id':'one','image_path':'photo'}],
                     'review_record':{'id':'review','payload':{'visual_review':{'core':{k:check for k in ['wearability','thermal','color_pattern','occasion']}},'evaluated_at':'now'}}}],
          'job_counts':{'complete':1,'failed':1},'config':{'generation_model':'test','evaluation_model':'test'},'generation_key':'key'}
    out=tmp_path/'export';out.mkdir()
    assert append_workbook(path,data,{'photo':image},out)==1
    result=load_workbook(path)
    assert result['Outfit Annotation']['D5'].value=='No'
    assert result['Outfit Annotation']['G5'].value=='Preserve my notes'
    assert len(result['Outfit Annotation']._images)==1
    assert len(result[NAMES[0]]._images)==1
    assert result[NAMES[0]]['D5'].value is None
    assert result[NAMES[1]]['F5'].value is None
    assert result[NAMES[1]]['E5'].value=='Yes'
    assert result[NAMES[1]]['C5'].value=='Holdout'
    assert "'Method 2 Outfits'!D5" in result[NAMES[1]]['L5'].value
    assert '"failed": 1' in result[NAMES[1]]['A2'].value
    with pytest.raises(FileExistsError):append_workbook(path,data,{'photo':image},out)


def test_open_excel_blocks_write(tmp_path):
    path=tmp_path/'outfit_annotation_en.xlsx'
    path.with_name('~$'+path.name).touch()
    with pytest.raises(RuntimeError,match='Close Excel'):
        append_workbook(path,{}, {},tmp_path)
