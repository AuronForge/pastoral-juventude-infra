#!/usr/bin/env python3
"""Run the actual deploy validation Bash with an isolated GitHub API fixture."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
E2E_SHA = "e" * 40
SOURCE_SHA = "a" * 40
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
args = sys.argv[1:]
log = Path(os.environ["CALL_LOG"])
calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
with log.open("a") as stream:
    stream.write(json.dumps(args) + "\n")
endpoint = args[1]
query = args[args.index("--jq") + 1]
case = os.environ["CASE"]
e2e_repo = "repos/AuronForge/pastoral-juventude-e2e"
if endpoint == e2e_repo + "/branches/develop":
    if case == "api-denied":
        sys.exit(1)
    previous = sum(call[1] == endpoint for call in calls)
    sha = "invalid" if case == "malformed" else ("f" if previous else "e") * 40
    payload = {"commit": {"sha": sha}}
elif endpoint.endswith("/branches/develop"):
    payload = {"commit": {"sha": "a" * 40}}
elif "/actions/runs?head_sha=" in endpoint:
    run = {"name": "CI", "head_branch": "develop", "event": "push",
           "conclusion": "success", "head_sha": "e" * 40}
    if endpoint.startswith(e2e_repo):
        if case == "pending": run["conclusion"] = None
        if case == "failed": run["conclusion"] = "failure"
        if case == "pr-only": run["event"] = "pull_request"
        if case == "wrong-sha": run["head_sha"] = "f" * 40
        if case == "wrong-branch": run["head_branch"] = "release"
        sha = parse_qs(urlsplit(endpoint).query)["head_sha"][0]
        runs = [run] if case != "missing" and run["head_sha"] == sha else []
    else: runs = [run]
    payload = {"workflow_runs": runs}
elif "/actions/runs?event=workflow_run" in endpoint:
    payload = {"workflow_runs": [{"path": ".github/workflows/publish-development.yml",
                "display_title": "Publish development " + "a" * 40,
                "conclusion": "success"}]}
else:
    sys.exit(2)
result = subprocess.run(["jq", "-r", query], input=json.dumps(payload), text=True)
sys.exit(result.returncode)
'''


def validation_script():
    workflow = (ROOT / ".github/workflows/deploy-development.yml").read_text()
    lines = workflow.splitlines()
    start = lines.index("        run: |") + 1
    body = []
    for line in lines[start:]:
        if line and not line.startswith("          "):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


class AutomaticE2ESelection(unittest.TestCase):
    def exercise(self, case):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            gh = root / "gh"
            gh.write_text(FAKE_GH)
            gh.chmod(0o755)
            log = root / "calls.jsonl"
            output = root / "output"
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       CASE=case, CALL_LOG=str(log), COMPONENT="backend",
                       SOURCE_SHA=SOURCE_SHA, INFRA_SHA="b" * 40,
                       GITHUB_OUTPUT=str(output), E2E_SHA="old-manual-reference")
            result = subprocess.run(["bash", "-c", validation_script()], env=env,
                                    capture_output=True, text=True, timeout=5)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls, output.read_text() if output.exists() else ""

    def test_selects_approved_head_and_ignores_old_variable(self):
        result, calls, output = self.exercise("approved")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, f"e2e_sha={E2E_SHA}\n")
        branches = [call for call in calls if call[1].endswith("e2e/branches/develop")]
        self.assertEqual(len(branches), 1)
        self.assertTrue(any(f"head_sha={E2E_SHA}" in call[1] for call in calls))

    def test_rejects_unapproved_head_without_falling_back(self):
        for case in ("pending", "failed", "missing", "pr-only", "wrong-sha", "wrong-branch"):
            with self.subTest(case=case):
                result, calls, output = self.exercise(case)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("no successful push CI", result.stdout)
                self.assertEqual(output, "")
                self.assertFalse(any("/commits/" in call[1] for call in calls))

    def test_rejects_malformed_sha_and_api_failure(self):
        for case in ("malformed", "api-denied"):
            with self.subTest(case=case):
                result, calls, output = self.exercise(case)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")
                self.assertFalse(any("e2e/actions/runs" in call[1] for call in calls))

    def test_checkout_uses_validated_output(self):
        workflow = (ROOT / ".github/workflows/deploy-development.yml").read_text()
        self.assertIn("ref: ${{ needs.validate.outputs.e2e_sha }}", workflow)
        self.assertNotIn("vars.DEV_E2E_REF", workflow)


if __name__ == "__main__":
    unittest.main()
