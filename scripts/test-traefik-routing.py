#!/usr/bin/env python3
"""Exercise the actual Traefik version routers against local HTTP stubs."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent


def stub(identity):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = f"{identity} {self.path}".encode()
            self.send_response(200)
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
            print(f"{path.name}: version routing and API-only isolation passed")
        except Exception:
            subprocess.run(["docker", "logs", container], check=False)
            raise
        finally:
            subprocess.run(["docker", "rm", "--force", container],
                           check=False, stdout=subprocess.DEVNULL)


def main():
    backend, frontend = stub("backend"), stub("frontend")
    try:
        for filename in ("dynamic.development.yml", "dynamic.yml"):
            check_config(ROOT / "traefik" / filename,
                         backend.server_port, frontend.server_port)
    finally:
        backend.shutdown()
        frontend.shutdown()


if __name__ == "__main__":
    main()
