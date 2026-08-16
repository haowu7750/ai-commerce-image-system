from fastapi.testclient import TestClient

from tests.conftest import auth_header


def demo_login(client: TestClient, role: str) -> str:
    response = client.post("/api/v1/auth/demo-login", json={"role": role})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_role_workspaces_persist_and_enforce_boundaries(client: TestClient) -> None:
    operator_token = demo_login(client, "operator")
    designer_token = demo_login(client, "designer")
    admin_token = demo_login(client, "admin")
    operator = client.get(
        "/api/v1/auth/me", headers=auth_header(operator_token)
    ).json()
    designer = client.get(
        "/api/v1/auth/me", headers=auth_header(designer_token)
    ).json()

    project_response = client.post(
        "/api/v1/projects",
        headers=auth_header(operator_token),
        json={
            "name": "角色功能联调项目",
            "platform": "拼多多",
            "store_name": "测试店铺",
            "category": "家居",
        },
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]

    card_response = client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=auth_header(operator_token),
        json={
            "product_name": "桌面收纳盒",
            "brand": "示例品牌",
            "current_title": "桌面收纳盒",
            "facts": {"color": "白色", "material": "ABS"},
            "selling_points": [{"text": "分区收纳"}],
            "specs": [{"name": "尺寸", "value": "20×10cm"}],
            "constraints": {"must_not_change": ["颜色"]},
            "field_sources": {"color": "operator"},
            "completeness_percent": 95,
        },
    )
    assert card_response.status_code == 200, card_response.text
    assert card_response.json()["facts"]["color"] == "白色"
    confirm_response = client.post(
        f"/api/v1/projects/{project_id}/product-card/confirm",
        headers=auth_header(operator_token),
    )
    assert confirm_response.status_code == 200

    content_response = client.post(
        f"/api/v1/projects/{project_id}/content-versions",
        headers=auth_header(operator_token),
        json={
            "content_type": "title",
            "content": {
                "text": "桌面分区收纳盒 家用简约整理盒",
                "risk_level": "low",
            },
            "source_kind": "human",
        },
    )
    assert content_response.status_code == 201, content_response.text
    content_id = content_response.json()["id"]
    finalize_response = client.post(
        f"/api/v1/projects/{project_id}/content-versions/{content_id}/finalize",
        headers=auth_header(operator_token),
    )
    assert finalize_response.status_code == 200
    assert finalize_response.json()["is_final"] is True

    admin_cannot_finalize = client.post(
        f"/api/v1/projects/{project_id}/content-versions/{content_id}/finalize",
        headers=auth_header(admin_token),
    )
    assert admin_cannot_finalize.status_code == 403

    task_response = client.post(
        "/api/v1/design-tasks",
        headers=auth_header(operator_token),
        json={
            "project_id": project_id,
            "assigned_to_id": designer["id"],
            "title": "制作白底主图",
            "brief": "保持商品白色和几何比例，制作清晰白底主图。",
            "requirements": [
                {"item": "保持颜色", "acceptance": "不得偏色"},
                {"item": "画布", "acceptance": "1:1"},
            ],
            "priority": "high",
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = task_response.json()["id"]

    delete_with_open_task = client.post(
        f"/api/v1/projects/{project_id}/delete",
        headers=auth_header(operator_token),
        json={"reason": "测试未完成任务阻断"},
    )
    assert delete_with_open_task.status_code == 409
    assert "未完成美工任务" in delete_with_open_task.json()["detail"]

    designer_tasks = client.get(
        "/api/v1/design-tasks", headers=auth_header(designer_token)
    )
    assert designer_tasks.status_code == 200
    assert [task["id"] for task in designer_tasks.json()] == [task_id]

    status_response = client.patch(
        f"/api/v1/design-tasks/{task_id}/status",
        headers=auth_header(designer_token),
        json={"status": "in_progress"},
    )
    assert status_response.status_code == 200
    submission_response = client.post(
        f"/api/v1/design-tasks/{task_id}/submissions",
        headers=auth_header(designer_token),
        json={
            "file_url": "data:image/png;base64,iVBORw0KGgo=",
            "notes": "第一版，已保持白色与原比例。",
        },
    )
    assert submission_response.status_code == 201, submission_response.text
    assert submission_response.json()["status"] == "submitted"
    assert submission_response.json()["submissions"][0]["version_no"] == 1

    review_response = client.post(
        f"/api/v1/design-tasks/{task_id}/review",
        headers=auth_header(operator_token),
        json={"decision": "accepted", "notes": "符合要求，确认通过。"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["status"] == "completed"

    designer_cannot_create_task = client.post(
        "/api/v1/design-tasks",
        headers=auth_header(designer_token),
        json={
            "project_id": project_id,
            "assigned_to_id": designer["id"],
            "title": "越权任务",
            "brief": "这个请求必须被服务端角色权限拒绝。",
        },
    )
    assert designer_cannot_create_task.status_code == 403

    resource_response = client.post(
        "/api/v1/admin/resources",
        headers=auth_header(admin_token),
        json={
            "kind": "prompt",
            "name": "主图保真模板",
            "description": "供运营生成保真提示词时使用",
            "content": {"template": "保持参考图中的商品事实"},
        },
    )
    assert resource_response.status_code == 201, resource_response.text
    assert resource_response.json()["version"] == 1
    operator_cannot_create_resource = client.post(
        "/api/v1/admin/resources",
        headers=auth_header(operator_token),
        json={
            "kind": "prompt",
            "name": "越权模板",
            "content": {},
        },
    )
    assert operator_cannot_create_resource.status_code == 403

    result_response = client.get(
        f"/api/v1/projects/{project_id}/result-summary",
        headers=auth_header(operator_token),
    )
    assert result_response.status_code == 200
    result = result_response.json()
    assert result["product_card_confirmed"] is True
    assert result["accepted_design_count"] == 1
    assert result["final_content"]["title"]["text"].startswith("桌面")
    assert result["blockers"] == []

    audit_response = client.get(
        "/api/v1/admin/audit-events",
        headers=auth_header(admin_token),
    )
    assert audit_response.status_code == 200
    actions = {event["action"] for event in audit_response.json()}
    assert "design_task.reviewed" in actions
    assert "content_version.finalized" in actions
    assert operator["roles"] == ["operator"]

    user_update = client.patch(
        f"/api/v1/admin/users/{designer['id']}",
        headers=auth_header(admin_token),
        json={
            "display_name": "设计体验账号（已更新）",
            "roles": ["designer", "operator"],
        },
    )
    assert user_update.status_code == 200, user_update.text
    assert user_update.json()["display_name"].endswith("（已更新）")
    assert set(user_update.json()["roles"]) == {"designer", "operator"}
