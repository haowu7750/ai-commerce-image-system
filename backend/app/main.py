from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import Settings, get_settings
from app.database import Database
from app.providers.factory import build_image_provider
from app.schemas.system import HealthResponse
from app.services.bootstrap import seed_demo_accounts


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if runtime_settings.auto_create_tables:
            application.state.database.create_schema()
        with application.state.database.session_factory() as db:
            seed_demo_accounts(db, runtime_settings)
        yield
        await application.state.image_provider.close()
        application.state.database.engine.dispose()

    application = FastAPI(
        title=runtime_settings.app_name,
        debug=runtime_settings.debug,
        version="0.1.0",
        lifespan=lifespan,
    )
    configured_origin = runtime_settings.web_origin.rstrip("/")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(
            {
                configured_origin,
                configured_origin.replace("127.0.0.1", "localhost"),
            }
        ),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.state.settings = runtime_settings
    application.state.database = Database(runtime_settings)
    application.state.image_provider = build_image_provider(runtime_settings)

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            environment=runtime_settings.environment,
            image_provider=runtime_settings.image_provider,
            image_model=runtime_settings.image_model,
        )

    application.include_router(api_router, prefix=runtime_settings.api_prefix)
    return application


app = create_app()
