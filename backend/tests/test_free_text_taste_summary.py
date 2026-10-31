from uuid import uuid4

from app.models.domain import ClothingItemRecord
from app.outfits.personal import OutfitFeedbackRequest, PersonalOutfits
from app.services.free_text_taste_summary import FreeTextTasteSummary, FreeTextTasteSummaryService
from app.services.taste_profile_service import TasteProfileService
from app.services.taste_profile import ALGORITHM_VERSION


def test_free_text_summary_waits_for_threshold_and_processes_once(repository, tmp_path):
    from app.outfits.store import LocalOutfitStore
    store=LocalOutfitStore(tmp_path/'outfits.sqlite3')
    uid='user';item=ClothingItemRecord(user_id=uid,image_url='',category='Tops',subtype='T-shirt')
    repository.add_item(item)
    personal=PersonalOutfits(repository,store)
    for index in range(10):
        personal.record_feedback(uid,OutfitFeedbackRequest(id=uuid4(),outfit_id=None,
            item_ids=[item.id],action='liked',surface='library',note=f'feedback {index}'))
    profiles=TasteProfileService(store)
    profile=profiles.reduce_user(uid)
    assert profile['new_free_text_count']==10
    calls=[]
    def summarize(previous, notes):
        calls.append((previous,notes))
        return FreeTextTasteSummary(summary='Prefers clean lines',preferred_cues=['clean lines'],
            avoided_cues=[],occasion_preferences=[],confidence='medium'),{'input_tokens':100}
    service=FreeTextTasteSummaryService(store,request=summarize)
    assert service.pending_users()==[uid]
    result=service.summarize_user(uid)
    assert result['new_free_text_count']==0
    assert result['summarized_free_text_count']==10
    assert result['free_text_summary']['preferred_cues']==['clean lines']
    service.summarize_user(uid)
    assert len(calls)==1


def test_old_taste_algorithm_is_pending_and_reprojected(tmp_path):
    from app.outfits.store import LocalOutfitStore
    store=LocalOutfitStore(tmp_path/'outfits.sqlite3')
    profiles=TasteProfileService(store)
    with store.db() as db:
        for table in ('outfit_feedback_events','personal_outfits','outfit_wear_events'):
            db.execute(f'create table if not exists {table} (user_id text,data text not null)')
    profile=profiles.get('user')
    profile.update(algorithm_version='taste-profile-v1',source_version=3,projected_version=3)
    profiles._put(profile)
    assert profiles.pending_users()==['user']
    current=profiles.ensure_current('user')
    assert current['algorithm_version']==ALGORITHM_VERSION
    assert current['projected_version']==3
