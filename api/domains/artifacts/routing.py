"""Compose the artifact domain's management, download and runtime HTTP surfaces."""

from fastapi import APIRouter

from api.domains.artifacts.download_routes import router as download_router
from api.domains.artifacts.routes import router as management_router
from api.domains.artifacts.runtime_routes import router as runtime_router

router = APIRouter()
router.include_router(management_router)
router.include_router(download_router)
router.include_router(runtime_router)
