#!/usr/bin/env python3
"""Collect tool usage patterns from Claude Code session history for permission rule suggestions."""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# Tools that are always safe (read-only, no side effects) - auto-consolidate to tool-level rules
SAFE_TOOLS = {"Glob", "Grep", "WebSearch"}

# File tools that need scope-based analysis
FILE_TOOLS = {"Read", "Edit", "Write"}

# Bash commands that must never be auto-allowed (arbitrary code execution or shell constructs)
NEVER_ALLOW_COMMANDS = {
    # Script interpreters
    "node", "python3", "python", "ruby", "perl", "bash", "sh", "deno", "bun",
    # Shell control structures (wrap arbitrary commands)
    "for", "if", "while", "case", "eval",
}

# Commands that are destructive / high-risk (should not be in allow without careful scoping)
HIGH_RISK_COMMANDS = {
    "rm", "rmdir", "sudo", "kill", "killall",
    "ssh", "docker", "kubectl", "terraform", "aws",
    "cp", "mv", "rsync",
}

# Sensitive path patterns (regex) — file tool rules matching these need attention
SENSITIVE_PATH_PATTERNS = [
    r"~/\.ssh",
    r"~/\.aws",
    r"~/\.gnupg",
    r"~/\.config/gh",
    r"\.env($|\.)",
    r"credentials",
    r"secrets?\.",
    r"\.pem$",
    r"\.key$",
    r"id_rsa",
    r"id_ed25519",
]

# Commands where wildcard allows dangerous flags/subcommands
DANGEROUS_FLAG_MAP = {
    "git branch": ["-D"],
    "git checkout": ["."],
    "git stash": ["drop", "clear"],
    "git reset": ["--hard"],
    "git push": ["--force", "--force-with-lease"],
    "rm": ["-rf", "-r"],
    "gh pr": ["create", "merge", "close"],
    "gh issue": ["create", "close"],
    "curl": ["-X POST", "-X PUT", "-X DELETE", "-d"],
    "git tag": ["-d"],
}

# Recommended deny rules for common sensitive paths
RECOMMENDED_DENY = [
    "Read(.env)",
    "Read(.env.*)",
    "Read(~/.ssh/**)",
    "Read(~/.aws/**)",
]

# Severity ordering for review findings
REVIEW_SEVERITY = ["CRITICAL", "HIGH", "MED", "LOW", "INFO"]


# 30日: 1開発スプリント程度。直近の作業パターンを反映しつつノイズを抑える
DEFAULT_DAYS = 30
# 3回: 1-2回は試行的使用。3回以上で定常的パターンと判断
DEFAULT_MIN_COUNT = 3
# 2リポジトリ: 単一リポジトリ固有のルールを除外する最小閾値
DEFAULT_MIN_REPOS = 2


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect tool usage patterns from session history"
    )
    parser.add_argument("--project", help="Project name filter (substring match)")
    parser.add_argument("--session", help="Session ID filter")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Days to look back (default: %(default)s)")
    parser.add_argument("--tool", help="Tool name filter (case-insensitive)")
    parser.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT, help="Min occurrences to suggest (default: %(default)s)")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    parser.add_argument("--show-all", action="store_true", help="Include already-allowed patterns")
    # Review mode
    parser.add_argument("--review", nargs="?", const="all", choices=["global", "project", "all"],
                        help="Review existing settings for dangerous configurations (default: all)")
    parser.add_argument("--show-suppressed", action="store_true",
                        help="Show acknowledged (suppressed) findings with a (suppressed) marker")
    # Consolidate mode
    parser.add_argument("--consolidate", nargs="+", metavar="GHQ_PREFIX",
                        help="Consolidate common rules from repos matching ghq prefix(es)")
    parser.add_argument("--min-repos", type=int, default=DEFAULT_MIN_REPOS,
                        help="Min repos to consider a rule common (default: %(default)s)")
    return parser.parse_args()


def get_project_name(project_dir):
    """Extract project name from directory name (returns full basename)."""
    return os.path.basename(project_dir) or project_dir


def split_chained_commands(command):
    """Split a command line by &&, ||, ; into individual commands.

    Returns a list of stripped command strings.
    Handles pipes (|) as part of a single command, not a separator.
    """
    if not command:
        return []
    first_line = command.strip().split("\n")[0]
    # Split by &&, ||, ; — but not inside quotes
    # Use a simple approach: split by these delimiters
    # (full shell parsing is overkill for permission analysis)
    parts = re.split(r'\s*(?:&&|\|\||;)\s*', first_line)
    return [p.strip() for p in parts if p.strip()]


def extract_bash_pattern(command):
    """Extract a meaningful pattern from a Bash command for rule suggestion.

    Only extracts from the first command in a chain (&&, ||, ;).
    Use extract_all_bash_patterns() to get patterns from all commands in a chain.
    """
    if not command:
        return None
    cmd = command.strip()
    if cmd.startswith("#"):
        return None

    first_line = cmd.split("\n")[0]
    # Take only the first command in a chain
    chain = split_chained_commands(first_line)
    if not chain:
        return None
    first_cmd = chain[0]

    parts = first_cmd.split()
    if not parts:
        return None

    base = parts[0]
    if base.startswith("\\"):
        base = base[1:]

    # Variable assignment (e.g., VAR=$(cmd ...), VAR="$(cmd ...)")
    # Permission rules can't contain $() due to parentheses parsing,
    # so extract the inner command instead.
    if "=" in base:
        rhs = first_cmd.split("=", 1)[1].strip()
        # Strip optional quotes and $(
        rhs = rhs.lstrip('"\'')
        if rhs.startswith("$("):
            inner = rhs[2:]
            # Strip trailing ) and optional quote
            inner = inner.rstrip('"\'')
            inner = inner.rstrip(")").strip()
            if inner:
                # Re-parse inner command
                return extract_bash_pattern(inner)
        return None

    # For commands with subcommands, include the subcommand
    if len(parts) >= 2 and base in (
        "git", "gh", "npm", "npx", "yarn", "pnpm", "cargo", "go", "docker",
        "kubectl", "terraform", "pip", "pip3", "brew", "jj", "claude",
    ):
        return f"{base} {parts[1]}"

    return base


def extract_all_bash_patterns(command):
    """Extract patterns from all commands in a chained command line.

    Returns a list of (pattern, single_command) tuples.
    e.g., "git status && git push origin main" -> [("git status", "git status"), ("git push", "git push origin main")]
    """
    if not command:
        return []
    cmd = command.strip()
    if cmd.startswith("#"):
        return []

    first_line = cmd.split("\n")[0]
    chain = split_chained_commands(first_line)
    results = []
    for single_cmd in chain:
        pattern = extract_bash_pattern(single_cmd)
        if pattern:
            results.append((pattern, single_cmd))
    return results


def analyze_bash_args(pattern, full_command):
    """Analyze flags and arguments in a command relative to its extracted pattern.

    Returns a dict with:
        flags: list of flag tokens (starting with -)
        positionals: list of positional arg tokens
        dangerous_flags_found: list of flags matching DANGEROUS_FLAG_MAP
    """
    if not pattern or not full_command:
        return {"flags": [], "positionals": [], "dangerous_flags_found": []}

    # Use only the single command portion (not the whole chain)
    # full_command may be a single command already or the relevant segment
    first_line = full_command.strip().split("\n")[0]
    # Isolate the command segment that matches the pattern
    chain = split_chained_commands(first_line)
    target = first_line  # fallback
    for seg in chain:
        normalized_seg = re.sub(r"^\\", "", seg.strip())
        if normalized_seg.startswith(pattern):
            target = seg.strip()
            break

    # Strip the pattern prefix from the command to get the arguments
    # Handle backslash-prefixed commands (e.g., \rm -> rm)
    normalized = re.sub(r"^\\", "", target)
    # Remove the pattern prefix
    if normalized.startswith(pattern):
        remainder = normalized[len(pattern):].strip()
    else:
        # Pattern might not match literally (e.g., \git vs git)
        parts = target.split()
        # Skip tokens until we've consumed the pattern
        pattern_parts = pattern.split()
        skip = len(pattern_parts)
        remainder = " ".join(parts[skip:]) if len(parts) > skip else ""

    if not remainder:
        return {"flags": [], "positionals": [], "dangerous_flags_found": []}

    tokens = remainder.split()
    flags = []
    positionals = []
    for token in tokens:
        if token.startswith("-"):
            flags.append(token)
        else:
            positionals.append(token)

    # Check for dangerous flags
    dangerous_found = []
    dangerous_flags = DANGEROUS_FLAG_MAP.get(pattern, [])
    for dflag in dangerous_flags:
        dflag_parts = dflag.split()
        # Single-token flag (e.g., "-D", "--force")
        if len(dflag_parts) == 1:
            if dflag in flags or dflag in positionals:
                dangerous_found.append(dflag)
        else:
            # Multi-token dangerous pattern (e.g., "-X POST")
            remainder_str = " ".join(tokens)
            if dflag in remainder_str:
                dangerous_found.append(dflag)

    return {
        "flags": flags,
        "positionals": positionals,
        "dangerous_flags_found": dangerous_found,
    }


def classify_file_scope(file_path, cwd=None):
    """Classify a file path into a scope category.

    Returns: ("project", None) | ("tmp", None) | ("external", directory)
    """
    if not file_path:
        return "project", None
    # /tmp
    if file_path.startswith("/tmp") or file_path.startswith("/private/tmp"):
        return "tmp", None
    # ~/.claude/
    home = str(Path.home())
    if file_path.startswith(os.path.join(home, ".claude")):
        return "external", os.path.join(home, ".claude")
    # Project-relative: heuristic - if under cwd or doesn't start with / it's project-local
    if cwd and file_path.startswith(cwd):
        return "project", None
    if not file_path.startswith("/"):
        return "project", None
    # External: group by repo root or top-level directory
    if file_path.startswith(home):
        # Try to find a meaningful grouping (e.g., ~/repos/github.com/org/repo)
        rel = file_path[len(home) + 1:]
        parts = rel.split("/")
        # Use up to 4 segments for grouping (repos/github.com/org/repo)
        depth = min(len(parts), 4)
        group_dir = os.path.join(home, *parts[:depth])
        return "external", group_dir
    return "external", os.path.dirname(file_path)


def generate_file_rule(tool_name, scope, directory=None):
    """Generate a file tool rule based on scope."""
    if scope == "project":
        return f"{tool_name}([project])"
    if scope == "tmp":
        return f"{tool_name}(///tmp/**)"
    # external
    home = str(Path.home())
    if directory and directory.startswith(home):
        rel = "~" + directory[len(home):]
        return f"{tool_name}({rel}/**)"
    if directory:
        return f"{tool_name}(//{directory}/**)"
    return tool_name


def generate_bash_rule(pattern):
    """Generate a Bash allow rule from a command pattern."""
    return f"Bash({pattern} *)"


def is_never_allow(rule):
    """Check if a rule matches a never-auto-allow command."""
    match = re.match(r"^Bash\((\S+)", rule)
    if not match:
        return False
    cmd = match.group(1)
    # Strip leading backslash (e.g., \rm -> rm)
    if cmd.startswith("\\"):
        cmd = cmd[1:]
    return cmd in NEVER_ALLOW_COMMANDS


def load_allow_rules_from(directory):
    """Load allow rules from settings files in a directory."""
    rules = set()
    for name in ("settings.json", "settings.local.json"):
        path = Path(directory) / name
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for rule in data.get("permissions", {}).get("allow", []):
                    rules.add(rule)
            except (json.JSONDecodeError, OSError) as e:
                print(f"warning: {path}: {e}", file=sys.stderr)
    return rules


def load_current_allow_rules(cwd=None):
    """Load current allow rules from global and project settings files."""
    global_rules = load_allow_rules_from(Path.home() / ".claude")
    project_rules = set()
    if cwd:
        project_settings_dir = Path(cwd) / ".claude"
        if project_settings_dir.exists():
            project_rules = load_allow_rules_from(project_settings_dir)
    return global_rules | project_rules


def is_already_allowed(rule, existing_rules):
    """Check if a rule (or a broader version) already exists in the allow list."""
    if rule in existing_rules:
        return True
    match = re.match(r"^(\w+)\((.+)\)$", rule)
    if not match:
        return rule in existing_rules
    tool, pattern = match.groups()
    if tool in existing_rules or f"{tool}(*)" in existing_rules:
        return True
    for existing in existing_rules:
        em = re.match(r"^(\w+)\((.+)\)$", existing)
        if not em:
            continue
        etool, epattern = em.groups()
        if etool != tool:
            continue
        if epattern.endswith(" *"):
            prefix = epattern[:-2]
            if pattern.startswith(prefix):
                return True
    return False


def load_all_rules_from(directory):
    """Load allow, ask, and deny rules from settings files in a directory.

    Returns: {
        "allow": set, "ask": set, "deny": set,
        "rule_origins": {rule: filename, ...}  # which file each rule came from
    }
    """
    result = {"allow": set(), "ask": set(), "deny": set(), "rule_origins": {}}
    for name in ("settings.json", "settings.local.json"):
        path = Path(directory) / name
        if path.exists():
            try:
                data = json.loads(path.read_text())
                perms = data.get("permissions", {})
                for key in ("allow", "ask", "deny"):
                    for rule in perms.get(key, []):
                        result[key].add(rule)
                        result["rule_origins"][rule] = name
            except (json.JSONDecodeError, OSError) as e:
                print(f"warning: {path}: {e}", file=sys.stderr)
    return result


def parse_bash_rule(rule):
    """Parse a Bash rule and return (command, full_pattern) or None.

    e.g. "Bash(git push *)" -> ("git push", "git push *")
         "Bash(rm *)" -> ("rm", "rm *")
    """
    match = re.match(r"^Bash\((.+)\)$", rule)
    if not match:
        return None
    pattern = match.group(1)
    # Extract command (first word or first two words for subcommand tools)
    parts = pattern.split()
    if not parts:
        return None
    base = parts[0]
    if base.startswith("\\"):
        base = base[1:]
    # Check for subcommand pattern
    if len(parts) >= 2 and base in (
        "git", "gh", "npm", "npx", "yarn", "pnpm", "cargo", "go", "docker",
        "kubectl", "terraform", "pip", "pip3", "brew", "jj", "claude",
    ):
        cmd = f"{base} {parts[1]}"
    else:
        cmd = base
    return cmd, pattern


def parse_file_rule(rule):
    """Parse a file tool rule and return (tool, path_pattern) or None.

    e.g. "Read(~/.ssh/**)" -> ("Read", "~/.ssh/**")
         "Edit" -> ("Edit", None)
    """
    match = re.match(r"^(Read|Edit|Write)\((.+)\)$", rule)
    if match:
        return match.group(1), match.group(2)
    if rule in ("Read", "Edit", "Write"):
        return rule, None
    return None


def is_guarded(dangerous_pattern, deny_rules, ask_rules):
    """Check if a dangerous pattern is covered by a deny or ask rule."""
    guard_rule = f"Bash({dangerous_pattern})"
    all_guards = deny_rules | ask_rules
    if guard_rule in all_guards:
        return True
    # Check wildcard guards: e.g. "Bash(git push --force *)" guards "git push --force"
    for guard in all_guards:
        gm = re.match(r"^Bash\((.+)\)$", guard)
        if not gm:
            continue
        gpat = gm.group(1)
        if gpat.endswith(" *"):
            prefix = gpat[:-2]
            if dangerous_pattern.startswith(prefix):
                return True
        if dangerous_pattern == gpat:
            return True
    return False


def make_finding(severity, category, rule, source, rule_list, message, recommendation="", file=""):
    """Create a finding dict."""
    return {
        "severity": severity,
        "category": category,
        "rule": rule,
        "source": source,
        "list": rule_list,
        "file": file,
        "message": message,
        "recommendation": recommendation,
    }


def is_scoped_interpreter(rule):
    """Check if a never-allow rule is scoped to a specific path (not arbitrary execution).

    e.g. "Bash(python3 /specific/path/*)" is scoped — the interpreter can only run
    specific scripts, not arbitrary code.
    "Bash(python3 *)" or "Bash(python3 -c *)" is NOT scoped.
    """
    parsed = parse_bash_rule(rule)
    if not parsed:
        return False
    cmd, pattern = parsed
    # pattern is e.g. "python3 /specific/path/*" or "python3 *"
    parts = pattern.split(None, 1)
    if len(parts) < 2:
        return False
    arg = parts[1]
    # Scoped if the argument starts with an absolute path or ~ path (not a bare wildcard)
    return arg.startswith("/") or arg.startswith("~/") or arg.startswith("~/.") or arg.startswith("$HOME/")


def check_never_allow_violation(rule, source):
    """Check if a never-auto-allow command is in allow."""
    if not is_never_allow(rule):
        return []
    parsed = parse_bash_rule(rule)
    cmd = parsed[0] if parsed else rule
    # Scoped interpreter rules (specific script paths) are lower severity
    if is_scoped_interpreter(rule):
        return [make_finding(
            "INFO", "scoped-interpreter", rule, source, "allow",
            f"Interpreter '{cmd}' scoped to specific path — verify the target script is trusted",
            "",
        )]
    return [make_finding(
        "CRITICAL", "never-allow-violation", rule, source, "allow",
        f"Script interpreter / shell construct '{cmd}' in allow — permits arbitrary code execution",
        "Move to 'ask' or remove. Scope to specific scripts if needed.",
    )]


def check_destructive_in_allow(rule, source):
    """Check if a destructive command is in allow."""
    parsed = parse_bash_rule(rule)
    if not parsed:
        return []
    cmd, pattern = parsed
    base = cmd.split()[0]
    if base in HIGH_RISK_COMMANDS:
        return [make_finding(
            "HIGH", "destructive-in-allow", rule, source, "allow",
            f"Destructive command '{cmd}' in allow — risk of data loss or system modification",
            f"Move to 'ask', or restrict scope.",
        )]
    return []


def check_sensitive_path(rule, source, all_deny):
    """Check if a file tool rule allows access to sensitive paths."""
    parsed = parse_file_rule(rule)
    if not parsed:
        return []
    tool, path_pattern = parsed
    if not path_pattern:
        return []
    findings = []
    for sp in SENSITIVE_PATH_PATTERNS:
        if re.search(sp, path_pattern):
            # Check if guarded by deny
            if rule in all_deny:
                findings.append(make_finding(
                    "INFO", "sensitive-path-guarded", rule, source, "allow",
                    f"Sensitive path in allow, but overridden by deny rule",
                ))
            else:
                findings.append(make_finding(
                    "HIGH", "sensitive-path-allowed", rule, source, "allow",
                    f"Allows {tool} access to sensitive path matching '{sp}'",
                    f"Add to 'deny' list or remove from 'allow'.",
                ))
            break  # One finding per rule is enough
    return findings


def check_overly_broad(rule, source):
    """Check for overly broad rules."""
    findings = []
    # Bash(*) — allows any command
    if rule == "Bash(*)":
        return [make_finding(
            "CRITICAL", "overly-broad", rule, source, "allow",
            "Allows execution of ANY Bash command",
            "Remove and add specific command rules instead.",
        )]
    # Bare Edit/Write without scope
    if rule in ("Edit", "Write"):
        return [make_finding(
            "MED", "overly-broad", rule, source, "allow",
            f"'{rule}' without scope allows modification of ANY file",
            f"Add path scope, e.g. {rule}(/**).",
        )]
    # Bare Read without scope
    if rule == "Read":
        return [make_finding(
            "LOW", "overly-broad", rule, source, "allow",
            "'Read' without scope — read-only but exposes all files including secrets",
            "Add path scope, e.g. Read(/**).",
        )]
    return findings


def check_wildcard_overmatch(rule, source, all_deny, all_ask):
    """Check if a wildcard rule covers dangerous flags without guards."""
    parsed = parse_bash_rule(rule)
    if not parsed:
        return []
    cmd, pattern = parsed
    if not pattern.endswith(" *"):
        return []
    dangerous_flags = DANGEROUS_FLAG_MAP.get(cmd)
    if not dangerous_flags:
        return []
    unguarded = []
    for flag in dangerous_flags:
        dangerous_pat = f"{cmd} {flag}"
        if not is_guarded(dangerous_pat, all_deny, all_ask):
            unguarded.append(flag)
    if not unguarded:
        return []
    flags_str = ", ".join(unguarded)
    return [make_finding(
        "MED", "wildcard-overmatch", rule, source, "allow",
        f"Wildcard matches dangerous flag(s): {flags_str}",
        f"Add ask/deny guard for: {', '.join(f'Bash({cmd} {f} *)' for f in unguarded)}",
    )]


def check_ask_overrides_allow(project_rules, global_rules):
    """Check if broad project ask/deny rules override specific global allow rules."""
    findings = []
    project_ask_deny = project_rules["ask"] | project_rules["deny"]
    for ask_rule in sorted(project_ask_deny):
        # Only check Bash wildcard rules (e.g. Bash(bash *), Bash(git *))
        m = re.match(r"^Bash\((.+)\)$", ask_rule)
        if not m:
            continue
        ask_pattern = m.group(1)
        if not ask_pattern.endswith(" *"):
            continue
        ask_prefix = ask_pattern[:-2]  # e.g. "bash", "git"
        # Find global allow rules that this would override
        overridden = []
        for allow_rule in sorted(global_rules["allow"]):
            am = re.match(r"^Bash\((.+)\)$", allow_rule)
            if not am:
                continue
            allow_pattern = am.group(1)
            if allow_pattern.startswith(ask_prefix) and allow_rule != ask_rule:
                overridden.append(allow_rule)
        if overridden:
            rule_list = "ask" if ask_rule in project_rules["ask"] else "deny"
            overridden_str = ", ".join(overridden[:3])
            if len(overridden) > 3:
                overridden_str += f" (+{len(overridden) - 3} more)"
            findings.append(make_finding(
                "MED", "ask-overrides-allow", ask_rule, "project", rule_list,
                f"Overrides {len(overridden)} global allow rule(s): {overridden_str}",
                f"Remove '{ask_rule}' from project {rule_list}, add specific dangerous commands instead.",
            ))
    return findings


def load_acknowledged_findings(cwd):
    """Load acknowledgedFindings from project-scoped .claude/settings.json.

    Returns a list of normalized entries: [{pattern, severity, note, acknowledgedAt}, ...].

    Failure modes (per Issue #26):
    - settings.json missing → return []
    - JSON parse error or top-level value not an object → warn, return []
    - acknowledgedFindings missing or not a list → warn (only when not a list), return []
    - individual entry missing pattern / invalid severity → warn, skip that entry
    - note / acknowledgedAt missing or wrong type → silently treat as empty (optional fields)
    """
    path = Path(cwd) / ".claude" / "settings.json"
    if not path.exists():
        return []
    try:
        raw_text = path.read_text()
    except OSError as e:
        print(f"warning: {path}: {e}; suppression disabled", file=sys.stderr)
        return []
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"warning: {path}: JSON parse error: {e}; suppression disabled", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        return []
    section = data.get("suggestPermissions")
    if section is None:
        return []
    if not isinstance(section, dict):
        print(f"warning: {path}: suggestPermissions is not an object; suppression disabled", file=sys.stderr)
        return []
    raw_list = section.get("acknowledgedFindings")
    if raw_list is None:
        return []
    if not isinstance(raw_list, list):
        print(f"warning: {path}: suggestPermissions.acknowledgedFindings is not an array; suppression disabled", file=sys.stderr)
        return []

    entries = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            print(f"warning: acknowledgedFindings[{i}] is not an object; skipping", file=sys.stderr)
            continue
        pattern = item.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            print(f"warning: acknowledgedFindings[{i}]: missing or invalid 'pattern'; skipping", file=sys.stderr)
            continue
        severity = item.get("severity")
        if not isinstance(severity, str) or severity.strip().upper() not in REVIEW_SEVERITY:
            print(f"warning: acknowledgedFindings[{i}]: missing or invalid 'severity'; skipping", file=sys.stderr)
            continue
        note = item.get("note", "")
        if not isinstance(note, str):
            note = ""
        ack_at = item.get("acknowledgedAt", "")
        if not isinstance(ack_at, str):
            ack_at = ""
        entries.append({
            "pattern": pattern.strip(),
            "severity": severity.strip().upper(),
            "note": note,
            "acknowledgedAt": ack_at,
        })
    return entries


def is_finding_acknowledged(finding, acknowledged):
    """Match a finding against acknowledgedFindings entries.

    Matching rule (per Issue #26):
    - severity equality (case-insensitive)
    - pattern matches finding["rule"] via fnmatch (glob); finding rule is whitespace-trimmed
    Returns the matching entry dict or None.
    """
    rule = (finding.get("rule") or "").strip()
    sev = (finding.get("severity") or "").strip().upper()
    if not rule:
        return None
    for entry in acknowledged:
        if entry["severity"] != sev:
            continue
        if fnmatch.fnmatchcase(rule, entry["pattern"]):
            return entry
    return None


def check_missing_protections(all_deny, all_ask):
    """Check for recommended deny rules that are missing."""
    findings = []
    for rec_rule in RECOMMENDED_DENY:
        if rec_rule not in all_deny and rec_rule not in all_ask:
            findings.append(make_finding(
                "LOW", "missing-protection", rec_rule, "-", "-",
                f"Recommended deny rule not configured",
                f"Add to 'deny' list in global settings.",
            ))
    return findings


def run_review(args):
    """Review existing permission settings for dangerous configurations.

    Returns an exit code:
        0 — no remaining (active, non-INFO) findings
        1 — at least one remaining (active, non-INFO) finding
        2 — abnormal stop (e.g. project scope requested but no .claude/ directory)
    """
    scope = args.review  # "global", "project", or "all"
    cwd = os.getcwd()

    # Load rules by scope
    empty_rules = {"allow": set(), "ask": set(), "deny": set(), "rule_origins": {}}
    if scope in ("global", "all"):
        global_rules = load_all_rules_from(Path.home() / ".claude")
    else:
        global_rules = empty_rules.copy()
    if scope in ("project", "all"):
        project_dir = Path(cwd) / ".claude"
        if project_dir.exists():
            project_rules = load_all_rules_from(project_dir)
        else:
            project_rules = empty_rules.copy()
            if scope == "project":
                print("No .claude/ directory found in current project.", file=sys.stderr)
                return 2
    else:
        project_rules = empty_rules.copy()

    # Merged deny/ask for guard checking
    all_deny = global_rules["deny"] | project_rules["deny"]
    all_ask = global_rules["ask"] | project_rules["ask"]

    # Run checks on allow rules
    findings = []
    for source_name, rules in [("global", global_rules), ("project", project_rules)]:
        origins = rules.get("rule_origins", {})
        for rule in sorted(rules["allow"]):
            origin_file = origins.get(rule, "")
            new_findings = []
            new_findings.extend(check_never_allow_violation(rule, source_name))
            new_findings.extend(check_destructive_in_allow(rule, source_name))
            new_findings.extend(check_sensitive_path(rule, source_name, all_deny))
            new_findings.extend(check_overly_broad(rule, source_name))
            new_findings.extend(check_wildcard_overmatch(rule, source_name, all_deny, all_ask))
            # Attach file origin to each finding
            for f in new_findings:
                f["file"] = origin_file
            findings.extend(new_findings)

    # Check ask-overrides-allow conflicts (only meaningful when both scopes are loaded)
    if scope == "all":
        findings.extend(check_ask_overrides_allow(project_rules, global_rules))

    # Check missing protections
    findings.extend(check_missing_protections(all_deny, all_ask))

    # Sort by severity
    findings.sort(key=lambda f: REVIEW_SEVERITY.index(f["severity"]))

    # Apply acknowledged findings suppression (project-scoped settings.json only)
    acknowledged = load_acknowledged_findings(cwd)
    for f in findings:
        ack = is_finding_acknowledged(f, acknowledged) if acknowledged else None
        if ack:
            f["suppressed"] = True
            f["acknowledged_pattern"] = ack["pattern"]
            f["acknowledged_note"] = ack["note"]
            f["acknowledged_at"] = ack["acknowledgedAt"]
        else:
            f["suppressed"] = False

    active_findings = [f for f in findings if not f["suppressed"]]
    suppressed_findings = [f for f in findings if f["suppressed"]]
    suppressed_count = len(suppressed_findings)

    # Remaining count drives the exit code: only actionable severities (CRITICAL/HIGH/MED)
    # gate the exit code. LOW is recommended/optional and INFO is informational, so they
    # surface in output but do not fail the run. This lets `--review && echo OK` work
    # without forcing every project to add every recommended deny rule.
    actionable = {"CRITICAL", "HIGH", "MED"}
    remaining_issues = sum(1 for f in active_findings if f["severity"] in actionable)

    # Summary counts (for displayed findings)
    display_findings = findings if args.show_suppressed else active_findings
    summary = {s: 0 for s in REVIEW_SEVERITY}
    for f in display_findings:
        summary[f["severity"]] += 1

    if args.format == "json":
        output = {
            "settings": {
                "global": {k: dict(sorted(v.items())) if isinstance(v, dict) else sorted(v) for k, v in global_rules.items()},
                "project": {k: dict(sorted(v.items())) if isinstance(v, dict) else sorted(v) for k, v in project_rules.items()},
            },
            "findings": display_findings,
            "summary": summary,
            "suppressed_count": suppressed_count,
            "remaining_issues": remaining_issues,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0 if remaining_issues == 0 else 1

    # Table format
    scope_label = {"global": "global only", "project": "project only", "all": "global + project"}
    print(f"Permission Review ({scope_label[scope]}):\n")

    print("Settings:")
    if scope in ("global", "all"):
        print(f"  Global (~/.claude/): {len(global_rules['deny'])} deny, "
              f"{len(global_rules['ask'])} ask, {len(global_rules['allow'])} allow")
    if scope in ("project", "all"):
        print(f"  Project (.claude/): {len(project_rules['deny'])} deny, "
              f"{len(project_rules['ask'])} ask, {len(project_rules['allow'])} allow")

    if not display_findings:
        if suppressed_count > 0 and not args.show_suppressed:
            print(f"\nNo active issues. {suppressed_count} acknowledged finding(s) suppressed.")
            print("(Use --show-suppressed to inspect them.)")
        else:
            print("\nNo issues found. Settings look good.")
        return 0 if remaining_issues == 0 else 1

    issue_count = sum(v for k, v in summary.items() if k != "INFO")
    print(f"\nFindings ({issue_count} issues):\n")

    fmt = "  {:<10} {:<45} {}"
    print(fmt.format("SEV", "RULE", "MESSAGE"))
    print("  " + "-" * 108)

    for f in display_findings:
        # Build source label: e.g. [project/settings.json/allow] or [global/allow]
        if f["source"] != "-":
            file_part = f["file"].replace(".json", "") + "/" if f["file"] else ""
            source_label = f"[{f['source']}/{file_part}{f['list']}]"
        else:
            source_label = ""
        rule_col = f"{f['rule'][:30]}  {source_label}" if f["rule"] else "-"
        msg = f["message"]
        if f.get("suppressed"):
            msg = f"(suppressed) {msg}"
        print(fmt.format(f["severity"], rule_col[:45], msg[:80]))

    print()
    summary_parts = [f"{summary[s]} {s.lower()}" for s in REVIEW_SEVERITY if summary[s] > 0]
    print(f"Summary: {', '.join(summary_parts)}")

    if suppressed_count > 0 and not args.show_suppressed:
        print(f"\nℹ {suppressed_count}件の既知指摘を抑制しました（詳細は --show-suppressed）")

    # Show recommendations for HIGH+ findings (active only)
    high_findings = [f for f in active_findings
                     if f["severity"] in ("CRITICAL", "HIGH") and f["recommendation"]]
    if high_findings:
        print("\nRecommendations:")
        for f in high_findings:
            print(f"  {f['rule']}: {f['recommendation']}")

    return 0 if remaining_issues == 0 else 1


def list_ghq_repos(prefixes):
    """List repository full paths matching ghq prefixes."""
    try:
        root = subprocess.check_output(["ghq", "root"], text=True).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("Error: ghq が見つかりません。インストール: https://github.com/x-motemen/ghq", file=sys.stderr)
        sys.exit(1)

    repos = set()
    for prefix in prefixes:
        try:
            output = subprocess.check_output(["ghq", "list", prefix], text=True).strip()
            for line in output.splitlines():
                if line:
                    repos.add(os.path.join(root, line))
        except subprocess.CalledProcessError:
            pass  # prefix にマッチするリポジトリがないのは正常
    return sorted(repos)


def find_common_rules(repo_rules_map, min_repos, global_rules):
    """Find rules common across multiple repos, excluding already-global rules."""
    rule_repos = defaultdict(list)
    for repo_path, rules in repo_rules_map.items():
        repo_name = os.path.basename(repo_path)
        for rule in rules:
            if not is_already_allowed(rule, global_rules):
                rule_repos[rule].append(repo_name)

    results = []
    for rule, repo_list in rule_repos.items():
        if len(repo_list) >= min_repos:
            results.append((rule, len(repo_list), sorted(repo_list)))
    results.sort(key=lambda x: (-x[1], x[0]))
    return results


def run_consolidate(args):
    """Consolidate common rules from multiple repos."""
    repos = list_ghq_repos(args.consolidate)
    if not repos:
        print("No repos found matching the given prefix(es).", file=sys.stderr)
        sys.exit(1)

    # Load rules from each repo
    repo_rules_map = {}
    for repo_path in repos:
        settings_dir = os.path.join(repo_path, ".claude")
        if os.path.isdir(settings_dir):
            rules = load_allow_rules_from(settings_dir)
            if rules:
                repo_rules_map[repo_path] = rules

    if not repo_rules_map:
        print("No project settings found in any of the matched repos.")
        return

    # Load global rules
    global_rules = load_allow_rules_from(Path.home() / ".claude")

    # Find common rules
    common = find_common_rules(repo_rules_map, args.min_repos, global_rules)

    total_repos = len(repos)
    repos_with_settings = len(repo_rules_map)

    if args.format == "json":
        # Build removable map
        common_rule_set = {r[0] for r in common if not is_never_allow(r[0])}
        removable = {}
        for repo_path, rules in repo_rules_map.items():
            repo_name = os.path.basename(repo_path)
            to_remove = sorted(r for r in rules if r in common_rule_set)
            if to_remove:
                removable[repo_name] = to_remove

        output = {
            "repos_scanned": total_repos,
            "repos_with_settings": repos_with_settings,
            "global_rules": sorted(global_rules),
            "common_rules": [
                {
                    "rule": rule,
                    "count": count,
                    "never_allow": is_never_allow(rule),
                    "repos": repo_list,
                }
                for rule, count, repo_list in common
            ],
            "removable": removable,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # Table format
    prefix_display = ", ".join(args.consolidate)
    print(f"Consolidation analysis ({repos_with_settings}/{total_repos} repos with settings, prefix: {prefix_display}):\n")

    if global_rules:
        print(f"Current global rules ({len(global_rules)} rules in ~/.claude/):")
        for r in sorted(global_rules):
            print(f"  {r}")
        print()

    if not common:
        print(f"No common rules found across {args.min_repos}+ repos (excluding already-global rules).")
        return

    print(f"Common project rules (found in {args.min_repos}+ repos):\n")
    fmt = "{:<4} {:<7} {:<50} {}"
    print(fmt.format("", "REPOS", "RULE", "FOUND IN"))
    print("-" * 110)

    suggested = []
    for rule, count, repo_list in common:
        if is_never_allow(rule):
            status = "[!!]"
        else:
            status = f"[{len(suggested) + 1:>2}]"
            suggested.append(rule)
        repos_str = ", ".join(repo_list[:3])
        if len(repo_list) > 3:
            repos_str += f", ... (+{len(repo_list) - 3})"
        print(fmt.format(status, f"{count}/{repos_with_settings}", rule[:50], repos_str))

    never_count = sum(1 for r, _, _ in common if is_never_allow(r))
    if never_count:
        print(f"\n[!!] = never auto-allow ({never_count} patterns)")

    if suggested:
        print(f"\nSuggested global additions ({len(suggested)} rules):")
        for r in suggested:
            print(f"  {r}")

    # Show removable rules per repo
    common_rule_set = set(suggested)
    removable_repos = []
    for repo_path, rules in repo_rules_map.items():
        repo_name = os.path.basename(repo_path)
        to_remove = sorted(r for r in rules if r in common_rule_set)
        if to_remove:
            removable_repos.append((repo_name, to_remove))

    if removable_repos:
        print("\nAfter adding to global, removable from project settings:")
        removable_repos.sort(key=lambda x: x[0])
        for repo_name, rules in removable_repos:
            rules_str = ", ".join(rules[:5])
            if len(rules) > 5:
                rules_str += f", ... (+{len(rules) - 5})"
            print(f"  {repo_name}: {rules_str}")


def collect_tool_uses(filepath, project_name, args):
    """Collect tool_use events from a JSONL file."""
    tool_uses = []

    parse_errors = 0
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    parse_errors += 1
                    continue

                session_id = record.get("sessionId", "")
                if args.session and args.session not in session_id:
                    continue

                message = record.get("message")
                if not message or message.get("role") != "assistant":
                    continue

                content = message.get("content")
                if not isinstance(content, list):
                    continue

                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue

                    tool_uses.append({
                        "tool": block.get("name", ""),
                        "input": block.get("input", {}),
                        "timestamp": record.get("timestamp", ""),
                        "session_id": session_id,
                        "project": project_name,
                        "cwd": record.get("cwd", ""),
                    })

    except (OSError, IOError) as e:
        print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)

    if parse_errors:
        print(f"Warning: {parse_errors} JSON parse error(s) in {os.path.basename(filepath)}", file=sys.stderr)

    return tool_uses


def main():
    args = parse_args()

    if args.review is not None:
        return run_review(args) or 0

    if args.consolidate:
        run_consolidate(args)
        return 0

    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.exists():
        print("No Claude projects directory found.", file=sys.stderr)
        sys.exit(1)

    cutoff = time.time() - (args.days * 86400)
    all_uses = []

    for project_dir in claude_projects.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = get_project_name(str(project_dir))

        if args.project and args.project.lower() not in project_name.lower():
            if args.project.lower() not in project_dir.name.lower():
                continue

        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                if jsonl_file.stat().st_mtime < cutoff:
                    continue
            except OSError as e:
                print(f"warning: {jsonl_file}: {e}", file=sys.stderr)
                continue

            uses = collect_tool_uses(str(jsonl_file), project_name, args)
            all_uses.extend(uses)

    # Apply tool filter
    if args.tool:
        tool_lower = args.tool.lower()
        all_uses = [u for u in all_uses if tool_lower in u["tool"].lower()]

    # Generate rule suggestions
    rule_counts = Counter()
    rule_examples = defaultdict(list)
    # Track argument/flag statistics per rule for deeper analysis
    rule_arg_stats = defaultdict(lambda: {
        "flag_counts": Counter(),
        "positional_counts": Counter(),
        "dangerous_flags_seen": Counter(),
        "unique_commands": set(),
        "pattern": "",  # the extracted pattern (e.g., "git push")
    })

    for use in all_uses:
        tool = use["tool"]
        inp = use["input"] if isinstance(use["input"], dict) else {}

        if tool in SAFE_TOOLS:
            # Consolidate safe tools to tool-level rules
            rule = tool
            rule_counts[rule] += 1
        elif tool == "Bash":
            cmd = inp.get("command", "")
            # Extract patterns from all commands in a chain (&&, ||, ;)
            all_patterns = extract_all_bash_patterns(cmd)
            if not all_patterns:
                # Fallback to single extraction
                pattern = extract_bash_pattern(cmd)
                if pattern:
                    all_patterns = [(pattern, cmd)]
            for pattern, single_cmd in all_patterns:
                rule = generate_bash_rule(pattern)
                rule_counts[rule] += 1
                if len(rule_examples[rule]) < 20:
                    rule_examples[rule].append(single_cmd[:200])
                # Analyze arguments/flags
                stats = rule_arg_stats[rule]
                stats["pattern"] = pattern
                args_info = analyze_bash_args(pattern, single_cmd)
                for flag in args_info["flags"]:
                    stats["flag_counts"][flag] += 1
                for pos in args_info["positionals"]:
                    stats["positional_counts"][pos] += 1
                for dflag in args_info["dangerous_flags_found"]:
                    stats["dangerous_flags_seen"][dflag] += 1
                if single_cmd and len(stats["unique_commands"]) < 30:
                    stats["unique_commands"].add(single_cmd[:200])
        elif tool in FILE_TOOLS:
            fp = inp.get("file_path", "")
            cwd = use.get("cwd", "")
            scope, directory = classify_file_scope(fp, cwd)
            rule = generate_file_rule(tool, scope, directory)
            rule_counts[rule] += 1
            if fp and len(rule_examples[rule]) < 20:
                rule_examples[rule].append(fp[:200])
        elif tool == "Agent":
            rule = "Agent"
            rule_counts[rule] += 1
        else:
            # Other tools (WebFetch, MCP tools, etc.)
            rule = tool
            rule_counts[rule] += 1
            if len(rule_examples[rule]) < 20:
                rule_examples[rule].append(json.dumps(inp, ensure_ascii=False)[:200])

    # Load existing rules (global + project)
    cwd = os.getcwd()
    existing_rules = load_current_allow_rules(cwd)

    # Build suggestions
    suggestions = []
    for rule, count in rule_counts.most_common():
        if count < args.min_count:
            continue
        already = is_already_allowed(rule, existing_rules)
        if not args.show_all and already:
            continue
        stats = rule_arg_stats.get(rule)
        suggestion = {
            "rule": rule,
            "count": count,
            "already_allowed": already,
            "never_allow": is_never_allow(rule),
            "examples": rule_examples.get(rule, []),
        }
        # Add argument analysis for Bash rules
        if stats and stats["pattern"]:
            arg_analysis = {}
            if stats["flag_counts"]:
                arg_analysis["flags"] = dict(stats["flag_counts"].most_common(15))
            if stats["positional_counts"]:
                arg_analysis["positionals"] = dict(stats["positional_counts"].most_common(15))
            if stats["dangerous_flags_seen"]:
                arg_analysis["dangerous_flags_seen"] = dict(stats["dangerous_flags_seen"])
            if stats["unique_commands"]:
                arg_analysis["unique_commands"] = sorted(stats["unique_commands"])[:10]
            if arg_analysis:
                suggestion["arg_analysis"] = arg_analysis
        suggestions.append(suggestion)

    if not suggestions:
        print("No rule suggestions found. Try lowering --min-count or using --show-all.")
        return

    if args.format == "json":
        print(json.dumps(suggestions, indent=2, ensure_ascii=False))
        return

    # Table format
    print(f"Tool usage patterns (last {args.days} days, min {args.min_count} uses):\n")

    # Current allow rules (show global and project separately)
    global_rules = load_allow_rules_from(Path.home() / ".claude")
    project_settings_dir = Path(cwd) / ".claude"
    project_rules = load_allow_rules_from(project_settings_dir) if project_settings_dir.exists() else set()
    if global_rules:
        print("Current allow rules (global: ~/.claude/):")
        for r in sorted(global_rules):
            print(f"  {r}")
        print()
    if project_rules:
        print("Current allow rules (project: .claude/):")
        for r in sorted(project_rules):
            print(f"  {r}")
        print()

    # Dangerous usage warnings (show before the main table)
    dangerous_suggestions = [s for s in suggestions if s.get("arg_analysis", {}).get("dangerous_flags_seen")]
    if dangerous_suggestions:
        print("!! Dangerous flags detected in actual usage:\n")
        for s in dangerous_suggestions:
            dflags = s["arg_analysis"]["dangerous_flags_seen"]
            dflags_str = ", ".join(f"{f}({c}x)" for f, c in sorted(dflags.items(), key=lambda x: -x[1]))
            print(f"  {s['rule']}  : {dflags_str}")
            pattern = rule_arg_stats[s["rule"]]["pattern"]
            guards = [f"Bash({pattern} {f} *)" for f in dflags]
            print(f"    -> recommend ask guard: {', '.join(guards)}")
        print()

    fmt = "{:<4} {:<6} {:<50} {}"
    print(fmt.format("", "COUNT", "RULE", "EXAMPLES"))
    print("-" * 110)

    for i, s in enumerate(suggestions, 1):
        if s["already_allowed"]:
            status = "[OK]"
        elif s.get("never_allow"):
            status = "[!!]"
        else:
            status = f"[{i:>2}]"
        examples_str = " | ".join(ex[:50] for ex in s["examples"][:2])
        print(fmt.format(status, s["count"], s["rule"][:50], examples_str))

        # Show argument breakdown for Bash rules with non-trivial usage
        arg_analysis = s.get("arg_analysis", {})
        if arg_analysis:
            # Show top flags
            flags = arg_analysis.get("flags", {})
            dflags = arg_analysis.get("dangerous_flags_seen", {})
            if flags:
                flag_parts = []
                for f, c in sorted(flags.items(), key=lambda x: -x[1])[:8]:
                    marker = "[!]" if f in dflags else ""
                    flag_parts.append(f"{f}({c}){marker}")
                print(f"       flags: {', '.join(flag_parts)}")
            # Show top positional args
            positionals = arg_analysis.get("positionals", {})
            if positionals:
                pos_parts = [f"{p}({c})" for p, c in sorted(positionals.items(), key=lambda x: -x[1])[:8]]
                print(f"       args:  {', '.join(pos_parts)}")
            # Show deduplicated examples
            unique_cmds = arg_analysis.get("unique_commands", [])
            if unique_cmds:
                print(f"       examples ({len(unique_cmds)}):")
                for cmd in unique_cmds[:5]:
                    print(f"         {cmd[:100]}")

    never_count = sum(1 for s in suggestions if s.get("never_allow"))
    if never_count:
        print(f"\n[!!] = never auto-allow ({never_count} patterns) — use 'ask' or leave default")

    new_count = sum(1 for s in suggestions if not s["already_allowed"])
    print(f"\nTotal: {len(suggestions)} patterns, {new_count} new (not yet in allow list)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
