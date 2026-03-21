---
name: suggest-permissions
description: >
  Suggests permission auto-approval rules based on session history with risk assessment.
  Triggers on "suggest-permissions", "自動承認", "許可ルール",
  "allow rules", "permission suggestions", or requests to optimize tool approval settings.
  Also handles "consolidate", "共通化", "グローバルに集約", "共通ルール" for
  extracting common rules across multiple ghq-managed repositories.
  Also handles "review", "レビュー", "監査", "audit", "危険な設定" for
  auditing existing permission settings for dangerous configurations.
argument-hint: "[--project {name}] [--days {N}] [--tool {name}] [--min-count {N}] [--consolidate {ghq-prefix}...] [--review [global|project|all]]"
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

## 通常モード チェックリスト

このチェックリストをコピーして進行状況を追跡します：

```
タスク進捗：
- [ ] Step 1: スクリプト実行（使用データ収集）
- [ ] Step 2: リスク評価（各ルールの危険度判定）
- [ ] Step 3: 推奨提示（設定ファイル振り分け）
```

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

スクリプト出力を深く分析し、具体的な根拠に基づいてルールを評価する。
最終的に COUNT, RISK, RULE, RATIONALE のテーブルを提示する。

**参照ドキュメント**:
- [references/risk-criteria.md](references/risk-criteria.md)（リスクレベル、well-known 分類、never-auto-allow ルール）
- [references/file-tool-rules.md](references/file-tool-rules.md)（スコープ別ルール、変数代入、ワイルドカードオーバーマッチ、コンテキスト判定）

### Step 2a: 危険フラグ警告の確認

スクリプト出力に `!! Dangerous flags detected` セクションがある場合、最優先で対処する:

- 各 UNGUARDED な危険フラグに対して ask/deny ガードルールを提案する
- ルール全体が SAFE でも（例: `git push`）、特定フラグ（`--force`）でリスクが変わることを明記する

### Step 2b: 引数分布の分析

各 Bash ルールについて、スクリプト出力の `flags` / `args` / `examples` を必ず確認する:

1. **フラグ内訳を確認**: どのフラグが何回使われたか。`[!]` マーク付きは危険フラグ
2. **位置引数を確認**: 同じ引数ばかりなら、ワイルドカードよりスコープを絞れる可能性がある
3. **ユニーク例を確認**: 実際のコマンドを読んで、何をしているか理解する

### Step 2c: スコープ絞り込みの検討

ワイルドカード (`*`) 付きルールについて、より狭いルールで十分かを検討する:

- 使用の90%以上が特定パターンに該当する場合、狭いルールを提案する
- 例: `git push` が45回中40回 `origin` 宛 → `Bash(git push origin *)` を提案
- 残りのケースは手動承認で対応

**判断例**:
```
スクリプト出力:
  Bash(git push *)  count=45
    flags: -u(12), --force(3)[!], --force-with-lease(2)[!]
    args:  origin(40), main(25), feature/auth(5)

分析:
  1. 危険フラグ --force, --force-with-lease が計5回使用 → ask ガード必須
  2. 全45回が origin リモート宛 → Bash(git push origin *) に絞れる
  3. 基本リスク: HIGH（リモート影響、元に戻しにくい）
     ask ガード付き: MED に軽減

結論: allow Bash(git push origin *)
      + ask Bash(git push --force *), Bash(git push --force-with-lease *)
```

### Step 2d: リスク分類と根拠の記述

上記の分析を踏まえて、各ルールにリスクレベルと **具体的な根拠** を付ける:

- **RATIONALE には実際の使用データを引用する**（「45回中40回は origin main へのpush」等）
- Well-known 分類だけで終わらせない。フラグ/引数の分布に基づいて判断する
- ガードルールを提案する場合、セットで記述する（allow + ask のペア）

## Step 3: Present recommendations

Group rules by risk level and present:
1. **SAFE/LOW** → `allow` を推奨
2. **MED** → `allow` or `ask` をユーザー判断で提案
3. **HIGH** → `ask`（確認付き許可）or `deny`（完全ブロック）を提案。ワイルドカードで allow する場合は危険フラグを `ask`/`deny` でガードすること

### 設定ファイルの振り分け

ルールを **グローバル** (`~/.claude/settings.json`) と **プロジェクト** (`.claude/settings.local.json`) に振り分けて出力すること。

| 振り分け基準 | 設定先 | 例 |
|-------------|--------|-----|
| どのプロジェクトでも使う汎用コマンド | グローバル | `Bash(ls:*)`, `Bash(git status *)`, `WebSearch`, `WebFetch` |
| プロジェクト固有のスクリプト・ツール | プロジェクト | `Bash(npm run *)`, `Bash(cargo *)`, `Bash(bin/*)` |
| プロジェクト固有のパス指定 | プロジェクト | `Bash(docs/aidlc/bin/*)`, `Read(/**)`  |
| ファイルツール（スコープ付き） | スコープによる | `Read(///tmp/**)` → グローバル、`Edit(/**)`(プロジェクト相対) → プロジェクト |
| MCP ツール | プロジェクト | `mcp__codex__codex` |

既存のグローバル/プロジェクト設定がある場合はそれぞれ読み込んで、重複を除外すること。

### 出力フォーマット

JSON スニペットを設定先ごとに分けて出力する：

**グローバル** (`~/.claude/settings.json`):
```json
{
  "permissions": {
    "deny": [],
    "ask": ["Bash(git push --force *)", "Bash(rm *)"],
    "allow": [
      "WebSearch",
      "WebFetch",
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

## Consolidate モード チェックリスト

このチェックリストをコピーして進行状況を追跡します：

```
タスク進捗：
- [ ] Step C1: スクリプト実行（共通ルールデータ収集）
- [ ] Step C2: 共通ルールの評価（汎用性・リスク判定）
- [ ] Step C3: 推奨提示（グローバル昇格・プロジェクト削除）
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

1. **グローバルに昇格すべきルール** — `~/.claude/settings.json` に追加する JSON スニペット
2. **プロジェクトから削除可能なルール** — リポジトリごとに削除できるルールの一覧
3. **グローバル昇格すべきでないルール** — プロジェクト固有のままにすべき理由を付記

### 注意

- セッション履歴解析（通常モード）とは排他。`--consolidate` 指定時は `--project`, `--days` 等は無視される
- read-only: 設定ファイルの書き換えは行わない。出力を元にユーザーが手動で設定を更新する
- `docs/aidlc/bin/*` のようなプロジェクト相対パスのルールは、全リポジトリで同じパス構造を持つ場合のみ共通化が有効

## Review モード チェックリスト

このチェックリストをコピーして進行状況を追跡します：

```
タスク進捗：
- [ ] Step R1: スクリプト実行（既存設定の監査）
- [ ] Step R2: 結果評価と推奨の提示
```

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
| MED | ask-overrides-allow | プロジェクトの広い ask/deny ルールがグローバルの個別 allow ルールを上書きしている |
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

## Examples

User: 「自動承認ルールを提案して」
→ 通常モード。カレントリポジトリの履歴を分析し、リスク付きでルールを提案。

User: 「グローバルに共通化して」(ghq 環境)
→ Consolidate モード。複数リポジトリの共通ルールを抽出し、グローバル昇格を提案。

User: 「既存の許可設定を監査して」
→ Review モード。危険な allow ルール（任意コード実行、破壊的コマンド等）を検出。

## Troubleshooting

### セッション履歴が見つからない

`~/.claude/projects/` 配下に JSONL ファイルが必要。Claude Code を使用した履歴がないと分析できない。

### ghq が見つからない（Consolidate モード）

`ghq` コマンドが PATH に必要。`brew install ghq` 等でインストールする。

## Permissions

このスキルは以下のツールを自動承認して使用します:

- `Bash(python3 *suggest-permissions.py:*)` — 分析スクリプトの実行
- `Bash(python3 ~/.claude/plugins/cache/ikeisuke-skills/tools/*/skills/suggest-permissions/*)` — プラグインキャッシュ経由での実行
- `Bash(ghq *)` — ghq コマンド（consolidate モードでリポジトリ列挙に使用）

スクリプトは `~/.claude/projects/` 配下のセッション履歴（JSONL）および各リポジトリの `.claude/settings*.json` を**読み取り専用**で解析します。ファイルの書き換えや外部通信は行いません。
