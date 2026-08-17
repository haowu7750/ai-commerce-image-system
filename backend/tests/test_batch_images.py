from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.commerce import AuditEvent
from app.providers.base import EditImageParams, ImageInput, ProviderImageResponse
from app.providers.mock_image import MOCK_PNG_B64, MockImageProvider
from tests.conftest import auth_header, login


class CountingBatchProvider(MockImageProvider):
    def __init__(self) -> None:
        super().__init__(model="gpt-image-2")
        self.edit_calls = 0

    async def edit_image(
        self, params: EditImageParams, images: list[ImageInput]
    ) -> ProviderImageResponse:
        self.edit_calls += 1
        return await super().edit_image(params, images)


def _project_with_assets(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, str, list[str]]:
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "批量改图商品", "platform": "拼多多", "store_name": "测试店铺"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    assert client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={
            "product_name": "透明收纳盒",
            "facts": {"color": "透明", "material": "PET"},
            "constraints": {"must_not_change": ["透明材质", "卡扣结构"]},
        },
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project_id}/product-card/confirm", headers=headers
    ).status_code == 200

    data_url = f"data:image/png;base64,{MOCK_PNG_B64}"

    def create_asset(asset_type: str, suffix: str) -> str:
        response = client.post(
            f"/api/v1/projects/{project_id}/assets",
            headers=headers,
            json={
                "asset_type": asset_type,
                "file_url": data_url,
                "file_hash": f"sha256:{suffix}",
                "mime_type": "image/png",
                "file_size": 68,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    reference_id = create_asset("product_reference", "reference")
    source_ids = [
        create_asset("main_image", "source-1"),
        create_asset("competitor_image", "source-2"),
    ]
    return project_id, reference_id, source_ids


def test_supervised_batch_edit_requires_review_and_is_idempotent(
    client: TestClient,
) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id, reference_id, source_ids = _project_with_assets(client, headers)
    provider = CountingBatchProvider()
    client.app.state.image_provider = provider
    payload = {
        "project_id": project_id,
        "mode": "custom_edit",
        "product_reference_asset_ids": [reference_id],
        "source_asset_ids": source_ids,
        "instruction": "统一替换为干净的厨房收纳背景，商品本体保持原样",
        "size": "1024x1024",
        "idempotency_key": "batch-edit-test-0001",
    }
    created = client.post("/api/v1/batch-image-tasks", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    task = client.get(f"/api/v1/batch-image-tasks/{task_id}", headers=headers)
    assert task.status_code == 200, task.text
    assert task.json()["status"] == "succeeded"
    assert task.json()["progress_done"] == 2
    assert task.json()["succeeded_count"] == 2
    assert provider.edit_calls == 2

    repeated = client.post("/api/v1/batch-image-tasks", headers=headers, json=payload)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == task_id
    assert provider.edit_calls == 2

    no_unreviewed_download = client.get(
        f"/api/v1/batch-image-tasks/{task_id}/download", headers=headers
    )
    assert no_unreviewed_download.status_code == 409

    first, second = task.json()["items"]
    high_review = client.post(
        f"/api/v1/batch-image-tasks/{task_id}/items/{first['id']}/review",
        headers=headers,
        json={
            "expected_revision": first["revision"],
            "product_facts_match": True,
            "geometry_and_count_match": True,
            "logo_text_and_personalization_match": True,
            "thumbnail_readable": True,
            "compliance_risk": "high",
            "notes": "候选图出现无法接受的高风险宣传文案，需要重新生成。",
        },
    )
    assert high_review.status_code == 200, high_review.text
    assert high_review.json()["compliance_status"] == "high_open"
    blocked = client.post(
        f"/api/v1/batch-image-tasks/{task_id}/items/{first['id']}/confirm",
        headers=headers,
        json={"expected_revision": high_review.json()["revision"]},
    )
    assert blocked.status_code == 409
    assert client.post(
        f"/api/v1/batch-image-tasks/{task_id}/items/{first['id']}/review",
        headers=headers,
        json={
            "expected_revision": high_review.json()["revision"],
            "product_facts_match": True,
            "geometry_and_count_match": True,
            "logo_text_and_personalization_match": True,
            "thumbnail_readable": True,
            "compliance_risk": "clear",
            "notes": "尝试覆盖原有高风险检查记录，不应被允许通过。",
        },
    ).status_code == 409

    clear_review = client.post(
        f"/api/v1/batch-image-tasks/{task_id}/items/{second['id']}/review",
        headers=headers,
        json={
            "expected_revision": second["revision"],
            "product_facts_match": True,
            "geometry_and_count_match": True,
            "logo_text_and_personalization_match": True,
            "thumbnail_readable": True,
            "compliance_risk": "clear",
            "notes": "已逐项核对商品事实、结构、文字与缩略图，结果可以使用。",
        },
    )
    assert clear_review.status_code == 200, clear_review.text
    confirmed = client.post(
        f"/api/v1/batch-image-tasks/{task_id}/items/{second['id']}/confirm",
        headers=headers,
        json={"expected_revision": clear_review.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirmed_by_id"] is not None
    assert confirmed.json()["output_asset_id"] is not None

    archive_source = client.post(
        f"/api/v1/projects/{project_id}/assets/{source_ids[0]}/archive",
        headers=headers,
    )
    assert archive_source.status_code == 409
    download = client.get(
        f"/api/v1/batch-image-tasks/{task_id}/download", headers=headers
    )
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"

    admin = auth_header(login(client, "admin@example.local"))
    designer = auth_header(login(client, "designer@example.local"))
    for denied_headers in (admin, designer):
        assert client.get(
            f"/api/v1/batch-image-tasks/{task_id}", headers=denied_headers
        ).status_code == 403

    with client.app.state.database.session_factory() as db:
        actions = list(db.scalars(select(AuditEvent.action)).all())
    assert "batch_image_item.confirmation_denied" in actions
    assert "batch_image_item.operator_confirmed" in actions
    assert not any("publish" in action or "erp" in action for action in actions)


def test_batch_modes_and_input_gates(client: TestClient) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id, reference_id, source_ids = _project_with_assets(client, headers)
    provider = CountingBatchProvider()
    client.app.state.image_provider = provider
    for index, mode in enumerate(("replace_product", "resize"), start=1):
        response = client.post(
            "/api/v1/batch-image-tasks",
            headers=headers,
            json={
                "project_id": project_id,
                "mode": mode,
                "product_reference_asset_ids": [reference_id],
                "source_asset_ids": [source_ids[index - 1]],
                "instruction": "保留商品事实并自然处理画面",
                "size": "1024x1024",
                "idempotency_key": f"batch-mode-test-{index:04d}",
            },
        )
        assert response.status_code == 201, response.text
        detail = client.get(
            f"/api/v1/batch-image-tasks/{response.json()['id']}", headers=headers
        )
        assert detail.json()["status"] == "succeeded"
    assert provider.edit_calls == 2

    missing_reference = client.post(
        "/api/v1/batch-image-tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "mode": "custom_edit",
            "product_reference_asset_ids": [],
            "source_asset_ids": [source_ids[0]],
            "instruction": "改成白色背景",
            "idempotency_key": "batch-invalid-0001",
        },
    )
    assert missing_reference.status_code == 422
    assert provider.edit_calls == 2

    stale_candidate = client.post(
        "/api/v1/batch-image-tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "mode": "custom_edit",
            "product_reference_asset_ids": [reference_id],
            "source_asset_ids": [source_ids[0]],
            "instruction": "统一为自然光背景，商品结构保持原样",
            "idempotency_key": "batch-stale-test-0001",
        },
    )
    assert stale_candidate.status_code == 201, stale_candidate.text
    stale_detail = client.get(
        f"/api/v1/batch-image-tasks/{stale_candidate.json()['id']}", headers=headers
    ).json()
    assert stale_detail["status"] == "succeeded"
    assert provider.edit_calls == 3
    assert client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={
            "product_name": "透明收纳盒（事实已更新）",
            "facts": {"color": "透明", "material": "PET"},
        },
    ).status_code == 200
    blocked_stale_review = client.post(
        f"/api/v1/batch-image-tasks/{stale_detail['id']}/items/{stale_detail['items'][0]['id']}/review",
        headers=headers,
        json={
            "expected_revision": stale_detail["items"][0]["revision"],
            "product_facts_match": True,
            "geometry_and_count_match": True,
            "logo_text_and_personalization_match": True,
            "thumbnail_readable": True,
            "compliance_risk": "clear",
            "notes": "商品事实已经变化，旧候选不应再允许进入确认流程。",
        },
    )
    assert blocked_stale_review.status_code == 409
