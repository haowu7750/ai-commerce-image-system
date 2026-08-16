from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.commerce import AuditEvent
from app.models.erp import MockERPProduct
from app.models.generation import ImageGenerationJob
from tests.conftest import auth_header, login


def _assert_ok(response: httpx.Response, expected: int = 200) -> dict[str, Any]:
    assert response.status_code == expected, response.text
    return response.json()


def _create_final_content(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    content_type: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    version = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/content-versions",
            headers=headers,
            json={
                "content_type": content_type,
                "content": content,
                "source_kind": "ai",
            },
        ),
        201,
    )
    return _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/content-versions/{version['id']}/finalize",
            headers=headers,
        )
    )


def _advance_image_workflow(
    client: TestClient,
    headers: dict[str, str],
    workflow_id: str,
) -> dict[str, Any]:
    steps = [
        (
            "draft",
            "product_type_ready",
            {
                "product_type": {
                    "type": "桌面补光灯",
                    "confirmed_facts": ["便携", "白色"],
                    "unknowns": [],
                }
            },
        ),
        (
            "product_type_ready",
            "scene_plan_ready",
            {
                "scene_plan": {
                    "scenes": [
                        {
                            "scene": "居家桌面直播补光",
                            "why_realistic": "符合补光灯的实际用途",
                        }
                    ]
                }
            },
        ),
        (
            "scene_plan_ready",
            "hero_scene_selected",
            {
                "selected_scene": {
                    "scene": "居家桌面直播补光",
                    "reason": "真实使用场景且商品主体清晰",
                }
            },
        ),
        (
            "hero_scene_selected",
            "prompt_ready",
            {
                "approved_prompt": (
                    "居家桌面直播补光的真实使用场景，严格保持商品外形、结构、比例、"
                    "白色材质、数量、Logo 和可见文字不变，不新增品牌、功能、认证或配件。"
                )
            },
        ),
    ]
    revision = 1
    current: dict[str, Any] = {}
    for expected, target, extra in steps:
        current = _assert_ok(
            client.patch(
                f"/api/v1/image-workflows/{workflow_id}/transition",
                headers=headers,
                json={
                    "expected_status": expected,
                    "expected_revision": revision,
                    "target_status": target,
                    **extra,
                },
            )
        )
        revision = current["revision"]
    return current


def _create_candidate(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    reference_asset_id: str,
    idempotency_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = _assert_ok(
        client.post(
            "/api/v1/image-workflows",
            headers=headers,
            json={"project_id": project_id},
        ),
        201,
    )
    _advance_image_workflow(client, headers, workflow["id"])
    generation = _assert_ok(
        client.post(
            "/api/v1/image-generations",
            headers=headers,
            json={
                "workflow_id": workflow["id"],
                "reference_asset_ids": [reference_asset_id],
                "n": 1,
                "size": "1024x1024",
                "idempotency_key": idempotency_key,
            },
        ),
        201,
    )
    assert generation["provider"] == "mock"
    assert generation["model"] == "gpt-image-2"
    assert generation["status"] == "succeeded"
    assert len(generation["outputs"]) == 1
    current = _assert_ok(
        client.get(
            f"/api/v1/image-workflows/{workflow['id']}", headers=headers
        )
    )
    assert current["status"] == "candidate_ready"
    return current, generation


def test_initial_mvp_operator_can_complete_generation_collaboration_and_mock_erp(
    client: TestClient,
    monkeypatch,
) -> None:
    """Run the MVP through the real FastAPI router with deterministic local adapters."""

    async def reject_external_http(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("The deterministic MVP E2E test attempted external HTTP")

    # The in-process TestClient uses the sync transport; only application-side async
    # provider traffic is blocked here. A relay/provider regression therefore fails fast.
    monkeypatch.setattr(httpx.AsyncClient, "request", reject_external_http)

    operator = auth_header(login(client, "operator@example.local"))
    designer = auth_header(login(client, "designer@example.local"))
    admin = auth_header(login(client, "admin@example.local"))

    runtime = _assert_ok(
        client.get("/api/v1/config/image-runtime", headers=operator)
    )
    assert runtime == {
        "provider": "mock",
        "model": "gpt-image-2",
        "configured": True,
        "paid_requests_enabled": False,
        "reference_mode": "edit",
    }

    project = _assert_ok(
        client.post(
            "/api/v1/projects",
            headers=operator,
            json={
                "name": "初步可用验收-桌面补光灯",
                "platform": "拼多多",
                "store_name": "MVP 演示店",
                "category": "直播设备",
            },
        ),
        201,
    )
    project_id = project["id"]
    assert _assert_ok(
        client.post(f"/api/v1/projects/{project_id}/start", headers=operator)
    )["status"] == "in_progress"

    # Establish an external mapping through the Mock ERP before facts are confirmed.
    import_preview = _assert_ok(
        client.post(
            "/api/v1/erp/import-previews",
            headers=operator,
            json={
                "external_id": "MOCK-PROD-001",
                "store_name": "MVP 演示店",
                "target_project_id": project_id,
            },
        ),
        201,
    )
    imported = _assert_ok(
        client.post(
            f"/api/v1/erp/import-previews/{import_preview['record']['id']}/apply",
            headers=operator,
        ),
        201,
    )
    assert imported["project_id"] == project_id
    external_id = imported["mapping"]["external_entity_id"]

    product_card = _assert_ok(
        client.put(
            f"/api/v1/projects/{project_id}/product-card",
            headers=operator,
            json={
                "product_name": "便携式桌面补光灯",
                "brand": "演示品牌",
                "current_title": "桌面补光灯",
                "facts": {
                    "material": "ABS",
                    "color": "白色",
                    "origin": "中国",
                    "intended_use": "桌面直播与视频会议补光",
                },
                "selling_points": [
                    {"text": "三档亮度", "source": "operator"},
                    {"text": "便携桌面使用", "source": "operator"},
                ],
                "specs": [
                    {"name": "颜色", "value": "白色"},
                    {"name": "供电", "value": "USB"},
                ],
                "constraints": {
                    "forbidden_claims": ["世界第一", "100%有效"],
                    "image_truth": "不得改变外形、比例、颜色、数量或 Logo",
                },
                "field_sources": {
                    "product_name": "operator",
                    "brand": "operator",
                    "material": "operator",
                    "color": "operator",
                },
            },
        )
    )
    assert product_card["revision"] >= 2
    assert product_card["field_sources"]["product_name"] == "operator"

    reference = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/assets",
            headers=operator,
            json={
                "asset_type": "product_reference",
                "file_url": (
                    "data:image/png;base64,"
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
                    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
                ),
                "file_hash": "sha256:mvp-reference-v1",
                "mime_type": "image/png",
                "file_size": 68,
                "width": 1,
                "height": 1,
                "usage_note": "商品真实外观事实来源",
            },
        ),
        201,
    )
    competitor = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/assets",
            headers=operator,
            json={
                "asset_type": "competitor_image",
                "file_url": "https://example.invalid/competitor.png",
                "file_hash": "sha256:competitor-v1",
                "mime_type": "image/png",
                "usage_note": "仅用于构图对比，不作为商品事实",
            },
        ),
        201,
    )
    selected = _assert_ok(
        client.put(
            f"/api/v1/projects/{project_id}/assets/{reference['id']}/selection",
            headers=operator,
            json={"selected_for_generation": True},
        )
    )
    assert selected["selected_for_generation"] is True

    for unprivileged in (designer, admin):
        assert client.post(
            f"/api/v1/projects/{project_id}/product-card/confirm",
            headers=unprivileged,
        ).status_code == 403
    confirmed_card = _assert_ok(
        client.post(
            f"/api/v1/projects/{project_id}/product-card/confirm",
            headers=operator,
        )
    )
    assert confirmed_card["confirmed_by_id"] is not None

    analysis = _assert_ok(
        client.post(
            f"/api/v1/content-ai/projects/{project_id}/image-analysis",
            headers=operator,
            json={
                "selected_asset_ids": [reference["id"], competitor["id"]],
                "operator_ocr_texts": ["三档亮度", "USB 供电"],
            },
        ),
        201,
    )
    assert analysis["facts"]
    assert analysis["judgments"]
    assert analysis["suggestions"]
    assert analysis["uncertainties"]
    assert analysis["trace"]["network_used"] is False

    titles = _assert_ok(
        client.post(
            f"/api/v1/content-ai/projects/{project_id}/title-candidates",
            headers=operator,
            json={
                "keywords": ["桌面补光灯", "直播", "视频会议"],
                "required_words": ["桌面补光灯"],
                "forbidden_words": ["世界第一", "100%有效"],
                "candidate_count": 3,
                "target_length": 30,
            },
        ),
        201,
    )
    assert len(titles["candidates"]) == 3
    assert all(item["char_count"] == len(item["text"]) for item in titles["candidates"])
    assert titles["trace"]["network_used"] is False

    skus = _assert_ok(
        client.post(
            f"/api/v1/content-ai/projects/{project_id}/sku-suggestions",
            headers=operator,
            json={
                "items": [
                    {
                        "item_id": "white-usb",
                        "external_sku_id": "EXT-SKU-001",
                        "merchant_code": "SELLER-CODE-001",
                        "original_name": "白色 USB 款",
                        "attributes": {"颜色": "白色", "供电": "USB"},
                        "price": 39.9,
                        "stock": 25,
                    }
                ],
                "naming_order": ["颜色", "供电"],
                "separator": " / ",
                "max_length": 40,
            },
        ),
        201,
    )
    assert skus["protected_fields_unchanged"] is True
    assert skus["suggestions"][0]["protected"] == {
        "external_sku_id": "EXT-SKU-001",
        "merchant_code": "SELLER-CODE-001",
        "price": 39.9,
        "stock": 25,
    }

    safe_compliance = _assert_ok(
        client.post(
            f"/api/v1/content-ai/projects/{project_id}/compliance-check",
            headers=operator,
            json={
                "content_type": "title",
                "segments": [
                    {"segment_id": "safe-title", "text": "桌面补光灯 白色 USB 款"}
                ],
            },
        ),
        201,
    )
    assert safe_compliance["high_risk_blocked"] is False
    high_compliance = _assert_ok(
        client.post(
            f"/api/v1/content-ai/projects/{project_id}/compliance-check",
            headers=operator,
            json={
                "content_type": "title",
                "segments": [
                    {"segment_id": "unsafe-title", "text": "世界第一且100%有效"}
                ],
            },
        ),
        201,
    )
    assert high_compliance["high_risk_blocked"] is True
    assert high_compliance["can_finalize"] is False
    assert high_compliance["summary"]["high"] == 2

    final_title = _create_final_content(
        client,
        operator,
        project_id,
        "title",
        {
            "text": titles["candidates"][0]["text"],
            "risk_level": "low",
            "source_trace_id": titles["trace"]["content_version_id"],
        },
    )
    final_sku = _create_final_content(
        client,
        operator,
        project_id,
        "sku",
        {
            "items": skus["suggestions"],
            "risk_level": "low",
            "source_trace_id": skus["trace"]["content_version_id"],
        },
    )
    final_compliance = _create_final_content(
        client,
        operator,
        project_id,
        "compliance",
        {
            "risk_level": "clear",
            "issues": safe_compliance["issues"],
            "source_trace_id": safe_compliance["trace"]["content_version_id"],
        },
    )
    assert final_title["is_final"] is True
    assert final_sku["is_final"] is True
    assert final_compliance["is_final"] is True

    for unprivileged in (designer, admin):
        assert client.post(
            f"/api/v1/projects/{project_id}/content-versions/{titles['trace']['content_version_id']}/finalize",
            headers=unprivileged,
        ).status_code == 403
    # The generated high-risk compliance result itself must never be finalizable.
    assert client.post(
        f"/api/v1/projects/{project_id}/content-versions/{high_compliance['trace']['content_version_id']}/finalize",
        headers=operator,
    ).status_code == 409

    candidate, generation = _create_candidate(
        client,
        operator,
        project_id,
        reference["id"],
        "mvp-clear-candidate-001",
    )
    checked = _assert_ok(
        client.post(
            f"/api/v1/image-workflows/{candidate['id']}/mock-checks",
            headers=operator,
            json={"expected_revision": candidate["revision"], "scenario": "clear"},
        )
    )
    assert checked["status"] == "awaiting_operator_confirmation"
    assert checked["qa_status"] == "passed"
    assert checked["compliance_status"] == "clear"
    for unprivileged in (designer, admin):
        assert client.post(
            f"/api/v1/image-workflows/{candidate['id']}/confirm",
            headers=unprivileged,
            json={"expected_revision": checked["revision"]},
        ).status_code == 403
    confirmed_image = _assert_ok(
        client.post(
            f"/api/v1/image-workflows/{candidate['id']}/confirm",
            headers=operator,
            json={"expected_revision": checked["revision"]},
        )
    )
    assert confirmed_image["status"] == "operator_confirmed"

    designers = _assert_ok(
        client.get("/api/v1/design-tasks/designers", headers=operator)
    )
    designer_id = next(item["id"] for item in designers if item["email"] == "designer@example.local")
    design_task = _assert_ok(
        client.post(
            "/api/v1/design-tasks",
            headers=operator,
            json={
                "project_id": project_id,
                "assigned_to_id": designer_id,
                "title": "桌面补光灯主图优化",
                "brief": "以已确认生图为基础优化商品主图，保持商品事实和结构完全不变。",
                "requirements": [
                    {"target": "主体清晰", "acceptance": "缩略图可识别"},
                    {"forbidden": "不得改变颜色、比例、Logo 或数量"},
                ],
                "priority": "normal",
            },
        ),
        201,
    )
    task_id = design_task["id"]
    assert _assert_ok(
        client.patch(
            f"/api/v1/design-tasks/{task_id}/status",
            headers=designer,
            json={"status": "in_progress", "note": "已查看并开始处理"},
        )
    )["status"] == "in_progress"

    submission_v1 = _assert_ok(
        client.post(
            f"/api/v1/design-tasks/{task_id}/submissions",
            headers=designer,
            json={
                "file_url": "data:image/png;base64,design-v1",
                "notes": "第一版：已完成构图调整",
            },
        ),
        201,
    )
    assert submission_v1["submissions"][0]["version_no"] == 1
    for unprivileged in (designer, admin):
        assert client.post(
            f"/api/v1/design-tasks/{task_id}/review",
            headers=unprivileged,
            json={"decision": "accepted", "notes": "越权验收应失败"},
        ).status_code == 403
    rework = _assert_ok(
        client.post(
            f"/api/v1/design-tasks/{task_id}/review",
            headers=operator,
            json={"decision": "rework", "notes": "请提高主体亮度并保留原始颜色"},
        )
    )
    assert rework["status"] == "rework"
    _assert_ok(
        client.patch(
            f"/api/v1/design-tasks/{task_id}/status",
            headers=designer,
            json={"status": "in_progress", "note": "按退回意见修改"},
        )
    )
    submission_v2 = _assert_ok(
        client.post(
            f"/api/v1/design-tasks/{task_id}/submissions",
            headers=designer,
            json={
                "file_url": "data:image/png;base64,design-v2",
                "notes": "第二版：提高主体亮度，未改变商品颜色",
            },
        ),
        201,
    )
    assert [item["version_no"] for item in submission_v2["submissions"]] == [1, 2]
    accepted = _assert_ok(
        client.post(
            f"/api/v1/design-tasks/{task_id}/review",
            headers=operator,
            json={"decision": "accepted", "notes": "第二版符合验收标准"},
        )
    )
    assert accepted["status"] == "completed"

    report = _assert_ok(
        client.get(f"/api/v1/reports/projects/{project_id}", headers=operator)
    )
    assert report["blockers"] == []
    assert report["final_content"]["title"]["text"] == final_title["content"]["text"]
    assert report["accepted_designs"][0]["version_no"] == 2
    assert report["confirmed_images"][0]["job_id"] == generation["id"]
    assert any(event["action"] == "image_workflow.operator_confirmed" for event in report["timeline"])
    markdown = _assert_ok(
        client.get(
            f"/api/v1/reports/projects/{project_id}/exports/markdown",
            headers=operator,
        )
    )
    assert "运营成果包" in markdown["content"]
    assert final_title["content"]["text"] in markdown["content"]

    writeback_preview = _assert_ok(
        client.post(
            f"/api/v1/erp/projects/{project_id}/writeback-previews",
            headers=operator,
            json={"idempotency_key": "mvp-writeback-safe-001"},
        ),
        201,
    )
    assert writeback_preview["status"] == "ready"
    assert writeback_preview["payload_json"]["target"] == "draft"
    assert writeback_preview["payload_json"]["publish"] is False
    assert any(
        path.endswith("price") for path in writeback_preview["omitted_protected_fields_json"]
    )
    assert any(
        path.endswith("stock") for path in writeback_preview["omitted_protected_fields_json"]
    )
    for unprivileged in (designer, admin):
        assert client.post(
            f"/api/v1/erp/writeback-previews/{writeback_preview['id']}/confirm",
            headers=unprivileged,
            json={"confirm": True},
        ).status_code == 403
    writeback = _assert_ok(
        client.post(
            f"/api/v1/erp/writeback-previews/{writeback_preview['id']}/confirm",
            headers=operator,
            json={"confirm": True},
        )
    )
    assert writeback["status"] == "confirmed"
    assert writeback["confirmed_by_id"] is not None

    # A second, high-risk image candidate proves both confirmation and subsequent
    # write-back are blocked, with no override path for any role.
    risky_candidate, _ = _create_candidate(
        client,
        operator,
        project_id,
        reference["id"],
        "mvp-high-risk-candidate-001",
    )
    risky_checked = _assert_ok(
        client.post(
            f"/api/v1/image-workflows/{risky_candidate['id']}/mock-checks",
            headers=operator,
            json={
                "expected_revision": risky_candidate["revision"],
                "scenario": "high_risk",
            },
        )
    )
    assert risky_checked["compliance_status"] == "high_open"
    assert client.post(
        f"/api/v1/image-workflows/{risky_candidate['id']}/confirm",
        headers=operator,
        json={"expected_revision": risky_checked["revision"]},
    ).status_code == 409
    for unprivileged in (designer, admin):
        assert client.post(
            f"/api/v1/image-workflows/{risky_candidate['id']}/confirm",
            headers=unprivileged,
            json={"expected_revision": risky_checked["revision"]},
        ).status_code == 403
    blocked_writeback = client.post(
        f"/api/v1/erp/projects/{project_id}/writeback-previews",
        headers=operator,
        json={"idempotency_key": "mvp-writeback-blocked-001"},
    )
    assert blocked_writeback.status_code == 409
    assert "compliance risk" in blocked_writeback.json()["detail"].lower()

    with client.app.state.database.session_factory() as db:
        jobs = list(db.scalars(select(ImageGenerationJob)).all())
        mock_product = db.scalar(
            select(MockERPProduct).where(MockERPProduct.external_id == external_id)
        )
        audit_actions = list(db.scalars(select(AuditEvent.action)).all())
    assert jobs and all(job.provider == "mock" for job in jobs)
    assert mock_product is not None
    assert mock_product.published is False
    assert mock_product.draft_payload_json["publish"] is False
    assert not any(action in {"product.published", "erp.publish"} for action in audit_actions)
