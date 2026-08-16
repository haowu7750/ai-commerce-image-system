from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


LAUNCHER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "start_local.py"
SPEC = importlib.util.spec_from_file_location("commerce_image_start_local", LAUNCHER_PATH)
assert SPEC is not None and SPEC.loader is not None
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def _install_running_identities(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    monkeypatch.setattr(launcher, "port_is_available", lambda _port: False)

    def fake_identity(url: str) -> dict[str, str]:
        if url.endswith("/health") and ":8100" in url:
            return {
                "service": "ai-commerce-operations-backend",
                "image_provider": provider,
                "image_model": "gpt-image-2",
            }
        return {"service": "ai-commerce-operations-frontend"}

    monkeypatch.setattr(launcher, "fetch_service_identity", fake_identity)


def test_same_running_system_is_reused_without_duplicate_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_running_identities(monkeypatch, "shulicode")
    opened: list[str] = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)

    reused = launcher.reuse_running_system(
        backend_port=8100,
        frontend_port=3100,
        desired_provider="shulicode",
        backend_only=False,
        frontend_only=False,
        open_browser=True,
    )

    assert reused is True
    assert opened == ["http://127.0.0.1:3100/login"]


def test_running_image_mode_must_match_requested_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_running_identities(monkeypatch, "mock")

    with pytest.raises(RuntimeError, match="Stop-System.cmd"):
        launcher.reuse_running_system(
            backend_port=8100,
            frontend_port=3100,
            desired_provider="shulicode",
            backend_only=False,
            frontend_only=False,
            open_browser=False,
        )


def test_unrelated_port_owner_is_not_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher, "port_is_available", lambda _port: False)
    monkeypatch.setattr(launcher, "fetch_service_identity", lambda _url: None)

    assert (
        launcher.reuse_running_system(
            backend_port=8100,
            frontend_port=3100,
            desired_provider="mock",
            backend_only=False,
            frontend_only=False,
            open_browser=False,
        )
        is False
    )
