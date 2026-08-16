from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: str = "ai-commerce-operations-backend"
    environment: str
    image_provider: str
    image_model: str
    status: str = "ok"


class SafeConfigResponse(BaseModel):
    app_name: str
    environment: str
    debug: bool
    database_backend: str
    image_provider: str
    image_model: str
    image_api_configured: bool
    demo_seed_enabled: bool


class ImageRuntimeResponse(BaseModel):
    provider: str
    model: str
    configured: bool
    paid_requests_enabled: bool
    reference_mode: str = "edit"
