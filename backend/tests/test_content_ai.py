from __future__ import annotations

import socket
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models.commerce import AuditEvent, ContentVersion
from app.config import Settings
from tests.conftest import DEMO_PASSWORD, auth_header, login


@pytest.fixture()
def content_client(settings: Settings) -> Generator[TestClient, None, None]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def _create_project_with_facts(content_client: TestClient, token: str) -> tuple[str, list[str]]:
    project_response = content_client.post(
        "/api/v1/projects",
        headers=auth_header(token),
        json={
            "name": "阶段4内容实验室",
            "platform": "拼多多",
            "store_name": "演示店铺",
            "category": "家居收纳",
        },
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    card_response = content_client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=auth_header(token),
        json={
            "product_name": "桌面分区收纳盒",
            "brand": "示例品牌",
            "current_title": "桌面分区收纳盒",
            "facts": {"color": "白色", "material": "ABS", "use": "桌面收纳"},
            "selling_points": [{"text": "分区收纳"}, {"text": "可叠放"}],
            "specs": [
                {"name": "尺寸", "value": "20×10cm"},
                {"name": "颜色", "value": "白色"},
            ],
            "constraints": {"forbidden_claims": ["治疗功效"]},
            "field_sources": {"color": "operator", "material": "operator"},
            "completeness_percent": 95,
        },
    )
    assert card_response.status_code == 200, card_response.text

    asset_ids: list[str] = []
    for asset_type, width, height in (
        ("main_image", 1200, 1200),
        ("competitor_image", 800, 800),
    ):
        asset_response = content_client.post(
            f"/api/v1/projects/{project_id}/assets",
            headers=auth_header(token),
            json={
                "asset_type": asset_type,
                "file_url": "data:image/png;base64,iVBORw0KGgo=",
                "file_hash": f"hash-{asset_type}",
                "mime_type": "image/png",
                "width": width,
                "height": height,
                "metadata": {"purpose": "test-fixture"},
            },
        )
        assert asset_response.status_code == 201, asset_response.text
        asset_ids.append(asset_response.json()["id"])
    return project_id, asset_ids


def test_content_ai_mock_workflow_is_deterministic_traceable_and_safe(
    content_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_token = login(content_client, "operator@example.local")
    designer_token = login(content_client, "designer@example.local")
    admin_token = login(content_client, "admin@example.local")
    project_id, asset_ids = _create_project_with_facts(content_client, operator_token)

    def reject_network(*_args, **_kwargs):
        raise AssertionError("Content AI Mock must not open a network socket")

    monkeypatch.setattr(socket.socket, "connect", reject_network)

    image_payload = {
        "selected_asset_ids": asset_ids,
        "operator_ocr_texts": ["运营人工修正：白色 ABS 收纳盒"],
    }
    first_analysis = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/image-analysis",
        headers=auth_header(operator_token),
        json=image_payload,
    )
    second_analysis = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/image-analysis",
        headers=auth_header(operator_token),
        json=image_payload,
    )
    assert first_analysis.status_code == 201, first_analysis.text
    assert second_analysis.status_code == 201, second_analysis.text
    first_analysis_json = first_analysis.json()
    second_analysis_json = second_analysis.json()
    for key in ("facts", "judgments", "suggestions", "uncertainties", "mock_limitations"):
        assert first_analysis_json[key] == second_analysis_json[key]
    assert first_analysis_json["trace"]["input_digest"] == second_analysis_json["trace"]["input_digest"]
    assert first_analysis_json["trace"]["network_used"] is False
    assert first_analysis_json["trace"]["is_final"] is False
    assert any(item["code"] == "PIXEL_CONTENT_UNKNOWN" for item in first_analysis_json["uncertainties"])

    title_response = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/title-candidates",
        headers=auth_header(operator_token),
        json={
            "keywords": ["桌面收纳", "世界第一"],
            "required_words": ["ABS", "国家级"],
            "forbidden_words": ["治愈"],
            "candidate_count": 5,
            "target_length": 36,
        },
    )
    assert title_response.status_code == 201, title_response.text
    title_json = title_response.json()
    assert len(title_json["candidates"]) == 5
    assert all(candidate["char_count"] == len(candidate["text"]) for candidate in title_json["candidates"])
    assert all("国家级" not in candidate["text"] for candidate in title_json["candidates"])
    assert all("世界第一" not in candidate["text"] for candidate in title_json["candidates"])
    assert {item["term"] for item in title_json["excluded_terms"]} >= {"国家级", "世界第一"}
    assert title_json["trace"]["provider"] == "deterministic_mock"

    sku_payload = {
        "items": [
            {
                "item_id": "sku-a",
                "external_sku_id": "external-a",
                "merchant_code": "MERCHANT-A",
                "original_name": "原白色小号",
                "attributes": {"颜色": "白色", "尺寸": "小号"},
                "price": 19.9,
                "stock": 12,
            },
            {
                "item_id": "sku-b",
                "external_sku_id": "external-b",
                "merchant_code": "MERCHANT-B",
                "original_name": "原白色小号副本",
                "attributes": {"颜色": "白色", "尺寸": "小号"},
                "price": "21.90",
                "stock": 5,
            },
        ],
        "naming_order": ["颜色", "尺寸"],
        "separator": " / ",
        "max_length": 20,
        "abbreviations": {},
    }
    sku_response = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/sku-suggestions",
        headers=auth_header(operator_token),
        json=sku_payload,
    )
    assert sku_response.status_code == 201, sku_response.text
    sku_json = sku_response.json()
    assert sku_json["protected_fields_unchanged"] is True
    assert sku_json["can_confirm_batch"] is False
    assert sku_json["batch_issues"][0]["code"] == "DUPLICATE_DISPLAY_NAME"
    for submitted, suggestion in zip(sku_payload["items"], sku_json["suggestions"], strict=True):
        assert suggestion["protected"] == {
            "external_sku_id": submitted["external_sku_id"],
            "merchant_code": submitted["merchant_code"],
            "price": submitted["price"],
            "stock": submitted["stock"],
        }

    compliance_response = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/compliance-check",
        headers=auth_header(operator_token),
        json={
            "content_type": "title",
            "segments": [
                {
                    "segment_id": "title-main",
                    "text": "世界第一收纳盒，100%有效且绝对安全",
                }
            ],
        },
    )
    assert compliance_response.status_code == 201, compliance_response.text
    compliance_json = compliance_response.json()
    assert compliance_json["overall_risk"] == "high"
    assert compliance_json["high_risk_blocked"] is True
    assert compliance_json["can_finalize"] is False
    assert compliance_json["summary"]["high"] >= 3
    assert {issue["original_text"] for issue in compliance_json["issues"]} >= {
        "世界第一",
        "100%有效",
        "绝对安全",
    }
    high_version_id = compliance_json["trace"]["content_version_id"]
    finalize_response = content_client.post(
        f"/api/v1/projects/{project_id}/content-versions/{high_version_id}/finalize",
        headers=auth_header(operator_token),
    )
    assert finalize_response.status_code == 409
    assert "High-risk" in finalize_response.json()["detail"]

    history_response = content_client.get(
        f"/api/v1/content-ai/projects/{project_id}/history",
        headers=auth_header(operator_token),
    )
    assert history_response.status_code == 200, history_response.text
    history = history_response.json()
    assert len(history) == 5
    assert {item["operation"] for item in history} == {
        "image_analysis",
        "title_generation",
        "sku_generation",
        "compliance_check",
    }
    assert all(item["is_final"] is False for item in history)
    assert all(item["input_digest"] for item in history)

    designer_denied = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/compliance-check",
        headers=auth_header(designer_token),
        json={"content_type": "title", "segments": [{"segment_id": "x", "text": "安全标题"}]},
    )
    admin_denied = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/compliance-check",
        headers=auth_header(admin_token),
        json={"content_type": "title", "segments": [{"segment_id": "x", "text": "安全标题"}]},
    )
    assert designer_denied.status_code == 403
    assert admin_denied.status_code == 403

    create_second_operator = content_client.post(
        "/api/v1/admin/users",
        headers=auth_header(admin_token),
        json={
            "email": "other.operator@example.local",
            "display_name": "其他运营",
            "password": DEMO_PASSWORD,
            "roles": ["operator"],
        },
    )
    assert create_second_operator.status_code == 201, create_second_operator.text
    other_operator_token = login(content_client, "other.operator@example.local")
    other_operator_denied = content_client.post(
        f"/api/v1/content-ai/projects/{project_id}/title-candidates",
        headers=auth_header(other_operator_token),
        json={"candidate_count": 5},
    )
    assert other_operator_denied.status_code == 404

    with content_client.app.state.database.session_factory() as db:
        content_versions = db.scalars(
            select(ContentVersion).where(ContentVersion.project_id == project_id)
        ).all()
        assert len(content_versions) == 5
        assert all(version.source_kind == "mock_ai" for version in content_versions)
        assert all(version.is_final is False for version in content_versions)
        actions = set(db.scalars(select(AuditEvent.action)).all())
        assert {
            "content_ai.image_analysis.generated",
            "content_ai.title_generation.generated",
            "content_ai.sku_generation.generated",
            "content_ai.compliance_check.generated",
            "content_ai.access_denied",
            "content_ai.object_scope_denied",
        }.issubset(actions)
