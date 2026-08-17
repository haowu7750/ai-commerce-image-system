from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commerce import Asset, ProductCard, Project
from app.models.enums import (
    AssetType,
    BatchImageItemStatus,
    BatchImageMode,
    BatchImageTaskStatus,
    ImageComplianceStatus,
    ImageQaStatus,
)
from app.models.generation import BatchImageItem, BatchImageTask
from app.models.identity import User
from app.providers.base import EditImageParams, ModelProvider, ProviderError
from app.schemas.batch_images import BatchImageTaskCreate
from app.services.audit import add_audit_event
from app.services.image_generation import asset_to_image_input


def create_batch_image_task(
    db: Session,
    *,
    payload: BatchImageTaskCreate,
    project: Project,
    user: User,
    provider: ModelProvider,
    request_id: str | None,
) -> tuple[BatchImageTask, bool]:
    existing = db.scalar(
        select(BatchImageTask).where(
            BatchImageTask.created_by_id == user.id,
            BatchImageTask.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if existing.project_id != project.id:
            raise ValueError("幂等键已被其他项目使用")
        return existing, False

    reference_ids = list(payload.product_reference_asset_ids)
    source_ids = list(payload.source_asset_ids)
    requested_ids = set(reference_ids + source_ids)
    assets = db.scalars(
        select(Asset).where(
            Asset.id.in_(requested_ids),
            Asset.project_id == project.id,
            Asset.is_archived.is_(False),
        )
    ).all()
    if len(assets) != len(requested_ids):
        raise LookupError("一个或多个图片素材不属于当前项目、已归档或不存在")
    by_id = {asset.id: asset for asset in assets}
    references = [by_id[asset_id] for asset_id in reference_ids]
    sources = [by_id[asset_id] for asset_id in source_ids]
    if any(asset.asset_type != AssetType.PRODUCT_REFERENCE for asset in references):
        raise ValueError("商品保真参考图必须使用“商品参考图”类型")
    if any(not asset.file_hash for asset in references + sources):
        raise ValueError("所有批量输入图片都必须有文件哈希，请重新上传")
    if project.product_card is None or project.product_card.confirmed_at is None:
        raise ValueError("批量改图前必须先由运营确认商品信息卡")

    prompt = build_batch_prompt(
        payload.mode,
        payload.instruction,
        project.product_card,
    )
    snapshot = {
        "product_card_id": project.product_card.id,
        "product_card_revision": project.product_card.revision,
        "reference_assets": [
            {"id": asset.id, "sha256": asset.file_hash} for asset in references
        ],
        "source_assets": [
            {"id": asset.id, "sha256": asset.file_hash} for asset in sources
        ],
        "unattended_or_scheduled": False,
    }
    task = BatchImageTask(
        project_id=project.id,
        created_by_id=user.id,
        mode=payload.mode,
        status=BatchImageTaskStatus.QUEUED,
        provider=provider.name,
        model=provider.default_model,
        prompt=prompt,
        options_json={"size": payload.size, "candidate_count_per_source": 1},
        product_reference_asset_ids_json=reference_ids,
        source_asset_ids_json=source_ids,
        input_snapshot_json=snapshot,
        idempotency_key=payload.idempotency_key,
        progress_total=len(sources),
    )
    db.add(task)
    db.flush()
    for position, source in enumerate(sources, start=1):
        db.add(
            BatchImageItem(
                task_id=task.id,
                source_asset_id=source.id,
                position=position,
                status=BatchImageItemStatus.QUEUED,
                metadata_json={"source_sha256": source.file_hash},
            )
        )
    add_audit_event(
        db,
        action="batch_image_task.created",
        object_type="batch_image_task",
        object_id=task.id,
        project_id=task.project_id,
        actor_id=user.id,
        request_id=request_id,
        payload_summary={
            "mode": payload.mode.value,
            "source_count": len(sources),
            "reference_count": len(references),
            "scheduled": False,
        },
    )
    db.commit()
    db.refresh(task)
    return task, True


def build_batch_prompt(
    mode: BatchImageMode,
    instruction: str,
    card: ProductCard,
) -> str:
    facts = {
        "商品名称": card.product_name,
        "品牌": card.brand,
        "商品事实": card.facts_json,
        "规格": card.specs_json,
        "禁改项": card.constraints_json,
    }
    fidelity = (
        "商品参考图是视觉事实源。严格保持商品的外形、结构、几何比例、材质、颜色、"
        "数量、Logo、可见文字、刻字和个性化信息；不得新增商品不存在的功能、认证、"
        "品牌或配件。商品事实：" + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    )
    instructions = {
        BatchImageMode.REPLACE_PRODUCT: (
            "将商品参考图中的真实商品替换到每张待处理图中；保留待处理图的场景、构图、"
            "主体位置和光照方向，并使透视、阴影自然融合。"
        ),
        BatchImageMode.CUSTOM_EDIT: (
            "对每张待处理图执行相同修改说明。只允许修改说明明确要求的环境或呈现方式，"
            "不得让修改说明覆盖商品保真规则。"
        ),
        BatchImageMode.RESIZE: (
            "将每张待处理图智能重排到目标尺寸；商品、文字和关键版式不变形、不裁切，"
            "缺失区域使用与原场景一致的内容自然扩展。"
        ),
    }
    user_instruction = instruction.strip()
    suffix = f"运营补充说明：{user_instruction}" if user_instruction else "运营未提供额外说明。"
    return f"{fidelity}\n{instructions[mode]}\n{suffix}"


async def run_batch_image_task(
    session_factory: Callable[[], Session],
    provider: ModelProvider,
    task_id: str,
    request_id: str | None,
) -> None:
    db = session_factory()
    try:
        task = db.scalar(select(BatchImageTask).where(BatchImageTask.id == task_id))
        if task is None or task.status != BatchImageTaskStatus.QUEUED:
            return
        task.status = BatchImageTaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        add_audit_event(
            db,
            action="batch_image_task.started",
            object_type="batch_image_task",
            object_id=task.id,
            project_id=task.project_id,
            actor_id=task.created_by_id,
            request_id=request_id,
            payload_summary={"progress_total": task.progress_total},
        )
        db.commit()

        references = db.scalars(
            select(Asset).where(
                Asset.id.in_(task.product_reference_asset_ids_json),
                Asset.project_id == task.project_id,
                Asset.is_archived.is_(False),
            )
        ).all()
        reference_by_id = {asset.id: asset for asset in references}
        ordered_references = [
            reference_by_id[asset_id]
            for asset_id in task.product_reference_asset_ids_json
            if asset_id in reference_by_id
        ]
        if len(ordered_references) != len(task.product_reference_asset_ids_json):
            raise ProviderError(
                "BATCH_REFERENCE_STALE",
                "商品参考图已变更或归档，请新建批量任务",
            )
        snapshot = task.input_snapshot_json or {}
        card = db.scalar(select(ProductCard).where(ProductCard.project_id == task.project_id))
        if (
            card is None
            or card.confirmed_at is None
            or card.revision != snapshot.get("product_card_revision")
        ):
            raise ProviderError(
                "BATCH_PRODUCT_CARD_STALE",
                "商品信息卡已变化，请基于最新确认事实新建批量任务",
            )
        expected_reference_hashes = {
            row.get("id"): row.get("sha256")
            for row in snapshot.get("reference_assets", [])
            if isinstance(row, dict)
        }
        if any(
            expected_reference_hashes.get(asset.id) != asset.file_hash
            for asset in ordered_references
        ):
            raise ProviderError(
                "BATCH_REFERENCE_STALE",
                "商品参考图内容已变化，请新建批量任务",
            )

        for item in task.items:
            item.status = BatchImageItemStatus.RUNNING
            db.commit()
            try:
                source = db.scalar(
                    select(Asset).where(
                        Asset.id == item.source_asset_id,
                        Asset.project_id == task.project_id,
                        Asset.is_archived.is_(False),
                    )
                )
                if source is None:
                    raise ProviderError(
                        "BATCH_SOURCE_STALE", "待处理图片已变更或归档，请新建批量任务"
                    )
                if (item.metadata_json or {}).get("source_sha256") != source.file_hash:
                    raise ProviderError(
                        "BATCH_SOURCE_STALE", "待处理图片内容已变化，请新建批量任务"
                    )
                inputs = [
                    *(asset_to_image_input(asset) for asset in ordered_references),
                    asset_to_image_input(source),
                ]
                response = await provider.edit_image(
                    EditImageParams(
                        prompt=task.prompt,
                        model=task.model,
                        n=1,
                        size=str(task.options_json.get("size", "1024x1024")),
                    ),
                    inputs,
                )
                if not response.images:
                    raise ProviderError(
                        "IMAGE_PROVIDER_RESPONSE_EMPTY", "图片服务没有返回候选图"
                    )
                output = response.images[0]
                item.output_mime_type = "image/png" if output.b64_json else None
                item.provider_url = output.url
                item.b64_json = output.b64_json
                item.revised_prompt = output.revised_prompt
                item.metadata_json = {
                    **(item.metadata_json or {}),
                    **output.metadata,
                    "provider_response": response.metadata,
                    "input_order": [
                        *[asset.id for asset in ordered_references], source.id
                    ],
                }
                item.status = BatchImageItemStatus.SUCCEEDED
                task.succeeded_count += 1
                add_audit_event(
                    db,
                    action="batch_image_item.succeeded",
                    object_type="batch_image_item",
                    object_id=item.id,
                    project_id=task.project_id,
                    actor_id=task.created_by_id,
                    request_id=request_id,
                    payload_summary={"position": item.position},
                )
            except ProviderError as exc:
                item.status = BatchImageItemStatus.FAILED
                item.error_code = exc.code
                item.error_message = exc.safe_message
                task.failed_count += 1
                add_audit_event(
                    db,
                    action="batch_image_item.failed",
                    object_type="batch_image_item",
                    object_id=item.id,
                    project_id=task.project_id,
                    actor_id=task.created_by_id,
                    request_id=request_id,
                    payload_summary={"position": item.position, "error_code": exc.code},
                    result="failed",
                )
            except Exception:
                item.status = BatchImageItemStatus.FAILED
                item.error_code = "BATCH_ITEM_INTERNAL_ERROR"
                item.error_message = "该图片处理失败，请保留其他成功结果并重试此图片"
                task.failed_count += 1
                add_audit_event(
                    db,
                    action="batch_image_item.failed",
                    object_type="batch_image_item",
                    object_id=item.id,
                    project_id=task.project_id,
                    actor_id=task.created_by_id,
                    request_id=request_id,
                    payload_summary={
                        "position": item.position,
                        "error_code": "BATCH_ITEM_INTERNAL_ERROR",
                    },
                    result="failed",
                )
            task.progress_done += 1
            db.commit()

        if task.succeeded_count == task.progress_total:
            task.status = BatchImageTaskStatus.SUCCEEDED
        elif task.succeeded_count > 0:
            task.status = BatchImageTaskStatus.PARTIAL
            task.error_code = "BATCH_PARTIAL_FAILURE"
            task.error_message = "部分图片修改失败，可保留成功结果并重新提交失败图片"
        else:
            task.status = BatchImageTaskStatus.FAILED
            task.error_code = "BATCH_ALL_FAILED"
            task.error_message = "全部图片修改失败，请检查输入或图片服务配置"
        task.finished_at = datetime.now(timezone.utc)
        add_audit_event(
            db,
            action="batch_image_task.completed",
            object_type="batch_image_task",
            object_id=task.id,
            project_id=task.project_id,
            actor_id=task.created_by_id,
            request_id=request_id,
            payload_summary={
                "status": task.status.value,
                "succeeded_count": task.succeeded_count,
                "failed_count": task.failed_count,
            },
            result="success" if task.succeeded_count else "failed",
        )
        db.commit()
    except ProviderError as exc:
        task = db.scalar(select(BatchImageTask).where(BatchImageTask.id == task_id))
        if task is not None:
            task.status = BatchImageTaskStatus.FAILED
            task.error_code = exc.code
            task.error_message = exc.safe_message
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        task = db.scalar(select(BatchImageTask).where(BatchImageTask.id == task_id))
        if task is not None:
            task.status = BatchImageTaskStatus.FAILED
            task.error_code = "BATCH_TASK_INTERNAL_ERROR"
            task.error_message = "批量任务执行失败，已保存现有进度，请重新提交"
            task.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
