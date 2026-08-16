from fastapi.testclient import TestClient

from tests.conftest import auth_header, login


def _project(client: TestClient, headers: dict[str, str], *, name: str = "收纳盒项目") -> str:
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": name,
            "platform": "拼多多",
            "store_name": "一号店铺",
            "category": "家居收纳",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _asset(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    asset_type: str,
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/projects/{project_id}/assets",
        headers=headers,
        json={
            "asset_type": asset_type,
            "file_url": f"data:image/png;base64,{asset_type}",
            "file_hash": f"sha256:{asset_type}",
            "mime_type": "image/png",
            "file_size": 128,
            "usage_note": "用于验证素材分类和用途",
            "metadata": {
                "original_name": f"{asset_type}.png",
                "selected_for_generation": True,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_operator_can_edit_search_and_filter_project(client: TestClient) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id = _project(client, headers)
    _project(client, headers, name="服饰项目")

    changed = client.patch(
        f"/api/v1/projects/{project_id}",
        headers=headers,
        json={
            "name": "透明收纳盒主图项目",
            "platform": "Amazon",
            "store_name": "日本站店铺",
            "category": "厨房收纳",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["name"] == "透明收纳盒主图项目"
    assert changed.json()["platform"] == "Amazon"

    searched = client.get(
        "/api/v1/projects?bucket=draft&q=透明&platform=Amazon&store_name=日本&category=厨房",
        headers=headers,
    )
    assert searched.status_code == 200, searched.text
    assert [item["id"] for item in searched.json()] == [project_id]

    admin_headers = auth_header(login(client, "admin@example.local"))
    assert client.patch(
        f"/api/v1/projects/{project_id}",
        headers=admin_headers,
        json={"name": "管理员越权修改"},
    ).status_code == 403


def test_product_card_returns_sources_and_missing_field_impacts(
    client: TestClient,
) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id = _project(client, headers)
    response = client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={
            "product_name": "透明收纳盒",
            "facts": {"color": "透明", "material": ""},
            "field_sources": {"product_name": "operator", "color": "reference_image"},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["field_sources"]["color"] == "reference_image"
    gaps = {item["field"]: item for item in payload["missing_fields"]}
    assert {"material", "selling_points", "specs", "must_not_change"}.issubset(gaps)
    assert "AI 生图" in gaps["material"]["required_for"]
    assert payload["completeness_percent"] < 100


def test_material_categories_selection_and_safe_archive(client: TestClient) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id = _project(client, headers)
    assets = {
        asset_type: _asset(client, headers, project_id, asset_type)
        for asset_type in (
            "product_raw",
            "main_image",
            "competitor_image",
            "product_reference",
        )
    }
    assert all(item["selected_for_generation"] is False for item in assets.values())
    reference_id = str(assets["product_reference"]["id"])
    selected = client.put(
        f"/api/v1/projects/{project_id}/assets/{reference_id}/selection",
        headers=headers,
        json={"selected_for_generation": True},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_for_generation"] is True
    assert selected.json()["usage_note"] == "用于验证素材分类和用途"

    raw_id = str(assets["product_raw"]["id"])
    archived = client.post(
        f"/api/v1/projects/{project_id}/assets/{raw_id}/archive",
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_archived"] is True
    listed_ids = {
        item["id"]
        for item in client.get(
            f"/api/v1/projects/{project_id}/assets", headers=headers
        ).json()
    }
    assert raw_id not in listed_ids

    designer_headers = auth_header(login(client, "designer@example.local"))
    assert client.put(
        f"/api/v1/projects/{project_id}/assets/{reference_id}/selection",
        headers=designer_headers,
        json={"selected_for_generation": False},
    ).status_code == 403


def test_referenced_material_cannot_be_archived(client: TestClient) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id = _project(client, headers)
    final_asset = _asset(client, headers, project_id, "main_image")
    task_asset = _asset(client, headers, project_id, "style_reference")

    content = client.post(
        f"/api/v1/projects/{project_id}/content-versions",
        headers=headers,
        json={
            "content_type": "result_note",
            "content": {"text": "采用主图", "asset_ids": [final_asset["id"]]},
            "source_kind": "human",
        },
    )
    assert content.status_code == 201, content.text
    assert client.post(
        f"/api/v1/projects/{project_id}/content-versions/{content.json()['id']}/finalize",
        headers=headers,
    ).status_code == 200

    designers = client.get("/api/v1/design-tasks/designers", headers=headers)
    assert designers.status_code == 200, designers.text
    task = client.post(
        "/api/v1/design-tasks",
        headers=headers,
        json={
            "project_id": project_id,
            "assigned_to_id": designers.json()[0]["id"],
            "title": "处理素材",
            "brief": "请严格根据关联素材完成设计，不得修改商品事实。",
            "requirements": [{"item": "关联素材", "asset_ids": [task_asset["id"]]}],
        },
    )
    assert task.status_code == 201, task.text

    final_blocked = client.post(
        f"/api/v1/projects/{project_id}/assets/{final_asset['id']}/archive",
        headers=headers,
    )
    assert final_blocked.status_code == 409
    assert "最终内容" in final_blocked.json()["detail"]
    task_blocked = client.post(
        f"/api/v1/projects/{project_id}/assets/{task_asset['id']}/archive",
        headers=headers,
    )
    assert task_blocked.status_code == 409
    assert "美工任务" in task_blocked.json()["detail"]

    detail = client.get(f"/api/v1/projects/{project_id}", headers=headers)
    by_id = {item["id"]: item for item in detail.json()["assets"]}
    assert by_id[final_asset["id"]]["archive_blockers"]
    assert by_id[task_asset["id"]]["archive_blockers"]
