from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_model_provider, require_roles
from app.models.commerce import Asset, ProductCard, Project
from app.models.enums import (
    AssetType,
    BatchImageItemStatus,
    BatchImageMode,
    BatchImageTaskStatus,
    ImageComplianceStatus,
    ImageQaStatus,
    ProjectStatus,
    RoleName,
)
from app.models.generation import BatchImageItem, BatchImageTask
from app.models.identity import User
from app.providers.base import ModelProvider
from app.schemas.batch_images import (
    BatchImageItemConfirm,
    BatchImageItemReview,
    BatchImageItemView,
    BatchImageTaskCreate,
    BatchImageTaskSelection,
    BatchImageTaskView,
)
from app.services.audit import add_audit_event
from app.services.batch_images import create_batch_image_task, run_batch_image_task


router = APIRouter()


def to_item_view(item: BatchImageItem) -> BatchImageItemView:
    return BatchImageItemView(
        id=item.id,
        task_id=item.task_id,
        source_asset_id=item.source_asset_id,
        output_asset_id=item.output_asset_id,
        position=item.position,
        status=item.status,
        error_code=item.error_code,
        error_message=item.error_message,
        output_mime_type=item.output_mime_type,
        provider_url=item.provider_url,
        preview_data_url=(
            f"data:{item.output_mime_type or 'image/png'};base64,{item.b64_json}"
            if item.b64_json
            else item.provider_url
        ),
        revised_prompt=item.revised_prompt,
        metadata=item.metadata_json or {},
        qa_status=item.qa_status,
        compliance_status=item.compliance_status,
        review_report=item.review_report_json or {},
        reviewed_by_id=item.reviewed_by_id,
        reviewed_at=item.reviewed_at,
        confirmed_by_id=item.confirmed_by_id,
        confirmed_at=item.confirmed_at,
        revision=item.revision,
    )


def to_task_view(task: BatchImageTask) -> BatchImageTaskView:
    return BatchImageTaskView(
        id=task.id,
        project_id=task.project_id,
        created_by_id=task.created_by_id,
        mode=task.mode,
        status=task.status,
        provider=task.provider,
        model=task.model,
        prompt=task.prompt,
        options=task.options_json or {},
        product_reference_asset_ids=task.product_reference_asset_ids_json or [],
        source_asset_ids=task.source_asset_ids_json or [],
        is_archived=bool((task.options_json or {}).get("archived_at")),
        progress_total=task.progress_total,
        progress_done=task.progress_done,
        succeeded_count=task.succeeded_count,
        failed_count=task.failed_count,
        error_code=task.error_code,
        error_message=task.error_message,
        started_at=task.started_at,
        finished_at=task.finished_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        items=[to_item_view(item) for item in task.items],
    )


def owned_task(db: Session, task_id: str, operator_id: str) -> BatchImageTask:
    task = db.scalar(
        select(BatchImageTask).where(
            BatchImageTask.id == task_id,
            BatchImageTask.created_by_id == operator_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="批量任务不存在")
    return task


def owned_item(
    db: Session, task_id: str, item_id: str, operator_id: str
) -> tuple[BatchImageTask, BatchImageItem]:
    task = owned_task(db, task_id, operator_id)
    item = db.scalar(
        select(BatchImageItem).where(
            BatchImageItem.id == item_id,
            BatchImageItem.task_id == task.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="批量结果不存在")
    return task, item


def confirmed_local_items(task: BatchImageTask) -> list[BatchImageItem]:
    return [item for item in task.items if item.confirmed_at and item.b64_json]


def build_result_archive(tasks: list[BatchImageTask]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for task in tasks:
            for item in confirmed_local_items(task):
                extension = "jpg" if item.output_mime_type == "image/jpeg" else "png"
                archive.writestr(
                    f"{task.mode.value}-{task.id}-{item.position:02d}.{extension}",
                    base64.b64decode(item.b64_json or ""),
                )
    buffer.seek(0)
    return buffer


def ensure_task_inputs_current(db: Session, task: BatchImageTask) -> None:
    if (task.options_json or {}).get("archived_at"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务已删除，请先恢复")
    project = db.get(Project, task.project_id)
    if project is None or project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目已删除，请先恢复")
    if project.status == ProjectStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目已完成，请先重新开启")
    snapshot = task.input_snapshot_json or {}
    card = db.scalar(select(ProductCard).where(ProductCard.project_id == task.project_id))
    if (
        card is None
        or card.confirmed_at is None
        or card.revision != snapshot.get("product_card_revision")
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="商品信息卡已变化，旧批量候选已失效，请新建任务",
        )
    expected_hashes = {
        row.get("id"): row.get("sha256")
        for key in ("reference_assets", "source_assets", "secondary_assets")
        for row in snapshot.get(key, [])
        if isinstance(row, dict)
    }
    assets = db.scalars(
        select(Asset).where(
            Asset.id.in_(expected_hashes),
            Asset.project_id == task.project_id,
            Asset.is_archived.is_(False),
        )
    ).all()
    if len(assets) != len(expected_hashes) or any(
        expected_hashes.get(asset.id) != asset.file_hash for asset in assets
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="批量任务输入图片已变化或归档，旧候选已失效，请新建任务",
        )


@router.post("", response_model=BatchImageTaskView, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: BatchImageTaskCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
    provider: ModelProvider = Depends(get_model_provider),
) -> BatchImageTaskView:
    project = db.scalar(
        select(Project).where(
            Project.id == payload.project_id,
            Project.created_by_id == operator.id,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目已删除，请先恢复")
    if project.status == ProjectStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目已完成，请先重新开启")
    request_id = getattr(request.state, "request_id", None)
    try:
        task, created = create_batch_image_task(
            db,
            payload=payload,
            project=project,
            user=operator,
            provider=provider,
            request_id=request_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if created:
        background_tasks.add_task(
            run_batch_image_task,
            request.app.state.database.session_factory,
            provider,
            task.id,
            request_id,
        )
    return to_task_view(task)


@router.get("", response_model=list[BatchImageTaskView])
def list_tasks(
    project_id: str | None = None,
    mode: BatchImageMode | None = None,
    task_status: BatchImageTaskStatus | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[BatchImageTaskView]:
    query = (
        select(BatchImageTask)
        .where(BatchImageTask.created_by_id == operator.id)
        .order_by(BatchImageTask.created_at.desc())
    )
    if project_id:
        query = query.where(BatchImageTask.project_id == project_id)
    if mode:
        query = query.where(BatchImageTask.mode == mode)
    if task_status:
        query = query.where(BatchImageTask.status == task_status)
    tasks = list(db.scalars(query).all())
    if not include_archived:
        tasks = [task for task in tasks if not (task.options_json or {}).get("archived_at")]
    return [to_task_view(task) for task in tasks]


@router.post("/download-selection")
def download_selected_results(
    payload: BatchImageTaskSelection,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> StreamingResponse:
    tasks = list(
        db.scalars(
            select(BatchImageTask).where(
                BatchImageTask.id.in_(payload.task_ids),
                BatchImageTask.created_by_id == operator.id,
            )
        ).all()
    )
    if len(tasks) != len(set(payload.task_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="一个或多个批量任务不存在")
    if not any(confirmed_local_items(task) for task in tasks):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="所选任务暂无已由运营确认且可本地打包的图片",
        )
    return StreamingResponse(
        build_result_archive(tasks),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="batch-selected-confirmed.zip"'},
    )


@router.post("/archive-selection", response_model=list[BatchImageTaskView])
def archive_selected_tasks(
    payload: BatchImageTaskSelection,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[BatchImageTaskView]:
    tasks = list(
        db.scalars(
            select(BatchImageTask).where(
                BatchImageTask.id.in_(payload.task_ids),
                BatchImageTask.created_by_id == operator.id,
            )
        ).all()
    )
    if len(tasks) != len(set(payload.task_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="一个或多个批量任务不存在")
    if any(task.status in {BatchImageTaskStatus.QUEUED, BatchImageTaskStatus.RUNNING} for task in tasks):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="排队中或运行中的任务不能删除")
    archived_at = datetime.now(timezone.utc).isoformat()
    for task in tasks:
        task.options_json = {
            **(task.options_json or {}),
            "archived_at": archived_at,
            "archived_by_id": operator.id,
        }
        add_audit_event(
            db,
            action="batch_image_task.archived",
            object_type="batch_image_task",
            object_id=task.id,
            project_id=task.project_id,
            actor_id=operator.id,
            request_id=getattr(request.state, "request_id", None),
            payload_summary={"soft_delete": True},
        )
    db.commit()
    return [to_task_view(task) for task in tasks]


@router.get("/{task_id}", response_model=BatchImageTaskView)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> BatchImageTaskView:
    return to_task_view(owned_task(db, task_id, operator.id))


@router.delete("/{task_id}", response_model=BatchImageTaskView)
def archive_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> BatchImageTaskView:
    task = owned_task(db, task_id, operator.id)
    if task.status in {BatchImageTaskStatus.QUEUED, BatchImageTaskStatus.RUNNING}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="排队中或运行中的任务不能删除")
    task.options_json = {
        **(task.options_json or {}),
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "archived_by_id": operator.id,
    }
    add_audit_event(
        db,
        action="batch_image_task.archived",
        object_type="batch_image_task",
        object_id=task.id,
        project_id=task.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"soft_delete": True},
    )
    db.commit()
    return to_task_view(task)


@router.post("/{task_id}/restore", response_model=BatchImageTaskView)
def restore_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> BatchImageTaskView:
    task = owned_task(db, task_id, operator.id)
    task.options_json = {
        key: value
        for key, value in (task.options_json or {}).items()
        if key not in {"archived_at", "archived_by_id"}
    }
    add_audit_event(
        db,
        action="batch_image_task.restored",
        object_type="batch_image_task",
        object_id=task.id,
        project_id=task.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"soft_delete": True},
    )
    db.commit()
    return to_task_view(task)


@router.post("/{task_id}/items/{item_id}/review", response_model=BatchImageItemView)
def review_item(
    task_id: str,
    item_id: str,
    payload: BatchImageItemReview,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> BatchImageItemView:
    task, item = owned_item(db, task_id, item_id, operator.id)
    ensure_task_inputs_current(db, task)
    if item.status != BatchImageItemStatus.SUCCEEDED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有成功生成的候选图可以检查")
    if item.confirmed_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已确认结果不能覆盖检查记录")
    if item.reviewed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="检查记录不可覆盖；如需修改图片，请新建批量任务产生新候选",
        )
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="结果版本已变化，请刷新后重试")
    checks = (
        payload.product_facts_match,
        payload.geometry_and_count_match,
        payload.logo_text_and_personalization_match,
        payload.thumbnail_readable,
    )
    item.qa_status = ImageQaStatus.PASSED if all(checks) else ImageQaStatus.FAILED
    if payload.compliance_risk == "high":
        item.compliance_status = ImageComplianceStatus.HIGH_OPEN
    elif payload.compliance_risk == "medium":
        item.compliance_status = ImageComplianceStatus.MEDIUM_RESOLVED
    else:
        item.compliance_status = ImageComplianceStatus.CLEAR
    item.review_report_json = payload.model_dump()
    item.reviewed_by_id = operator.id
    item.reviewed_at = datetime.now(timezone.utc)
    item.revision += 1
    add_audit_event(
        db,
        action="batch_image_item.reviewed",
        object_type="batch_image_item",
        object_id=item.id,
        project_id=task.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "qa_status": item.qa_status.value,
            "compliance_status": item.compliance_status.value,
        },
    )
    db.commit()
    db.refresh(item)
    return to_item_view(item)


@router.post("/{task_id}/items/{item_id}/confirm", response_model=BatchImageItemView)
def confirm_item(
    task_id: str,
    item_id: str,
    payload: BatchImageItemConfirm,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> BatchImageItemView:
    task, item = owned_item(db, task_id, item_id, operator.id)
    ensure_task_inputs_current(db, task)
    if item.revision != payload.expected_revision:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="结果版本已变化，请刷新后重试")
    if item.confirmed_at is not None:
        return to_item_view(item)
    denial_reason = None
    if item.qa_status != ImageQaStatus.PASSED:
        denial_reason = "真实性或缩略图检查未通过"
    elif item.compliance_status not in {
        ImageComplianceStatus.CLEAR,
        ImageComplianceStatus.MEDIUM_RESOLVED,
    }:
        denial_reason = "合规风险尚未处理，不能确认"
    if denial_reason:
        add_audit_event(
            db,
            action="batch_image_item.confirmation_denied",
            object_type="batch_image_item",
            object_id=item.id,
            project_id=task.project_id,
            actor_id=operator.id,
            request_id=getattr(request.state, "request_id", None),
            payload_summary={"reason": denial_reason},
            result="denied",
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=denial_reason)

    file_hash = None
    file_size = None
    file_url = item.provider_url
    if item.b64_json:
        raw = base64.b64decode(item.b64_json)
        file_hash = hashlib.sha256(raw).hexdigest()
        file_size = len(raw)
        file_url = f"data:{item.output_mime_type or 'image/png'};base64,{item.b64_json}"
    asset = Asset(
        project_id=task.project_id,
        uploaded_by_id=operator.id,
        asset_type=AssetType.GENERATED_IMAGE,
        source="ai_batch",
        file_url=file_url,
        file_hash=file_hash,
        mime_type=item.output_mime_type,
        file_size=file_size,
        metadata_json={
            "batch_task_id": task.id,
            "batch_item_id": item.id,
            "batch_mode": task.mode.value,
            "source_asset_id": item.source_asset_id,
            "operator_confirmed": True,
        },
    )
    db.add(asset)
    db.flush()
    item.output_asset_id = asset.id
    item.confirmed_by_id = operator.id
    item.confirmed_at = datetime.now(timezone.utc)
    item.revision += 1
    add_audit_event(
        db,
        action="batch_image_item.operator_confirmed",
        object_type="batch_image_item",
        object_id=item.id,
        project_id=task.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"output_asset_id": asset.id, "no_publish_or_erp": True},
    )
    db.commit()
    db.refresh(item)
    return to_item_view(item)


@router.get("/{task_id}/download")
def download_confirmed_results(
    task_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> StreamingResponse:
    task = owned_task(db, task_id, operator.id)
    confirmed = confirmed_local_items(task)
    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="暂无已由运营确认且可本地打包的图片",
        )
    return StreamingResponse(
        build_result_archive([task]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="batch-{task.id}-confirmed.zip"'
        },
    )
