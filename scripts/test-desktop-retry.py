#!/usr/bin/env python3
"""Exercise actual retry script safety/ordering with an isolated Docker fixture."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
TARGET = "unix:///home/example/.docker/desktop/docker.sock"
FAKE_DOCKER = r'''#!/usr/bin/env python3
import io, json, os, sys, tarfile
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\n")
command = args[2:]
mode = os.environ["CASE"]
if command[0] == "info":
    print("engine" if args[1].endswith("/var/run/docker.sock") else "desktop")
elif command[0] == "ps":
    print("source-backend" if "-q" in command else "candidate")
elif command[0] == "exec":
    sys.exit(1 if mode == "source-down" else 0)
elif command[0] == "inspect":
    print("true" if mode == "running" else "false")
elif command[:2] == ["volume", "inspect"]:
    print("pastoral-dev")
elif command[0] == "run":
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|"):
        pass
'''
class RetrySafety(unittest.TestCase):
    def exercise(self, case):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backups").mkdir()
            script = (ROOT / "prepare-desktop-retry.sh").read_text()
            self.assertIn("root=/opt/pastoral/dev\n", script)
            script = script.replace("root=/opt/pastoral/dev\n", f"root={root}\n")
            (root / "retry.sh").write_text(script)
            (root / "docker").write_text(FAKE_DOCKER)
            (root / "docker").chmod(0o755)
            if case == "committed":
                (root / "docker-host").write_text(TARGET)
            log = root / "calls.jsonl"
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       CASE=case, CALL_LOG=str(log))
            result = subprocess.run(["bash", str(root / "retry.sh"), TARGET],
                                    env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            archives = list((root / "backups").glob("*/*.tar"))
            return result.returncode, calls, len(archives)

    def test_rejects_already_committed_desktop(self):
        status, calls, archives = self.exercise("committed")
        self.assertNotEqual(status, 0)
        self.assertEqual(calls, [])
        self.assertEqual(archives, 0)

    def test_rejects_running_candidate_and_unready_source(self):
        for case in ("running", "source-down"):
            with self.subTest(case=case):
                status, calls, archives = self.exercise(case)
                self.assertNotEqual(status, 0)
                self.assertEqual(archives, 0)
                self.assertFalse(any(call[2] == "rm" or call[2:4] == ["volume", "rm"]
                                     for call in calls))

    def test_archives_both_volumes_before_target_only_removal(self):
        status, calls, archives = self.exercise("stopped")
        self.assertEqual(status, 0)
        self.assertEqual(archives, 2)
        archive_indices = [i for i, call in enumerate(calls) if call[2] == "run"]
        removals = [(i, call) for i, call in enumerate(calls)
                    if call[2] == "rm" or call[2:4] == ["volume", "rm"]]
        self.assertEqual(len(removals), 3)
        self.assertLess(max(archive_indices), min(i for i, _ in removals))
        self.assertTrue(all(call[1] == TARGET for _, call in removals))

if __name__ == "__main__":
    unittest.main()
