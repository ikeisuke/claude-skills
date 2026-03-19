"""Tests for risk assessment and review functions."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import importlib
sp = importlib.import_module("suggest-permissions")


class TestCheckWildcardOvermatch(unittest.TestCase):
    """Tests for check_wildcard_overmatch()."""

    def test_git_push_without_guard(self):
        """git push * without deny/ask for --force should flag."""
        findings = sp.check_wildcard_overmatch("Bash(git push *)", "global", set(), set())
        self.assertTrue(len(findings) > 0)
        self.assertEqual(findings[0]["severity"], "MED")
        self.assertIn("--force", findings[0]["message"])

    def test_git_push_with_ask_guard(self):
        """git push * with ask guard for --force should not flag."""
        findings = sp.check_wildcard_overmatch(
            "Bash(git push *)", "global", set(), {"Bash(git push --force *)"}
        )
        self.assertEqual(len(findings), 0)

    def test_git_push_with_deny_guard(self):
        """git push * with deny guard for --force should not flag."""
        findings = sp.check_wildcard_overmatch(
            "Bash(git push *)", "global", {"Bash(git push --force *)"}, set()
        )
        self.assertEqual(len(findings), 0)

    def test_non_wildcard_rule(self):
        """Non-wildcard rules should not be flagged."""
        findings = sp.check_wildcard_overmatch("Bash(git push origin main)", "global", set(), set())
        self.assertEqual(len(findings), 0)

    def test_command_without_dangerous_flags(self):
        """Commands not in DANGEROUS_FLAG_MAP should not be flagged."""
        findings = sp.check_wildcard_overmatch("Bash(echo *)", "global", set(), set())
        self.assertEqual(len(findings), 0)


class TestCheckNeverAllowViolation(unittest.TestCase):
    """Tests for check_never_allow_violation()."""

    def test_interpreter_in_allow(self):
        findings = sp.check_never_allow_violation("Bash(python3 *)", "global")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "CRITICAL")

    def test_scoped_interpreter(self):
        """Scoped interpreter (specific path) should be INFO, not CRITICAL."""
        findings = sp.check_never_allow_violation("Bash(python3 /specific/script.py)", "global")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "INFO")

    def test_safe_command(self):
        findings = sp.check_never_allow_violation("Bash(ls *)", "global")
        self.assertEqual(len(findings), 0)


class TestCheckSensitivePath(unittest.TestCase):
    """Tests for check_sensitive_path()."""

    def test_ssh_path(self):
        findings = sp.check_sensitive_path("Read(~/.ssh/**)", "global", set())
        self.assertTrue(len(findings) > 0)
        self.assertEqual(findings[0]["severity"], "HIGH")

    def test_ssh_path_guarded_by_deny(self):
        findings = sp.check_sensitive_path("Read(~/.ssh/**)", "global", {"Read(~/.ssh/**)"})
        self.assertTrue(len(findings) > 0)
        self.assertEqual(findings[0]["severity"], "INFO")

    def test_normal_path(self):
        findings = sp.check_sensitive_path("Read(/src/**)", "global", set())
        self.assertEqual(len(findings), 0)

    def test_non_file_rule(self):
        findings = sp.check_sensitive_path("Bash(ls *)", "global", set())
        self.assertEqual(len(findings), 0)


class TestCheckOverlyBroad(unittest.TestCase):
    """Tests for check_overly_broad()."""

    def test_bash_wildcard(self):
        findings = sp.check_overly_broad("Bash(*)", "global")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "CRITICAL")

    def test_bare_edit(self):
        findings = sp.check_overly_broad("Edit", "global")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "MED")

    def test_bare_write(self):
        findings = sp.check_overly_broad("Write", "global")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "MED")

    def test_bare_read(self):
        findings = sp.check_overly_broad("Read", "global")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "LOW")

    def test_scoped_edit(self):
        findings = sp.check_overly_broad("Edit(/**)", "global")
        self.assertEqual(len(findings), 0)

    def test_glob(self):
        findings = sp.check_overly_broad("Glob", "global")
        self.assertEqual(len(findings), 0)


class TestCheckAskOverridesAllow(unittest.TestCase):
    """Tests for check_ask_overrides_allow()."""

    def _make_rules(self, allow=None, ask=None, deny=None):
        return {
            "allow": set(allow or []),
            "ask": set(ask or []),
            "deny": set(deny or []),
            "rule_origins": {},
        }

    def test_broad_ask_overrides_specific_allow(self):
        """Project ask Bash(bash *) should flag override of global allow."""
        project = self._make_rules(ask=["Bash(bash *)"])
        global_r = self._make_rules(allow=["Bash(bash ~/.claude/plugins/cache/session-title.sh *)"])
        findings = sp.check_ask_overrides_allow(project, global_r)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "MED")
        self.assertEqual(findings[0]["category"], "ask-overrides-allow")

    def test_no_conflict(self):
        """No conflict when ask and allow don't overlap."""
        project = self._make_rules(ask=["Bash(docker *)"])
        global_r = self._make_rules(allow=["Bash(git status *)"])
        findings = sp.check_ask_overrides_allow(project, global_r)
        self.assertEqual(len(findings), 0)

    def test_deny_also_detected(self):
        """Project deny rules should also be checked for overrides."""
        project = self._make_rules(deny=["Bash(git *)"])
        global_r = self._make_rules(allow=["Bash(git status *)", "Bash(git log *)"])
        findings = sp.check_ask_overrides_allow(project, global_r)
        self.assertEqual(len(findings), 1)
        self.assertIn("2 global allow", findings[0]["message"])

    def test_non_wildcard_ask_ignored(self):
        """Non-wildcard ask rules should not be flagged."""
        project = self._make_rules(ask=["Bash(git push --force *)"])
        global_r = self._make_rules(allow=["Bash(git push *)"])
        findings = sp.check_ask_overrides_allow(project, global_r)
        self.assertEqual(len(findings), 0)


class TestCheckMissingProtections(unittest.TestCase):
    """Tests for check_missing_protections()."""

    def test_no_protections(self):
        findings = sp.check_missing_protections(set(), set())
        self.assertTrue(len(findings) > 0)
        self.assertTrue(all(f["severity"] == "LOW" for f in findings))

    def test_all_deny_configured(self):
        deny_rules = set(sp.RECOMMENDED_DENY)
        findings = sp.check_missing_protections(deny_rules, set())
        self.assertEqual(len(findings), 0)

    def test_ask_also_counts(self):
        ask_rules = set(sp.RECOMMENDED_DENY)
        findings = sp.check_missing_protections(set(), ask_rules)
        self.assertEqual(len(findings), 0)


if __name__ == "__main__":
    unittest.main()
