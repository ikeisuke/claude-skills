#!/usr/bin/env python3
"""Collect tool usage patterns from Claude Code session history for permission rule suggestions."""

import argparse
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
    # Consolidate mode
    parser.add_argument("--consolidate", nargs="+", metavar="GHQ_PREFIX",
                        help="Consolidate common rules from repos matching ghq prefix(es)")
    parser.add_argument("--min-repos", type=int, default=DEFAULT_MIN_REPOS,
                        help="Min repos to consider a rule common (default: %(default)s)")
    return parser.parse_args()


def get_project_name(project_dir):
    """Extract project name from directory name (returns full basename)."""
    return os.path.basename(project_dir) or project_dir


def extract_bash_pattern(command):
    """Extract a meaningful pattern from a Bash command for rule suggestion."""
    if not command:
        return None
    cmd = command.strip()
    if cmd.startswith("#"):
        return None

    first_line = cmd.split("\n")[0]
    parts = first_line.split()
    if not parts:
        return None

    base = parts[0]
    if base.startswith("\\"):
        base = base[1:]

    # Variable assignment (e.g., VAR=$(cmd ...), VAR="$(cmd ...)")
    # Permission rules can't contain $() due to parentheses parsing,
    # so extract the inner command instead.
    if "=" in base:
        rhs = first_line.split("=", 1)[1].strip()
        # Strip optional quotes and $(
        rhs = rhs.lstrip('"\'')
        if rhs.startswith("$("):
            inner = rhs[2:].rstrip(")").strip()
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
            except (json.JSONDecodeError, OSError):
                pass
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
            except (json.JSONDecodeError, OSError):
                pass
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
    """Review existing permission settings for dangerous configurations."""
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
                sys.exit(1)
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

    # Check missing protections
    findings.extend(check_missing_protections(all_deny, all_ask))

    # Sort by severity
    findings.sort(key=lambda f: REVIEW_SEVERITY.index(f["severity"]))

    # Summary counts
    summary = {s: 0 for s in REVIEW_SEVERITY}
    for f in findings:
        summary[f["severity"]] += 1

    if args.format == "json":
        output = {
            "settings": {
                "global": {k: dict(sorted(v.items())) if isinstance(v, dict) else sorted(v) for k, v in global_rules.items()},
                "project": {k: dict(sorted(v.items())) if isinstance(v, dict) else sorted(v) for k, v in project_rules.items()},
            },
            "findings": findings,
            "summary": summary,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

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

    if not findings:
        print("\nNo issues found. Settings look good.")
        return

    print(f"\nFindings ({sum(v for k, v in summary.items() if k != 'INFO')} issues):\n")

    fmt = "  {:<10} {:<45} {}"
    print(fmt.format("SEV", "RULE", "MESSAGE"))
    print("  " + "-" * 108)

    for f in findings:
        # Build source label: e.g. [project/settings.json/allow] or [global/allow]
        if f["source"] != "-":
            file_part = f["file"].replace(".json", "") + "/" if f["file"] else ""
            source_label = f"[{f['source']}/{file_part}{f['list']}]"
        else:
            source_label = ""
        rule_col = f"{f['rule'][:30]}  {source_label}" if f["rule"] else "-"
        print(fmt.format(f["severity"], rule_col[:45], f["message"][:80]))

    print()
    summary_parts = [f"{summary[s]} {s.lower()}" for s in REVIEW_SEVERITY if summary[s] > 0]
    print(f"Summary: {', '.join(summary_parts)}")

    # Show recommendations for HIGH+ findings
    high_findings = [f for f in findings if f["severity"] in ("CRITICAL", "HIGH") and f["recommendation"]]
    if high_findings:
        print("\nRecommendations:")
        for f in high_findings:
            print(f"  {f['rule']}: {f['recommendation']}")


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
            pass
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
        run_review(args)
        return

    if args.consolidate:
        run_consolidate(args)
        return

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
            except OSError:
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

    for use in all_uses:
        tool = use["tool"]
        inp = use["input"] if isinstance(use["input"], dict) else {}

        if tool in SAFE_TOOLS:
            # Consolidate safe tools to tool-level rules
            rule = tool
            rule_counts[rule] += 1
        elif tool == "Bash":
            pattern = extract_bash_pattern(inp.get("command", ""))
            if pattern:
                rule = generate_bash_rule(pattern)
                rule_counts[rule] += 1
                cmd = inp.get("command", "")
                if len(rule_examples[rule]) < 5:
                    rule_examples[rule].append(cmd[:120])
        elif tool in FILE_TOOLS:
            fp = inp.get("file_path", "")
            cwd = use.get("cwd", "")
            scope, directory = classify_file_scope(fp, cwd)
            rule = generate_file_rule(tool, scope, directory)
            rule_counts[rule] += 1
            if fp and len(rule_examples[rule]) < 5:
                rule_examples[rule].append(fp[:120])
        elif tool == "Agent":
            rule = "Agent"
            rule_counts[rule] += 1
        else:
            # Other tools (WebFetch, MCP tools, etc.)
            rule = tool
            rule_counts[rule] += 1
            if len(rule_examples[rule]) < 5:
                rule_examples[rule].append(json.dumps(inp, ensure_ascii=False)[:120])

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
        suggestions.append({
            "rule": rule,
            "count": count,
            "already_allowed": already,
            "never_allow": is_never_allow(rule),
            "examples": rule_examples.get(rule, []),
        })

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
        examples_str = " | ".join(ex[:40] for ex in s["examples"][:2])
        print(fmt.format(status, s["count"], s["rule"][:50], examples_str))

    never_count = sum(1 for s in suggestions if s.get("never_allow"))
    if never_count:
        print(f"\n[!!] = never auto-allow ({never_count} patterns) — use 'ask' or leave default")

    new_count = sum(1 for s in suggestions if not s["already_allowed"])
    print(f"\nTotal: {len(suggestions)} patterns, {new_count} new (not yet in allow list)")


if __name__ == "__main__":
    main()
