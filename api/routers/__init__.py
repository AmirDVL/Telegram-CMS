from api.routers.admins import router as admins_router
from api.routers.ai_settings import router as ai_settings_router
from api.routers.audit import router as audit_router
from api.routers.queue import router as queue_router
from api.routers.source_channels import router as source_channels_router
from api.routers.tags import router as tags_router
from api.routers.templates import router as templates_router
from api.routers.tenants import router as tenants_router

__all__ = [
    "admins_router",
    "ai_settings_router",
    "audit_router",
    "queue_router",
    "source_channels_router",
    "tags_router",
    "templates_router",
    "tenants_router",
]
