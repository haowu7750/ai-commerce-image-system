from app.config import Settings
from app.providers.base import ModelProvider
from app.providers.mock_image import MockImageProvider
from app.providers.shulicode import ShulicodeImageProvider


def build_image_provider(settings: Settings) -> ModelProvider:
    if settings.image_provider == "mock":
        return MockImageProvider(model=settings.image_model)
    if settings.image_api_key is None:
        raise RuntimeError("APP_IMAGE_API_KEY is required when APP_IMAGE_PROVIDER=shulicode")
    return ShulicodeImageProvider(
        api_key=settings.image_api_key,
        base_url=settings.image_api_base_url,
        model=settings.image_model,
        timeout_seconds=settings.image_request_timeout_seconds,
    )

