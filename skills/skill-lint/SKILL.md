---
name: skill-lint
description: >
  Checks Claude Code skills against official best practices and reports violations.
  Triggers on "skill-lint", "スキルチェック", "lint skill", "ベストプラクティスチェック",
  or requests to validate skill structure, naming, or quality.
---

# Skill Lint

Validate skills against [official best practices](https://platform.claude.com/docs/ja/agents-and-tools/agent-skills/best-practices).

## Usage

Run the lint script with the path to a skill directory or parent directory. **Use absolute path.**

```bash
python3 /path/to/skills/skill-lint/scripts/skill-lint.py <target> [OPTIONS]
```

Build the absolute path from the skill's Base directory.

| Flag | Description | Default |
|------|-------------|---------|
| `<target>` | Skill directory or parent containing multiple skills | (required) |
| `--format` | `table` or `json` | table |

### Single skill

```bash
python3 /path/to/scripts/skill-lint.py skills/suggest-permissions/
```

### All skills

```bash
python3 /path/to/scripts/skill-lint.py skills/
```

## Severity Levels

| Level | Meaning |
|-------|---------|
| ERROR | Clear best practices violation (missing frontmatter, body > 500 lines) |
| WARN | Non-compliance with recommendations (second-person description, no checklist) |
| INFO | Improvement suggestion (add TOC, descriptive filename) |

## Interpreting Results

Present findings grouped by skill. For each finding, explain the issue and suggest a fix.
If no issues found, confirm the skill passes all checks.
