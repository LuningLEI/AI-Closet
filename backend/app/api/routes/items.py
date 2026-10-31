from __future__ import annotations

import json
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status

from app.api import dependencies as deps
from app.core.constants import MAX_BATCH_UPLOADS
from app.models.api import (BatchUploadFailure, BatchUploadResponse, ClothingItemUpdateRequest,
                            ClosetSummaryResponse, ImageEditMetadata, UploadQueueStatus)
from app.models.domain import ClothingItemRecord

router = APIRouter()


def signed_item(item: ClothingItemRecord, request: Request) -> ClothingItemRecord:
    return deps.signing_service.item(item, str(request.base_url))


def signed_items(items: list[ClothingItemRecord], request: Request) -> list[ClothingItemRecord]:
    return deps.signing_service.items(items, str(request.base_url))


@router.get("/items", response_model=list[ClothingItemRecord])
def list_items(request: Request) -> list[ClothingItemRecord]:
    return signed_items(deps.repository.list_items(deps.current_user_id(request)), request)


@router.get("/items/{item_id}", response_model=ClothingItemRecord)
def get_item(request: Request, item_id: str) -> ClothingItemRecord:
    item = deps.repository.get_item(item_id, deps.current_user_id(request))
    if item is None:
        raise HTTPException(status_code=404, detail="Clothing item not found")
    return signed_item(item, request)


@router.get("/summary", response_model=ClosetSummaryResponse)
def closet_summary(request: Request) -> ClosetSummaryResponse:
    result = deps.repository.summary(deps.current_user_id(request))
    result["recent_items"] = signed_items(result["recent_items"], request)
    return ClosetSummaryResponse.model_validate(result)


@router.patch("/items/{item_id}", response_model=ClothingItemRecord)
def update_item(request: Request, item_id: str, payload: ClothingItemUpdateRequest) -> ClothingItemRecord:
    return signed_item(deps.item_service.update_item(deps.mutation_user_id(request), item_id, payload), request)


@router.post("/items/{item_id}/image", response_model=ClothingItemRecord)
async def replace_item_image(request: Request, item_id: str, file: UploadFile = File(...),
                             edit_metadata: str | None = Form(default=None)) -> ClothingItemRecord:
    metadata = None
    if edit_metadata:
        try:
            metadata = ImageEditMetadata.model_validate_json(edit_metadata)
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=422, detail="Invalid image edit metadata.") from error
    item = await deps.item_service.replace_item_image(deps.mutation_user_id(request), item_id, file,
                                                       str(request.base_url), metadata)
    return signed_item(item, request)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(request: Request, item_id: str) -> Response:
    deps.item_service.delete_item(deps.mutation_user_id(request), item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def queue_uploaded_item(request: Request, file: UploadFile,
                              upload_id: str | None = None) -> ClothingItemRecord:
    item = await deps.upload_service.queue_clothing_item(deps.mutation_user_id(request), file,
                                                         str(request.base_url), upload_id=upload_id)
    return signed_item(item, request)


@router.post("/items/upload", response_model=ClothingItemRecord)
async def upload_item(request: Request, file: UploadFile = File(...)) -> ClothingItemRecord:
    return await queue_uploaded_item(request, file)


@router.post("/items/upload-batch", response_model=BatchUploadResponse)
async def upload_items(request: Request, files: list[UploadFile] = File(...),
                       upload_ids: str | None = Form(None)) -> BatchUploadResponse:
    if not files or len(files) > MAX_BATCH_UPLOADS:
        raise HTTPException(status_code=400, detail=f"Upload between 1 and {MAX_BATCH_UPLOADS} images.")
    ids: list[str | None] = [None] * len(files)
    if upload_ids is not None:
        try:
            parsed = json.loads(upload_ids)
            if (not isinstance(parsed, list) or len(parsed) != len(files)
                    or any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in parsed)
                    or len(set(parsed)) != len(parsed)):
                raise ValueError
            ids = parsed
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="upload_ids must contain one unique ID per file.")
    deps.mutation_user_id(request)
    items: list[ClothingItemRecord] = []
    errors: list[BatchUploadFailure] = []
    for file, upload_id in zip(files, ids):
        try:
            items.append(await queue_uploaded_item(request, file, upload_id))
        except Exception as error:
            errors.append(BatchUploadFailure(filename=file.filename or "upload.jpg", detail=str(error)))
    return BatchUploadResponse(items=items, errors=errors, queued=[
        UploadQueueStatus(clothing_item_id=item.id, recognition_status=item.recognition_status,
                          image_path=item.image_path) for item in items])
