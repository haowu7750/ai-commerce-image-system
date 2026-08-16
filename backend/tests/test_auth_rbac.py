from fastapi.testclient import TestClient

from tests.conftest import DEMO_PASSWORD, auth_header, login


def test_builtin_roles_are_isolated(client: TestClient) -> None:
    operator = login(client, "operator@example.local")
    admin = login(client, "admin@example.local")
    designer = login(client, "designer@example.local")

    assert client.get("/api/v1/admin/users", headers=auth_header(operator)).status_code == 403
    assert client.get("/api/v1/projects", headers=auth_header(admin)).status_code == 403
    assert client.get("/api/v1/projects", headers=auth_header(designer)).status_code == 403
    assert client.get("/api/v1/admin/users", headers=auth_header(admin)).status_code == 200


def test_admin_can_create_multi_role_user(client: TestClient) -> None:
    admin = login(client, "admin@example.local")
    response = client.post(
        "/api/v1/admin/users",
        headers=auth_header(admin),
        json={
            "email": "combined@example.local",
            "display_name": "运营管理员",
            "password": DEMO_PASSWORD,
            "roles": ["operator", "admin"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["roles"] == ["admin", "operator"]

    combined = login(client, "combined@example.local")
    assert client.get("/api/v1/admin/users", headers=auth_header(combined)).status_code == 200
    assert client.get("/api/v1/projects", headers=auth_header(combined)).status_code == 200

