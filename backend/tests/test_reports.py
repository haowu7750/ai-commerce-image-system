from fastapi.testclient import TestClient

from tests.conftest import auth_header, login


def _create_project_with_final_content(
    client: TestClient, headers: dict[str, str]
) -> str:
    project = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "成果导出商品", "platform": "拼多多", "store_name": "本地店铺"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    assert client.put(
        f"/api/v1/projects/{project_id}/product-card",
        headers=headers,
        json={
            "product_name": "玻璃水杯",
            "facts": {"color": "透明", "material": "高硼硅玻璃"},
            "selling_points": [{"text": "耐冷热"}],
            "specs": [{"capacity": "500ml"}],
            "constraints": {"must_not_change": ["容量刻度"]},
        },
    ).status_code == 200
    assert client.post(
        f"/api/v1/projects/{project_id}/product-card/confirm", headers=headers
    ).status_code == 200
    for content_type, content in (
        ("title", {"text": "高硼硅玻璃水杯 500ml", "risk_level": "low"}),
        (
            "sku",
            {
                "items": [
                    {"sku_name": "透明-500ml", "color": "透明", "capacity": "500ml"}
                ]
            },
        ),
    ):
        created = client.post(
            f"/api/v1/projects/{project_id}/content-versions",
            headers=headers,
            json={"content_type": content_type, "content": content, "source_kind": "human"},
        )
        assert created.status_code == 201, created.text
        assert client.post(
            f"/api/v1/projects/{project_id}/content-versions/{created.json()['id']}/finalize",
            headers=headers,
        ).status_code == 200
    return project_id


def test_delivery_package_timeline_and_exports_are_operator_scoped(
    client: TestClient,
) -> None:
    operator_headers = auth_header(login(client, "operator@example.local"))
    project_id = _create_project_with_final_content(client, operator_headers)

    package = client.get(
        f"/api/v1/reports/projects/{project_id}", headers=operator_headers
    )
    assert package.status_code == 200, package.text
    assert package.json()["product_card"]["product_name"] == "玻璃水杯"
    assert package.json()["final_content"]["title"]["risk_level"] == "low"
    assert "尚无运营确认通过的生图结果" in package.json()["blockers"]
    assert any(item["action"] == "product_card.confirmed" for item in package.json()["timeline"])

    markdown = client.get(
        f"/api/v1/reports/projects/{project_id}/exports/markdown",
        headers=operator_headers,
    )
    assert markdown.status_code == 200
    assert markdown.json()["filename"].endswith(".md")
    assert "高硼硅玻璃水杯" in markdown.json()["content"]

    sku_csv = client.get(
        f"/api/v1/reports/projects/{project_id}/exports/sku-csv",
        headers=operator_headers,
    )
    assert sku_csv.status_code == 200
    assert sku_csv.json()["content"].startswith("\ufeff")
    assert "500ml" in sku_csv.json()["content"]

    designer_headers = auth_header(login(client, "designer@example.local"))
    assert client.get(
        f"/api/v1/reports/projects/{project_id}", headers=designer_headers
    ).status_code == 403


def test_high_risk_final_content_cannot_be_exported_as_a_knowledge_case(
    client: TestClient,
) -> None:
    headers = auth_header(login(client, "operator@example.local"))
    project_id = _create_project_with_final_content(client, headers)
    response = client.post(
        f"/api/v1/reports/projects/{project_id}/knowledge-case",
        headers=headers,
        json={"name": "未过门禁案例", "notes": "不应保存"},
    )
    assert response.status_code == 409
    assert "门禁" in response.json()["detail"]


def test_library_exposes_admin_prompt_to_operator_without_granting_admin_write(
    client: TestClient,
) -> None:
    operator_headers = auth_header(login(client, "operator@example.local"))
    admin_headers = auth_header(login(client, "admin@example.local"))
    created = client.post(
        "/api/v1/admin/resources",
        headers=admin_headers,
        json={
            "kind": "prompt",
            "name": "保真场景 Prompt 模板",
            "description": "运营可读模板",
            "content": {"template": "严格保持参考图中的商品事实"},
        },
    )
    assert created.status_code == 201, created.text
    library = client.get(
        "/api/v1/reports/library?kind=prompt", headers=operator_headers
    )
    assert library.status_code == 200, library.text
    assert library.json()[0]["name"] == "保真场景 Prompt 模板"
    assert client.post(
        "/api/v1/admin/resources",
        headers=operator_headers,
        json={"kind": "prompt", "name": "越权模板", "content": {}},
    ).status_code == 403
