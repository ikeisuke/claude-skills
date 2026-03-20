#!/usr/bin/env python3
"""Translate Claude Code permission settings to Kiro CLI custom agent configuration."""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

# Claude tools that map to Kiro's built-in "read" tool
READ_TOOLS = {"Glob", "Grep", "Read"}

# Claude tools that map to Kiro's built-in "write" tool
WRITE_TOOLS = {"Edit", "Write"}

# Claude tools with no Kiro built-in equivalent (skipped)
SKIPPED_TOOLS = {"WebSearch", "WebFetch", "Agent", "AskUserQuestion",
                 "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskOutput", "TaskStop",
                 "NotebookEdit", "EnterPlanMode", "ExitPlanMode",
                 "EnterWorktree", "ExitWorktree"}

# Pattern for file-tool rules: ToolName(path)
FILE_TOOL_RE = re.compile(r"^(Read|Edit|Write|Glob|Grep)\((.+)\)$")

# Pattern for Bash rules: Bash(command)
BASH_RE = re.compile(r"^Bash\((.+)\)$")

# Pattern for MCP tool rules: mcp__serverName__toolName
MCP_RE = re.compile(r"^mcp__([^_]+(?:_[^_]+)*)__(.+)$")

# Pattern for WebFetch with domain: WebFetch(domain:example.com)
WEBFETCH_DOMAIN_RE = re.compile(r"^WebFetch\(domain:(.+)\)$")

# Pattern for Skill rules: Skill(name)
SKILL_RE = re.compile(r"^Skill\((.+)\)$")


def load_claude_settings(scope, input_path=None):
    """Load and merge Claude Code permission settings.

    Merge order (later overrides earlier):
    1. ~/.claude/settings.json (global)
    2. .claude/settings.json (project)
    3. .claude/settings.local.json (project local)

    Returns dict with keys: allow, deny, ask (each a list of rule strings).
    """
    if input_path:
        if not Path(input_path).exists():
            print(f"Error: file not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        with open(input_path) as f:
            data = json.load(f)
        perms = data.get("permissions", data)
        return {
            "allow": perms.get("allow", []),
            "deny": perms.get("deny", []),
            "ask": perms.get("ask", []),
        }

    merged = {"allow": [], "deny": [], "ask": []}

    files_to_load = []
    if scope in ("global", "all"):
        files_to_load.append(Path.home() / ".claude" / "settings.json")
    if scope in ("project", "all"):
        files_to_load.append(Path(".claude") / "settings.json")
        files_to_load.append(Path(".claude") / "settings.local.json")

    for filepath in files_to_load:
        if not filepath.exists():
            continue
        try:
            with open(filepath) as f:
                data = json.load(f)
            perms = data.get("permissions", {})
            for key in ("allow", "deny", "ask"):
                rules = perms.get(key, [])
                if isinstance(rules, list):
                    merged[key].extend(rules)
        except (json.JSONDecodeError, OSError):
            print(f"Warning: could not read {filepath}", file=sys.stderr)

    # Deduplicate while preserving order
    for key in merged:
        merged[key] = list(dict.fromkeys(merged[key]))

    return merged


def parse_permission_rule(rule):
    """Parse a Claude permission rule string into structured form.

    Returns dict with keys: tool, pattern (optional), raw.
    """
    # Bash(command)
    m = BASH_RE.match(rule)
    if m:
        return {"tool": "Bash", "pattern": m.group(1), "raw": rule}

    # File tools with path: Read(/**), Edit(src/**)
    m = FILE_TOOL_RE.match(rule)
    if m:
        return {"tool": m.group(1), "pattern": m.group(2), "raw": rule}

    # MCP tools: mcp__server__tool
    m = MCP_RE.match(rule)
    if m:
        return {"tool": "mcp", "server": m.group(1), "tool_name": m.group(2), "raw": rule}

    # WebFetch(domain:...)
    m = WEBFETCH_DOMAIN_RE.match(rule)
    if m:
        return {"tool": "WebFetch", "pattern": m.group(1), "raw": rule}

    # Skill(name)
    m = SKILL_RE.match(rule)
    if m:
        return {"tool": "Skill", "pattern": m.group(1), "raw": rule}

    # Simple tool name: Glob, Grep, Read, WebSearch, etc.
    return {"tool": rule, "pattern": None, "raw": rule}


def normalize_bash_pattern(pattern):
    """Convert Claude Bash pattern to Kiro shell command pattern.

    - 'git add:*' -> 'git add *'
    - 'git status *' -> 'git status *' (unchanged)
    """
    return pattern.replace(":*", " *")


def normalize_file_path(pattern):
    """Convert Claude file path pattern to Kiro allowedPaths pattern.

    - '/**' -> '**' (project-relative)
    - '/src/**' -> 'src/**' (strip leading slash)
    - '///tmp/**' -> '/tmp/**' (absolute, strip double slash prefix)
    - '~/.ssh/**' -> None (home-relative, no Kiro equivalent)

    Returns normalized path string or None if unmappable.
    """
    if pattern.startswith("~"):
        return None

    # Triple-slash: absolute path (Claude convention)
    if pattern.startswith("///"):
        return pattern[2:]  # Keep single leading slash

    # Single leading slash: project-relative
    if pattern.startswith("/"):
        stripped = pattern[1:]
        return stripped if stripped else "**"

    # Already relative
    return pattern


def parse_mcp_tool(rule):
    """Parse mcp__serverName__toolName into (server_name, tool_name).

    Returns tuple (server, tool) or None if not an MCP rule.
    """
    m = MCP_RE.match(rule)
    if m:
        return (m.group(1), m.group(2))
    return None


def translate_to_kiro(permissions, agent_name, description):
    """Translate Claude Code permissions to Kiro agent configuration.

    Args:
        permissions: dict with allow/deny/ask lists
        agent_name: name for the Kiro agent
        description: description for the Kiro agent

    Returns:
        dict: Kiro agent configuration
    """
    tools = set()
    allowed_tools = []
    allowed_commands = []
    ask_commands = []
    denied_commands = []
    write_allowed_paths = []
    mcp_servers = set()  # Track server names for tools array
    mcp_allowed = []  # @server/tool entries for allowedTools
    skipped = []

    for category in ("allow", "deny", "ask"):
        for rule in permissions.get(category, []):
            parsed = parse_permission_rule(rule)
            tool = parsed["tool"]

            # Skipped tools (no Kiro equivalent)
            if tool in SKIPPED_TOOLS:
                skipped.append(rule)
                continue

            # Skill rules — skip (Kiro uses resources/skills differently)
            if tool == "Skill":
                skipped.append(rule)
                continue

            # WebFetch with domain — skip
            if tool == "WebFetch":
                skipped.append(rule)
                continue

            # Read-family tools
            # Note: Kiro has no read.allowedPaths, so path-scoped Read rules
            # cannot be auto-approved without widening access. Only bare
            # Read (no path) is added to allowedTools.
            if tool in READ_TOOLS:
                if category == "deny":
                    skipped.append(rule)
                elif category == "allow":
                    tools.add("read")
                    if not parsed.get("pattern"):
                        allowed_tools.append("read")
                else:  # ask
                    tools.add("read")
                continue

            # Write-family tools
            if tool in WRITE_TOOLS:
                if category == "deny":
                    skipped.append(rule)
                else:
                    if parsed.get("pattern"):
                        path = normalize_file_path(parsed["pattern"])
                        if path is not None:
                            tools.add("write")
                            write_allowed_paths.append(path)
                            if category == "allow":
                                allowed_tools.append("write")
                        else:
                            skipped.append(rule)
                    else:
                        tools.add("write")
                        if category == "allow":
                            allowed_tools.append("write")
                continue

            # Bash commands
            if tool == "Bash":
                cmd = normalize_bash_pattern(parsed["pattern"])
                if category == "allow":
                    tools.add("shell")
                    allowed_commands.append(cmd)
                elif category == "deny":
                    denied_commands.append(cmd)
                elif category == "ask":
                    tools.add("shell")
                    ask_commands.append(cmd)
                continue

            # MCP tools
            if tool == "mcp":
                if category == "deny":
                    skipped.append(rule)
                    continue
                server = parsed["server"]
                tool_name = parsed["tool_name"]
                mcp_servers.add(server)
                kiro_ref = f"@{server}/{tool_name}"
                if category == "allow":
                    mcp_allowed.append(kiro_ref)
                # ask: server is in tools but tool is not in allowedTools
                continue

            # Unknown tools — skip
            skipped.append(rule)

    # Filter out allow commands whose wildcards would override ask commands.
    # In Claude, ask rules narrow broader allow rules (e.g. allow "git push *"
    # + ask "git push --force *" means --force requires confirmation).
    # Kiro's allowedCommands has no such override, so we must remove the
    # broad allow pattern to prevent it from bypassing the ask intent.
    if ask_commands and allowed_commands:
        filtered_allowed = []
        for allow_cmd in allowed_commands:
            covers_ask = any(
                fnmatch.fnmatch(ask_cmd, allow_cmd)
                for ask_cmd in ask_commands
            )
            if not covers_ask:
                filtered_allowed.append(allow_cmd)
        allowed_commands = filtered_allowed

    return build_kiro_config(
        tools=tools,
        allowed_tools=allowed_tools,
        allowed_commands=allowed_commands,
        denied_commands=denied_commands,
        write_allowed_paths=write_allowed_paths,
        mcp_servers=mcp_servers,
        mcp_allowed=mcp_allowed,
        skipped=skipped,
        agent_name=agent_name,
        description=description,
    )


def build_kiro_config(
    tools, allowed_tools, allowed_commands, denied_commands,
    write_allowed_paths, mcp_servers, mcp_allowed, skipped,
    agent_name, description,
):
    """Assemble the final Kiro agent JSON structure."""
    config = {
        "name": agent_name,
        "description": description,
    }

    # Build tools array
    tools_list = sorted(tools)
    for server in sorted(mcp_servers):
        tools_list.append(f"@{server}")
    config["tools"] = tools_list

    # Build allowedTools
    all_allowed = list(allowed_tools)
    all_allowed.extend(mcp_allowed)
    if all_allowed:
        config["allowedTools"] = sorted(set(all_allowed))

    # Build toolsSettings
    tools_settings = {}

    if write_allowed_paths:
        # Deduplicate while preserving order
        paths = list(dict.fromkeys(write_allowed_paths))
        tools_settings["write"] = {"allowedPaths": paths}

    # Only emit shell settings if shell is in tools (i.e. has allow/ask rules)
    if "shell" in tools:
        shell_settings = {}
        if allowed_commands:
            shell_settings["allowedCommands"] = list(dict.fromkeys(allowed_commands))
        if denied_commands:
            shell_settings["deniedCommands"] = list(dict.fromkeys(denied_commands))
        if shell_settings:
            tools_settings["shell"] = shell_settings

    if tools_settings:
        config["toolsSettings"] = tools_settings

    # Add skipped rules as metadata (informational, ignored by Kiro)
    if skipped:
        config["_skippedClaudeRules"] = sorted(set(skipped))

    return config


def format_output(config, fmt="json"):
    """Format the config as JSON (pretty-printed)."""
    return json.dumps(config, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(
        description="Translate Claude Code permissions to Kiro agent configuration"
    )
    parser.add_argument(
        "--agent-name",
        default="translated-agent",
        help="Name for the Kiro agent (default: translated-agent)",
    )
    parser.add_argument(
        "--description",
        default="Translated from Claude Code settings",
        help="Description for the Kiro agent",
    )
    parser.add_argument(
        "--scope",
        choices=["global", "project", "all"],
        default="all",
        help="Which settings to read: global, project, or all (default: all)",
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--input",
        help="Path to a Claude settings JSON file (instead of auto-detection)",
    )

    args = parser.parse_args()

    permissions = load_claude_settings(args.scope, args.input)

    total_rules = sum(len(v) for v in permissions.values())
    if total_rules == 0:
        print("No permission rules found.", file=sys.stderr)
        sys.exit(1)

    config = translate_to_kiro(permissions, args.agent_name, args.description)
    print(format_output(config, args.format))


if __name__ == "__main__":
    main()
