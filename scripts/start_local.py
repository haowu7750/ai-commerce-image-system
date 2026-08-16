from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = WORKSPACE_ROOT / "backend"
FRONTEND_ROOT = WORKSPACE_ROOT / "frontend"
NEXT_ENTRY = FRONTEND_ROOT / "node_modules" / "next" / "dist" / "bin" / "next"


def find_node() -> Path:
    candidates: list[Path] = []
    path_node = shutil.which("node")
    if path_node:
        candidates.append(Path(path_node))
    candidates.extend(
        [
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe",
            Path.home() / "AppData" / "Local" / "Programs" / "nodejs" / "node.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "nodejs"
            / "node.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("Node.js was not found; the frontend cannot start.")


def port_is_available(port: int) -> bool:
    bind_targets: list[tuple[int, tuple[object, ...]]] = []
    if socket.has_ipv6:
        bind_targets.append((socket.AF_INET6, ("::", port, 0, 0)))
    bind_targets.append((socket.AF_INET, ("0.0.0.0", port)))

    for family, address in bind_targets:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    probe.setsockopt(
                        socket.SOL_SOCKET,
                        socket.SO_EXCLUSIVEADDRUSE,
                        1,
                    )
                if family == socket.AF_INET6:
                    probe.setsockopt(
                        socket.IPPROTO_IPV6,
                        socket.IPV6_V6ONLY,
                        0,
                    )
                probe.bind(address)
        except OSError:
            return False
    return True


def require_available_port(
    label: str,
    port: int,
    reserved_ports: set[int],
) -> int:
    if port in reserved_ports:
        raise RuntimeError(
            f"The fixed {label} port {port} duplicates another service "
            "in this project."
        )
    if not port_is_available(port):
        raise RuntimeError(
            f"The fixed {label} port {port} is already in use. "
            "This launcher will not silently switch ports. Check the global "
            "port registry and stop the conflicting service, or register a "
            f"new fixed port before changing --{label}-port."
        )
    return port


def fetch_service_identity(url: str) -> dict[str, object] | None:
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=0.75) as response:
                if not 200 <= response.status < 400:
                    return None
                payload = json.loads(response.read(8192).decode("utf-8"))
                return payload if isinstance(payload, dict) else None
        except (OSError, ValueError, urllib.error.URLError):
            if attempt < 4:
                time.sleep(0.35)
    return None


def reuse_running_system(
    *,
    backend_port: int,
    frontend_port: int,
    desired_provider: str,
    backend_only: bool,
    frontend_only: bool,
    open_browser: bool,
) -> bool:
    check_backend = not frontend_only
    check_frontend = not backend_only
    backend_available = not check_backend or port_is_available(backend_port)
    frontend_available = not check_frontend or port_is_available(frontend_port)
    if backend_available and frontend_available:
        return False

    backend_identity = (
        fetch_service_identity(f"http://127.0.0.1:{backend_port}/health")
        if check_backend and not backend_available
        else None
    )
    frontend_identity = (
        fetch_service_identity(f"http://127.0.0.1:{frontend_port}/api/health")
        if check_frontend and not frontend_available
        else None
    )
    backend_matches = (
        not check_backend
        or (
            backend_identity is not None
            and backend_identity.get("service") == "ai-commerce-operations-backend"
        )
    )
    frontend_matches = (
        not check_frontend
        or (
            frontend_identity is not None
            and frontend_identity.get("service") == "ai-commerce-operations-frontend"
        )
    )
    every_requested_port_is_occupied = (
        (not check_backend or not backend_available)
        and (not check_frontend or not frontend_available)
    )
    if not (every_requested_port_is_occupied and backend_matches and frontend_matches):
        return False

    if check_backend:
        running_provider = str(backend_identity.get("image_provider", "unknown"))
        running_model = str(backend_identity.get("image_model", "unknown"))
        if running_provider != desired_provider or running_model != "gpt-image-2":
            raise RuntimeError(
                "This project is already running, but its image mode is "
                f"{running_provider}/{running_model}; the requested mode is "
                f"{desired_provider}/gpt-image-2. Run Stop-System.cmd first, "
                "then start the required mode."
            )

    print("This project is already running; no duplicate process was started.", flush=True)
    if check_backend:
        print(f"Backend: http://127.0.0.1:{backend_port}/health", flush=True)
    if check_frontend:
        frontend_url = f"http://127.0.0.1:{frontend_port}/login"
        print(f"Open: {frontend_url}", flush=True)
        if open_browser:
            webbrowser.open(frontend_url)
    return True


def wait_for_http(
    url: str,
    process: subprocess.Popen[bytes],
    timeout: float,
    expected_body: bytes,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"The service exited early with code {return_code}.")
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                response_body = response.read(8192)
                if (
                    200 <= response.status < 400
                    and expected_body in response_body
                ):
                    return
                last_error = (
                    f"HTTP {response.status} did not identify the expected service"
                )
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.35)
    raise RuntimeError(f"Timed out waiting for {url}. Last error: {last_error}")


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def build_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.setdefault("APP_IMAGE_PROVIDER", "mock")
    environment["APP_TEXT_PROVIDER"] = "mock"
    environment["APP_VISION_PROVIDER"] = "mock"
    environment.setdefault("APP_IMAGE_MODEL", "gpt-image-2")
    if environment["APP_IMAGE_PROVIDER"] not in {"mock", "shulicode"}:
        raise RuntimeError("APP_IMAGE_PROVIDER must be mock or shulicode.")
    if environment["APP_IMAGE_MODEL"] != "gpt-image-2":
        raise RuntimeError("APP_IMAGE_MODEL must be gpt-image-2.")
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the local commerce image system.")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--backend-port", type=int, default=8100)
    parser.add_argument("--frontend-port", type=int, default=3100)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--smoke-seconds", type=float, default=0, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.backend_only and args.frontend_only:
        raise RuntimeError("--backend-only and --frontend-only cannot be used together.")
    for port in (args.backend_port, args.frontend_port):
        if not 1 <= port <= 65535:
            raise RuntimeError("Ports must be between 1 and 65535.")

    node: Path | None = None
    if not args.backend_only:
        node = find_node()
        if not NEXT_ENTRY.is_file():
            raise RuntimeError(
                "Frontend dependencies are incomplete: Next.js entry was not found."
            )
    environment = build_environment()
    if args.check:
        print(f"Python: {sys.executable}")
        if node is not None:
            print(f"Node: {node}")
        print("Launcher check: passed")
        return 0

    if reuse_running_system(
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
        desired_provider=environment["APP_IMAGE_PROVIDER"],
        backend_only=args.backend_only,
        frontend_only=args.frontend_only,
        open_browser=args.smoke_seconds <= 0 and not args.no_browser,
    ):
        return 0

    reserved_ports: set[int] = set()
    if not args.frontend_only:
        args.backend_port = require_available_port(
            "backend",
            args.backend_port,
            reserved_ports,
        )
        reserved_ports.add(args.backend_port)
    if not args.backend_only:
        args.frontend_port = require_available_port(
            "frontend",
            args.frontend_port,
            reserved_ports,
        )
        reserved_ports.add(args.frontend_port)

    environment["APP_WEB_ORIGIN"] = (
        f"http://127.0.0.1:{args.frontend_port}"
    )
    environment["NEXT_PUBLIC_API_BASE_URL"] = (
        f"http://127.0.0.1:{args.backend_port}/api/v1"
    )

    backend_process: subprocess.Popen[bytes] | None = None
    frontend_process: subprocess.Popen[bytes] | None = None
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        if not args.frontend_only:
            backend_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.backend_port),
                ],
                cwd=BACKEND_ROOT,
                env=environment,
                creationflags=creation_flags,
            )
            backend_url = f"http://127.0.0.1:{args.backend_port}/health"
            wait_for_http(
                backend_url,
                backend_process,
                timeout=25,
                expected_body=b'"service":"ai-commerce-operations-backend"',
            )
            print(f"Backend ready: {backend_url}", flush=True)

        if not args.backend_only:
            if node is None:
                raise RuntimeError("Node.js resolution unexpectedly failed.")
            frontend_process = subprocess.Popen(
                [
                    str(node),
                    str(NEXT_ENTRY),
                    "dev",
                    "--webpack",
                    "--port",
                    str(args.frontend_port),
                ],
                cwd=FRONTEND_ROOT,
                env=environment,
                creationflags=creation_flags,
            )
            frontend_url = f"http://127.0.0.1:{args.frontend_port}"
            frontend_health_url = f"{frontend_url}/api/health"
            wait_for_http(
                frontend_health_url,
                frontend_process,
                timeout=60,
                expected_body=b'"service":"ai-commerce-operations-frontend"',
            )
            print(f"Frontend ready: {frontend_url}", flush=True)
            print(
                "Open the frontend URL in your browser. Press Ctrl+C to stop.",
                flush=True,
            )
            if args.smoke_seconds <= 0 and not args.no_browser:
                webbrowser.open(f"{frontend_url}/login")

        smoke_deadline = (
            time.monotonic() + args.smoke_seconds
            if args.smoke_seconds > 0
            else None
        )
        while True:
            for label, process in (
                ("backend", backend_process),
                ("frontend", frontend_process),
            ):
                if process is None:
                    continue
                return_code = process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"The {label} service exited with code {return_code}."
                    )
            if smoke_deadline is not None and time.monotonic() >= smoke_deadline:
                return 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping services...", flush=True)
        return 0
    finally:
        stop_process(frontend_process)
        stop_process(backend_process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
