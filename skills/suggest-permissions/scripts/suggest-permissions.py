#!/usr/bin/env python3
"""Collect tool usage patterns from Claude Code session history for permission rule suggestions."""

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# Tools that are always safe (read-only, no side effects) - auto-consolidate to tool-level rules
SAFE_TOOLS = {"Glob", "Grep", "WebSearch"}

# File tools that need scope-based analysis
FILE_TOOLS = {"Read", "Edit", "Write"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect tool usage patterns from session history"
    )
    parser.add_argument("--project", help="Project name filter (substring match)")
    parser.add_argument("--session", help="Session ID filter")
    parser.add_argument("--days", type=int, default=30, help="Days to look back (default: 30)")
    parser.add_argument("--tool", help="Tool name filter (case-insensitive)")
    parser.add_argument("--min-count", type=int, default=3, help="Min occurrences to suggest (default: 3)")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    parser.add_argument("--show-all", action="store_true", help="Include already-allowed patterns")
    return parser.parse_args()


def get_project_name(project_dir):
    """Extract project name from directory name."""
    name = os.path.basename(project_dir)
    parts = name.split("-")
    for part in reversed(parts):
        if part:
            return part
    return name


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


def load_current_allow_rules():
    """Load current allow rules from all settings files."""
    rules = set()
    for name in ("settings.json", "settings.local.json"):
        path = Path.home() / ".claude" / name
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for rule in data.get("permissions", {}).get("allow", []):
                    rules.add(rule)
            except (json.JSONDecodeError, OSError):
                pass
    return rules


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


def collect_tool_uses(filepath, project_name, args):
    """Collect tool_use events from a JSONL file."""
    tool_uses = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
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

    except (OSError, IOError):
        pass

    return tool_uses


def main():
    args = parse_args()

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

    # Load existing rules
    existing_rules = load_current_allow_rules()

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

    # Current allow rules
    if existing_rules:
        print("Current allow rules:")
        for r in sorted(existing_rules):
            print(f"  {r}")
        print()

    fmt = "{:<4} {:<6} {:<50} {}"
    print(fmt.format("", "COUNT", "RULE", "EXAMPLES"))
    print("-" * 110)

    for i, s in enumerate(suggestions, 1):
        status = "[OK]" if s["already_allowed"] else f"[{i:>2}]"
        examples_str = " | ".join(ex[:40] for ex in s["examples"][:2])
        print(fmt.format(status, s["count"], s["rule"][:50], examples_str))

    new_count = sum(1 for s in suggestions if not s["already_allowed"])
    print(f"\nTotal: {len(suggestions)} patterns, {new_count} new (not yet in allow list)")


if __name__ == "__main__":
    main()
