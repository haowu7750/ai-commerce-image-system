from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import get_runtime_settings, require_roles
from app.models.enums import RoleName
from app.schemas.system import ImageRuntimeResponse, SafeConfigResponse


router = APIRouter()


@router.get("/config/safe", response_model=SafeConfigResponse)
def safe_config(
    settings: Settings = Depends(get_runtime_settings),
    _=Depends(require_roles(RoleName.ADMIN.value)),
) -> SafeConfigResponse:
    return SafeConfigResponse(
        app_name=settings.app_name,
        environment=settings.environment,
        debug=settings.debug,
        database_backend=settings.database_backend,
        image_provider=settings.image_provider,
        image_model=settings.image_model,
        image_api_configured=settings.image_api_configured,
        demo_seed_enabled=settings.seed_demo_data,
    )


@router.get("/config/image-runtime", response_model=ImageRuntimeResponse)
def image_runtime(
    settings: Settings = Depends(get_runtime_settings),
    _=Depends(
        require_roles(RoleName.OPERATOR.value, RoleName.ADMIN.value)
    ),
) -> ImageRuntimeResponse:
    return ImageRuntimeResponse(
        provider=settings.image_provider,
        model=settings.image_model,
        configured=settings.image_api_configured,
        paid_requests_enabled=(
            settings.image_provider != "mock" and settings.image_api_configured
        ),
    )
