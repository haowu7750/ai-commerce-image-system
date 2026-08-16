from sqlalchemy import select
from fastapi.testclient import TestClient

from app.models.commerce import AuditEvent
from app.providers.base import GenerateImageParams, ProviderImageResponse
from app.providers.mock_image import MockImageProvider
from tests.conftest import auth_header, login


class CountingMockProvider(MockImageProvider):
    def __init__(self) -> None:
        super().__init__(model="gpt-image-2")
        self.generate_calls = 0

    async def generate_image(self, params: GenerateImageParams) -> ProviderImageResponse:
        self.generate_calls += 1
        return await super().generate_image(params)


def _create_project(client: TestClient, headers: dict[str, str]) -> str:
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "测试商品", "platform": "拼多多", "store_name": "测试店铺"},
    )
    assert project_response.status_code == 201, project_response.text
    return project_response.json()["id"]


def test_project_delete_restore_preserves_data_and_supports_admin_recovery(
    client: TestClient,
) -> None:
    operator_token = login(client, "operator@example.local")
    headers = auth_header(operator_token)
    project_id = _create_project(client, headers)
    card = client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={"product_name": "待归档商品", "facts": {"color": "白色"}},
    )
    assert card.status_code == 200, card.text

    started = client.post(
        f"/api/v1/projects/{project_id}/start",
        headers=headers,
    )
    assert started.status_code == 200
    deleted = client.post(
        f"/api/v1/projects/{project_id}/delete",
        headers=headers,
        json={"reason": "重复创建，保留记录后删除"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "archived"
    assert deleted.json()["archived_at"] is not None
    assert deleted.json()["deletion_reason"] == "重复创建，保留记录后删除"
    assert deleted.json()["status_before_delete"] == "in_progress"
    assert client.get("/api/v1/projects", headers=headers).json() == []
    deleted_list = client.get(
        "/api/v1/projects?bucket=deleted",
        headers=headers,
    )
    assert [row["id"] for row in deleted_list.json()] == [project_id]

    blocked_detail = client.get(
        f"/api/v1/projects/{project_id}",
        headers=headers,
    )
    assert blocked_detail.status_code == 409
    blocked_workflow = client.post(
        "/api/v1/image-workflows",
        headers=headers,
        json={"project_id": project_id},
    )
    assert blocked_workflow.status_code == 404
    admin_token = login(client, "admin@example.local")
    admin_list = client.get(
        "/api/v1/admin/deleted-projects",
        headers=auth_header(admin_token),
    )
    assert admin_list.status_code == 200
    assert admin_list.json()[0]["deletion_reason"].startswith("重复创建")
    assert client.delete(
        f"/api/v1/projects/{project_id}",
        headers=headers,
    ).status_code == 405

    restored = client.post(
        f"/api/v1/admin/deleted-projects/{project_id}/restore",
        headers=auth_header(admin_token),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "in_progress"
    assert restored.json()["archived_at"] is None
    restored_detail = client.get(
        f"/api/v1/projects/{project_id}",
        headers=headers,
    )
    assert restored_detail.status_code == 200, restored_detail.text
    assert restored_detail.json()["product_card"]["product_name"] == "待归档商品"

    with client.app.state.database.session_factory() as db:
        actions = set(db.scalars(select(AuditEvent.action)).all())
    assert {"project.deleted", "project.restored", "project.started"}.issubset(actions)


def test_project_draft_progress_completed_reopen_and_restore_flow(
    client: TestClient,
) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id = _create_project(client, headers)
    assert client.get(
        "/api/v1/projects?bucket=draft", headers=headers
    ).json()[0]["id"] == project_id
    assert client.post(
        f"/api/v1/projects/{project_id}/complete", headers=headers
    ).status_code == 409
    assert client.post(
        f"/api/v1/projects/{project_id}/start", headers=headers
    ).status_code == 200
    incomplete = client.post(
        f"/api/v1/projects/{project_id}/complete", headers=headers
    )
    assert incomplete.status_code == 409
    assert "商品信息卡" in incomplete.json()["detail"]

    assert client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={"product_name": "完整商品", "facts": {"material": "PP"}},
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project_id}/product-card/confirm", headers=headers
    ).status_code == 200
    content = client.post(
        f"/api/v1/projects/{project_id}/content-versions",
        headers=headers,
        json={
            "content_type": "title",
            "content": {"text": "完整商品测试标题", "risk_level": "low"},
            "source_kind": "human",
        },
    )
    assert content.status_code == 201, content.text
    assert client.post(
        f"/api/v1/projects/{project_id}/content-versions/{content.json()['id']}/finalize",
        headers=headers,
    ).status_code == 200
    completed = client.post(
        f"/api/v1/projects/{project_id}/complete", headers=headers
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert client.post(
        f"/api/v1/projects/{project_id}/assets",
        headers=headers,
        json={"asset_type": "product_reference", "file_hash": "hash"},
    ).status_code == 409

    reopened = client.post(
        f"/api/v1/projects/{project_id}/reopen", headers=headers
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "in_progress"
    assert client.post(
        f"/api/v1/projects/{project_id}/complete", headers=headers
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project_id}/delete",
        headers=headers,
        json={"reason": "完成项目清理"},
    ).status_code == 200
    restored = client.post(
        f"/api/v1/projects/{project_id}/restore", headers=headers
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "completed"


def _advance_to_prompt_ready(
    client: TestClient, headers: dict[str, str], workflow_id: str
) -> int:
    transitions = [
        ("draft", "product_type_ready", {"product_type": {"type": "收纳盒"}}),
        (
            "product_type_ready",
            "scene_plan_ready",
            {"scene_plan": {"scenes": ["厨房收纳"]}},
        ),
        (
            "scene_plan_ready",
            "hero_scene_selected",
            {"selected_scene": {"scene": "厨房收纳"}},
        ),
        (
            "hero_scene_selected",
            "prompt_ready",
            {
                "approved_prompt": (
                    "厨房中的真实商品使用场景，严格保持产品比例、透明材质、颜色、"
                    "数量、卡扣结构和可见文字不变，不新增任何功能或品牌。"
                )
            },
        ),
    ]
    revision = 1
    for expected, target, extra in transitions:
        response = client.patch(
            f"/api/v1/image-workflows/{workflow_id}/transition",
            headers=headers,
            json={
                "expected_status": expected,
                "expected_revision": revision,
                "target_status": target,
                **extra,
            },
        )
        assert response.status_code == 200, response.text
        revision = response.json()["revision"]
    return revision


def _create_asset(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    asset_type: str,
    *,
    with_hash: bool = True,
) -> str:
    response = client.post(
        f"/api/v1/projects/{project_id}/assets",
        headers=headers,
        json={
            "asset_type": asset_type,
            "file_url": f"https://example.invalid/{asset_type}.png",
            "file_hash": "sha256:test-reference-hash" if with_hash else None,
            "mime_type": "image/png",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_generation_gates_prevent_provider_calls_until_workflow_is_ready(
    client: TestClient,
) -> None:
    operator = login(client, "operator@example.local")
    headers = auth_header(operator)
    project_id = _create_project(client, headers)
    workflow_response = client.post(
        "/api/v1/image-workflows", headers=headers, json={"project_id": project_id}
    )
    assert workflow_response.status_code == 201, workflow_response.text
    workflow_id = workflow_response.json()["id"]

    provider = CountingMockProvider()
    client.app.state.image_provider = provider
    body = {
        "workflow_id": workflow_id,
        "reference_asset_ids": ["missing-reference"],
        "n": 1,
        "size": "1024x1024",
        "idempotency_key": "test-generation-0001",
    }

    not_ready = client.post("/api/v1/image-generations", headers=headers, json=body)
    assert not_ready.status_code == 409
    assert provider.generate_calls == 0

    _advance_to_prompt_ready(client, headers, workflow_id)
    no_card = client.post("/api/v1/image-generations", headers=headers, json=body)
    assert no_card.status_code == 409
    assert provider.generate_calls == 0

    card = client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={"product_name": "收纳盒", "facts": {"material": "PP"}},
    )
    assert card.status_code == 200, card.text
    confirmed = client.post(
        f"/api/v1/projects/{project_id}/product-card/confirm", headers=headers
    )
    assert confirmed.status_code == 200, confirmed.text

    style_id = _create_asset(client, headers, project_id, "style_reference")
    raw_id = _create_asset(client, headers, project_id, "product_raw")
    body["reference_asset_ids"] = [style_id, raw_id]
    non_product_references = client.post(
        "/api/v1/image-generations", headers=headers, json=body
    )
    assert non_product_references.status_code == 409
    assert provider.generate_calls == 0

    unhashed_product_reference_id = _create_asset(
        client,
        headers,
        project_id,
        "product_reference",
        with_hash=False,
    )
    body["reference_asset_ids"] = [unhashed_product_reference_id]
    unhashed_reference = client.post(
        "/api/v1/image-generations", headers=headers, json=body
    )
    assert unhashed_reference.status_code == 409
    assert provider.generate_calls == 0

    product_reference_id = _create_asset(
        client, headers, project_id, "product_reference"
    )
    body["reference_asset_ids"] = [product_reference_id, style_id]
    first = client.post("/api/v1/image-generations", headers=headers, json=body)
    second = client.post("/api/v1/image-generations", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "succeeded"
    assert first.json()["workflow_id"] == workflow_id
    assert len(first.json()["outputs"]) == 1
    assert provider.generate_calls == 1

    listed = client.get(
        f"/api/v1/image-generations?workflow_id={workflow_id}",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert [job["id"] for job in listed.json()] == [first.json()["id"]]
    assert listed.json()[0]["outputs"][0]["b64_json"] is not None

    workflow = client.get(
        f"/api/v1/image-workflows/{workflow_id}", headers=headers
    )
    assert workflow.status_code == 200
    assert workflow.json()["status"] == "candidate_ready"


def test_generation_payload_rejects_direct_prompt(client: TestClient) -> None:
    operator = login(client, "operator@example.local")
    response = client.post(
        "/api/v1/image-generations",
        headers=auth_header(operator),
        json={
            "workflow_id": "workflow-id",
            "reference_asset_ids": ["asset-id"],
            "prompt": "绕过已审批 Prompt",
            "idempotency_key": "direct-prompt-0001",
        },
    )
    assert response.status_code == 422


def test_workflow_rejects_stale_revision_and_skipped_stage(client: TestClient) -> None:
    operator = login(client, "operator@example.local")
    headers = auth_header(operator)
    project_id = _create_project(client, headers)
    created = client.post(
        "/api/v1/image-workflows", headers=headers, json={"project_id": project_id}
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]

    stale_revision = client.patch(
        f"/api/v1/image-workflows/{workflow_id}/transition",
        headers=headers,
        json={
            "expected_status": "draft",
            "expected_revision": 99,
            "target_status": "product_type_ready",
            "product_type": {"type": "收纳盒"},
        },
    )
    assert stale_revision.status_code == 409
    skipped_stage = client.patch(
        f"/api/v1/image-workflows/{workflow_id}/transition",
        headers=headers,
        json={
            "expected_status": "draft",
            "expected_revision": 1,
            "target_status": "scene_plan_ready",
            "scene_plan": {"scenes": ["厨房"]},
        },
    )
    assert skipped_stage.status_code == 409
    current = client.get(
        f"/api/v1/image-workflows/{workflow_id}", headers=headers
    ).json()
    assert current["status"] == "draft"
    assert current["revision"] == 1


def _prepare_candidate(
    client: TestClient,
) -> tuple[dict[str, str], str, str, dict[str, object]]:
    operator = login(client, "operator@example.local")
    headers = auth_header(operator)
    project_id = _create_project(client, headers)
    card = client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={"product_name": "收纳盒", "facts": {"material": "PET"}},
    )
    assert card.status_code == 200, card.text
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/product-card/confirm", headers=headers
        ).status_code
        == 200
    )
    reference_id = _create_asset(
        client, headers, project_id, "product_reference", with_hash=True
    )
    created = client.post(
        "/api/v1/image-workflows", headers=headers, json={"project_id": project_id}
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    _advance_to_prompt_ready(client, headers, workflow_id)
    generated = client.post(
        "/api/v1/image-generations",
        headers=headers,
        json={
            "workflow_id": workflow_id,
            "reference_asset_ids": [reference_id],
            "idempotency_key": f"candidate-{workflow_id}",
        },
    )
    assert generated.status_code == 201, generated.text
    workflow = client.get(
        f"/api/v1/image-workflows/{workflow_id}", headers=headers
    )
    assert workflow.status_code == 200, workflow.text
    assert workflow.json()["status"] == "candidate_ready"
    return headers, project_id, workflow_id, workflow.json()


def _run_checks(
    client: TestClient,
    headers: dict[str, str],
    workflow_id: str,
    revision: int,
    scenario: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/image-workflows/{workflow_id}/mock-checks",
        headers=headers,
        json={"expected_revision": revision, "scenario": scenario},
    )
    assert response.status_code == 200, response.text
    assert response.json()["qa_report"]["mode"] == "mock"
    assert response.json()["compliance_report"]["mode"] == "mock"
    return response.json()


def test_high_risk_has_no_override_and_confirmation_has_no_side_effects(
    client: TestClient,
) -> None:
    headers, _project_id, workflow_id, candidate = _prepare_candidate(client)
    checked = _run_checks(
        client,
        headers,
        workflow_id,
        int(candidate["revision"]),
        "high_risk",
    )
    assert checked["status"] == "compliance_blocked"
    assert checked["compliance_status"] == "high_open"

    blocked = client.post(
        f"/api/v1/image-workflows/{workflow_id}/confirm",
        headers=headers,
        json={"expected_revision": checked["revision"]},
    )
    assert blocked.status_code == 409
    assert client.post(
        f"/api/v1/image-workflows/{workflow_id}/resolve-medium-risk",
        headers=headers,
        json={
            "expected_revision": checked["revision"],
            "reason": "高风险不允许使用中风险保留理由绕过。",
        },
    ).status_code == 409

    admin = login(client, "admin@example.local")
    designer = login(client, "designer@example.local")
    for token in (admin, designer):
        denied = client.post(
            f"/api/v1/image-workflows/{workflow_id}/confirm",
            headers=auth_header(token),
            json={"expected_revision": checked["revision"]},
        )
        assert denied.status_code == 403

    with client.app.state.database.session_factory() as db:
        actions = list(db.scalars(select(AuditEvent.action)).all())
    assert "image_workflow.confirmation_denied" in actions
    assert not any("publish" in action or "erp" in action for action in actions)


def test_clear_mock_checks_allow_operator_confirmation_then_fact_change_stales(
    client: TestClient,
) -> None:
    headers, project_id, workflow_id, candidate = _prepare_candidate(client)
    checked = _run_checks(
        client, headers, workflow_id, int(candidate["revision"]), "clear"
    )
    assert checked["status"] == "awaiting_operator_confirmation"
    confirmed = client.post(
        f"/api/v1/image-workflows/{workflow_id}/confirm",
        headers=headers,
        json={"expected_revision": checked["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "operator_confirmed"
    assert confirmed.json()["confirmed_by_id"] is not None

    changed = client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={"product_name": "收纳盒（修订）", "facts": {"material": "PP"}},
    )
    assert changed.status_code == 200, changed.text
    stale = client.get(
        f"/api/v1/image-workflows/{workflow_id}", headers=headers
    ).json()
    assert stale["status"] == "stale"
    assert stale["qa_status"] == "invalidated"
    assert stale["compliance_status"] == "invalidated"
    assert stale["confirmed_by_id"] is None


def test_medium_risk_requires_retained_operator_reason(client: TestClient) -> None:
    headers, _project_id, workflow_id, candidate = _prepare_candidate(client)
    checked = _run_checks(
        client,
        headers,
        workflow_id,
        int(candidate["revision"]),
        "medium_risk",
    )
    assert checked["compliance_status"] == "medium_open"
    assert client.post(
        f"/api/v1/image-workflows/{workflow_id}/confirm",
        headers=headers,
        json={"expected_revision": checked["revision"]},
    ).status_code == 409

    resolved = client.post(
        f"/api/v1/image-workflows/{workflow_id}/resolve-medium-risk",
        headers=headers,
        json={
            "expected_revision": checked["revision"],
            "reason": "运营已核对商品事实并记录保留该中风险候选的具体理由。",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["compliance_status"] == "medium_resolved"
    final = client.post(
        f"/api/v1/image-workflows/{workflow_id}/confirm",
        headers=headers,
        json={"expected_revision": resolved.json()["revision"]},
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "operator_confirmed"


def test_failed_authenticity_check_never_reaches_confirmation(client: TestClient) -> None:
    headers, _project_id, workflow_id, candidate = _prepare_candidate(client)
    checked = _run_checks(
        client,
        headers,
        workflow_id,
        int(candidate["revision"]),
        "qa_failed",
    )
    assert checked["status"] == "qa_failed"
    assert checked["qa_status"] == "failed"
    denied = client.post(
        f"/api/v1/image-workflows/{workflow_id}/confirm",
        headers=headers,
        json={"expected_revision": checked["revision"]},
    )
    assert denied.status_code == 409
    assert client.get(
        f"/api/v1/image-workflows/{workflow_id}", headers=headers
    ).json()["status"] == "qa_failed"
