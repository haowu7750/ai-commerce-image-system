from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_roles
from app.models.collaboration import DesignTask, SystemResource
from app.models.commerce import AuditEvent, ContentVersion, Project
from app.models.enums import ImageJobStatus, ImageWorkflowStatus, ProjectStatus, RoleName
from app.models.generation import (
    BatchImageItem,
    BatchImageTask,
    ImageGenerationJob,
    ImageGenerationOutput,
    ImageWorkflow,
)
from app.models.identity import User
from app.schemas.reports import (
    DesignArtifactView,
    ImageArtifactView,
    KnowledgeCaseCreate,
    LibraryKind,
    LibraryResourceView,
    ProjectDeliveryPackage,
    TextExportView,
    TimelineEventView,
)
from app.services.audit import add_audit_event


router = APIRouter()


def _owned_project(db: Session, project_id: str, operator_id: str) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.created_by_id == operator_id,
            Project.status != ProjectStatus.ARCHIVED,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _card_snapshot(project: Project) -> dict[str, Any] | None:
    card = project.product_card
    if card is None:
        return None
    return {
        "id": card.id,
        "product_name": card.product_name,
        "brand": card.brand,
        "current_title": card.current_title,
        "facts": card.facts_json,
        "selling_points": card.selling_points_json,
        "specs": card.specs_json,
        "constraints": card.constraints_json,
        "field_sources": card.field_sources_json,
        "revision": card.revision,
        "confirmed_by_id": card.confirmed_by_id,
        "confirmed_at": card.confirmed_at.isoformat() if card.confirmed_at else None,
    }


def _final_content(db: Session, project_id: str) -> dict[str, dict[str, Any]]:
    versions = db.scalars(
        select(ContentVersion).where(
            ContentVersion.project_id == project_id,
            ContentVersion.is_final.is_(True),
        )
    ).all()
    return {version.content_type: version.content_json for version in versions}


def _accepted_designs(db: Session, project_id: str) -> list[DesignArtifactView]:
    tasks = db.scalars(
        select(DesignTask).where(
            DesignTask.project_id == project_id,
            DesignTask.status == "completed",
        )
    ).all()
    artifacts: list[DesignArtifactView] = []
    for task in tasks:
        if not task.submissions:
            continue
        submission = max(task.submissions, key=lambda item: item.version_no)
        artifacts.append(
            DesignArtifactView(
                task_id=task.id,
                task_title=task.title,
                submission_id=submission.id,
                version_no=submission.version_no,
                file_url=submission.file_url,
                notes=submission.notes,
            )
        )
    return artifacts


def _confirmed_images(db: Session, project_id: str) -> list[ImageArtifactView]:
    workflows = db.scalars(
        select(ImageWorkflow).where(
            ImageWorkflow.project_id == project_id,
            ImageWorkflow.status == ImageWorkflowStatus.OPERATOR_CONFIRMED,
        )
    ).all()
    artifacts: list[ImageArtifactView] = []
    for workflow in workflows:
        jobs = db.scalars(
            select(ImageGenerationJob).where(
                ImageGenerationJob.workflow_id == workflow.id,
                ImageGenerationJob.status == ImageJobStatus.SUCCEEDED,
            )
        ).all()
        for job in jobs:
            outputs = db.scalars(
                select(ImageGenerationOutput).where(
                    ImageGenerationOutput.job_id == job.id
                )
            ).all()
            artifacts.extend(
                ImageArtifactView(
                    workflow_id=workflow.id,
                    job_id=job.id,
                    output_id=output.id,
                    asset_id=output.asset_id,
                    provider=job.provider,
                    model=job.model,
                    mime_type=output.mime_type,
                    provider_url=output.provider_url,
                    preview_data_url=(
                        f"data:{output.mime_type or 'image/png'};base64,{output.b64_json}"
                        if output.b64_json
                        else None
                    ),
                    revised_prompt=output.revised_prompt,
                )
                for output in outputs
            )
    batch_items = db.scalars(
        select(BatchImageItem)
        .join(BatchImageTask, BatchImageTask.id == BatchImageItem.task_id)
        .where(
            BatchImageTask.project_id == project_id,
            BatchImageItem.confirmed_at.is_not(None),
        )
        .order_by(BatchImageTask.created_at, BatchImageItem.position)
    ).all()
    for item in batch_items:
        task = db.get(BatchImageTask, item.task_id)
        if task is None:
            continue
        artifacts.append(
            ImageArtifactView(
                workflow_id=f"batch:{task.id}",
                job_id=task.id,
                output_id=item.id,
                asset_id=item.output_asset_id,
                provider=task.provider,
                model=task.model,
                mime_type=item.output_mime_type,
                provider_url=item.provider_url,
                preview_data_url=(
                    f"data:{item.output_mime_type or 'image/png'};base64,{item.b64_json}"
                    if item.b64_json
                    else None
                ),
                revised_prompt=item.revised_prompt,
            )
        )
    return artifacts


def _timeline(db: Session, project_id: str) -> list[TimelineEventView]:
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.project_id == project_id)
        .order_by(AuditEvent.created_at.desc())
    ).all()
    return [
        TimelineEventView(
            id=event.id,
            action=event.action,
            object_type=event.object_type,
            object_id=event.object_id,
            actor_id=event.actor_id,
            summary=event.payload_summary_json,
            result=event.result,
            created_at=event.created_at,
        )
        for event in events
    ]


def _delivery_blockers(
    project: Project,
    final_content: dict[str, dict[str, Any]],
    images: list[ImageArtifactView],
) -> list[str]:
    blockers: list[str] = []
    if project.product_card is None or project.product_card.confirmed_at is None:
        blockers.append("商品信息卡尚未由运营确认")
    if "title" not in final_content:
        blockers.append("最终标题尚未由运营确认")
    for content in final_content.values():
        risk = str(content.get("risk_level", content.get("compliance_status", ""))).lower()
        if risk in {"high", "high_open", "blocked"}:
            blockers.append("存在高风险内容，禁止交付或写回")
            break
    if not images:
        blockers.append("尚无运营确认通过的生图结果")
    return blockers


def build_package(db: Session, project: Project) -> ProjectDeliveryPackage:
    final_content = _final_content(db, project.id)
    images = _confirmed_images(db, project.id)
    return ProjectDeliveryPackage(
        project={
            "id": project.id,
            "name": project.name,
            "platform": project.platform,
            "store_name": project.store_name,
            "category": project.category,
            "status": project.status.value,
            "updated_at": project.updated_at.isoformat(),
        },
        product_card=_card_snapshot(project),
        final_content=final_content,
        accepted_designs=_accepted_designs(db, project.id),
        confirmed_images=images,
        blockers=_delivery_blockers(project, final_content, images),
        timeline=_timeline(db, project.id),
    )


@router.get("/projects/{project_id}", response_model=ProjectDeliveryPackage)
def get_delivery_package(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ProjectDeliveryPackage:
    return build_package(db, _owned_project(db, project_id, operator.id))


def _markdown(package: ProjectDeliveryPackage) -> str:
    lines = [
        f"# {package.project['name']} - 运营成果包",
        "",
        f"- 平台：{package.project['platform']}",
        f"- 店铺：{package.project['store_name']}",
        f"- 状态：{package.project['status']}",
        "",
        "## 商品事实",
        "",
        "```json",
        json.dumps(package.product_card or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 定稿内容",
        "",
        "```json",
        json.dumps(package.final_content, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 已确认生图",
        "",
    ]
    if package.confirmed_images:
        lines.extend(
            f"- 输出 {item.output_id} | {item.provider}/{item.model} | {item.provider_url or '已保存到本地素材'}"
            for item in package.confirmed_images
        )
    else:
        lines.append("- 暂无")
    lines.extend(["", "## 交付门禁", ""])
    lines.extend(f"- {item}" for item in package.blockers or ["全部关键门禁已通过"])
    return "\n".join(lines) + "\n"


@router.get("/projects/{project_id}/exports/markdown", response_model=TextExportView)
def export_markdown(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> TextExportView:
    package = build_package(db, _owned_project(db, project_id, operator.id))
    return TextExportView(
        filename=f"{package.project['name']}-运营成果包.md",
        mime_type="text/markdown;charset=utf-8",
        content=_markdown(package),
    )


def _sku_rows(content: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("items", "skus", "variants", "rows"):
        value = content.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [content] if content else []


@router.get("/projects/{project_id}/exports/sku-csv", response_model=TextExportView)
def export_sku_csv(
    project_id: str,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> TextExportView:
    project = _owned_project(db, project_id, operator.id)
    sku = _final_content(db, project.id).get("sku")
    if not sku:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先由运营确认一个最终 SKU 版本",
        )
    rows = _sku_rows(sku)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row.keys()))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames or ["sku"])
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            }
        )
    return TextExportView(
        filename=f"{project.name}-SKU.csv",
        mime_type="text/csv;charset=utf-8",
        content="\ufeff" + output.getvalue(),
    )


@router.post(
    "/projects/{project_id}/knowledge-case",
    response_model=LibraryResourceView,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_case(
    project_id: str,
    payload: KnowledgeCaseCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> LibraryResourceView:
    project = _owned_project(db, project_id, operator.id)
    package = build_package(db, project)
    if package.blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="成果仍有门禁，不能沉淀为典型案例：" + "；".join(package.blockers),
        )
    existing = db.scalar(
        select(SystemResource).where(
            SystemResource.kind == "knowledge_case",
            SystemResource.name == payload.name,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="案例名称已存在")
    resource = SystemResource(
        kind="knowledge_case",
        name=payload.name,
        description=payload.notes,
        content_json={
            "source_project_id": project.id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "product_card": package.product_card,
            "final_content": package.final_content,
            "confirmed_images": [item.model_dump(mode="json") for item in package.confirmed_images],
        },
        version=1,
        is_active=True,
        updated_by_id=operator.id,
    )
    db.add(resource)
    db.flush()
    add_audit_event(
        db,
        action="knowledge_case.created",
        object_type="system_resource",
        object_id=resource.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"name": resource.name, "version": resource.version},
    )
    db.commit()
    db.refresh(resource)
    return LibraryResourceView(
        id=resource.id,
        kind=resource.kind,
        name=resource.name,
        description=resource.description,
        content=resource.content_json,
        version=resource.version,
        updated_at=resource.updated_at,
    )


@router.get("/library", response_model=list[LibraryResourceView])
def list_library(
    kind: LibraryKind | None = None,
    query: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    _operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[LibraryResourceView]:
    statement = select(SystemResource).where(SystemResource.is_active.is_(True))
    if kind:
        statement = statement.where(SystemResource.kind == kind)
    else:
        statement = statement.where(
            SystemResource.kind.in_(["prompt", "compliance_rule", "knowledge_case"])
        )
    if query and query.strip():
        statement = statement.where(SystemResource.name.contains(query.strip()))
    resources = db.scalars(statement.order_by(SystemResource.updated_at.desc())).all()
    return [
        LibraryResourceView(
            id=item.id,
            kind=item.kind,
            name=item.name,
            description=item.description,
            content=item.content_json,
            version=item.version,
            updated_at=item.updated_at,
        )
        for item in resources
    ]
