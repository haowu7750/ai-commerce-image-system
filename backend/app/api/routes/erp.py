from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_roles
from app.erp.base import ERPConnectorCapabilities, UnifiedProduct
from app.erp.mock import DEFAULT_FIELD_MAPPING, MockERPConnector
from app.models.commerce import ContentVersion, ProductCard, Project
from app.models.enums import (
    ContentStatus,
    ImageComplianceStatus,
    ProjectStatus,
    RoleName,
)
from app.models.erp import (
    ERPExternalEntityMapping,
    ERPFieldMapping,
    ERPSyncRecord,
    ERPWritebackPreview,
)
from app.models.generation import ImageWorkflow
from app.models.identity import User
from app.schemas.erp import (
    ERPExternalEntityMappingView,
    ERPFieldMappingCreate,
    ERPFieldMappingView,
    ERPImportApplyView,
    ERPImportPreviewRequest,
    ERPImportPreviewView,
    ERPMockExternalChangeView,
    ERPSyncRecordView,
    ERPWritebackConfirmRequest,
    ERPWritebackPreviewRequest,
    ERPWritebackPreviewView,
)
from app.services.audit import add_audit_event


router = APIRouter()

CANONICAL_MAPPING_FIELDS = {
    "external_id",
    "external_version",
    "name",
    "brand",
    "title",
    "category",
    "facts",
    "selling_points",
    "specs",
    "skus",
    "images",
}
REQUIRED_MAPPING_FIELDS = {"external_id", "external_version", "name"}
PROTECTED_WRITEBACK_FIELDS = {
    "price",
    "inventory",
    "stock",
    "merchant_code",
    "merchantcode",
    "seller_sku",
    "sellersku",
    "sku_code",
    "skucode",
    "source_code",
    "sourcecode",
}
SAFE_COMPLIANCE_VALUES = {
    "clear",
    "low",
    "low_risk",
    "passed",
    "approved",
    "safe",
    "resolved",
    "medium_resolved",
}
BLOCKED_RISK_VALUES = {
    "high",
    "high_open",
    "blocked",
    "medium",
    "medium_open",
    "failed",
}


def _sync_view(record: ERPSyncRecord) -> ERPSyncRecordView:
    return ERPSyncRecordView.model_validate(record)


def _owned_project(db: Session, project_id: str, operator: User) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.created_by_id == operator.id,
        )
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived projects cannot use ERP operations",
        )
    return project


def _validate_field_mapping(mapping: dict[str, str]) -> dict[str, str]:
    unknown = set(mapping) - CANONICAL_MAPPING_FIELDS
    missing = REQUIRED_MAPPING_FIELDS - set(mapping)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown canonical mapping fields: {', '.join(sorted(unknown))}",
        )
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required mapping fields: {', '.join(sorted(missing))}",
        )
    if any(not path.strip() for path in mapping.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Field mapping paths cannot be blank",
        )
    return {key: path.strip() for key, path in mapping.items()}


def _resolved_field_mapping(
    db: Session, payload: ERPImportPreviewRequest
) -> dict[str, str]:
    if payload.field_mapping_id:
        saved = db.scalar(
            select(ERPFieldMapping).where(
                ERPFieldMapping.id == payload.field_mapping_id,
                ERPFieldMapping.connector_key == "mock",
                ERPFieldMapping.is_active.is_(True),
            )
        )
        if saved is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active ERP field mapping not found",
            )
        return _validate_field_mapping(saved.mapping_json)
    return _validate_field_mapping(payload.field_mapping or deepcopy(DEFAULT_FIELD_MAPPING))


def _add_sync_record(
    db: Session,
    *,
    direction: str,
    operation: str,
    record_status: str,
    actor_id: str,
    project_id: str | None = None,
    external_entity_id: str | None = None,
    external_version_before: str | None = None,
    external_version_after: str | None = None,
    idempotency_key: str | None = None,
    request_json: dict[str, Any] | None = None,
    result_json: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> ERPSyncRecord:
    record = ERPSyncRecord(
        connector_key="mock",
        direction=direction,
        operation=operation,
        status=record_status,
        actor_id=actor_id,
        project_id=project_id,
        external_entity_id=external_entity_id,
        external_version_before=external_version_before,
        external_version_after=external_version_after,
        idempotency_key=idempotency_key,
        request_json=request_json or {},
        result_json=result_json or {},
        error_message=error_message,
    )
    db.add(record)
    db.flush()
    return record


def _contains_blocked_risk(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key in {
                "risk_level",
                "risk",
                "severity",
                "compliance_status",
                "status",
            } and str(child).lower() in BLOCKED_RISK_VALUES:
                return True
            if _contains_blocked_risk(child):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_blocked_risk(child) for child in value)
    return False


def _compliance_value(content: dict[str, Any]) -> str:
    return str(
        content.get(
            "risk_level",
            content.get("compliance_status", content.get("status", "")),
        )
    ).lower()


def _final_versions_and_compliance(
    db: Session, project: Project
) -> tuple[dict[str, ContentVersion], dict[str, Any]]:
    finals = db.scalars(
        select(ContentVersion).where(
            ContentVersion.project_id == project.id,
            ContentVersion.is_final.is_(True),
            ContentVersion.status == ContentStatus.FINAL,
        )
    ).all()
    by_type = {version.content_type: version for version in finals}
    missing = [kind for kind in ("title", "sku", "compliance") if kind not in by_type]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ERP write-back requires final versions for: " + ", ".join(missing),
        )
    compliance = by_type["compliance"].content_json
    normalized = _compliance_value(compliance)
    if normalized not in SAFE_COMPLIANCE_VALUES or _contains_blocked_risk(compliance):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Open compliance risk blocks ERP write-back",
        )
    risky_workflow = db.scalar(
        select(ImageWorkflow.id).where(
            ImageWorkflow.project_id == project.id,
            ImageWorkflow.compliance_status.in_(
                [ImageComplianceStatus.HIGH_OPEN, ImageComplianceStatus.MEDIUM_OPEN]
            ),
        )
    )
    if risky_workflow is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Open image compliance risk blocks ERP write-back",
        )
    return by_type, {
        "content_version_id": by_type["compliance"].id,
        "status": normalized,
        "checked": True,
    }


def _strip_protected_fields(
    value: Any, *, path: str = ""
) -> tuple[Any, list[str]]:
    omitted: list[str] = []
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized = str(key).lower().replace("-", "_")
            if normalized in PROTECTED_WRITEBACK_FIELDS:
                omitted.append(child_path)
                continue
            cleaned_child, child_omitted = _strip_protected_fields(
                child, path=child_path
            )
            cleaned[key] = cleaned_child
            omitted.extend(child_omitted)
        return cleaned, omitted
    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            cleaned_child, child_omitted = _strip_protected_fields(
                child, path=child_path
            )
            cleaned_list.append(cleaned_child)
            omitted.extend(child_omitted)
        return cleaned_list, omitted
    return value, omitted


def _build_writeback_payload(
    project: Project,
    card: ProductCard,
    finals: dict[str, ContentVersion],
) -> tuple[dict[str, Any], list[str]]:
    source_payload = {
        "target": "draft",
        "publish": False,
        "product": {
            "title": finals["title"].content_json,
            "sku_copy": finals["sku"].content_json,
            "selling_points": card.selling_points_json,
        },
        "trace": {
            "project_id": project.id,
            "product_card_revision": card.revision,
            "final_content_version_ids": {
                key: version.id for key, version in finals.items()
            },
        },
    }
    cleaned, omitted = _strip_protected_fields(source_payload)
    return cleaned, sorted(set(omitted))


@router.get("/capabilities", response_model=ERPConnectorCapabilities)
def get_capabilities(
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.OPERATOR.value, RoleName.ADMIN.value)),
) -> ERPConnectorCapabilities:
    return MockERPConnector(db).capabilities()


@router.get("/mock/products", response_model=list[UnifiedProduct])
def list_mock_products(
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.OPERATOR.value, RoleName.ADMIN.value)),
) -> list[UnifiedProduct]:
    products = MockERPConnector(db).list_products()
    db.commit()
    return products


@router.get("/field-mappings", response_model=list[ERPFieldMappingView])
def list_field_mappings(
    db: Session = Depends(get_db),
    _=Depends(require_roles(RoleName.OPERATOR.value, RoleName.ADMIN.value)),
) -> list[ERPFieldMappingView]:
    return list(
        db.scalars(
            select(ERPFieldMapping).order_by(
                ERPFieldMapping.connector_key,
                ERPFieldMapping.name,
            )
        ).all()
    )


@router.post(
    "/field-mappings",
    response_model=ERPFieldMappingView,
    status_code=status.HTTP_201_CREATED,
)
def create_field_mapping(
    payload: ERPFieldMappingCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(RoleName.ADMIN.value)),
) -> ERPFieldMappingView:
    mapping_json = _validate_field_mapping(payload.mapping)
    mapping = ERPFieldMapping(
        connector_key=payload.connector_key,
        name=payload.name.strip(),
        mapping_json=mapping_json,
        created_by_id=admin.id,
    )
    db.add(mapping)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Field mapping name already exists for this connector",
        ) from exc
    add_audit_event(
        db,
        action="erp.field_mapping.created",
        object_type="erp_field_mapping",
        object_id=mapping.id,
        actor_id=admin.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"connector": "mock", "name": mapping.name},
    )
    db.commit()
    db.refresh(mapping)
    return mapping


@router.post(
    "/import-previews",
    response_model=ERPImportPreviewView,
    status_code=status.HTTP_201_CREATED,
)
def create_import_preview(
    payload: ERPImportPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ERPImportPreviewView:
    if payload.target_project_id:
        _owned_project(db, payload.target_project_id, operator)
    mapping = _resolved_field_mapping(db, payload)
    connector = MockERPConnector(db)
    try:
        product = connector.get_product_with_mapping(payload.external_id, mapping)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Field mapping did not produce a valid unified product",
        ) from exc
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock ERP product not found",
        )
    warnings: list[str] = []
    if any(sku.price is not None or sku.inventory is not None for sku in product.skus):
        warnings.append("价格和库存仅作只读导入展示，写回时将被移除")
    record = _add_sync_record(
        db,
        direction="import",
        operation="import_preview",
        record_status="preview_ready",
        actor_id=operator.id,
        project_id=payload.target_project_id,
        external_entity_id=product.external_id,
        external_version_before=product.external_version,
        request_json={
            "store_name": payload.store_name,
            "project_name": payload.project_name,
            "target_project_id": payload.target_project_id,
            "field_mapping": mapping,
        },
        result_json={
            "unified_product": product.model_dump(mode="json"),
            "warnings": warnings,
        },
    )
    add_audit_event(
        db,
        action="erp.import.previewed",
        object_type="erp_sync_record",
        object_id=record.id,
        project_id=payload.target_project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "connector": "mock",
            "external_entity_id": product.external_id,
            "external_version": product.external_version,
        },
    )
    db.commit()
    db.refresh(record)
    return ERPImportPreviewView(
        record=_sync_view(record),
        product=product,
        field_mapping=mapping,
        warnings=warnings,
    )


@router.post(
    "/import-previews/{preview_id}/apply",
    response_model=ERPImportApplyView,
    status_code=status.HTTP_201_CREATED,
)
def apply_import_preview(
    preview_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ERPImportApplyView:
    preview = db.scalar(
        select(ERPSyncRecord).where(
            ERPSyncRecord.id == preview_id,
            ERPSyncRecord.operation == "import_preview",
            ERPSyncRecord.actor_id == operator.id,
        )
    )
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import preview not found",
        )
    if preview.status != "preview_ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Import preview has already been applied or is no longer valid",
        )
    product = UnifiedProduct.model_validate(preview.result_json["unified_product"])
    target_project_id = preview.request_json.get("target_project_id")
    if target_project_id:
        project = _owned_project(db, target_project_id, operator)
        if project.status == ProjectStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Reopen a completed project before importing ERP data",
            )
        if project.product_card and project.product_card.confirmed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Confirmed product facts cannot be overwritten by an ERP import",
            )
    else:
        project = Project(
            created_by_id=operator.id,
            name=preview.request_json.get("project_name") or product.name,
            platform="拼多多",
            store_name=preview.request_json["store_name"],
            category=product.category,
            source="erp_mock",
            status=ProjectStatus.DRAFT,
        )
        db.add(project)
        db.flush()

    card = project.product_card
    source_skus = [sku.model_dump(mode="json") for sku in product.skus]
    facts = deepcopy(product.facts)
    if source_skus:
        facts["erp_read_only_skus"] = source_skus
    completeness_fields = [product.name, product.title, product.category, product.facts]
    completeness = round(
        100 * sum(bool(value) for value in completeness_fields) / len(completeness_fields),
        1,
    )
    if card is None:
        card = ProductCard(
            project_id=project.id,
            product_name=product.name,
            brand=product.brand,
            current_title=product.title,
            facts_json=facts,
            selling_points_json=product.selling_points,
            specs_json=product.specs,
            constraints_json={
                "protected_erp_fields": sorted(PROTECTED_WRITEBACK_FIELDS),
            },
            field_sources_json={
                "product_name": "erp:mock",
                "brand": "erp:mock",
                "current_title": "erp:mock",
                "facts": "erp:mock",
                "selling_points": "erp:mock",
                "specs": "erp:mock",
            },
            completeness_percent=completeness,
        )
        db.add(card)
    else:
        card.product_name = product.name
        card.brand = product.brand
        card.current_title = product.title
        card.facts_json = facts
        card.selling_points_json = product.selling_points
        card.specs_json = product.specs
        card.field_sources_json = {
            "product_name": "erp:mock",
            "brand": "erp:mock",
            "current_title": "erp:mock",
            "facts": "erp:mock",
            "selling_points": "erp:mock",
            "specs": "erp:mock",
        }
        card.completeness_percent = completeness
        card.revision += 1
    db.flush()

    existing_external = db.scalar(
        select(ERPExternalEntityMapping).where(
            ERPExternalEntityMapping.connector_key == "mock",
            ERPExternalEntityMapping.external_entity_type == "product",
            ERPExternalEntityMapping.external_entity_id == product.external_id,
        )
    )
    if existing_external is not None and existing_external.project_id != project.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This external Mock ERP product is already mapped to another project",
        )
    entity_mapping = existing_external or ERPExternalEntityMapping(
        connector_key="mock",
        project_id=project.id,
        external_entity_type="product",
        external_entity_id=product.external_id,
        external_version=product.external_version,
    )
    entity_mapping.external_version = product.external_version
    entity_mapping.last_synced_at = datetime.now(timezone.utc)
    if existing_external is None:
        db.add(entity_mapping)
    db.flush()

    preview.status = "applied"
    preview.project_id = project.id
    apply_record = _add_sync_record(
        db,
        direction="import",
        operation="import_apply",
        record_status="succeeded",
        actor_id=operator.id,
        project_id=project.id,
        external_entity_id=product.external_id,
        external_version_before=product.external_version,
        external_version_after=product.external_version,
        request_json={"preview_id": preview.id},
        result_json={
            "project_id": project.id,
            "product_card_id": card.id,
            "external_mapping_id": entity_mapping.id,
            "published": False,
        },
    )
    add_audit_event(
        db,
        action="erp.import.applied",
        object_type="erp_sync_record",
        object_id=apply_record.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "connector": "mock",
            "external_entity_id": product.external_id,
            "product_card_revision": card.revision,
        },
    )
    db.commit()
    db.refresh(entity_mapping)
    db.refresh(apply_record)
    return ERPImportApplyView(
        project_id=project.id,
        product_card_id=card.id,
        mapping=ERPExternalEntityMappingView.model_validate(entity_mapping),
        record=_sync_view(apply_record),
    )


@router.get("/external-mappings", response_model=list[ERPExternalEntityMappingView])
def list_external_mappings(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(RoleName.OPERATOR.value, RoleName.ADMIN.value)
    ),
) -> list[ERPExternalEntityMappingView]:
    query = select(ERPExternalEntityMapping).order_by(
        ERPExternalEntityMapping.updated_at.desc()
    )
    if RoleName.ADMIN.value not in current_user.role_names:
        query = query.join(Project).where(Project.created_by_id == current_user.id)
    return list(db.scalars(query).all())


@router.post(
    "/projects/{project_id}/writeback-previews",
    response_model=ERPWritebackPreviewView,
    status_code=status.HTTP_201_CREATED,
)
def create_writeback_preview(
    project_id: str,
    payload: ERPWritebackPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ERPWritebackPreviewView:
    project = _owned_project(db, project_id, operator)
    if project.product_card is None or project.product_card.confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operator-confirmed product facts are required before ERP write-back",
        )
    entity_mapping = db.scalar(
        select(ERPExternalEntityMapping).where(
            ERPExternalEntityMapping.connector_key == "mock",
            ERPExternalEntityMapping.project_id == project.id,
            ERPExternalEntityMapping.external_entity_type == "product",
        )
    )
    if entity_mapping is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Project has no Mock ERP external entity mapping",
        )
    connector = MockERPConnector(db)
    external = connector.get_product(entity_mapping.external_entity_id)
    if external is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mapped Mock ERP product no longer exists",
        )
    if external.external_version != entity_mapping.external_version:
        blocked_record = _add_sync_record(
            db,
            direction="writeback",
            operation="writeback_preview",
            record_status="blocked_external_version",
            actor_id=operator.id,
            project_id=project.id,
            external_entity_id=entity_mapping.external_entity_id,
            external_version_before=entity_mapping.external_version,
            external_version_after=external.external_version,
            idempotency_key=payload.idempotency_key,
            error_message="External version conflict",
        )
        add_audit_event(
            db,
            action="erp.writeback.blocked",
            object_type="erp_sync_record",
            object_id=blocked_record.id,
            project_id=project.id,
            actor_id=operator.id,
            request_id=getattr(request.state, "request_id", None),
            payload_summary={"reason": "external_version_conflict"},
            result="blocked",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="External version changed; refresh the project before write-back",
        )
    finals, compliance_snapshot = _final_versions_and_compliance(db, project)
    write_payload, omitted = _build_writeback_payload(
        project, project.product_card, finals
    )
    final_ids = sorted(version.id for version in finals.values())

    existing = db.scalar(
        select(ERPWritebackPreview).where(
            ERPWritebackPreview.connector_key == "mock",
            ERPWritebackPreview.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.project_id == project.id
            and existing.payload_json == write_payload
            and sorted(existing.final_version_ids_json) == final_ids
        ):
            return existing
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for a different write-back payload",
        )

    preview = ERPWritebackPreview(
        connector_key="mock",
        project_id=project.id,
        external_mapping_id=entity_mapping.id,
        created_by_id=operator.id,
        expected_external_version=external.external_version,
        idempotency_key=payload.idempotency_key,
        payload_json=write_payload,
        final_version_ids_json=final_ids,
        compliance_snapshot_json=compliance_snapshot,
        omitted_protected_fields_json=omitted,
        status="ready",
    )
    db.add(preview)
    db.flush()
    record = _add_sync_record(
        db,
        direction="writeback",
        operation="writeback_preview",
        record_status="preview_ready",
        actor_id=operator.id,
        project_id=project.id,
        external_entity_id=entity_mapping.external_entity_id,
        external_version_before=external.external_version,
        idempotency_key=payload.idempotency_key,
        request_json={"project_id": project.id},
        result_json={
            "writeback_preview_id": preview.id,
            "target": "draft",
            "published": False,
            "omitted_protected_fields": omitted,
        },
    )
    add_audit_event(
        db,
        action="erp.writeback.previewed",
        object_type="erp_writeback_preview",
        object_id=preview.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "connector": "mock",
            "target": "draft",
            "external_version": external.external_version,
            "sync_record_id": record.id,
        },
    )
    db.commit()
    db.refresh(preview)
    return preview


def _block_writeback(
    db: Session,
    *,
    preview: ERPWritebackPreview,
    operator: User,
    entity_mapping: ERPExternalEntityMapping,
    request: Request,
    reason_code: str,
    detail: str,
    current_external_version: str | None = None,
) -> None:
    preview.status = f"blocked_{reason_code}"
    record = _add_sync_record(
        db,
        direction="writeback",
        operation="writeback_confirm",
        record_status=preview.status,
        actor_id=operator.id,
        project_id=preview.project_id,
        external_entity_id=entity_mapping.external_entity_id,
        external_version_before=preview.expected_external_version,
        external_version_after=current_external_version,
        idempotency_key=preview.idempotency_key,
        request_json={"preview_id": preview.id, "operator_confirmation": True},
        error_message=detail,
    )
    add_audit_event(
        db,
        action="erp.writeback.blocked",
        object_type="erp_writeback_preview",
        object_id=preview.id,
        project_id=preview.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"reason": reason_code, "sync_record_id": record.id},
        result="blocked",
    )
    db.commit()
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.post(
    "/writeback-previews/{preview_id}/confirm",
    response_model=ERPWritebackPreviewView,
)
def confirm_writeback_preview(
    preview_id: str,
    payload: ERPWritebackConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ERPWritebackPreviewView:
    preview = db.scalar(
        select(ERPWritebackPreview).where(
            ERPWritebackPreview.id == preview_id,
            ERPWritebackPreview.created_by_id == operator.id,
        )
    )
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Write-back preview not found",
        )
    if preview.status == "confirmed":
        return preview
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Explicit operator confirmation is required",
        )
    if preview.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Write-back preview is no longer ready; create a new preview",
        )
    project = _owned_project(db, preview.project_id, operator)
    entity_mapping = db.get(ERPExternalEntityMapping, preview.external_mapping_id)
    if entity_mapping is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="External entity mapping is missing",
        )
    if project.product_card is None or project.product_card.confirmed_at is None:
        _block_writeback(
            db,
            preview=preview,
            operator=operator,
            entity_mapping=entity_mapping,
            request=request,
            reason_code="product_facts",
            detail="Product facts changed or are no longer operator-confirmed",
        )
    try:
        finals, compliance_snapshot = _final_versions_and_compliance(db, project)
    except HTTPException as exc:
        _block_writeback(
            db,
            preview=preview,
            operator=operator,
            entity_mapping=entity_mapping,
            request=request,
            reason_code="compliance_or_final_version",
            detail=str(exc.detail),
        )
    current_final_ids = sorted(version.id for version in finals.values())
    if current_final_ids != sorted(preview.final_version_ids_json):
        _block_writeback(
            db,
            preview=preview,
            operator=operator,
            entity_mapping=entity_mapping,
            request=request,
            reason_code="final_version",
            detail="Final content versions changed after preview",
        )
    if compliance_snapshot != preview.compliance_snapshot_json:
        _block_writeback(
            db,
            preview=preview,
            operator=operator,
            entity_mapping=entity_mapping,
            request=request,
            reason_code="compliance",
            detail="Compliance result changed after preview",
        )

    connector = MockERPConnector(db)
    external = connector.get_product(entity_mapping.external_entity_id)
    if external is None or external.external_version != preview.expected_external_version:
        _block_writeback(
            db,
            preview=preview,
            operator=operator,
            entity_mapping=entity_mapping,
            request=request,
            reason_code="external_version",
            detail="External version changed after preview; write-back was blocked",
            current_external_version=(
                external.external_version if external is not None else None
            ),
        )
    try:
        new_version, draft_snapshot = connector.write_draft(
            external_id=entity_mapping.external_entity_id,
            expected_external_version=preview.expected_external_version,
            payload=preview.payload_json,
            idempotency_key=preview.idempotency_key,
        )
    except (KeyError, ValueError) as exc:
        _block_writeback(
            db,
            preview=preview,
            operator=operator,
            entity_mapping=entity_mapping,
            request=request,
            reason_code="connector",
            detail=str(exc),
        )
    entity_mapping.external_version = new_version
    entity_mapping.last_synced_at = datetime.now(timezone.utc)
    preview.status = "confirmed"
    preview.confirmed_by_id = operator.id
    preview.confirmed_at = datetime.now(timezone.utc)
    preview.external_version_after = new_version
    record = _add_sync_record(
        db,
        direction="writeback",
        operation="writeback_confirm",
        record_status="succeeded",
        actor_id=operator.id,
        project_id=project.id,
        external_entity_id=entity_mapping.external_entity_id,
        external_version_before=preview.expected_external_version,
        external_version_after=new_version,
        idempotency_key=preview.idempotency_key,
        request_json={"preview_id": preview.id, "operator_confirmation": True},
        result_json={
            "target": "draft",
            "published": False,
            "draft_snapshot": draft_snapshot,
        },
    )
    add_audit_event(
        db,
        action="erp.writeback.confirmed",
        object_type="erp_writeback_preview",
        object_id=preview.id,
        project_id=project.id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={
            "connector": "mock",
            "target": "draft",
            "published": False,
            "external_version_after": new_version,
            "sync_record_id": record.id,
        },
    )
    db.commit()
    db.refresh(preview)
    return preview


@router.post(
    "/mock/products/{external_id}/simulate-version-change",
    response_model=ERPMockExternalChangeView,
)
def simulate_external_version_change(
    external_id: str,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> ERPMockExternalChangeView:
    mapping = db.scalar(
        select(ERPExternalEntityMapping)
        .join(Project, Project.id == ERPExternalEntityMapping.project_id)
        .where(
            ERPExternalEntityMapping.connector_key == "mock",
            ERPExternalEntityMapping.external_entity_id == external_id,
            Project.created_by_id == operator.id,
        )
    )
    if mapping is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mapped Mock ERP product not found for this operator",
        )
    try:
        new_version = MockERPConnector(db).simulate_external_change(external_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    add_audit_event(
        db,
        action="erp.mock.external_version_changed",
        object_type="erp_external_entity",
        object_id=external_id,
        project_id=mapping.project_id,
        actor_id=operator.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"external_version": new_version},
    )
    db.commit()
    return ERPMockExternalChangeView(
        external_id=external_id,
        external_version=new_version,
        message="Mock external version changed; any older preview must now be blocked",
    )


@router.get("/records", response_model=list[ERPSyncRecordView])
def list_sync_records(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(RoleName.OPERATOR.value, RoleName.ADMIN.value)
    ),
) -> list[ERPSyncRecordView]:
    safe_limit = min(max(limit, 1), 500)
    query = select(ERPSyncRecord).order_by(ERPSyncRecord.created_at.desc())
    if RoleName.ADMIN.value not in current_user.role_names:
        owned_project_ids = select(Project.id).where(
            Project.created_by_id == current_user.id
        )
        query = query.where(
            or_(
                ERPSyncRecord.actor_id == current_user.id,
                ERPSyncRecord.project_id.in_(owned_project_ids),
            )
        )
    return list(db.scalars(query.limit(safe_limit)).all())


@router.get("/writeback-previews", response_model=list[ERPWritebackPreviewView])
def list_writeback_previews(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    operator: User = Depends(require_roles(RoleName.OPERATOR.value)),
) -> list[ERPWritebackPreviewView]:
    query = (
        select(ERPWritebackPreview)
        .join(Project, Project.id == ERPWritebackPreview.project_id)
        .where(Project.created_by_id == operator.id)
        .order_by(ERPWritebackPreview.created_at.desc())
    )
    if project_id:
        query = query.where(ERPWritebackPreview.project_id == project_id)
    return list(db.scalars(query).all())
