"""Tests for acknowledged-findings suppression and review exit codes."""

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import importlib
sp = importlib.import_module("suggest-permissions")


def _make_finding(severity="CRITICAL", rule="Bash(bash -n *)"):
    return sp.make_finding(severity, "test-cat", rule, "global", "allow", "msg")


class TestIsFindingAcknowledged(unittest.TestCase):
    def test_exact_match(self):
        ack = [{"pattern": "Bash(bash -n *)", "severity": "CRITICAL", "note": "", "acknowledgedAt": ""}]
        self.assertIsNotNone(sp.is_finding_acknowledged(_make_finding(), ack))

    def test_glob_match(self):
        ack = [{"pattern": "Bash(rm /tmp/*)", "severity": "HIGH", "note": "", "acknowledgedAt": ""}]
        self.assertIsNotNone(sp.is_finding_acknowledged(
            _make_finding("HIGH", "Bash(rm /tmp/aidlc-foo)"), ack))

    def test_severity_must_match(self):
        ack = [{"pattern": "Bash(bash -n *)", "severity": "HIGH", "note": "", "acknowledgedAt": ""}]
        self.assertIsNone(sp.is_finding_acknowledged(_make_finding("CRITICAL"), ack))

    def test_pattern_must_match(self):
        ack = [{"pattern": "Bash(rm *)", "severity": "CRITICAL", "note": "", "acknowledgedAt": ""}]
        self.assertIsNone(sp.is_finding_acknowledged(_make_finding(), ack))

    def test_empty_ack_list(self):
        self.assertIsNone(sp.is_finding_acknowledged(_make_finding(), []))


class TestLoadAcknowledgedFindings(unittest.TestCase):
    def _write(self, tmp, content):
        claude_dir = Path(tmp) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text(content)

    def test_no_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(sp.load_acknowledged_findings(tmp), [])

    def test_no_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, json.dumps({"permissions": {"allow": []}}))
            self.assertEqual(sp.load_acknowledged_findings(tmp), [])

    def test_valid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, json.dumps({
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"pattern": "Bash(bash -n *)", "severity": "CRITICAL", "note": "syntax check"},
                        {"pattern": "Bash(rm /tmp/aidlc-*)", "severity": "high",
                         "acknowledgedAt": "2026-04-18"},
                    ]
                }
            }))
            entries = sp.load_acknowledged_findings(tmp)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["severity"], "CRITICAL")
            self.assertEqual(entries[1]["severity"], "HIGH")  # normalized to upper
            self.assertEqual(entries[0]["note"], "syntax check")
            self.assertEqual(entries[1]["acknowledgedAt"], "2026-04-18")

    def test_invalid_severity_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, json.dumps({
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"pattern": "Bash(bash -n *)", "severity": "BOGUS"},
                        {"pattern": "Bash(rm *)", "severity": "HIGH"},
                    ]
                }
            }))
            err = io.StringIO()
            with redirect_stderr(err):
                entries = sp.load_acknowledged_findings(tmp)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["pattern"], "Bash(rm *)")
            self.assertIn("severity", err.getvalue())

    def test_missing_pattern_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, json.dumps({
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"severity": "HIGH"},
                        {"pattern": "   ", "severity": "HIGH"},
                        {"pattern": "Bash(ok *)", "severity": "HIGH"},
                    ]
                }
            }))
            err = io.StringIO()
            with redirect_stderr(err):
                entries = sp.load_acknowledged_findings(tmp)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["pattern"], "Bash(ok *)")

    def test_not_a_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, json.dumps({
                "suggestPermissions": {"acknowledgedFindings": "oops"}
            }))
            err = io.StringIO()
            with redirect_stderr(err):
                entries = sp.load_acknowledged_findings(tmp)
            self.assertEqual(entries, [])
            self.assertIn("not an array", err.getvalue())

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".claude").mkdir()
            (Path(tmp) / ".claude" / "settings.json").write_text("{not-json")
            err = io.StringIO()
            with redirect_stderr(err):
                entries = sp.load_acknowledged_findings(tmp)
            self.assertEqual(entries, [])
            self.assertIn("JSON parse error", err.getvalue())
            self.assertIn("suppression disabled", err.getvalue())

    def test_optional_fields_wrong_type(self):
        """note / acknowledgedAt with wrong types should be silently coerced to ''."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, json.dumps({
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"pattern": "Bash(bash -n *)", "severity": "CRITICAL",
                         "note": 123, "acknowledgedAt": True}
                    ]
                }
            }))
            entries = sp.load_acknowledged_findings(tmp)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["note"], "")
            self.assertEqual(entries[0]["acknowledgedAt"], "")


class TestRunReviewExitCodes(unittest.TestCase):
    """Integration tests for run_review() exit codes and suppression output."""

    def _args(self, **overrides):
        ns = argparse.Namespace(
            review="project", format="table", show_suppressed=False,
            project=None, session=None, days=30, tool=None,
            min_count=3, show_all=False, consolidate=None, min_repos=2,
        )
        for k, v in overrides.items():
            setattr(ns, k, v)
        return ns

    def _run_in_dir(self, tmp, args):
        """Run run_review with cwd and HOME both pointing into the tmp sandbox.

        Overriding HOME isolates global ~/.claude/ rules from the test fixture,
        so that future tests using scope='all' don't pick up the real user's
        global settings on the CI host.
        """
        cwd = os.getcwd()
        prev_home = os.environ.get("HOME")
        os.chdir(tmp)
        os.environ["HOME"] = tmp
        out = io.StringIO()
        err = io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = sp.run_review(args)
        finally:
            os.chdir(cwd)
            if prev_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = prev_home
        return code, out.getvalue(), err.getvalue()

    def test_exit_0_when_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".claude").mkdir()
            (Path(tmp) / ".claude" / "settings.json").write_text(json.dumps({
                "permissions": {"allow": ["Bash(ls:*)"]}
            }))
            code, out, _ = self._run_in_dir(tmp, self._args())
            self.assertEqual(code, 0)

    def test_exit_1_when_remaining_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".claude").mkdir()
            (Path(tmp) / ".claude" / "settings.json").write_text(json.dumps({
                "permissions": {"allow": ["Bash(bash -n *)"]}  # CRITICAL never-allow
            }))
            code, out, _ = self._run_in_dir(tmp, self._args())
            self.assertEqual(code, 1)
            self.assertIn("CRITICAL", out)

    def test_exit_0_when_all_findings_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".claude").mkdir()
            (Path(tmp) / ".claude" / "settings.json").write_text(json.dumps({
                "permissions": {"allow": ["Bash(bash -n *)"]},
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"pattern": "Bash(bash -n *)", "severity": "CRITICAL",
                         "note": "syntax check only"}
                    ]
                }
            }))
            code, out, _ = self._run_in_dir(tmp, self._args())
            self.assertEqual(code, 0)
            self.assertIn("1件の既知指摘を抑制しました", out)
            self.assertNotIn("(suppressed)", out)

    def test_show_suppressed_displays_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".claude").mkdir()
            (Path(tmp) / ".claude" / "settings.json").write_text(json.dumps({
                "permissions": {"allow": ["Bash(bash -n *)"]},
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"pattern": "Bash(bash -n *)", "severity": "CRITICAL"}
                    ]
                }
            }))
            code, out, _ = self._run_in_dir(tmp, self._args(show_suppressed=True))
            # Even with --show-suppressed, exit code reflects active remaining
            self.assertEqual(code, 0)
            self.assertIn("(suppressed)", out)

    def test_exit_2_when_project_scope_no_claude_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self._run_in_dir(tmp, self._args(review="project"))
            self.assertEqual(code, 2)
            self.assertIn("No .claude/", err)

    def test_glob_suppression(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".claude").mkdir()
            # rm is HIGH (destructive); pattern with glob should match
            (Path(tmp) / ".claude" / "settings.json").write_text(json.dumps({
                "permissions": {"allow": ["Bash(rm /tmp/aidlc-*)"]},
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"pattern": "Bash(rm /tmp/*)", "severity": "HIGH"}
                    ]
                }
            }))
            code, out, _ = self._run_in_dir(tmp, self._args())
            self.assertEqual(code, 0)
            self.assertIn("既知指摘を抑制", out)

    def test_json_output_includes_remaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".claude").mkdir()
            (Path(tmp) / ".claude" / "settings.json").write_text(json.dumps({
                "permissions": {"allow": ["Bash(bash -n *)"]},
                "suggestPermissions": {
                    "acknowledgedFindings": [
                        {"pattern": "Bash(bash -n *)", "severity": "CRITICAL"}
                    ]
                }
            }))
            code, out, _ = self._run_in_dir(tmp, self._args(format="json"))
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(data["remaining_issues"], 0)
            self.assertEqual(data["suppressed_count"], 1)


if __name__ == "__main__":
    unittest.main()
