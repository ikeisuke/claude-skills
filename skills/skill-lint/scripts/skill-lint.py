#!/usr/bin/env python3
"""Check Claude Code skills against official best practices.

Based on "The Complete Guide to Building Skills for Claude" by Anthropic.
"""

import argparse
import json
import re
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Lint Claude Code skills against best practices")
    parser.add_argument("target", help="Skill directory or parent directory containing multiple skills")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    return parser.parse_args()


def parse_frontmatter(skill_md_path):
    """Parse YAML frontmatter from SKILL.md. Returns (frontmatter_dict, body_text, raw_frontmatter, error)."""
    try:
        text = Path(skill_md_path).read_text(encoding="utf-8")
    except OSError as e:
        return None, None, None, str(e)

    if not text.startswith("---"):
        return None, text, None, "Missing YAML frontmatter"

    end = text.find("---", 3)
    if end == -1:
        return None, text, None, "Unclosed YAML frontmatter"

    fm_text = text[3:end].strip()
    body = text[end + 3:].strip()

    # Simple YAML parser for name/description (avoid PyYAML dependency)
    fm = {}
    current_key = None
    current_val_lines = []

    for line in fm_text.split("\n"):
        m = re.match(r"^(\w[\w-]*):\s*(.*)", line)
        if m:
            if current_key:
                fm[current_key] = " ".join(current_val_lines).strip()
            current_key = m.group(1)
            val = m.group(2).strip()
            # Handle > (folded block scalar)
            if val == ">":
                current_val_lines = []
            else:
                current_val_lines = [val]
        elif current_key and line.startswith("  "):
            current_val_lines.append(line.strip())
    if current_key:
        fm[current_key] = " ".join(current_val_lines).strip()

    return fm, body, fm_text, None


def find_skills(target):
    """Find skill directories (containing SKILL.md) under target."""
    target = Path(target)
    if (target / "SKILL.md").exists():
        return [target]

    skills = []
    for child in sorted(target.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            skills.append(child)
    return skills


def make_finding(severity, check, message):
    return {"severity": severity, "check": check, "message": message}


# --- Check functions ---

def check_frontmatter(fm, fm_raw, skill_dir):
    """Check YAML frontmatter fields."""
    findings = []
    if fm is None:
        findings.append(make_finding("ERROR", "frontmatter", "Missing or invalid YAML frontmatter"))
        return findings

    # Security: XML angle brackets in frontmatter (guide p.11, 31)
    # Exclude YAML block scalar indicators (> at end of key: value line)
    if fm_raw:
        fm_no_scalars = re.sub(r":\s*>[+-]?\s*$", ": ", fm_raw, flags=re.MULTILINE)
        if re.search(r"[<>]", fm_no_scalars):
            findings.append(make_finding("ERROR", "frontmatter-xml",
                "Frontmatter contains XML angle brackets (< >) — forbidden for security (injection risk)"))

    # name
    name = fm.get("name", "")
    if not name:
        findings.append(make_finding("ERROR", "name-missing", "name field is missing"))
    else:
        if len(name) > 64:
            findings.append(make_finding("ERROR", "name-length", f"name is {len(name)} chars (max 64)"))
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
            findings.append(make_finding("WARN", "name-format", f"name '{name}' should be lowercase/digits/hyphens only"))
        if re.search(r"(anthropic|claude)", name, re.IGNORECASE):
            findings.append(make_finding("ERROR", "name-reserved", f"name '{name}' contains reserved word"))
        # Check name matches directory name
        dir_name = skill_dir.name
        if name != dir_name:
            findings.append(make_finding("WARN", "name-mismatch", f"name '{name}' doesn't match directory '{dir_name}'"))

    # description
    desc = fm.get("description", "")
    if not desc:
        findings.append(make_finding("ERROR", "description-missing", "description field is missing"))
    else:
        if len(desc) > 1024:
            findings.append(make_finding("ERROR", "description-length", f"description is {len(desc)} chars (max 1024)"))

        # XML angle brackets in description
        if re.search(r"[<>]", desc):
            findings.append(make_finding("ERROR", "description-xml",
                "description contains XML angle brackets (< >) — forbidden for security"))

        # Vague description patterns (guide p.12)
        vague_patterns = [
            r"^Helps with \w+\.$",
            r"^Does things\.?$",
            r"^A? ?skill for \w+\.?$",
            r"^Handles \w+\.?$",
        ]
        for pat in vague_patterns:
            if re.match(pat, desc, re.IGNORECASE):
                findings.append(make_finding("WARN", "description-vague",
                    "description is too vague — be specific about what it does and when to use it"))
                break

        # Short description likely too generic
        if len(desc) < 30:
            findings.append(make_finding("WARN", "description-short",
                f"description is only {len(desc)} chars — include what it does, when to use, and trigger phrases"))

        # Check for what + when (guide p.10-11)
        # Guide recommends: [What it does] + [When to use it] + [Key capabilities]
        has_what = len(desc) > 20  # minimal description
        trigger_patterns = r"(Use when|Trigger|trigger|When .* (says|asks|mentions|uploads|requests)|言|時|とき|場合|Triggers on)"
        has_when = bool(re.search(trigger_patterns, desc, re.IGNORECASE))
        if has_what and not has_when:
            findings.append(make_finding("WARN", "description-no-triggers",
                "description explains what the skill does but lacks trigger conditions — "
                "add 'Use when user says/asks/mentions...' or 'Triggers on ...'"))

    # compatibility (guide p.11)
    compat = fm.get("compatibility", "")
    if compat and len(compat) > 500:
        findings.append(make_finding("WARN", "compatibility-length",
            f"compatibility is {len(compat)} chars (max 500)"))

    return findings


def check_body(body, skill_dir):
    """Check SKILL.md body content."""
    findings = []
    if body is None:
        return findings

    lines = body.split("\n")
    line_count = len(lines)

    # Line count checks
    if line_count > 500:
        findings.append(make_finding("ERROR", "body-length",
            f"SKILL.md body is {line_count} lines (max 500). Split into references/"))
    elif line_count > 300:
        findings.append(make_finding("INFO", "body-length",
            f"SKILL.md body is {line_count} lines. Consider splitting detailed content into references/"))

    # Word count check (guide p.27: keep under 5,000 words)
    word_count = len(body.split())
    if word_count > 5000:
        findings.append(make_finding("WARN", "body-word-count",
            f"SKILL.md body is {word_count} words (recommended max 5,000). Move detailed docs to references/"))

    # Check reference links point to existing files
    ref_pattern = re.findall(r"\[.*?\]\(((?:references|scripts|assets)/[^\)]+)\)", body)
    for ref_path in ref_pattern:
        full_path = skill_dir / ref_path
        if not full_path.exists():
            findings.append(make_finding("ERROR", "broken-reference",
                f"Referenced file does not exist: {ref_path}"))

    # Check for time-sensitive information (dates)
    date_patterns = re.findall(r"\b(202[0-9]-[0-1][0-9]-[0-3][0-9]|as of 202[0-9]|updated on)\b", body, re.IGNORECASE)
    if date_patterns:
        findings.append(make_finding("WARN", "stale-date",
            f"Body contains date pattern(s) that may become stale: {', '.join(date_patterns[:3])}"))

    # Check for nested references (references linking to other references)
    refs_dir = skill_dir / "references"
    if refs_dir.exists():
        for ref_file in refs_dir.iterdir():
            if ref_file.suffix == ".md":
                try:
                    ref_text = ref_file.read_text(encoding="utf-8")
                    nested = re.findall(r"\[.*?\]\((references/[^\)]+)\)", ref_text)
                    if nested:
                        findings.append(make_finding("WARN", "nested-reference",
                            f"{ref_file.name} links to other references (keep 1 level deep): {', '.join(nested[:3])}"))
                except OSError as e:
                    print(f"warning: {e}", file=sys.stderr)

    # Check for examples section (guide p.12: recommended structure)
    has_examples = bool(re.search(r"^#{1,3}\s*(Examples?|使用例|サンプル)", body, re.MULTILINE | re.IGNORECASE))
    if not has_examples and line_count > 30:
        findings.append(make_finding("INFO", "no-examples",
            "No examples section found — add usage examples to help Claude follow the workflow"))

    # Check for error handling / troubleshooting section (guide p.12-13)
    has_troubleshooting = bool(re.search(
        r"^#{1,3}\s*(Troubleshoot|Error|Common Issues|トラブル|エラー|注意事項)",
        body, re.MULTILINE | re.IGNORECASE))
    if not has_troubleshooting and line_count > 50:
        findings.append(make_finding("INFO", "no-troubleshooting",
            "No troubleshooting/error handling section found — document common issues and solutions"))

    return findings


def check_scripts(skill_dir):
    """Check script quality."""
    findings = []
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.exists():
        return findings

    for script_file in sorted(scripts_dir.iterdir()):
        if script_file.suffix not in (".py", ".sh", ".bash"):
            continue
        try:
            text = script_file.read_text(encoding="utf-8")
        except OSError as e:
            print(f"warning: {e}", file=sys.stderr)
            continue

        rel_name = f"scripts/{script_file.name}"

        if script_file.suffix == ".py":
            # Check for magic numbers in argparse defaults
            magic_defaults = re.findall(r"default=(\d+)", text)
            # Filter: only flag if there's no constant reference nearby
            for val in magic_defaults:
                # Check if value is defined as a named constant
                const_pattern = re.compile(rf"\b[A-Z_]+\s*=\s*{val}\b")
                if not const_pattern.search(text):
                    findings.append(make_finding("INFO", "magic-number",
                        f"{rel_name}: argparse default={val} — consider using a named constant with comment"))
                    break  # One finding per file is enough

            # Check for bare except or silently swallowed exceptions
            bare_except = re.findall(r"except.*:\s*\n\s*(pass|continue)\s*$", text, re.MULTILINE)
            if bare_except:
                findings.append(make_finding("WARN", "silent-exception",
                    f"{rel_name}: Exception silently swallowed (pass/continue) — consider logging or counting"))

            # Check for error handling existence (try/except)
            if "try:" not in text and len(text.splitlines()) > 50:
                findings.append(make_finding("INFO", "no-error-handling",
                    f"{rel_name}: No try/except found in {len(text.splitlines())} line script"))

        if script_file.suffix in (".sh", ".bash"):
            # Check for set -e
            if "set -e" not in text and len(text.splitlines()) > 20:
                findings.append(make_finding("INFO", "no-set-e",
                    f"{rel_name}: Consider adding 'set -e' for error handling"))

    return findings


def check_structure(body, skill_dir):
    """Check structural best practices."""
    findings = []
    if body is None:
        return findings

    # Check for README.md inside skill folder (guide p.10: no README.md)
    readme = skill_dir / "README.md"
    if readme.exists():
        findings.append(make_finding("WARN", "readme-in-skill",
            "README.md found inside skill folder — all docs should go in SKILL.md or references/"))

    # Check for multi-step workflows without checklists
    step_headers = re.findall(r"^##\s+Step\s+", body, re.MULTILINE)
    if len(step_headers) >= 2:
        if "- [ ]" not in body:
            findings.append(make_finding("WARN", "no-checklist",
                f"Multi-step workflow ({len(step_headers)} steps) has no checklist for progress tracking"))

    # Check long reference files for TOC
    refs_dir = skill_dir / "references"
    if refs_dir.exists():
        for ref_file in sorted(refs_dir.iterdir()):
            if ref_file.suffix == ".md":
                try:
                    ref_text = ref_file.read_text(encoding="utf-8")
                    ref_lines = len(ref_text.splitlines())
                    if ref_lines > 100:
                        # Check for TOC (links to headers)
                        has_toc = bool(re.search(r"\[.*\]\(#", ref_text))
                        if not has_toc:
                            findings.append(make_finding("INFO", "no-toc",
                                f"references/{ref_file.name} is {ref_lines} lines — consider adding a table of contents"))
                except OSError as e:
                    print(f"warning: {e}", file=sys.stderr)

    # Check for Windows-style paths
    if "\\" in body and re.search(r"[A-Z]:\\", body):
        findings.append(make_finding("WARN", "windows-path",
            "Body contains Windows-style paths (use forward slashes)"))

    # Check for ambiguous resource file names
    for subdir_name in ("scripts", "references", "assets"):
        subdir = skill_dir / subdir_name
        if subdir.exists():
            for f in subdir.iterdir():
                if f.stem.lower() in ("helper", "helpers", "utils", "utility", "utilities", "misc", "common", "shared"):
                    findings.append(make_finding("INFO", "ambiguous-filename",
                        f"{subdir_name}/{f.name}: Consider a more descriptive filename"))

    return findings


def lint_skill(skill_dir):
    """Run all checks on a single skill. Returns list of findings."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return [make_finding("ERROR", "no-skill-md", "SKILL.md not found")]

    fm, body, fm_raw, fm_error = parse_frontmatter(skill_md)

    findings = []
    if fm_error and fm is None:
        findings.append(make_finding("ERROR", "frontmatter-parse", fm_error))
    else:
        findings.extend(check_frontmatter(fm, fm_raw, skill_dir))

    findings.extend(check_body(body, skill_dir))
    findings.extend(check_scripts(skill_dir))
    findings.extend(check_structure(body, skill_dir))

    return findings


def main():
    args = parse_args()
    target = Path(args.target).resolve()

    if not target.exists():
        print(f"Error: {target} does not exist", file=sys.stderr)
        sys.exit(1)

    skills = find_skills(target)
    if not skills:
        print(f"Error: No skills found in {target}", file=sys.stderr)
        sys.exit(1)

    severity_order = ["ERROR", "WARN", "INFO"]
    all_results = {}

    for skill_dir in skills:
        findings = lint_skill(skill_dir)
        findings.sort(key=lambda f: severity_order.index(f["severity"]))
        all_results[skill_dir.name] = findings

    if args.format == "json":
        print(json.dumps(all_results, indent=2, ensure_ascii=False))
        return

    # Table format
    print("Skill Lint Report:\n")
    total_skills = len(all_results)
    total_counts = {s: 0 for s in severity_order}

    for skill_name, findings in all_results.items():
        print(f"{skill_name}/")
        if not findings:
            print("  OK    All checks passed\n")
            continue
        for f in findings:
            sev = f["severity"]
            total_counts[sev] += 1
            print(f"  {sev:<6} {f['check']:<25} {f['message']}")
        print()

    # Summary
    parts = [f"{total_skills} skill(s) checked"]
    for sev in severity_order:
        if total_counts[sev]:
            parts.append(f"{total_counts[sev]} {sev.lower()}(s)")
    print(f"Summary: {', '.join(parts)}")


if __name__ == "__main__":
    main()
