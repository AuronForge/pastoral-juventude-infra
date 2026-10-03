#!/usr/bin/env python3
"""Check resolved development origins in both Engine and Desktop Compose."""
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


class DevelopmentOriginsTest(unittest.TestCase):
    def test_resolved_origins(self):
        cases = [
            ({}, ["http://localhost:8080", "http://traefik"]),
            ({"DEV_PUBLIC_URL": "https://dev.example.invalid"},
             ["https://dev.example.invalid", "http://traefik"]),
            ({"DEV_PUBLIC_URL": "https://fallback.example.invalid",
              "DEV_CORS_ORIGINS": "http://localhost:5173,https://web.example.invalid"},
             ["http://localhost:5173", "https://web.example.invalid", "http://traefik"]),
            ({"DEV_CORS_ORIGINS": "", "DEV_PUBLIC_URL": ""},
             ["http://localhost:8080", "http://traefik"]),
        ]
        for desktop in (False, True):
            for overrides, expected in cases:
                with self.subTest(desktop=desktop, overrides=overrides):
                    env = os.environ.copy()
                    for key in ("DEV_CORS_ORIGINS", "DEV_PUBLIC_URL"):
                        env.pop(key, None)
                    env.update({
                        "BACKEND_IMAGE": "backend:test",
                        "MIGRATION_IMAGE": "backend:migrations-test",
                        "FRONTEND_IMAGE": "frontend:test",
                        "DEV_RUNTIME_VOLUME": "pastoral-test-runtime",
                        **overrides,
                    })
                    command = ["docker", "compose", "--env-file", "/dev/null",
                               "-f", str(ROOT / "compose.development.yaml")]
                    if desktop:
                        command += ["-f", str(ROOT / "compose.development.desktop.yaml")]
                    # Only output the public origin list, never dump the Compose config.
                    result = subprocess.run(command + ["config", "--format", "json"],
                                            cwd=ROOT, env=env, check=True,
                                            capture_output=True, text=True)
                    config = json.loads(result.stdout)
                    actual = config["services"]["backend"]["environment"]["CORS_ORIGINS"]
                    self.assertEqual(actual.split(","), expected)
                    self.assertNotIn("*", actual)
                    self.assertNotIn("https://evil.invalid", actual.split(","))


if __name__ == "__main__":
    unittest.main()
