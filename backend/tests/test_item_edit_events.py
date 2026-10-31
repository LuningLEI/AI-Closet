from __future__ import annotations

import json
import asyncio
from io import BytesIO

from fastapi import UploadFile
from app.models.api import ClothingItemUpdateRequest, ImageEditMetadata
from app.models.domain import ClothingItemRecord
from app.services.taxonomy import OCCASIONS
from app.services.item_service import ItemService


class StubEmbeddingService:
    def create_embedding(self, _text: str) -> None:
        return None


class StubStorageService:
    async def store_image(self, _file, user_id: str) -> dict[str, str]:
        return {
            "image_path": f"{user_id}/replacement.jpg",
            "image_url": "https://example.test/replacement.jpg",
        }

    def signed_image_url(self, _image_path: str | None) -> str:
        return "https://example.test/signed-replacement.jpg"

    def delete_image(self, _image_path: str | None) -> None:
        pass


def test_attribute_updates_record_only_changed_card_fields(repository) -> None:
    user_id = "00000000-0000-4000-8000-0000000000a1"
    repository.add_item(
        ClothingItemRecord(
            id="item-a",
            user_id=user_id,
            image_url="https://example.test/item-a.jpg",
            image_path=f"{user_id}/item-a.jpg",
            category="Tops",
            subtype="T-shirt",
            color="White",
            season="All-Season",
            style="Casual",
            occasion="Everyday",
            recognition_summary="A white T-shirt.",
        )
    )
    service = ItemService(repository, StubEmbeddingService())

    service.update_item(
        user_id,
        "item-a",
        ClothingItemUpdateRequest(
            category="Tops",
            subtype="T-shirt",
            color="Blue",
            season="All-Season",
            style="Casual",
            occasion="Everyday",
            recognition_summary="A white T-shirt.",
            edit_source="ios",
        ),
    )

    events = json.loads(repository.item_edit_events_path.read_text(encoding="utf-8"))
    assert len(events) == 1
    assert events[0]["event_type"] == "item_attributes_updated"
    assert events[0]["source"] == "ios"
    assert events[0]["changed_fields"] == ["color"]
    assert events[0]["changes"] == {"color": {"before": "White", "after": "Blue"}}


def test_image_replacement_records_final_editor_transform(repository) -> None:
    user_id = "00000000-0000-4000-8000-0000000000a1"
    repository.add_item(
        ClothingItemRecord(
            id="item-a",
            user_id=user_id,
            image_url="https://example.test/item-a.jpg",
            image_path=f"{user_id}/item-a.jpg",
            category="Tops",
            color="White",
            season="All-Season",
            style="Casual",
            occasion="Everyday",
        )
    )
    service = ItemService(repository, StubEmbeddingService(), StubStorageService())
    file = UploadFile(filename="edited.jpg", file=BytesIO(b"jpeg-data"), headers={"content-type": "image/jpeg"})

    asyncio.run(
        service.replace_item_image(
            user_id,
            "item-a",
            file,
            "http://testserver/",
            ImageEditMetadata(
                rotation_quarter_turns=1,
                zoom_scale=1.25,
                drag_x=16,
                drag_y=-8,
                editor_side=362,
            ),
        ),
    )

    events = json.loads(repository.item_edit_events_path.read_text(encoding="utf-8"))
    assert len(events) == 1
    assert events[0]["event_type"] == "image_replaced"
    assert events[0]["source"] == "ios"
    assert events[0]["changes"]["image_path"]["before"] == f"{user_id}/item-a.jpg"
    assert events[0]["changes"]["image_transform"]["after"]["rotation_quarter_turns"] == 1


def scored_item(repository):
    return repository.add_item(ClothingItemRecord(
        id='scored', user_id='owner', image_url='https://example.test/scored.jpg', category='Tops',
        occasion='Everyday, Work, Travel', color='White',
        recognition_tags={'occasion_threshold':0.5, 'occasion_scores':[
            {'occasion':'Everyday','score':0.9}, {'occasion':'Work','score':0.85},
            {'occasion':'Travel','score':0.7}, {'occasion':'Date','score':0.3},
        ]},
    ))


def edit_payload(selection, before='Everyday, Work', threshold=0.8, color='White'):
    return ClothingItemUpdateRequest(category='Tops', color=color, season='All-Season', style='Casual',
        occasion=selection, occasion_before=before, occasion_threshold_at_edit=threshold, edit_source='ios')


def set_threshold(monkeypatch, value):
    from types import SimpleNamespace
    config=SimpleNamespace(recognition_occasion_threshold=value)
    monkeypatch.setattr('app.services.occasion_support.settings', config)
    monkeypatch.setattr('app.services.occasion_thresholds.settings', config)


def test_occasion_event_and_active_overrides_preserve_raw_scores(repository, monkeypatch):
    from app.services.occasion_support import effective_occasion
    set_threshold(monkeypatch,0.8)
    original=scored_item(repository)
    service=ItemService(repository,StubEmbeddingService())
    updated=service.update_item('owner','scored',edit_payload('Everyday, Date'))
    event=json.loads(repository.item_edit_events_path.read_text())[0]
    assert event['changed_fields']==['occasion']
    assert event['changes']['occasion']=={
        'before':'Everyday, Work', 'after':'Everyday, Date', 'added':['Date'], 'removed':['Work'],
        'thresholds_at_edit':dict.fromkeys(OCCASIONS, 0.8),
        'threshold_at_edit':0.8, 'model_selected_at_edit':['Everyday','Work'], 'effective_after':'Everyday, Date',
    }
    assert updated.metadata['occasion_overrides']=={'added':['Date'],'removed':['Work']}
    assert updated.recognition_tags['occasion_scores']==original.recognition_tags['occasion_scores']
    set_threshold(monkeypatch,0.7)
    assert effective_occasion(updated)=='Everyday, Date'  # Confirmed labels no longer drift with thresholds.
    # Reverse the previous choices. Opposing overrides must be removed.
    updated=service.update_item('owner','scored',edit_payload('Everyday, Work, Travel',before='Everyday, Date',threshold=0.7))
    assert updated.metadata['occasion_overrides']=={'added':['Work','Travel'],'removed':['Date']}
    assert len(json.loads(repository.item_edit_events_path.read_text()))==2
    # Reordering the same selection is not another user correction.
    service.update_item('owner','scored',edit_payload('Travel, Work, Everyday',before='Everyday, Work, Travel',threshold=0.7))
    assert len(json.loads(repository.item_edit_events_path.read_text()))==2


def test_color_edit_and_changed_threshold_do_not_create_false_occasion_event(repository,monkeypatch):
    from app.services.occasion_support import effective_occasion
    set_threshold(monkeypatch,0.7)
    scored_item(repository)
    # User opened at 0.8; API configuration changed to 0.7 before saving a color edit.
    updated=ItemService(repository,StubEmbeddingService()).update_item('owner','scored',edit_payload('Everyday, Work',color='Blue'))
    event=json.loads(repository.item_edit_events_path.read_text())[0]
    assert event['changed_fields']==['color']
    assert updated.metadata['occasion_overrides']=={'added':[],'removed':[]}
    assert effective_occasion(updated)=='Everyday, Work, Travel'


def test_stale_user_selection_is_rejected_before_writes(repository,monkeypatch):
    import pytest
    from fastapi import HTTPException
    set_threshold(monkeypatch,0.8)
    item=scored_item(repository)
    with pytest.raises(HTTPException) as failure:
        ItemService(repository,StubEmbeddingService()).update_item('owner','scored',edit_payload('Date',before='Workout'))
    assert failure.value.status_code==409
    assert repository.get_item(item.id)==item
    assert not repository.item_edit_events_path.exists()


def test_reset_modes_preserve_or_clear_active_overrides(repository, tmp_path,monkeypatch):
    from tools.admin.reset_recognition import reset_user_recognition
    set_threshold(monkeypatch,0.8)
    scored_item(repository)
    ItemService(repository,StubEmbeddingService()).update_item('owner','scored',edit_payload('Everyday, Date'))
    result=reset_user_recognition(repository,'owner',backup_dir=tmp_path/'backups')
    assert result['skipped']=={'manual':1}
    assert repository.get_item('scored').metadata['occasion_overrides']['added']==['Date']
    result=reset_user_recognition(repository,'owner',include_manual=True,backup_dir=tmp_path/'backups')
    assert result['queued_item_ids']==['scored']
    assert repository.get_item('scored').metadata['occasion_overrides']=={'added':[],'removed':[]}
    assert len(json.loads(repository.item_edit_events_path.read_text()))==1


def test_multiple_colors_round_trip_and_audit(repository):
    uid='00000000-0000-4000-8000-0000000000a1'
    repository.add_item(ClothingItemRecord(id='multicolor-item',user_id=uid,image_url='https://example.test/photo',category='Tops',color='Black'))
    saved=ItemService(repository,StubEmbeddingService()).update_item(uid,'multicolor-item',ClothingItemUpdateRequest(category='Tops',color='Black, White',season='Summer',style='Casual',occasion='Everyday'))
    assert saved.color=='Black, White'
    assert repository.get_item('multicolor-item',uid).color=='Black, White'
    events=json.loads(repository.item_edit_events_path.read_text())
    assert events[-1]['changes']['color']=={'before':'Black','after':'Black, White'}


def test_recognition_keeps_multiple_colors():
    from app.services.recognition_service import ClothingRecognitionService
    service=ClothingRecognitionService()
    assert service._normalize_color('black, white, Black')=='Black, White'
    assert service._normalize_color('navy, yellow')=='Navy, Yellow'
    assert service._normalize_color('Unknown, Blue')=='Blue'
    assert service._normalize_color('Black')=='Black'


def test_olive_and_athletic_jacket_normalization():
    from app.services.taxonomy import COLORS, SUBTYPES, normalize_subtype
    from app.services.recognition_service import ClothingRecognitionService
    service=ClothingRecognitionService()
    assert 'Olive' in COLORS
    assert service._normalize_color('olive green')=='Olive'
    assert service._normalize_color('Black, Olive')=='Black, Olive'
    assert service._normalize_color('green')=='Green'
    assert 'Athletic Jacket' in SUBTYPES['Activewear']
    assert 'Athletic Jacket' not in SUBTYPES['Outerwear']
    for label in ['Athletic Jacket','fitted athletic jacket','Define Jacket','track jacket']:
        assert normalize_subtype('Activewear',label)=='Athletic Jacket'
    assert normalize_subtype('Outerwear','Jacket')=='Jacket'


def test_visible_details_save_preserve_and_clear(repository):
    item = ClothingItemRecord(user_id='details-user', category='Tops', occasion='Everyday', image_url='https://example.test/photo',
                              material='Cotton', length='Hip', sleeve_length='Long Sleeve')
    repository.add_item(item)
    service = ItemService(repository, StubEmbeddingService())
    basic = dict(category=item.category, subtype=item.subtype, color=item.color,
                 season=item.season, style=item.style, occasion=item.occasion)
    updated = service.update_item(item.user_id, item.id, ClothingItemUpdateRequest(**basic, material='Wool', length='Cropped', sleeve_length='Short Sleeve'))
    assert (updated.material, updated.length, updated.sleeve_length) == ('Wool','Cropped','Short Sleeve')
    events = json.loads(repository.item_edit_events_path.read_text())
    assert set(events[-1]['changed_fields']) >= {'material','length','sleeve_length'}
    preserved = service.update_item(item.user_id, item.id, ClothingItemUpdateRequest(**basic))
    assert preserved.material == 'Wool' and preserved.length == 'Cropped'
    cleared = service.update_item(item.user_id, item.id, ClothingItemUpdateRequest(**basic, material='', length='', sleeve_length=''))
    assert cleared.material is None and cleared.length is None and cleared.sleeve_length is None
