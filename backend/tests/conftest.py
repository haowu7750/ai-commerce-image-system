from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app


DEMO_PASSWORD = "Test-Demo-Password-123!"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        auto_create_tables=True,
        seed_demo_data=True,
        demo_password=SecretStr(DEMO_PASSWORD),
        secret_key=SecretStr("test-only-signing-secret-with-sufficient-length"),
        image_provider="mock",
        image_model="gpt-image-2",
    )


@pytest.fixture()
def client(settings: Settings) -> Generator[TestClient, None, None]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": email, "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
