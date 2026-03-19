---
name: suggest-permissions
description: >
  Suggest permission auto-approval rules based on session history with risk assessment.
  Use when the user says "suggest-permissions", "自動承認", "許可ルール",
  "allow rules", "permission suggestions", or wants to optimize tool approval settings.
  Also handles "consolidate", "共通化", "グローバルに集約", "共通ルール" for
  extracting common rules across multiple ghq-managed repositories.
  Also handles "review", "レビュー", "監査", "audit", "危険な設定" for
  auditing existing permission settings for dangerous configurations.
argument-hint: "[--project <name>] [--days <N>] [--tool <name>] [--min-count <N>] [--consolidate <ghq-prefix>...] [--review [global|project|all]]"
allowed-tools: Bash(python3 *suggest-permissions.py:*), Bash(python3 ~/.claude/plugins/cache/ikeisuke-skills/tools/*/skills/suggest-permissions/*), Bash(ghq *)
---

# Suggest Permissions

Analyze tool usage from session history and suggest `permissions.allow` rules.

## モード判定

ユーザーの指示に応じて適切なモードを選択する:

| ユーザーの意図 | モード | 判定キーワード |
|---------------|--------|---------------|
| セッション履歴から新しいルールを提案してほしい | **通常モード** (Step 1〜3) | `suggest-permissions`, `自動承認`, `許可ルール`, `allow rules` |
| 複数リポジトリの共通ルールをグローバルに集約したい | **Consolidate モード** (Step C1〜C3) | `consolidate`, `共通化`, `グローバルに集約`, `共通ルール`, ghq prefix の指定 |
| 既存設定の安全性を監査したい | **Review モード** (Step R1〜R2) | `review`, `レビュー`, `監査`, `audit`, `危険な設定` |

## Step 1: Collect usage data

Run the script to collect tool usage patterns. **絶対パスで実行すること**（`cd` + 相対パスだと allow ルールにマッチしない）。

```bash
python3 /path/to/skills/suggest-permissions/scripts/suggest-permissions.py [OPTIONS]
```

スキルの Base directory からスクリプトの絶対パスを組み立てる。

### --project のデフォルト

ユーザーが `--project` を明示していない場合、カレントディレクトリのリポジトリ名を自動で `--project` に渡す：

```bash
# リポジトリ名を取得
git rev-parse --show-toplevel  # → basename を --project に使用
```

全プロジェクト横断で集計したい場合はユーザーが `--project all` を明示する。
`--project all` が指定された場合は `--project` を付けずにスクリプトを実行する。

Options:

| Flag | Description | Default |
|------|-------------|---------|
| `--project <name>` | Project name filter (substring) | Current repo name |
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
- **MED**: `sed`, `awk`, `chmod`
- **HIGH**: `rm`, `cp`, `mv`, `rsync`, `git push`, `git reset --hard`, `git clean`, `gh pr create/merge/close`, `docker`, `kubectl`, `terraform`, `aws`, `sudo`, `ssh`, `kill`

### Never auto-allow（allow に入れてはいけないもの）

以下は使用頻度に関係なく `allow` に含めてはならない。`ask` または未設定（デフォルト確認）にすること。

**スクリプトインタプリタ** — 任意コード実行が可能:
- `node`, `python3`, `python`, `ruby`, `perl`, `bash`, `sh`, `deno`, `bun`

**シェル制御構文** — 任意コマンドのラッパーであり、中身の危険度を継承する:
- `for`, `if`, `while`, `case`, `eval`

**ファイル操作（スコープ限定なしの場合）** — プロジェクト外のファイルを上書き・削除するリスク:
- `cp`, `mv`, `rsync`（スコープを限定できる場合は個別ルールで対応。例: `\rm /tmp/*`）

これらがスクリプト出力に現れた場合は、自動的に ask を推奨し、allow には含めないこと。

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

### Variable assignment commands

`VAR=$(command ...)` 形式のコマンドはパーミッションルールの `Bash(...)` 構文と括弧が衝突するため、ルールとして記述できない。
スクリプトは `$()` 内のコマンドを自動的に抽出してルール候補にする（例: `TMPFILE=$(mktemp /tmp/foo.XXXXX)` → `Bash(mktemp *)`）。

変数代入で始まるコマンドは個別ルールではカバーされないため、都度確認となる。

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

### 設定ファイルの振り分け

ルールを **グローバル** (`~/.claude/settings.local.json`) と **プロジェクト** (`.claude/settings.local.json`) に振り分けて出力すること。

| 振り分け基準 | 設定先 | 例 |
|-------------|--------|-----|
| どのプロジェクトでも使う汎用コマンド | グローバル | `Bash(ls:*)`, `Bash(git status *)`, `Glob`, `Grep` |
| プロジェクト固有のスクリプト・ツール | プロジェクト | `Bash(npm run *)`, `Bash(cargo *)`, `Bash(bin/*)` |
| プロジェクト固有のパス指定 | プロジェクト | `Bash(docs/aidlc/bin/*)`, `Read(/**)`  |
| ファイルツール（スコープ付き） | スコープによる | `Read(///tmp/**)` → グローバル、`Edit(/**)`(プロジェクト相対) → プロジェクト |
| MCP ツール | プロジェクト | `mcp__codex__codex` |

既存のグローバル/プロジェクト設定がある場合はそれぞれ読み込んで、重複を除外すること。

### 出力フォーマット

JSON スニペットを設定先ごとに分けて出力する：

**グローバル** (`~/.claude/settings.local.json`):
```json
{
  "permissions": {
    "deny": [],
    "ask": ["Bash(git push --force *)", "Bash(rm *)"],
    "allow": [
      "Glob",
      "Grep",
      "Bash(ls:*)",
      "Bash(git status *)",
      "Bash(git branch *)"
    ]
  }
}
```

**プロジェクト** (`.claude/settings.local.json`):
```json
{
  "permissions": {
    "allow": [
      "Bash(npm run *)",
      "Bash(bin/*)",
      "mcp__codex__codex"
    ]
  }
}
```

## Step C1: 共通ルールデータの収集（Consolidate モード）

ghq 管理下の複数リポジトリから共通の許可ルールを抽出する。**絶対パスで実行すること**。

```bash
python3 /path/to/skills/suggest-permissions/scripts/suggest-permissions.py --consolidate <ghq-prefix> [OPTIONS]
```

スキルの Base directory からスクリプトの絶対パスを組み立てる。

### ghq prefix の決定

ユーザーが prefix を明示していない場合、カレントリポジトリの org/ユーザー名を自動で使用する:

```bash
# ghq prefix を取得（例: github.com/ikeisuke）
ghq list --exact $(git remote get-url origin | sed 's|.*://[^/]*/||;s|\.git$||') | head -1 | sed 's|/[^/]*$||'
```

ユーザーが org 名やユーザー名を指定した場合はそれをそのまま `--consolidate` に渡す。

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--consolidate` | ghq prefix。org名、ユーザー名、`github.com/org` など。複数指定可 | — |
| `--min-repos` | 共通とみなす最低リポジトリ数 | 2 |
| `--format` | `table` or `json` | table |

## Step C2: 共通ルールの評価

スクリプト出力を分析し、以下の観点でルールを評価する:

1. **汎用性**: 本当にどのプロジェクトでも使うルールか？（`Bash(git add:*)` → 汎用、`Bash(docs/aidlc/bin/*)` → 特定ワークフロー依存）
2. **never-auto-allow**: `[!!]` マークのルールはグローバルに昇格しない
3. **リスク評価**: 通常モードの Step 2 と同じリスク基準を適用

### 出力の見方

- **Common project rules** テーブル: 共通ルール一覧。`REPOS` 列は「該当リポ数/全リポ数」
- **Suggested global additions**: グローバルに追加すべきルール（never-allow 除外済み）
- **After adding to global, removable from project settings**: 昇格後にプロジェクト側から削除できるルール

## Step C3: 推奨の提示

通常モードの Step 3 の「設定ファイルの振り分け」基準に従い、結果を提示する:

1. **グローバルに昇格すべきルール** — `~/.claude/settings.local.json` に追加する JSON スニペット
2. **プロジェクトから削除可能なルール** — リポジトリごとに削除できるルールの一覧
3. **グローバル昇格すべきでないルール** — プロジェクト固有のままにすべき理由を付記

### 注意

- セッション履歴解析（通常モード）とは排他。`--consolidate` 指定時は `--project`, `--days` 等は無視される
- read-only: 設定ファイルの書き換えは行わない。出力を元にユーザーが手動で設定を更新する
- `docs/aidlc/bin/*` のようなプロジェクト相対パスのルールは、全リポジトリで同じパス構造を持つ場合のみ共通化が有効

## Step R1: 既存設定の監査（Review モード）

既存のパーミッション設定（allow/ask/deny）を解析し、危険な構成を検出する。**絶対パスで実行すること**。

```bash
python3 /path/to/skills/suggest-permissions/scripts/suggest-permissions.py --review [SCOPE] [--format table|json]
```

スキルの Base directory からスクリプトの絶対パスを組み立てる。

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--review` | 監査スコープ: `global`（グローバルのみ）, `project`（プロジェクトのみ）, `all`（両方） | all |
| `--format` | `table` or `json` | table |

`--project`, `--days`, `--session` 等の通常モードオプションは Review モードでは無視される。

### 検出カテゴリと重要度

| 重要度 | カテゴリ | 検出内容 |
|--------|---------|---------|
| CRITICAL | never-allow-violation | スクリプトインタプリタ・シェル制御構文が allow にある（任意コード実行） |
| HIGH | destructive-in-allow | 破壊的コマンド（rm, sudo, kill 等）が allow にある |
| HIGH | sensitive-path-allowed | 機密パス（.ssh, .aws, .env 等）への Read/Edit/Write が allow にある |
| MED | wildcard-overmatch | ワイルドカードルールが危険フラグをカバーし、deny/ask ガードがない |
| MED | overly-broad | スコープなしの Edit/Write（任意ファイル変更可能） |
| LOW | missing-protection | 推奨 deny ルール（.env, .ssh 等）が未設定 |
| INFO | scoped-interpreter | スコープ付きインタプリタ（特定パス限定）— 信頼確認推奨 |
| INFO | sensitive-path-guarded | 機密パスが allow にあるが deny でオーバーライドされている |

### deny/ask によるガード判定

allow ルールが危険でも、対応する deny/ask ルールが存在すれば重要度が下がる（deny は allow より優先されるため）。例:

- `Bash(git push *)` が allow にあっても `Bash(git push --force *)` が ask にあれば、`--force` のワイルドカードオーバーマッチは検出されない
- `Read(~/.ssh/**)` が allow にあっても同じルールが deny にあれば INFO に降格

## Step R2: 結果評価と推奨の提示

スクリプト出力の findings を確認し、重要度別に対処を提案する:

1. **CRITICAL** — 即時対応が必要。allow から削除するか ask に移動。具体的な JSON スニペットを提示
2. **HIGH** — 対応を強く推奨。deny/ask への移動またはスコープの限定を提案
3. **MED** — トレードオフを説明し、ユーザーに判断を委ねる。deny/ask ガードの追加を提案
4. **LOW** — 推奨事項として提示。対応は任意
5. **INFO** — 情報提供のみ。適切に設定されている項目や確認推奨の項目

### 注意

- Review モードは read-only: 設定ファイルの書き換えは行わない
- `--review project` はプロジェクトの `.claude/` ディレクトリのみを対象とし、グローバル設定の deny/ask によるガードは考慮しない
- `--review all` はグローバルとプロジェクトの両方を対象とし、deny/ask のガードも統合して判定する

## Permissions

このスキルは以下のツールを自動承認して使用します:

- `Bash(python3 *suggest-permissions.py:*)` — 分析スクリプトの実行
- `Bash(python3 ~/.claude/plugins/cache/ikeisuke-skills/tools/*/skills/suggest-permissions/*)` — プラグインキャッシュ経由での実行
- `Bash(ghq *)` — ghq コマンド（consolidate モードでリポジトリ列挙に使用）

スクリプトは `~/.claude/projects/` 配下のセッション履歴（JSONL）および各リポジトリの `.claude/settings*.json` を**読み取り専用**で解析します。ファイルの書き換えや外部通信は行いません。
