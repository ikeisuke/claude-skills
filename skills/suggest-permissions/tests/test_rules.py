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
