---
name: skill-lint
description: >
  Checks Claude Code skills against official best practices and reports violations.
  Triggers on "skill-lint", "スキルチェック", "lint skill", "ベストプラクティスチェック",
  or requests to validate skill structure, naming, or quality.
---

# Skill Lint

Validate skills against [The Complete Guide to Building Skills for Claude](https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf).

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

## Checks

### Frontmatter

| Check | Severity | Description |
|-------|----------|-------------|
| `frontmatter-xml` | ERROR | XML angle brackets (`< >`) in frontmatter (injection risk) |
| `name-missing` | ERROR | name field is missing |
| `name-length` | ERROR | name exceeds 64 chars |
| `name-format` | WARN | name is not lowercase/digits/hyphens |
| `name-reserved` | ERROR | name contains "claude" or "anthropic" |
| `name-mismatch` | WARN | name doesn't match directory name |
| `description-missing` | ERROR | description field is missing |
| `description-length` | ERROR | description exceeds 1024 chars |
| `description-xml` | ERROR | XML angle brackets in description |
| `description-vague` | WARN | description too generic (e.g. "Helps with projects") |
| `description-short` | WARN | description under 30 chars |
| `description-no-triggers` | WARN | description lacks trigger conditions |
| `compatibility-length` | WARN | compatibility exceeds 500 chars |

### Body Content

| Check | Severity | Description |
|-------|----------|-------------|
| `body-length` | ERROR/INFO | Body exceeds 500 lines (ERROR) or 300 lines (INFO) |
| `body-word-count` | WARN | Body exceeds 5,000 words |
| `broken-reference` | ERROR | Referenced file does not exist |
| `stale-date` | WARN | Body contains date patterns that may become stale |
| `nested-reference` | WARN | Reference file links to other references |
| `no-examples` | INFO | No examples section found |
| `no-troubleshooting` | INFO | No troubleshooting/error handling section |

### Structure

| Check | Severity | Description |
|-------|----------|-------------|
| `readme-in-skill` | WARN | README.md found inside skill folder |
| `no-checklist` | WARN | Multi-step workflow without progress checklist |
| `no-toc` | INFO | Long reference file (100+ lines) without TOC |
| `windows-path` | WARN | Windows-style paths detected |
| `ambiguous-filename` | INFO | Generic filename (helper, utils, misc, etc.) |

### Scripts

| Check | Severity | Description |
|-------|----------|-------------|
| `magic-number` | INFO | Argparse default without named constant |
| `silent-exception` | WARN | Exception swallowed with pass/continue |
| `no-error-handling` | INFO | No try/except in 50+ line script |
| `no-set-e` | INFO | Shell script without `set -e` |

## Examples

User: 「スキルチェックして」
→ カレントディレクトリの `skills/` を対象にスクリプトを実行し、結果を報告。

User: "lint skill suggest-permissions"
→ `skills/suggest-permissions/` を対象にスクリプトを実行し、指摘ごとに修正案を提示。

## Troubleshooting

### スクリプトが見つからない

Base directory からの絶対パスが間違っている。スキルの展開先を確認する。

### 全チェック通過しているのに品質が低い

Lint は構造とメタデータのみをチェックする。指示の具体性や workflow の妥当性は手動レビューが必要。

## Severity Levels

| Level | Meaning |
|-------|---------|
| ERROR | Clear best practices violation (missing frontmatter, security issue) |
| WARN | Non-compliance with recommendations (vague description, README in skill) |
| INFO | Improvement suggestion (add examples, add TOC) |

## Interpreting Results

Present findings grouped by skill. For each finding, explain the issue and suggest a fix.
If no issues found, confirm the skill passes all checks.
