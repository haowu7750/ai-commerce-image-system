from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models.erp import ERPWritebackPreview, MockERPProduct
from tests.conftest import auth_header, login


@pytest.fixture()
def erp_client(settings) -> Generator[TestClient, None, None]:
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def _create_final_content(
    client: TestClient,
    project_id: str,
    headers: dict[str, str],
    content_type: str,
    content: dict,
) -> str:
    created = client.post(
        f"/api/v1/projects/{project_id}/content-versions",
        headers=headers,
        json={
            "content_type": content_type,
            "content": content,
            "source_kind": "human",
        },
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]
    finalized = client.post(
        f"/api/v1/projects/{project_id}/content-versions/{version_id}/finalize",
        headers=headers,
    )
    assert finalized.status_code == 200, finalized.text
    return version_id


def _import_demo_product(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, str]:
    preview = client.post(
        "/api/v1/erp/import-previews",
        headers=headers,
        json={
            "external_id": "MOCK-PROD-001",
            "store_name": "ERP 演示店",
            "project_name": "Mock ERP 导入项目",
        },
    )
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["product"]["name"] == "便携式桌面补光灯"
    assert body["product"]["source_snapshot"]["connector"] == "mock"
    assert body["warnings"]

    applied = client.post(
        f"/api/v1/erp/import-previews/{body['record']['id']}/apply",
        headers=headers,
    )
    assert applied.status_code == 201, applied.text
    applied_body = applied.json()
    return applied_body["project_id"], applied_body["mapping"]["external_entity_id"]


def test_mock_erp_import_writeback_idempotency_and_conflict(erp_client: TestClient) -> None:
    operator = auth_header(login(erp_client, "operator@example.local"))
    designer = auth_header(login(erp_client, "designer@example.local"))
    admin = auth_header(login(erp_client, "admin@example.local"))

    capabilities = erp_client.get("/api/v1/erp/capabilities", headers=operator)
    assert capabilities.status_code == 200
    assert capabilities.json()["mode"] == "mock"
    assert capabilities.json()["can_write_drafts"] is True
    assert capabilities.json()["can_publish"] is False

    assert erp_client.get("/api/v1/erp/capabilities", headers=designer).status_code == 403
    assert erp_client.post(
        "/api/v1/erp/import-previews",
        headers=designer,
        json={"external_id": "MOCK-PROD-001", "store_name": "无权店铺"},
    ).status_code == 403
    assert erp_client.post(
        "/api/v1/erp/import-previews",
        headers=admin,
        json={"external_id": "MOCK-PROD-001", "store_name": "管理员店铺"},
    ).status_code == 403

    saved_mapping = erp_client.post(
        "/api/v1/erp/field-mappings",
        headers=admin,
        json={
            "connector_key": "mock",
            "name": "标准 Mock 映射",
            "mapping": {
                "external_id": "mockItemId",
                "external_version": "mockVersion",
                "name": "itemName",
                "brand": "brandName",
                "title": "listingTitle",
                "category": "categoryName",
                "facts": "factData",
                "selling_points": "sellingPointRows",
                "specs": "specRows",
                "skus": "mockSkuRows",
                "images": "mockImageRows",
            },
        },
    )
    assert saved_mapping.status_code == 201, saved_mapping.text

    project_id, external_id = _import_demo_product(erp_client, operator)

    detail = erp_client.get(f"/api/v1/projects/{project_id}", headers=operator)
    assert detail.status_code == 200, detail.text
    card = detail.json()["product_card"]
    assert card["field_sources"]["product_name"] == "erp:mock"
    assert card["facts"]["erp_read_only_skus"][0]["price"] == 39.9

    confirmed_card = erp_client.post(
        f"/api/v1/projects/{project_id}/product-card/confirm",
        headers=operator,
    )
    assert confirmed_card.status_code == 200, confirmed_card.text

    _create_final_content(
        erp_client,
        project_id,
        operator,
        "title",
        {"text": "便携式桌面补光灯 可调亮度"},
    )
    _create_final_content(
        erp_client,
        project_id,
        operator,
        "sku",
        {
            "items": [
                {
                    "display_name": "白色款",
                    "copy": "白色便携款",
                    "source_code": "MUST-NOT-WRITE",
                    "price": 39.9,
                    "inventory": 25,
                }
            ]
        },
    )
    _create_final_content(
        erp_client,
        project_id,
        operator,
        "compliance",
        {"risk_level": "low", "issues": []},
    )

    writeback = erp_client.post(
        f"/api/v1/erp/projects/{project_id}/writeback-previews",
        headers=operator,
        json={"idempotency_key": "erp-demo-write-001"},
    )
    assert writeback.status_code == 201, writeback.text
    writeback_body = writeback.json()
    assert writeback_body["status"] == "ready"
    assert writeback_body["payload_json"]["target"] == "draft"
    assert writeback_body["payload_json"]["publish"] is False
    omitted = writeback_body["omitted_protected_fields_json"]
    assert any(path.endswith("source_code") for path in omitted)
    assert any(path.endswith("price") for path in omitted)
    assert any(path.endswith("inventory") for path in omitted)

    repeated_preview = erp_client.post(
        f"/api/v1/erp/projects/{project_id}/writeback-previews",
        headers=operator,
        json={"idempotency_key": "erp-demo-write-001"},
    )
    assert repeated_preview.status_code == 201, repeated_preview.text
    assert repeated_preview.json()["id"] == writeback_body["id"]

    refused_confirmation = erp_client.post(
        f"/api/v1/erp/writeback-previews/{writeback_body['id']}/confirm",
        headers=operator,
        json={"confirm": False},
    )
    assert refused_confirmation.status_code == 422

    confirmed = erp_client.post(
        f"/api/v1/erp/writeback-previews/{writeback_body['id']}/confirm",
        headers=operator,
        json={"confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmed_by_id"] is not None

    repeated_confirmation = erp_client.post(
        f"/api/v1/erp/writeback-previews/{writeback_body['id']}/confirm",
        headers=operator,
        json={"confirm": True},
    )
    assert repeated_confirmation.status_code == 200
    assert repeated_confirmation.json()["external_version_after"] == confirmed.json()[
        "external_version_after"
    ]

    database = erp_client.app.state.database
    with database.session_factory() as db:
        mock_product = db.scalar(
            select(MockERPProduct).where(MockERPProduct.external_id == external_id)
        )
        assert mock_product is not None
        assert mock_product.published is False
        assert mock_product.draft_payload_json["target"] == "draft"
        serialized_draft = str(mock_product.draft_payload_json).lower()
        assert "must-not-write" not in serialized_draft
        assert "39.9" not in serialized_draft

    stale_preview = erp_client.post(
        f"/api/v1/erp/projects/{project_id}/writeback-previews",
        headers=operator,
        json={"idempotency_key": "erp-demo-write-002"},
    )
    assert stale_preview.status_code == 201, stale_preview.text
    external_change = erp_client.post(
        f"/api/v1/erp/mock/products/{external_id}/simulate-version-change",
        headers=operator,
    )
    assert external_change.status_code == 200, external_change.text
    conflict = erp_client.post(
        f"/api/v1/erp/writeback-previews/{stale_preview.json()['id']}/confirm",
        headers=operator,
        json={"confirm": True},
    )
    assert conflict.status_code == 409
    assert "External version changed" in conflict.json()["detail"]

    with database.session_factory() as db:
        blocked = db.get(ERPWritebackPreview, stale_preview.json()["id"])
        assert blocked is not None
        assert blocked.status == "blocked_external_version"

    records = erp_client.get("/api/v1/erp/records", headers=operator)
    assert records.status_code == 200
    operations = {record["operation"] for record in records.json()}
    assert {"import_preview", "import_apply", "writeback_preview", "writeback_confirm"} <= operations
    assert erp_client.get("/api/v1/erp/records", headers=admin).status_code == 200
    assert erp_client.get("/api/v1/erp/records", headers=designer).status_code == 403


def test_mock_erp_writeback_requires_final_compliance(erp_client: TestClient) -> None:
    operator = auth_header(login(erp_client, "operator@example.local"))
    project_id, _ = _import_demo_product(erp_client, operator)
    assert erp_client.post(
        f"/api/v1/projects/{project_id}/product-card/confirm",
        headers=operator,
    ).status_code == 200
    _create_final_content(
        erp_client,
        project_id,
        operator,
        "title",
        {"text": "标题"},
    )
    _create_final_content(
        erp_client,
        project_id,
        operator,
        "sku",
        {"items": [{"display_name": "默认款"}]},
    )

    blocked = erp_client.post(
        f"/api/v1/erp/projects/{project_id}/writeback-previews",
        headers=operator,
        json={"idempotency_key": "missing-compliance-001"},
    )
    assert blocked.status_code == 409
    assert "compliance" in blocked.json()["detail"]
