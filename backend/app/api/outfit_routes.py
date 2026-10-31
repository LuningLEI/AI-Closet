from fastapi import APIRouter, HTTPException, Query, Request
from app.api import routes
from app.outfits.config import load_config
from app.outfits.models import LibraryResponse, BuildRequest, BuildResponse, OutfitDTO
from app.outfits.service import OutfitLibrary
from app.outfits.store import build_store
from app.services.taste_profile_service import TasteProfileService

router=APIRouter(prefix='/api/v1/outfits',tags=['Outfit library'])

def library():
    return OutfitLibrary(routes.repository,build_store(routes.repository),load_config())

def unavailable(error):
    # Schema-not-installed is actionable without exposing DB credentials or SQL details.
    raise HTTPException(status_code=503,detail='Outfit library is unavailable. Check the outfit database migration and configuration.') from error

@router.get('',response_model=LibraryResponse)
def list_outfits(request:Request,anchor_item_id:str|None=None,liked_only:bool=False,
                 offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100)):
    uid=routes.current_user_id(request)
    try:
        feedback=personal()
        disliked=feedback.disliked_signatures(uid)
        liked=feedback.liked_signatures(uid)
        outfit_library=library()
        def feedback_state(outfit):
            base_signature=feedback.composition_signature(item.id for item in outfit.items)
            variants=[];any_liked=base_signature in liked
            for variant in outfit.optional_additions:
                variant_signature=feedback.composition_signature(
                    [item.id for item in outfit.items]+[item.id for item in variant.items])
                variant_liked=variant_signature in liked
                any_liked=any_liked or variant_liked
                variants.append(variant.model_copy(update={'liked':variant_liked}))
            return outfit.model_copy(update={'liked':base_signature in liked,'optional_additions':variants}),any_liked,base_signature
        if liked_only:
            # Filtering after database pagination can miss liked rows and report a
            # false total. Traverse the projection in bounded pages, then paginate
            # the much smaller liked set.
            all_outfits=[];cursor=0;result=None
            while True:
                page=outfit_library.list(uid,routes.signing_service,str(request.base_url),anchor_item_id,cursor,100)
                result=result or page
                all_outfits.extend(page.outfits)
                if page.next_offset is None:break
                cursor=page.next_offset
            visible=[]
            for outfit in all_outfits:
                marked,any_liked,base_signature=feedback_state(outfit)
                if any_liked and base_signature not in disliked:visible.append(marked)
            result=result.model_copy(update={'outfits':visible[offset:offset+limit],'total':len(visible),
                'next_offset':offset+limit if offset+limit<len(visible) else None})
            return result
        result=outfit_library.list(uid,routes.signing_service,str(request.base_url),anchor_item_id,offset,limit)
        visible=[]
        for outfit in result.outfits:
            marked,_,signature=feedback_state(outfit)
            if signature in disliked:continue
            visible.append(marked)
        return result.model_copy(update={'outfits':visible,'total':max(0,result.total-(len(result.outfits)-len(visible)))})
    except Exception as error:unavailable(error)

@router.post('/build',response_model=BuildResponse)
def build_outfits(request:Request,payload:BuildRequest):
    uid=routes.mutation_user_id(request)
    try:return library().build(uid,payload.anchor_item_id,payload.retry_failed)
    except ValueError as error:raise HTTPException(status_code=422,detail=str(error)) from error
    except Exception as error:unavailable(error)


from datetime import date
from uuid import UUID
from app.outfits.personal import (PersonalOutfits, PersonalOutfitRequest, WearRequest, WearEvent,
                                  WearStatus, OutfitFeedbackRequest, OutfitFeedbackEvent)


def personal():
    return PersonalOutfits(routes.repository,build_store(routes.repository))


@router.get('/taste-profile')
def taste_profile(request: Request):
    uid = routes.current_user_id(request)
    service = TasteProfileService(build_store(routes.repository))
    return service.public(service.ensure_current(uid))


@router.delete('/taste-profile')
def reset_taste_profile(request: Request):
    uid = routes.mutation_user_id(request)
    service = TasteProfileService(build_store(routes.repository))
    return service.public(service.reset(uid))


@router.post('/personal',response_model=OutfitDTO)
def save_personal(request:Request,payload:PersonalOutfitRequest):
    uid=routes.mutation_user_id(request)
    result=personal().save(uid,payload)
    result.items=routes.signing_service.items(result.items,str(request.base_url))
    return result


@router.post('/wear',response_model=WearEvent)
def wear_outfit(request:Request,payload:WearRequest):
    return personal().record_wear(routes.mutation_user_id(request),payload)


@router.get('/wear/status',response_model=WearStatus)
def wear_status(request:Request,wear_date:date,item_ids:list[UUID]=Query(default=[])):
    uid=routes.current_user_id(request)
    result=personal().wear_status(uid,[str(item) for item in item_ids],wear_date)
    result.selected_today_items=routes.signing_service.items(result.selected_today_items,str(request.base_url))
    return result


@router.delete('/wear/{event_id}',status_code=204)
def undo_wear(request:Request,event_id:UUID):
    personal().undo_wear(routes.mutation_user_id(request),str(event_id))


@router.post('/feedback',response_model=OutfitFeedbackEvent)
def record_feedback(request:Request,payload:OutfitFeedbackRequest):
    return personal().record_feedback(routes.mutation_user_id(request),payload)
