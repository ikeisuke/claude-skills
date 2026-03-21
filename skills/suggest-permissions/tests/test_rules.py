"""Tests for rule extraction, matching, and classification functions."""

import os
import sys
import unittest

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import importlib
sp = importlib.import_module("suggest-permissions")


class TestExtractBashPattern(unittest.TestCase):
    """Tests for extract_bash_pattern()."""

    def test_simple_command(self):
        self.assertEqual(sp.extract_bash_pattern("ls -la"), "ls")

    def test_git_subcommand(self):
        self.assertEqual(sp.extract_bash_pattern("git status"), "git status")

    def test_npm_subcommand(self):
        self.assertEqual(sp.extract_bash_pattern("npm run build"), "npm run")

    def test_backslash_prefix(self):
        """Backslash-prefixed commands (alias bypass) should strip the backslash."""
        self.assertEqual(sp.extract_bash_pattern("\\rm file.txt"), "rm")

    def test_empty_command(self):
        self.assertIsNone(sp.extract_bash_pattern(""))
        self.assertIsNone(sp.extract_bash_pattern(None))

    def test_comment(self):
        self.assertIsNone(sp.extract_bash_pattern("# this is a comment"))

    def test_variable_assignment_with_subshell(self):
        """VAR=$(cmd ...) should extract the inner command."""
        result = sp.extract_bash_pattern('TMPFILE=$(mktemp /tmp/foo.XXXXX)')
        self.assertEqual(result, "mktemp")

    def test_variable_assignment_with_quoted_subshell(self):
        result = sp.extract_bash_pattern('OUTPUT="$(git status)"')
        self.assertEqual(result, "git status")

    def test_variable_assignment_without_subshell(self):
        """Plain variable assignment should return None."""
        self.assertIsNone(sp.extract_bash_pattern("FOO=bar"))

    def test_multiline_takes_first_line(self):
        self.assertEqual(sp.extract_bash_pattern("echo hello\necho world"), "echo")


class TestIsNeverAllow(unittest.TestCase):
    """Tests for is_never_allow()."""

    def test_interpreter_commands(self):
        self.assertTrue(sp.is_never_allow("Bash(python3 script.py)"))
        self.assertTrue(sp.is_never_allow("Bash(node app.js)"))
        self.assertTrue(sp.is_never_allow("Bash(bash script.sh)"))

    def test_shell_constructs(self):
        self.assertTrue(sp.is_never_allow("Bash(eval some_command)"))
        self.assertTrue(sp.is_never_allow("Bash(for i in *)"))

    def test_safe_commands(self):
        self.assertFalse(sp.is_never_allow("Bash(ls -la)"))
        self.assertFalse(sp.is_never_allow("Bash(git status)"))
        self.assertFalse(sp.is_never_allow("Glob"))

    def test_backslash_prefix(self):
        """\\rm should still match 'rm' (not in NEVER_ALLOW, but tests stripping)."""
        # rm is in HIGH_RISK not NEVER_ALLOW
        self.assertFalse(sp.is_never_allow("Bash(\\rm file)"))

    def test_backslash_interpreter(self):
        """\\python3 should still be detected as never-allow."""
        self.assertTrue(sp.is_never_allow("Bash(\\python3 script.py)"))


class TestIsAlreadyAllowed(unittest.TestCase):
    """Tests for is_already_allowed()."""

    def test_exact_match(self):
        rules = {"Bash(ls *)"}
        self.assertTrue(sp.is_already_allowed("Bash(ls *)", rules))

    def test_tool_level_match(self):
        rules = {"Glob"}
        self.assertTrue(sp.is_already_allowed("Glob", rules))

    def test_bare_tool_covers_scoped(self):
        rules = {"Read"}
        self.assertTrue(sp.is_already_allowed("Read(/tmp/**)", rules))

    def test_wildcard_prefix_match(self):
        """Bash(git *) should cover Bash(git status *)."""
        rules = {"Bash(git *)"}
        self.assertTrue(sp.is_already_allowed("Bash(git status *)", rules))

    def test_no_match(self):
        rules = {"Bash(ls *)"}
        self.assertFalse(sp.is_already_allowed("Bash(git status *)", rules))

    def test_empty_rules(self):
        self.assertFalse(sp.is_already_allowed("Bash(ls *)", set()))


class TestClassifyFileScope(unittest.TestCase):
    """Tests for classify_file_scope()."""

    def test_project_relative_path(self):
        scope, _ = sp.classify_file_scope("src/main.py")
        self.assertEqual(scope, "project")

    def test_project_absolute_path_under_cwd(self):
        scope, _ = sp.classify_file_scope("/home/user/project/src/main.py", cwd="/home/user/project")
        self.assertEqual(scope, "project")

    def test_tmp_path(self):
        scope, _ = sp.classify_file_scope("/tmp/test.txt")
        self.assertEqual(scope, "tmp")

    def test_private_tmp_path(self):
        scope, _ = sp.classify_file_scope("/private/tmp/test.txt")
        self.assertEqual(scope, "tmp")

    def test_external_path(self):
        scope, directory = sp.classify_file_scope("/usr/local/bin/test")
        self.assertEqual(scope, "external")

    def test_empty_path(self):
        scope, _ = sp.classify_file_scope("")
        self.assertEqual(scope, "project")


class TestSplitChainedCommands(unittest.TestCase):
    """Tests for split_chained_commands()."""

    def test_single_command(self):
        self.assertEqual(sp.split_chained_commands("git status"), ["git status"])

    def test_and_chain(self):
        self.assertEqual(
            sp.split_chained_commands("git add . && git commit -m 'test'"),
            ["git add .", "git commit -m 'test'"],
        )

    def test_or_chain(self):
        self.assertEqual(
            sp.split_chained_commands("test -f foo || echo missing"),
            ["test -f foo", "echo missing"],
        )

    def test_semicolon_chain(self):
        self.assertEqual(
            sp.split_chained_commands("cd /tmp; ls -la"),
            ["cd /tmp", "ls -la"],
        )

    def test_mixed_chain(self):
        result = sp.split_chained_commands("git add . && git commit -m 'x'; git push")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "git add .")
        self.assertEqual(result[2], "git push")

    def test_pipe_not_split(self):
        """Pipes should NOT be treated as command separators."""
        self.assertEqual(
            sp.split_chained_commands("git log | head -5"),
            ["git log | head -5"],
        )

    def test_empty(self):
        self.assertEqual(sp.split_chained_commands(""), [])
        self.assertEqual(sp.split_chained_commands(None), [])


class TestExtractAllBashPatterns(unittest.TestCase):
    """Tests for extract_all_bash_patterns()."""

    def test_single_command(self):
        result = sp.extract_all_bash_patterns("git status")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "git status")

    def test_chained_commands(self):
        result = sp.extract_all_bash_patterns("git add . && git push origin main")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], "git add")
        self.assertEqual(result[1][0], "git push")

    def test_three_commands(self):
        result = sp.extract_all_bash_patterns("ls -la && git status && git push origin main")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0][0], "ls")
        self.assertEqual(result[1][0], "git status")
        self.assertEqual(result[2][0], "git push")

    def test_empty(self):
        self.assertEqual(sp.extract_all_bash_patterns(""), [])
        self.assertEqual(sp.extract_all_bash_patterns(None), [])

    def test_preserves_single_command_text(self):
        result = sp.extract_all_bash_patterns("git status && git push --force origin main")
        self.assertEqual(result[1][1], "git push --force origin main")


class TestAnalyzeBashArgs(unittest.TestCase):
    """Tests for analyze_bash_args()."""

    def test_simple_flags(self):
        result = sp.analyze_bash_args("ls", "ls -la /tmp")
        self.assertIn("-la", result["flags"])
        self.assertIn("/tmp", result["positionals"])

    def test_git_push_with_force(self):
        result = sp.analyze_bash_args("git push", "git push --force origin main")
        self.assertIn("--force", result["flags"])
        self.assertIn("origin", result["positionals"])
        self.assertIn("main", result["positionals"])
        self.assertIn("--force", result["dangerous_flags_found"])

    def test_git_push_normal(self):
        result = sp.analyze_bash_args("git push", "git push origin main")
        self.assertEqual(result["flags"], [])
        self.assertEqual(result["dangerous_flags_found"], [])
        self.assertIn("origin", result["positionals"])

    def test_git_branch_delete(self):
        result = sp.analyze_bash_args("git branch", "git branch -D feature/old")
        self.assertIn("-D", result["dangerous_flags_found"])

    def test_rm_rf(self):
        result = sp.analyze_bash_args("rm", "\\rm -rf /tmp/test")
        self.assertIn("-rf", result["dangerous_flags_found"])

    def test_no_args(self):
        result = sp.analyze_bash_args("ls", "ls")
        self.assertEqual(result["flags"], [])
        self.assertEqual(result["positionals"], [])
        self.assertEqual(result["dangerous_flags_found"], [])

    def test_empty_input(self):
        result = sp.analyze_bash_args("", "")
        self.assertEqual(result["flags"], [])
        self.assertEqual(result["dangerous_flags_found"], [])

    def test_backslash_command(self):
        result = sp.analyze_bash_args("git push", "\\git push -u origin main")
        self.assertIn("-u", result["flags"])
        self.assertIn("origin", result["positionals"])

    def test_command_not_in_dangerous_map(self):
        result = sp.analyze_bash_args("echo", "echo hello world")
        self.assertEqual(result["dangerous_flags_found"], [])
        self.assertIn("hello", result["positionals"])

    def test_curl_dangerous_flag(self):
        """Multi-token dangerous flag detection (e.g., -X POST)."""
        result = sp.analyze_bash_args("curl", "curl -X POST https://example.com")
        self.assertIn("-X POST", result["dangerous_flags_found"])

    def test_git_reset_hard(self):
        result = sp.analyze_bash_args("git reset", "git reset --hard HEAD~1")
        self.assertIn("--hard", result["dangerous_flags_found"])

    def test_gh_pr_create(self):
        result = sp.analyze_bash_args("gh pr", "gh pr create --title test")
        self.assertIn("create", result["dangerous_flags_found"])

    def test_chained_command_isolates_segment(self):
        """analyze_bash_args should only analyze the matching segment in a chain."""
        result = sp.analyze_bash_args("git push", "git status && git push --force origin main")
        self.assertIn("--force", result["flags"])
        self.assertIn("--force", result["dangerous_flags_found"])
        # Should NOT include tokens from the first command
        self.assertNotIn("status", result["positionals"])

    def test_chained_command_first_segment(self):
        result = sp.analyze_bash_args("git add", "git add . && git push origin main")
        self.assertIn(".", result["positionals"])
        self.assertNotIn("origin", result["positionals"])


class TestGetProjectName(unittest.TestCase):
    """Tests for get_project_name()."""

    def test_simple_name(self):
        self.assertEqual(sp.get_project_name("/home/user/myproject"), "myproject")

    def test_hyphenated_name(self):
        """Should return the full basename, not just the last part."""
        self.assertEqual(sp.get_project_name("/home/user/my-awesome-project"), "my-awesome-project")

    def test_trailing_slash(self):
        # os.path.basename("/path/to/dir/") returns ""
        self.assertEqual(sp.get_project_name("/path/to/dir"), "dir")


if __name__ == "__main__":
    unittest.main()
