"""Tests for translate-permissions script."""

import os
import sys
import unittest

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import importlib
tp = importlib.import_module("translate-permissions")


class TestParsePermissionRule(unittest.TestCase):
    """Tests for parse_permission_rule()."""

    def test_simple_tool(self):
        result = tp.parse_permission_rule("Glob")
        self.assertEqual(result["tool"], "Glob")
        self.assertIsNone(result["pattern"])

    def test_read_with_path(self):
        result = tp.parse_permission_rule("Read(/**)")
        self.assertEqual(result["tool"], "Read")
        self.assertEqual(result["pattern"], "/**")

    def test_edit_with_path(self):
        result = tp.parse_permission_rule("Edit(/src/**)")
        self.assertEqual(result["tool"], "Edit")
        self.assertEqual(result["pattern"], "/src/**")

    def test_write_with_path(self):
        result = tp.parse_permission_rule("Write(///tmp/**)")
        self.assertEqual(result["tool"], "Write")
        self.assertEqual(result["pattern"], "///tmp/**")

    def test_bash_with_colon_wildcard(self):
        result = tp.parse_permission_rule("Bash(git add:*)")
        self.assertEqual(result["tool"], "Bash")
        self.assertEqual(result["pattern"], "git add:*")

    def test_bash_with_space_wildcard(self):
        result = tp.parse_permission_rule("Bash(git status *)")
        self.assertEqual(result["tool"], "Bash")
        self.assertEqual(result["pattern"], "git status *")

    def test_mcp_tool(self):
        result = tp.parse_permission_rule("mcp__codex__codex")
        self.assertEqual(result["tool"], "mcp")
        self.assertEqual(result["server"], "codex")
        self.assertEqual(result["tool_name"], "codex")

    def test_mcp_tool_with_underscores_in_server(self):
        result = tp.parse_permission_rule("mcp__my_server__my_tool")
        self.assertEqual(result["tool"], "mcp")
        self.assertEqual(result["server"], "my_server")
        self.assertEqual(result["tool_name"], "my_tool")

    def test_webfetch_domain(self):
        result = tp.parse_permission_rule("WebFetch(domain:example.com)")
        self.assertEqual(result["tool"], "WebFetch")
        self.assertEqual(result["pattern"], "example.com")

    def test_skill_rule(self):
        result = tp.parse_permission_rule("Skill(my-skill)")
        self.assertEqual(result["tool"], "Skill")
        self.assertEqual(result["pattern"], "my-skill")

    def test_websearch(self):
        result = tp.parse_permission_rule("WebSearch")
        self.assertEqual(result["tool"], "WebSearch")
        self.assertIsNone(result["pattern"])


class TestNormalizeBashPattern(unittest.TestCase):
    """Tests for normalize_bash_pattern()."""

    def test_colon_wildcard(self):
        self.assertEqual(tp.normalize_bash_pattern("git add:*"), "git add *")

    def test_space_wildcard(self):
        self.assertEqual(tp.normalize_bash_pattern("git status *"), "git status *")

    def test_no_wildcard(self):
        self.assertEqual(tp.normalize_bash_pattern("git status"), "git status")

    def test_multiple_colon_wildcards(self):
        self.assertEqual(tp.normalize_bash_pattern("cmd:* arg:*"), "cmd * arg *")

    def test_exact_command(self):
        self.assertEqual(tp.normalize_bash_pattern("ls -la"), "ls -la")


class TestNormalizeFilePath(unittest.TestCase):
    """Tests for normalize_file_path()."""

    def test_project_relative_root(self):
        self.assertEqual(tp.normalize_file_path("/**"), "**")

    def test_project_relative_subdir(self):
        self.assertEqual(tp.normalize_file_path("/src/**"), "src/**")

    def test_absolute_path(self):
        self.assertEqual(tp.normalize_file_path("///tmp/**"), "/tmp/**")

    def test_home_path(self):
        self.assertIsNone(tp.normalize_file_path("~/.ssh/**"))

    def test_home_path_dotenv(self):
        self.assertIsNone(tp.normalize_file_path("~/.aws/**"))

    def test_already_relative(self):
        self.assertEqual(tp.normalize_file_path("src/**"), "src/**")

    def test_root_slash_only(self):
        self.assertEqual(tp.normalize_file_path("/"), "**")

    def test_specific_file(self):
        self.assertEqual(tp.normalize_file_path("/README.md"), "README.md")


class TestParseMcpTool(unittest.TestCase):
    """Tests for parse_mcp_tool()."""

    def test_simple(self):
        result = tp.parse_mcp_tool("mcp__codex__codex")
        self.assertEqual(result, ("codex", "codex"))

    def test_complex_names(self):
        result = tp.parse_mcp_tool("mcp__my_server__my_tool")
        self.assertEqual(result, ("my_server", "my_tool"))

    def test_not_mcp(self):
        result = tp.parse_mcp_tool("Bash(ls)")
        self.assertIsNone(result)

    def test_not_mcp_simple(self):
        result = tp.parse_mcp_tool("Glob")
        self.assertIsNone(result)


class TestTranslateToKiro(unittest.TestCase):
    """End-to-end tests for translate_to_kiro()."""

    def test_basic_allow(self):
        permissions = {
            "allow": ["Glob", "Grep", "Read(/**)", "Edit(/**)", "Bash(git status *)"],
            "deny": [],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test-agent", "Test agent")
        self.assertEqual(config["name"], "test-agent")
        self.assertIn("read", config["tools"])
        self.assertIn("write", config["tools"])
        self.assertIn("shell", config["tools"])
        self.assertIn("git status *", config["toolsSettings"]["shell"]["allowedCommands"])
        self.assertIn("**", config["toolsSettings"]["write"]["allowedPaths"])

    def test_deny_bash(self):
        permissions = {
            "allow": ["Bash(git add:*)"],
            "deny": ["Bash(rm *)"],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("git add *", config["toolsSettings"]["shell"]["allowedCommands"])
        self.assertIn("rm *", config["toolsSettings"]["shell"]["deniedCommands"])

    def test_ask_overrides_broad_allow(self):
        """Ask rules should prevent broad allow wildcards from auto-approving."""
        permissions = {
            "allow": ["Bash(git push *)"],
            "deny": [],
            "ask": ["Bash(git push --force *)"],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("shell", config["tools"])
        # The broad "git push *" should be removed from allowedCommands
        # because it would override the ask intent for --force
        shell = config.get("toolsSettings", {}).get("shell", {})
        self.assertNotIn("git push *", shell.get("allowedCommands", []))

    def test_ask_does_not_remove_unrelated_allow(self):
        """Ask rules should not affect unrelated allow commands."""
        permissions = {
            "allow": ["Bash(git push *)", "Bash(git status *)", "Bash(ls:*)"],
            "deny": [],
            "ask": ["Bash(git push --force *)"],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        shell = config["toolsSettings"]["shell"]
        # git push * should be removed (covers ask pattern)
        self.assertNotIn("git push *", shell["allowedCommands"])
        # unrelated commands should remain
        self.assertIn("git status *", shell["allowedCommands"])
        self.assertIn("ls *", shell["allowedCommands"])

    def test_deny_only_bash_no_shell(self):
        """deny-only Bash rules should NOT enable shell tool or emit shell settings."""
        permissions = {
            "allow": [],
            "deny": ["Bash(rm -rf *)"],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertNotIn("shell", config["tools"])
        # No shell settings should be emitted without shell in tools
        self.assertNotIn("toolsSettings", config)

    def test_ask_bash(self):
        """ask rules should add shell to tools but not to allowedCommands."""
        permissions = {
            "allow": [],
            "deny": [],
            "ask": ["Bash(git push --force *)"],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("shell", config["tools"])
        # Should NOT have allowedCommands for ask rules
        shell_settings = config.get("toolsSettings", {}).get("shell", {})
        self.assertNotIn("allowedCommands", shell_settings)

    def test_mcp_allow(self):
        permissions = {
            "allow": ["mcp__codex__codex", "mcp__codex__codex_reply"],
            "deny": [],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("@codex", config["tools"])
        self.assertIn("@codex/codex", config["allowedTools"])
        self.assertIn("@codex/codex_reply", config["allowedTools"])

    def test_mcp_deny(self):
        """MCP deny rules should not enable the server, and appear in skipped."""
        permissions = {
            "allow": [],
            "deny": ["mcp__dangerous__rm_all"],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertNotIn("@dangerous", config["tools"])
        self.assertIn("mcp__dangerous__rm_all", config["_skippedClaudeRules"])

    def test_mcp_ask(self):
        """MCP ask rules: server in tools but tool not in allowedTools."""
        permissions = {
            "allow": [],
            "deny": [],
            "ask": ["mcp__git__git_push"],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("@git", config["tools"])
        self.assertNotIn("allowedTools", config)

    def test_skipped_tools(self):
        permissions = {
            "allow": ["WebSearch", "WebFetch", "Agent", "WebFetch(domain:example.com)"],
            "deny": [],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        # No tools should be added for skipped rules
        self.assertEqual(config["tools"], [])
        self.assertIn("_skippedClaudeRules", config)
        self.assertEqual(len(config["_skippedClaudeRules"]), 4)

    def test_skill_skipped(self):
        permissions = {
            "allow": ["Skill(my-skill)"],
            "deny": [],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertEqual(config["tools"], [])
        self.assertIn("Skill(my-skill)", config["_skippedClaudeRules"])

    def test_write_paths_deduplicated(self):
        permissions = {
            "allow": ["Edit(/**)", "Write(/**)", "Edit(/src/**)"],
            "deny": [],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        paths = config["toolsSettings"]["write"]["allowedPaths"]
        self.assertEqual(paths, ["**", "src/**"])

    def test_home_path_in_deny_skipped(self):
        """Home-relative deny rules should appear in _skippedClaudeRules."""
        permissions = {
            "allow": ["Read(/**)"],
            "deny": ["Read(~/.ssh/**)", "Read(~/.aws/**)"],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("read", config["tools"])
        self.assertNotIn("toolsSettings", config)
        self.assertIn("Read(~/.ssh/**)", config["_skippedClaudeRules"])
        self.assertIn("Read(~/.aws/**)", config["_skippedClaudeRules"])

    def test_unmappable_write_path_skipped(self):
        """Write rules with unmappable home paths should be skipped, not enable write."""
        permissions = {
            "allow": ["Write(~/.ssh/config)"],
            "deny": [],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertNotIn("write", config["tools"])
        self.assertIn("Write(~/.ssh/config)", config["_skippedClaudeRules"])

    def test_write_without_pattern_enables_write(self):
        """Write without a path pattern should enable write tool."""
        permissions = {
            "allow": ["Write"],
            "deny": [],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("write", config["tools"])

    def test_deny_file_rules_in_skipped(self):
        """Deny rules for file tools should appear in _skippedClaudeRules."""
        permissions = {
            "allow": ["Edit(/**)"],
            "deny": ["Read(.env)", "Edit(.env)"],
            "ask": [],
        }
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertIn("Read(.env)", config["_skippedClaudeRules"])
        self.assertIn("Edit(.env)", config["_skippedClaudeRules"])

    def test_empty_permissions(self):
        permissions = {"allow": [], "deny": [], "ask": []}
        config = tp.translate_to_kiro(permissions, "test", "test")
        self.assertEqual(config["tools"], [])

    def test_mixed_comprehensive(self):
        """Comprehensive test with mixed allow/deny/ask rules."""
        permissions = {
            "allow": [
                "Glob", "Grep", "Read(/**)", "Edit(/**)", "Write(/**)",
                "Bash(git status *)", "Bash(git add:*)", "Bash(ls:*)",
                "mcp__codex__codex",
            ],
            "deny": [
                "Read(.env)", "Read(~/.ssh/**)",
                "Bash(rm -rf *)",
            ],
            "ask": [
                "Bash(git push --force *)",
                "mcp__git__git_push",
            ],
        }
        config = tp.translate_to_kiro(permissions, "my-agent", "My agent config")

        # All tool types present
        self.assertIn("read", config["tools"])
        self.assertIn("write", config["tools"])
        self.assertIn("shell", config["tools"])
        self.assertIn("@codex", config["tools"])
        self.assertIn("@git", config["tools"])

        # allowedTools for MCP allow only
        self.assertIn("@codex/codex", config["allowedTools"])
        self.assertNotIn("@git/git_push", config.get("allowedTools", []))

        # Shell settings
        shell = config["toolsSettings"]["shell"]
        self.assertIn("git status *", shell["allowedCommands"])
        self.assertIn("git add *", shell["allowedCommands"])
        self.assertIn("ls *", shell["allowedCommands"])
        self.assertIn("rm -rf *", shell["deniedCommands"])
        # ask rule should NOT be in allowedCommands
        self.assertNotIn("git push --force *", shell.get("allowedCommands", []))

        # Write paths
        self.assertIn("**", config["toolsSettings"]["write"]["allowedPaths"])


if __name__ == "__main__":
    unittest.main()
