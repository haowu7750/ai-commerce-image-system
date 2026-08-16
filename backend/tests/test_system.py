import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from tests.conftest import auth_header, login


SHULICODE_ENV_NAMES = (
    "APP_IMAGE_PROVIDER",
    "APP_IMAGE_API_BASE_URL",
    "APP_IMAGE_API_KEY",
    "APP_IMAGE_MODEL",
    "SHULICODE_BASE_URL",
    "SHULICODE_API_KEY",
    "SHULICODE_IMAGE_MODEL",
)


def _secret_digest(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    return hashlib.sha256(secret.get_secret_value().encode("utf-8")).hexdigest()


def test_health_is_public_and_has_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "service": "ai-commerce-operations-backend",
        "environment": "test",
        "image_provider": "mock",
        "image_model": "gpt-image-2",
        "status": "ok",
    }
    assert response.headers["X-Request-ID"]


def test_safe_config_requires_admin_and_never_exposes_secrets(client: TestClient) -> None:
    operator = login(client, "operator@example.local")
    denied = client.get("/api/v1/config/safe", headers=auth_header(operator))
    assert denied.status_code == 403

    admin = login(client, "admin@example.local")
    response = client.get("/api/v1/config/safe", headers=auth_header(admin))
    assert response.status_code == 200
    payload = response.json()
    assert payload["image_provider"] == "mock"
    serialized = response.text.lower()
    assert "api_key" not in serialized
    assert "secret_key" not in serialized
    assert "password" not in serialized
    assert "sqlite:///" not in serialized


def test_shulicode_aliases_load_from_supplied_root_env_without_enabling_network(
    tmp_path: Path, monkeypatch
) -> None:
    for name in SHULICODE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    root_env = tmp_path / ".env.local"
    backend_env = tmp_path / "backend.env"
    root_env.write_text(
        "SHULICODE_BASE_URL=https://root-config.invalid/v1/\n"
        "SHULICODE_API_KEY=root-test-secret-17\n"
        "SHULICODE_IMAGE_MODEL=gpt-image-2\n",
        encoding="utf-8",
    )
    backend_env.write_text("", encoding="utf-8")

    settings = Settings(_env_file=(root_env, backend_env))

    assert settings.image_api_base_url == "https://root-config.invalid/v1"
    assert settings.image_model == "gpt-image-2"
    assert settings.image_provider == "mock"
    assert str(settings.image_api_key) == "**********"
    assert _secret_digest(settings.image_api_key) == hashlib.sha256(
        b"root-test-secret-17"
    ).hexdigest()


def test_backend_app_aliases_and_process_environment_override_root_env(
    tmp_path: Path, monkeypatch
) -> None:
    for name in SHULICODE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    root_env = tmp_path / ".env.local"
    backend_env = tmp_path / "backend.env"
    root_env.write_text(
        "SHULICODE_BASE_URL=https://root-config.invalid/v1\n"
        "SHULICODE_API_KEY=root-test-secret\n"
        "SHULICODE_IMAGE_MODEL=gpt-image-2\n",
        encoding="utf-8",
    )
    backend_env.write_text(
        "APP_IMAGE_API_BASE_URL=https://backend-config.invalid/v1/\n"
        "APP_IMAGE_API_KEY=backend-test-secret\n"
        "APP_IMAGE_MODEL=gpt-image-2\n",
        encoding="utf-8",
    )

    backend_settings = Settings(_env_file=(root_env, backend_env))
    assert backend_settings.image_api_base_url == "https://backend-config.invalid/v1"
    assert _secret_digest(backend_settings.image_api_key) == hashlib.sha256(
        b"backend-test-secret"
    ).hexdigest()

    monkeypatch.setenv("APP_IMAGE_API_BASE_URL", "https://process-config.invalid/v1/")
    monkeypatch.setenv("APP_IMAGE_API_KEY", "process-test-secret")
    monkeypatch.setenv("APP_IMAGE_MODEL", "gpt-image-2")
    process_settings = Settings(_env_file=(root_env, backend_env))
    assert process_settings.image_api_base_url == "https://process-config.invalid/v1"
    assert process_settings.image_model == "gpt-image-2"
    assert process_settings.image_provider == "mock"
    assert _secret_digest(process_settings.image_api_key) == hashlib.sha256(
        b"process-test-secret"
    ).hexdigest()
