---
name: suggest-permissions
description: >
  Suggest permission auto-approval rules based on session history with risk assessment.
  Use when the user says "suggest-permissions", "自動承認", "許可ルール",
  "allow rules", "permission suggestions", or wants to optimize tool approval settings.
argument-hint: "[--project <name>] [--days <N>] [--tool <name>] [--min-count <N>]"
allowed-tools: Bash(python3 *suggest-permissions.py:*)
---

# Suggest Permissions

Analyze tool usage from session history and suggest `permissions.allow` rules.

## Step 1: Collect usage data

Run the script to collect tool usage patterns. Pass user arguments directly.

```bash
python3 skills/suggest-permissions/scripts/suggest-permissions.py [OPTIONS]
```

Options:

| Flag | Description | Default |
|------|-------------|---------|
| `--project <name>` | Project name filter (substring) | All |
| `--session <id>` | Session ID filter | All |
| `--days <N>` | Look back N days | 30 |
| `--tool <name>` | Tool name filter (case-insensitive) | All |
| `--min-count <N>` | Min occurrences to suggest | 3 |
| `--format <fmt>` | `table` or `json` | table |
| `--show-all` | Include already-allowed patterns | false |

## Step 2: Evaluate risk and propose rules

After collecting the data, evaluate each suggested rule using the risk criteria below.
Present the results as a table with columns: COUNT, RISK, RULE, RATIONALE.

### Risk assessment criteria

Evaluate each rule candidate against these dimensions:

| Dimension | Question |
|-----------|----------|
| Reversibility | Can the action be undone? (undo-able = lower risk) |
| Scope of impact | Local only? Or affects remote/shared state? |
| Data safety | Can it delete, overwrite, or corrupt data? |
| Credential exposure | Could it leak secrets or tokens? |
| Network effects | Does it send data externally or modify remote systems? |

### Risk levels

| Level | Criteria | Auto-approve? |
|-------|----------|---------------|
| SAFE | Read-only, no side effects, fully reversible | Recommend |
| LOW | Minor local side effects, easily reversible, no network | Recommend |
| MED | Local modifications, build/test, reversible with effort | User decides |
| HIGH | Remote effects, data deletion, credential risk, hard to reverse | Warn |

### Well-known classifications (use directly without further analysis)

- **SAFE**: `Glob`, `Grep`, `WebSearch`, `ls`, `cat`, `head`, `tail`, `wc`, `file`, `which`, `echo`, `date`, `pwd`, `find`, `grep`, `rg`, `diff`, `tree`, `jq`, `git status`, `git log`, `git diff`, `git show`, `git blame`, `cd`
- **LOW**: `Agent`, `WebFetch`, `mkdir`, `mktemp`, `touch`, `sort`, `tar`, `curl`, `gh issue`(view/list only), `gh api`(GET only), `git tag`
- **HIGH**: `rm`, `git push`, `git reset --hard`, `git clean`, `gh pr create/merge/close`, `docker`, `kubectl`, `terraform`, `aws`, `sudo`, `ssh`, `kill`

### File tool rules (Read / Edit / Write)

ファイルツールはスコープ（どこを操作するか）でリスクが変わる。ツール単位の一括許可ではなくパス別に判断すること。

| スコープ | Read | Edit/Write | 推奨ルール |
|----------|------|------------|-----------|
| プロジェクト内 | SAFE | MED（通常許可） | `Read(/src/**)`, `Edit(/src/**)` （プロジェクト相対パス） |
| `/tmp` | SAFE | LOW | `Read(///tmp/**)`, `Write(///tmp/**)` |
| `~/.claude/` | SAFE | MED | 必要に応じて |
| それ以外（他リポジトリ、ホーム直下等） | ask を推奨 | ask を推奨 | プロジェクト外アクセスは意図確認が必要 |

スクリプト出力で `[project]` と表示されるものはプロジェクト内アクセス（cwd 配下）を意味する。
これは実際のルール構文ではないため、プロジェクト相対パスのルールに変換すること（例: `Read(/src/**)`、`Edit(/**)`）。

プロジェクト外パスへのアクセスが多いディレクトリがある場合は、そのパスを個別に `allow` に追加するかユーザーに確認すること。

```json
{
  "permissions": {
    "ask": ["Read", "Edit", "Write"],
    "allow": [
      "Read(/**)", "Read(///tmp/**)",
      "Edit(/**)", "Write(///tmp/**)",
      "Read(~/repos/github.com/myorg/**)"
    ]
  }
}
```

### Wildcard overmatch warning

`Bash(command *)` は全フラグ・引数を許可する。同一コマンドでも特定フラグで危険度が大きく変わるものがある。
このようなコマンドの場合、安全なサブコマンド/フラグだけを個別ルールにするか、ワイルドカードのリスクを明示すること。

危険フラグを持つコマンドの例:
- **`git branch`**: `--show-current`, `-v` は SAFE → `git branch -D` は HIGH（ブランチ強制削除）
- **`git checkout`**: `-b`（新規ブランチ）は LOW → `git checkout .`（変更全破棄）は HIGH
- **`git stash`**: `list`, `show` は SAFE → `drop`, `clear` は HIGH
- **`git reset`**: `--soft` は MED → `--hard` は HIGH（変更消失）
- **`rm`**: ファイル指定は MED → `-rf` は HIGH（再帰削除）
- **`gh pr`**: `list`, `view` は SAFE → `create`, `merge`, `close` は HIGH
- **`gh issue`**: `list`, `view` は SAFE → `create`, `close` は HIGH
- **`curl`/`wget`**: GET は LOW → `-X POST`, `-d` は MED〜HIGH

対処パターン（評価順: deny → ask → allow）:
1. **安全な用途だけ allow**: `Bash(git branch --show-current)`, `Bash(git branch -v *)`
2. **危険な用途を deny/ask + ワイルドカードで allow**: deny/ask は allow より優先される
3. **ワイルドカードで allow + リスクを明記**: ユーザーが承知の上で許可
4. **許可しない**: 毎回確認を求める（デフォルト動作）

`deny` は完全ブロック（実行不可）、`ask` は毎回確認を求める（ユーザーが判断）。
危険だが状況によっては使いたいコマンドには `ask` が適切。

```json
{
  "permissions": {
    "deny": ["Bash(rm -rf /*)"],
    "ask": ["Bash(git branch -D *)", "Bash(git push --force *)"],
    "allow": ["Bash(git branch *)", "Bash(git push *)"]
  }
}
```

### Rules requiring contextual judgment

These need analysis of the actual usage examples:

- **`bash`/`sh`**: Risk depends entirely on what's being executed. Check examples.
- **`Edit`/`Write`**: Generally MED, but scope matters. Editing config files or CI pipelines is riskier than source code.
- **`npm run`/`cargo test`**: Usually MED (local), but scripts could have side effects.
- **`curl`/`wget`**: LOW for reads, but POST/PUT requests are higher risk.
- **Project-specific scripts**: Check examples to understand what they do.
- **Environment-prefixed commands** (e.g., `AWS_PROFILE=... *`): Evaluate the actual command being run.

## Step 3: Present recommendations

Group rules by risk level and present:
1. **SAFE/LOW** → `allow` を推奨
2. **MED** → `allow` or `ask` をユーザー判断で提案
3. **HIGH** → `ask`（確認付き許可）or `deny`（完全ブロック）を提案。ワイルドカードで allow する場合は危険フラグを `ask`/`deny` でガードすること

Provide a ready-to-use JSON snippet for `~/.claude/settings.local.json` containing only the rules the user approves.

```json
{
  "permissions": {
    "deny": [],
    "ask": ["Bash(git push --force *)", "Bash(git branch -D *)"],
    "allow": [
      "Read",
      "Glob",
      "Grep",
      "Bash(ls *)",
      "Bash(git status *)",
      "Bash(git branch *)"
    ]
  }
}
```
