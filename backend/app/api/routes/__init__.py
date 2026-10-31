"""Aggregate v1 router and compatibility service aliases."""
from fastapi import APIRouter

from app.api.dependencies import *  # noqa: F403
from app.api.routes.items import router as items_router
from app.api.routes.preferences import router as preferences_router
from app.api.routes.recommendations import router as recommendations_router
from app.api.routes.system import router as system_router
from app.core.constants import API_V1_PREFIX

router = APIRouter(prefix=API_V1_PREFIX)
router.include_router(system_router)
router.include_router(items_router)
router.include_router(preferences_router)
router.include_router(recommendations_router)

from app.api.routes.items import queue_uploaded_item as _queue_uploaded_item  # noqa: F401
from app.api.routes.items import signed_item, signed_items  # noqa: F401
from app.api.routes.preferences import signed_preferences  # noqa: F401
from app.api.routes.recommendations import signed_recommendations  # noqa: F401
