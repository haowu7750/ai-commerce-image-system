from fastapi import APIRouter

from app.api.routes import (
    admin,
    auth,
    batch_images,
    content_ai,
    design_tasks,
    erp,
    generation,
    projects,
    reports,
    system,
    workflows,
)


api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    batch_images.router, prefix="/batch-image-tasks", tags=["batch-image-tasks"]
)
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(content_ai.router, prefix="/content-ai", tags=["content-ai"])
api_router.include_router(
    design_tasks.router, prefix="/design-tasks", tags=["design-tasks"]
)
api_router.include_router(
    workflows.router, prefix="/image-workflows", tags=["image-workflows"]
)
api_router.include_router(
    generation.router, prefix="/image-generations", tags=["image-generations"]
)
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(erp.router, prefix="/erp", tags=["erp"])
api_router.include_router(system.router, tags=["system"])
