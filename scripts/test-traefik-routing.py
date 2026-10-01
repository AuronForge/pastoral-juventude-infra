#!/usr/bin/env python3
"""Exercise the actual Traefik version routers against local HTTP stubs."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import uuid
import socket
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
HEALTHY = threading.Event()
HEALTHY.set()


def stub(identity):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = f"{identity} {self.path}".encode()
            self.send_response(503 if identity == "backend" and self.path == "/health/ready" and not HEALTHY.is_set() else 200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def request(port, path):
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return response.status, response.read().decode()
    except HTTPError as error:
        return error.code, error.read().decode()


def check_config(path, backend_port, frontend_port):
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "dynamic.yml"
        config.write_text(
            path.read_text()
            .replace("http://backend:3000", f"http://127.0.0.1:{backend_port}")
            .replace("http://frontend:8080", f"http://127.0.0.1:{frontend_port}")
        )
        # Use an available local port in this isolated GitHub-hosted test.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            api_port = sock.getsockname()[1]
        container = subprocess.check_output([
            "docker", "run", "--detach", "--network", "host",
            "--volume", f"{config}:/config/dynamic.yml:ro",
            "traefik:v3.7.13",
            f"--entrypoints.web.address=127.0.0.1:{port}",
            f"--entrypoints.api-public.address=127.0.0.1:{api_port}",
            "--providers.file.filename=/config/dynamic.yml",
        ], text=True).strip()
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    if request(port, "/") == (200, "frontend /"):
                        break
                except (URLError, TimeoutError, ConnectionError):
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError("Traefik did not become ready")
                time.sleep(0.25)

            for url in ("/api/v1", "/api/v1/", "/api/v1/pessoas",
                        "/api/v1/pessoas?pagina=1"):
                assert request(port, url) == (200, f"backend {url}"), url
            for url in ("/api", "/api/", "/api/v2", "/api/v2/pessoas",
                        "/api/v10/pessoas", "/api/v1extra"):
                assert request(port, url)[0] == 404, url
            for url in ("/", "/login", "/apiculture"):
                assert request(port, url) == (200, f"frontend {url}"), url
            for url in ("/", "/login", "/health/ready", "/api", "/api/v2/pessoas"):
                assert request(api_port, url)[0] == 404, url
            for url in ("/api/v1", "/api/v1/pessoas?pagina=1"):
                expected = ((200, f"backend {url}")
                            if path.name == "dynamic.development.yml"
                            else None)
                response = request(api_port, url)
                if expected:
                    assert response == expected, url
                else:
                    assert response[0] == 404, url
            if path.name == "dynamic.development.yml":
                assert request(api_port, "/api/v1/health") == (
                    200, "backend /health/ready"), "public health path"
                with urlopen(f"http://127.0.0.1:{api_port}/api/v1/health",
                             timeout=2) as response:
                    assert response.headers.get("Cache-Control") == "no-store"
                assert request(api_port, "/api/v1/health/extra") == (
                    200, "backend /api/v1/health/extra"), "exact health matcher"
                HEALTHY.clear()
                try:
                    assert request(api_port, "/api/v1/health") == (
                        503, "backend /health/ready"), "dependency failure visible"
                finally:
                    HEALTHY.set()
            print(f"{path.name}: version routing and public health isolation passed")
        except Exception:
            subprocess.run(["docker", "logs", container], check=False)
            raise
        finally:
            subprocess.run(["docker", "rm", "--force", container],
                           check=False, stdout=subprocess.DEVNULL)


def check_desktop_runtime(backend_port, frontend_port):
    """Load the actual Desktop static config/command from the runtime volume."""
    volume = "pastoral-dev_runtime-routing-" + uuid.uuid4().hex
    secrets_volume = "pastoral-dev_runtime-secrets"
    if subprocess.run(["docker", "volume", "inspect", secrets_volume],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise AssertionError("Refusing to touch existing development secrets")
    container = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / "scripts").mkdir()
            (stage / "traefik").mkdir()
            (stage / "secrets").mkdir()
            shutil.copyfile(ROOT / "scripts/backend-entrypoint.sh",
                            stage / "scripts/backend-entrypoint.sh")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                api_port = sock.getsockname()[1]
            (stage / "traefik/traefik.yml").write_text(
                (ROOT / "traefik/traefik.yml").read_text()
                .replace("address: :80\n", f"address: :{port}\n")
                .replace("address: :8082\n", f"address: :{api_port}\n"))
            (stage / "traefik/dynamic.development.yml").write_text(
                (ROOT / "traefik/dynamic.development.yml").read_text()
                .replace("http://backend:3000", f"http://127.0.0.1:{backend_port}")
                .replace("http://frontend:8080", f"http://127.0.0.1:{frontend_port}"))
            for name in ("postgres_password", "redis_password",
                         "jwt_private_key.pem", "jwt_public_key.pem"):
                (stage / "secrets" / name).write_text("fixture-only")
            subprocess.run(["bash", str(ROOT / "scripts/sync-development-runtime.sh"),
                            str(stage), volume, str(stage / "secrets")], check=True)
            # Exercise the command defined by the real overlay, not a CLI-only test.
            flags = re.findall(r"^\s+- (--.+)$",
                               (ROOT / "compose.development.desktop.yaml").read_text(),
                               re.MULTILINE)
            container = subprocess.check_output([
                "docker", "run", "--detach", "--network", "host",
                "--mount", f"type=volume,src={volume},dst=/etc/pastoral,readonly",
                "traefik:v3.7.13", *flags], text=True).strip()
            deadline = time.monotonic() + 30
            while True:
                try:
                    if request(port, "/") == (200, "frontend /"):
                        break
                except (URLError, TimeoutError, ConnectionError):
                    pass
                if time.monotonic() >= deadline:
                    raise AssertionError("Desktop runtime did not load frontend router")
                time.sleep(0.25)
            assert request(port, "/login") == (200, "frontend /login")
            assert request(api_port, "/api/v1/pessoas") == (200, "backend /api/v1/pessoas")
            assert request(api_port, "/api/v1/health") == (200, "backend /health/ready")
            assert request(api_port, "/")[0] == 404
            print("Desktop runtime: static config, frontend and API routing passed")
    except Exception:
        if container:
            subprocess.run(["docker", "logs", container], check=False)
        raise
    finally:
        if container:
            subprocess.run(["docker", "rm", "--force", container],
                           check=False, stdout=subprocess.DEVNULL)
        subprocess.run(["docker", "volume", "rm", volume, secrets_volume],
                       check=False, stdout=subprocess.DEVNULL)


def main():
    backend, frontend = stub("backend"), stub("frontend")
    try:
        for filename in ("dynamic.development.yml", "dynamic.yml"):
            check_config(ROOT / "traefik" / filename,
                         backend.server_port, frontend.server_port)
        check_desktop_runtime(backend.server_port, frontend.server_port)
    finally:
        backend.shutdown()
        frontend.shutdown()


if __name__ == "__main__":
    main()
