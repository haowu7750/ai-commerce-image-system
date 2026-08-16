from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.commerce import Asset, ContentVersion, ProductCard, Project
from app.models.enums import AssetType, ContentStatus
from app.models.identity import User
from app.schemas.content_ai import (
    ComplianceCheckRequest,
    ImageAnalysisRequest,
    SkuGenerationRequest,
    TitleGenerationRequest,
)
from app.services.audit import add_audit_event


MOCK_PROVIDER = "deterministic_mock"
MOCK_MODEL = "content-operations-mock-v1"
RULE_VERSION = "commerce-compliance-rules-mock-v1"

CONTENT_TYPE_BY_OPERATION = {
    "image_analysis": "image_analysis_mock",
    "title_generation": "title_candidates_mock",
    "sku_generation": "sku_suggestions_mock",
    "compliance_check": "compliance_report_mock",
}
OPERATION_BY_CONTENT_TYPE = {value: key for key, value in CONTENT_TYPE_BY_OPERATION.items()}
PROMPT_VERSION_BY_OPERATION = {
    "image_analysis": "image-analysis-mock-v1",
    "title_generation": "title-generation-mock-v1",
    "sku_generation": "sku-generation-mock-v1",
    "compliance_check": "compliance-check-mock-v1",
}


COMPLIANCE_RULES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "100%有效",
        "high",
        "ABSOLUTE_EFFECT_CLAIM",
        "绝对效果承诺缺少可核验边界，存在高风险。",
        "改为客观、可验证的商品事实描述，并保留相应证据。",
    ),
    (
        "世界第一",
        "high",
        "SUPERLATIVE_RANKING",
        "无法从商品卡证明世界范围排名。",
        "删除排名表述，改为商品规格或实际功能描述。",
    ),
    (
        "国家级",
        "high",
        "UNVERIFIED_AUTHORITY",
        "权威级别表述需要有效资质证据。",
        "无可核验证据时删除；有证据时改为准确的资质全称。",
    ),
    (
        "永久有效",
        "high",
        "PERMANENT_PROMISE",
        "永久性承诺通常无法合理验证。",
        "说明实际适用条件和期限，不作永久保证。",
    ),
    (
        "绝对安全",
        "high",
        "ABSOLUTE_SAFETY",
        "绝对安全承诺忽略使用条件和个体差异。",
        "改为具体安全设计或使用注意事项。",
    ),
    (
        "零风险",
        "high",
        "ZERO_RISK_PROMISE",
        "零风险属于不可验证的绝对承诺。",
        "删除绝对承诺并补充适用条件和注意事项。",
    ),
    (
        "根治",
        "high",
        "MEDICAL_CURE_CLAIM",
        "根治属于高风险医疗功效承诺。",
        "删除治疗承诺，仅描述有依据的商品用途。",
    ),
    (
        "包治",
        "high",
        "MEDICAL_CURE_CLAIM",
        "包治属于无条件医疗功效承诺。",
        "删除治疗承诺，仅描述有依据的商品用途。",
    ),
    (
        "无副作用",
        "high",
        "ABSOLUTE_SAFETY",
        "无副作用属于缺少适用边界的绝对安全表述。",
        "删除绝对表述，补充客观说明和必要注意事项。",
    ),
    (
        "官方认证",
        "medium",
        "UNVERIFIED_CERTIFICATION",
        "认证名称和证据不明确，需要运营核验。",
        "填写可核验的认证全称及证据，或删除该表述。",
    ),
    (
        "顶级",
        "medium",
        "VAGUE_SUPERLATIVE",
        "顶级属于缺少评价标准的模糊最高级表述。",
        "改为可核验的材质、规格或工艺。",
    ),
    (
        "万能",
        "medium",
        "UNBOUNDED_FUNCTION",
        "万能暗示没有适用范围限制。",
        "说明具体适用对象和不适用范围。",
    ),
    (
        "立刻见效",
        "medium",
        "IMMEDIATE_EFFECT",
        "即时效果承诺需要明确证据和适用条件。",
        "删除时效承诺，改为客观用途说明。",
    ),
    (
        "限时",
        "low",
        "TIME_LIMIT_NOTICE",
        "促销时效需要与实际活动时间一致。",
        "发布前核对活动起止时间，过期后及时删除。",
    ),
)


RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
AMBIGUOUS_SKU_VALUES = {
    "默认",
    "其他",
    "其它",
    "随机",
    "通用",
    "均码",
    "standard",
    "default",
}


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clean_text(value: Any, *, max_length: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:max_length]


def _deduplicate(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return result


def _flatten_values(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (str, int, float)):
        text = _clean_text(value, max_length=40)
        return [text] if text else []
    if isinstance(value, dict):
        flattened: list[str] = []
        for child in value.values():
            flattened.extend(_flatten_values(child))
        return flattened
    if isinstance(value, list):
        flattened = []
        for child in value:
            flattened.extend(_flatten_values(child))
        return flattened
    return []


def grounded_terms(card: ProductCard) -> list[str]:
    terms: list[str] = [card.product_name]
    if card.brand:
        terms.append(card.brand)
    terms.extend(_flatten_values(card.facts_json))
    terms.extend(_flatten_values(card.selling_points_json))
    terms.extend(_flatten_values(card.specs_json))
    return _deduplicate(terms)


def build_input_snapshot(
    *,
    project: Project,
    card: ProductCard | None,
    request_payload: dict[str, Any],
    assets: list[Asset] | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "project": {
            "id": project.id,
            "platform": project.platform,
            "category": project.category,
        },
        "product_card": None,
        "request": request_payload,
        "provider": MOCK_PROVIDER,
        "model": MOCK_MODEL,
        "rule_version": RULE_VERSION,
    }
    if card is not None:
        snapshot["product_card"] = {
            "id": card.id,
            "revision": card.revision,
            "confirmed_at": card.confirmed_at.isoformat() if card.confirmed_at else None,
            "product_name": card.product_name,
            "brand": card.brand,
            "facts": card.facts_json,
            "selling_points": card.selling_points_json,
            "specs": card.specs_json,
            "constraints": card.constraints_json,
        }
    if assets is not None:
        snapshot["assets"] = [
            {
                "id": asset.id,
                "asset_type": asset.asset_type.value,
                "file_hash": asset.file_hash,
                "mime_type": asset.mime_type,
                "width": asset.width,
                "height": asset.height,
                "metadata": asset.metadata_json,
            }
            for asset in assets
        ]
    return snapshot


def persist_mock_content(
    db: Session,
    *,
    project: Project,
    card: ProductCard | None,
    actor: User,
    operation: str,
    input_snapshot: dict[str, Any],
    content: dict[str, Any],
    request_id: str | None,
) -> ContentVersion:
    content_type = CONTENT_TYPE_BY_OPERATION[operation]
    input_digest = canonical_digest(input_snapshot)
    current_version = db.scalar(
        select(func.max(ContentVersion.version_no)).where(
            ContentVersion.project_id == project.id,
            ContentVersion.content_type == content_type,
        )
    )
    persisted_content = {
        **content,
        "provider": MOCK_PROVIDER,
        "model": MOCK_MODEL,
        "prompt_version": PROMPT_VERSION_BY_OPERATION[operation],
        "rule_version": RULE_VERSION,
        "input_digest": input_digest,
        "mock_notice": "确定性 Mock 结果，仅用于流程初步使用；不代表真实模型判断或平台审核结论。",
    }
    version = ContentVersion(
        project_id=project.id,
        content_type=content_type,
        version_no=(current_version or 0) + 1,
        content_json=persisted_content,
        source_kind="mock_ai",
        created_by_id=actor.id,
        status=ContentStatus.AI_DRAFT,
        is_final=False,
        input_snapshot_json={
            **input_snapshot,
            "operation": operation,
            "prompt_version": PROMPT_VERSION_BY_OPERATION[operation],
            "input_digest": input_digest,
            "product_card_revision": card.revision if card else None,
        },
    )
    db.add(version)
    db.flush()
    add_audit_event(
        db,
        action=f"content_ai.{operation}.generated",
        object_type="content_version",
        object_id=version.id,
        project_id=project.id,
        actor_id=actor.id,
        request_id=request_id,
        payload_summary={
            "content_type": content_type,
            "version_no": version.version_no,
            "provider": MOCK_PROVIDER,
            "model": MOCK_MODEL,
            "network_used": False,
            "input_digest": input_digest,
            "risk_level": persisted_content.get("risk_level", "none"),
        },
    )
    db.commit()
    db.refresh(version)
    return version


def trace_from_version(version: ContentVersion) -> dict[str, Any]:
    snapshot = version.input_snapshot_json
    operation = OPERATION_BY_CONTENT_TYPE[version.content_type]
    return {
        "content_version_id": version.id,
        "project_id": version.project_id,
        "version_no": version.version_no,
        "operation": operation,
        "provider": version.content_json["provider"],
        "model": version.content_json["model"],
        "prompt_version": version.content_json["prompt_version"],
        "rule_version": version.content_json["rule_version"],
        "input_digest": snapshot["input_digest"],
        "product_card_revision": snapshot.get("product_card_revision"),
        "generated_by_id": version.created_by_id,
        "generated_at": version.created_at,
        "network_used": False,
        "status": "ai_draft",
        "is_final": False,
    }


def generate_image_analysis(
    card: ProductCard,
    assets: list[Asset],
    payload: ImageAnalysisRequest,
) -> dict[str, Any]:
    asset_ids = [asset.id for asset in assets]
    facts: list[dict[str, Any]] = [
        {
            "code": "PRODUCT_CARD_NAME",
            "text": f"商品卡名称：{card.product_name}",
            "evidence": f"商品卡 revision {card.revision}",
            "source_asset_ids": [],
        },
        {
            "code": "SELECTED_ASSET_COUNT",
            "text": f"本次选择了 {len(assets)} 张图片素材。",
            "evidence": "服务端素材记录",
            "source_asset_ids": asset_ids,
        },
    ]
    for index, asset in enumerate(assets, start=1):
        dimensions = (
            f"{asset.width}×{asset.height}" if asset.width and asset.height else "尺寸未记录"
        )
        facts.append(
            {
                "code": f"ASSET_METADATA_{index}",
                "text": f"素材 {index} 类型为 {asset.asset_type.value}，{dimensions}，格式 {asset.mime_type or '未记录'}。",
                "evidence": "服务端保存的文件元数据；未读取图片像素",
                "source_asset_ids": [asset.id],
            }
        )
    for index, text in enumerate(payload.operator_ocr_texts, start=1):
        facts.append(
            {
                "code": f"OPERATOR_OCR_{index}",
                "text": f"运营提供/修正的图片文字：{_clean_text(text, max_length=500)}",
                "evidence": "运营本次请求输入，不是 Mock 自动 OCR",
                "source_asset_ids": asset_ids,
            }
        )

    asset_types = {asset.asset_type for asset in assets}
    judgments = [
        {
            "code": "SOURCE_COVERAGE",
            "text": (
                "已同时选择商品素材与竞品素材，可按来源分开比较。"
                if AssetType.COMPETITOR_IMAGE in asset_types
                and asset_types.intersection(
                    {AssetType.PRODUCT_RAW, AssetType.PRODUCT_REFERENCE, AssetType.MAIN_IMAGE}
                )
                else "当前素材来源类型较少，比较结论的覆盖面有限。"
            ),
            "evidence": "基于素材类型组合的确定性判断",
            "source_asset_ids": asset_ids,
        }
    ]
    suggestions: list[dict[str, Any]] = []
    if AssetType.MAIN_IMAGE not in asset_types:
        suggestions.append(
            {
                "code": "ADD_MAIN_IMAGE",
                "text": "补充或明确选择当前主图，便于后续人工核对主图信息层级。",
                "evidence": "本次所选素材中没有 main_image 类型",
                "source_asset_ids": asset_ids,
            }
        )
    if AssetType.COMPETITOR_IMAGE not in asset_types:
        suggestions.append(
            {
                "code": "ADD_COMPETITOR_IMAGE",
                "text": "如需竞品差异分析，请补充竞品图；竞品内容不得作为本商品事实。",
                "evidence": "本次所选素材中没有 competitor_image 类型",
                "source_asset_ids": asset_ids,
            }
        )
    low_resolution = [
        asset.id
        for asset in assets
        if asset.width and asset.height and min(asset.width, asset.height) < 600
    ]
    if low_resolution:
        suggestions.append(
            {
                "code": "CHECK_RESOLUTION",
                "text": "部分图片短边低于 600px，建议人工确认文字和商品细节是否可读。",
                "evidence": "服务端尺寸元数据检查",
                "source_asset_ids": low_resolution,
            }
        )
    if not suggestions:
        suggestions.append(
            {
                "code": "MANUAL_VISUAL_REVIEW",
                "text": "继续由运营人工核对构图、主体占比、文字可读性和商品事实一致性。",
                "evidence": "Mock 不执行真实像素语义分析",
                "source_asset_ids": asset_ids,
            }
        )

    uncertainties = [
        {
            "code": "PIXEL_CONTENT_UNKNOWN",
            "text": "Mock 未读取图片像素，无法确认商品颜色、Logo、可见文字、构图或遮挡情况。",
            "evidence": "确定性 Mock 能力边界",
            "source_asset_ids": asset_ids,
        },
        {
            "code": "OCR_NOT_AUTOMATIC",
            "text": "除运营明确提供的文字外，图片 OCR 内容均为未知。",
            "evidence": "本模块未调用 OCR 或外部视觉服务",
            "source_asset_ids": asset_ids,
        },
    ]
    return {
        "facts": facts,
        "judgments": judgments,
        "suggestions": suggestions,
        "uncertainties": uncertainties,
        "mock_limitations": [
            "未调用网络或付费模型。",
            "未读取图片像素，只使用商品卡、运营输入和文件元数据。",
            "结果必须由运营人工核对，不能直接作为最终内容。",
        ],
        "risk_level": "none",
    }


def _scan_compliance_segments(
    segments: list[dict[str, str]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    ordered_rules = sorted(COMPLIANCE_RULES, key=lambda item: len(item[0]), reverse=True)
    for segment in segments:
        occupied: list[tuple[int, int]] = []
        for phrase, level, code, reason, suggestion in ordered_rules:
            for match in re.finditer(re.escape(phrase), segment["text"], flags=re.IGNORECASE):
                start, end = match.span()
                if any(start < used_end and end > used_start for used_start, used_end in occupied):
                    continue
                occupied.append((start, end))
                issues.append(
                    {
                        "issue_id": f"risk-{len(issues) + 1:03d}",
                        "segment_id": segment["segment_id"],
                        "original_text": segment["text"][start:end],
                        "start": start,
                        "end": end,
                        "level": level,
                        "code": code,
                        "reason": reason,
                        "suggestion": suggestion,
                        "detector": "deterministic_lexicon",
                        "rule_source": RULE_VERSION,
                    }
                )
    return sorted(issues, key=lambda item: (item["segment_id"], item["start"], item["code"]))


def _highest_risk(levels: Iterable[str]) -> str:
    return max(levels, key=lambda item: RISK_ORDER[item], default="none")


def generate_title_candidates(
    card: ProductCard,
    payload: TitleGenerationRequest,
) -> dict[str, Any]:
    evidence_terms = grounded_terms(card)
    evidence_text = " ".join(evidence_terms).casefold()
    forbidden = {_clean_text(word).casefold() for word in payload.forbidden_words if _clean_text(word)}

    requested = _deduplicate([*payload.required_words, *payload.keywords])
    supported_requested: list[str] = []
    excluded_terms: list[dict[str, str]] = []
    for term in requested:
        normalized = term.casefold()
        if normalized in forbidden:
            excluded_terms.append({"term": term, "reason": "命中运营设置的禁用词，未加入候选。"})
        elif normalized in evidence_text or any(normalized in source.casefold() for source in evidence_terms):
            supported_requested.append(term)
        else:
            excluded_terms.append(
                {
                    "term": term,
                    "reason": "商品卡中未找到事实依据，Mock 不会擅自加入标题。",
                }
            )

    usable_terms = [
        term
        for term in _deduplicate([*supported_requested, *evidence_terms[1:]])
        if term.casefold() not in forbidden
        and term.casefold() not in card.product_name.casefold()
        and len(term) <= 24
    ][:10]
    brand_prefix = card.brand if card.brand and card.brand.casefold() not in card.product_name.casefold() else ""
    core = _deduplicate([brand_prefix, card.product_name])
    product_core = " ".join(core)

    templates: list[tuple[str, list[str], str]] = [
        ("核心事实优先", [product_core, *usable_terms[:2]], " "),
        ("属性前置", [*usable_terms[:1], product_core, *usable_terms[1:3]], " "),
        ("规格信息优先", [product_core, *usable_terms[2:5]], "｜"),
        ("关键词覆盖", [*supported_requested[:2], product_core, *usable_terms[:2]], " "),
        ("精简表达", [product_core, *usable_terms[:1]], " "),
        ("事实组合", [product_core, *reversed(usable_terms[:3])], "·"),
        ("卖点后置", [product_core, *usable_terms[3:6]], " "),
        ("规格后置", [product_core, *usable_terms[-3:]], "｜"),
    ]
    candidates: list[dict[str, Any]] = []
    duplicate_texts = False
    seen_texts: set[str] = set()
    for index in range(payload.candidate_count):
        strategy, parts, separator = templates[index % len(templates)]
        cleaned_parts = _deduplicate(parts)
        title = separator.join(cleaned_parts) or card.product_name
        if title.casefold() in seen_texts:
            duplicate_texts = True
        seen_texts.add(title.casefold())

        scanned = _scan_compliance_segments([{"segment_id": "title", "text": title}])
        risks = [
            {
                "code": issue["code"],
                "level": issue["level"],
                "original_text": issue["original_text"],
                "reason": issue["reason"],
                "suggestion": issue["suggestion"],
            }
            for issue in scanned
        ]
        if len(title) > payload.target_length:
            risks.append(
                {
                    "code": "OVER_TARGET_LENGTH",
                    "level": "medium",
                    "original_text": title,
                    "reason": f"标题长度 {len(title)} 超过目标 {payload.target_length}。",
                    "suggestion": "删减次要事实词，但不要截断商品名称或规格值。",
                }
            )
        risk_level = _highest_risk(risk["level"] for risk in risks)
        used_terms = [term for term in evidence_terms if term.casefold() in title.casefold()]
        candidates.append(
            {
                "candidate_id": f"title-{index + 1:02d}",
                "text": title,
                "char_count": len(title),
                "keywords": [term for term in supported_requested if term.casefold() in title.casefold()],
                "strategy": strategy,
                "evidence_terms": used_terms,
                "risks": risks,
                "risk_level": risk_level,
                "can_confirm": risk_level in {"none", "low"},
            }
        )

    warnings: list[str] = []
    if excluded_terms:
        warnings.append("部分请求词在商品卡中没有依据或被禁用，已从候选中排除。")
    if duplicate_texts:
        warnings.append("商品事实较少，部分候选差异有限；请先补充商品卡，而不是让 AI 猜测。")
    overall_risk = _highest_risk(candidate["risk_level"] for candidate in candidates)
    return {
        "candidates": candidates,
        "excluded_terms": excluded_terms,
        "warnings": warnings,
        "overall_risk": overall_risk,
        "high_risk_blocked": overall_risk == "high",
        "risk_level": overall_risk,
    }


def generate_sku_suggestions(payload: SkuGenerationRequest) -> dict[str, Any]:
    suggestions: list[dict[str, Any]] = []
    for item in payload.items:
        issues: list[dict[str, Any]] = []
        order = payload.naming_order or sorted(item.attributes)
        parts: list[str] = []
        for attribute_name in order:
            value = _clean_text(item.attributes.get(attribute_name, ""), max_length=120)
            if not value:
                issues.append(
                    {
                        "code": "MISSING_ATTRIBUTE",
                        "level": "blocking",
                        "message": f"缺少命名维度“{attribute_name}”。",
                        "related_item_ids": [item.item_id],
                    }
                )
                continue
            rendered = payload.abbreviations.get(value, value)
            parts.append(_clean_text(rendered, max_length=120))
            if value.casefold() in AMBIGUOUS_SKU_VALUES:
                issues.append(
                    {
                        "code": "AMBIGUOUS_ATTRIBUTE",
                        "level": "blocking",
                        "message": f"属性“{attribute_name}={value}”含义不明确。",
                        "related_item_ids": [item.item_id],
                    }
                )
        display_name = payload.separator.join(parts) if parts else item.original_name
        if len(display_name) > payload.max_length:
            issues.append(
                {
                    "code": "NAME_TOO_LONG",
                    "level": "blocking",
                    "message": f"建议名称长度 {len(display_name)} 超过上限 {payload.max_length}。",
                    "related_item_ids": [item.item_id],
                }
            )
        suggestions.append(
            {
                "item_id": item.item_id,
                "original_name": item.original_name,
                "proposed_display_name": display_name,
                "attributes": dict(item.attributes),
                "protected": {
                    "external_sku_id": item.external_sku_id,
                    "merchant_code": item.merchant_code,
                    "price": item.price,
                    "stock": item.stock,
                },
                "issues": issues,
                "can_confirm": not any(issue["level"] == "blocking" for issue in issues),
            }
        )

    by_name: dict[str, list[dict[str, Any]]] = {}
    for suggestion in suggestions:
        normalized = re.sub(r"[\s/|·_-]+", "", suggestion["proposed_display_name"]).casefold()
        by_name.setdefault(normalized, []).append(suggestion)
    batch_issues: list[dict[str, Any]] = []
    for duplicate_group in by_name.values():
        if len(duplicate_group) < 2:
            continue
        item_ids = [suggestion["item_id"] for suggestion in duplicate_group]
        issue = {
            "code": "DUPLICATE_DISPLAY_NAME",
            "level": "blocking",
            "message": "多个 SKU 生成了相同展示名，必须补充区分维度。",
            "related_item_ids": item_ids,
        }
        batch_issues.append(issue)
        for suggestion in duplicate_group:
            suggestion["issues"].append(issue)
            suggestion["can_confirm"] = False

    original_protected = [
        {
            "external_sku_id": item.external_sku_id,
            "merchant_code": item.merchant_code,
            "price": item.price,
            "stock": item.stock,
        }
        for item in payload.items
    ]
    output_protected = [suggestion["protected"] for suggestion in suggestions]
    unchanged = original_protected == output_protected
    return {
        "suggestions": suggestions,
        "batch_issues": batch_issues,
        "protected_fields": ["external_sku_id", "merchant_code", "price", "stock"],
        "protected_fields_unchanged": unchanged,
        "can_confirm_batch": unchanged
        and not batch_issues
        and all(suggestion["can_confirm"] for suggestion in suggestions),
        "risk_level": "medium" if batch_issues else "none",
    }


def generate_compliance_report(payload: ComplianceCheckRequest) -> dict[str, Any]:
    segments = [segment.model_dump() for segment in payload.segments]
    issues = _scan_compliance_segments(segments)
    summary = {
        level: sum(issue["level"] == level for issue in issues)
        for level in ("low", "medium", "high")
    }
    overall_risk = _highest_risk(issue["level"] for issue in issues)
    high_risk_blocked = summary["high"] > 0
    requires_operator_action = summary["medium"] > 0 or high_risk_blocked
    return {
        "content_type": payload.content_type,
        "issues": issues,
        "summary": summary,
        "overall_risk": overall_risk,
        "high_risk_blocked": high_risk_blocked,
        "requires_operator_action": requires_operator_action,
        "can_finalize": not requires_operator_action,
        "disclaimer": "本报告为确定性 Mock/词库检查，不能替代平台审核、法律意见或运营人工复核。",
        "risk_level": overall_risk,
    }
