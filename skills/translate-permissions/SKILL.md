---
name: translate-permissions
description: >
  Claude Code の許可設定（permissions）を Kiro CLI カスタムエージェント設定に翻訳する。
  Triggers on "translate-permissions", "Kiro変換", "kiro config", "permission to kiro",
  "Kiroエージェント", "kiro agent".
  将来的に --reverse フラグで Kiro → Claude の逆変換にも対応予定。
argument-hint: "[--agent-name <name>] [--scope global|project|all]"
allowed-tools: Bash(python3 *translate-permissions.py:*), Bash(python3 ~/.claude/plugins/cache/ikeisuke-skills/tools/*/skills/translate-permissions/*)
---

# Translate Permissions

Claude Code の許可設定を Kiro CLI カスタムエージェント設定 JSON に翻訳する。

## チェックリスト

```
タスク進捗：
- [ ] Step 1: スクリプト実行（設定読み込み＋翻訳）
- [ ] Step 2: 出力確認（スキップされたルールの説明）
- [ ] Step 3: 保存先の案内
```

## Step 1: スクリプト実行

**絶対パスで実行すること**（allow ルールにマッチさせるため）。

```bash
python3 /path/to/skills/translate-permissions/scripts/translate-permissions.py [OPTIONS]
```

スキルの Base directory からスクリプトの絶対パスを組み立てる。

### オプション

| Flag | Description | Default |
|------|-------------|---------|
| `--agent-name <name>` | Kiro エージェント名 | `translated-agent` |
| `--description <text>` | エージェント説明文 | `Translated from Claude Code settings` |
| `--scope <scope>` | 読み込み対象: `global`, `project`, `all` | `all` |
| `--input <path>` | 設定ファイルパス（自動検出の代わり） | 自動検出 |

### --agent-name のデフォルト

ユーザーが `--agent-name` を明示していない場合、カレントリポジトリ名を使用する。

## Step 2: 出力確認

出力 JSON を確認し、以下を説明する:

- `_skippedClaudeRules` に含まれるルール — Kiro に対応がないためスキップされたもの
- MCP ツール参照 (`@server/tool`) — サーバー定義 (`mcpServers`) は手動追加が必要

マッピングの詳細は [references/mapping-rules.md](references/mapping-rules.md) を参照。

## Step 3: 保存先の案内

生成された JSON の保存先をユーザーに案内する:

- **プロジェクト用**: `.kiro/agents/<agent-name>.json`
- **グローバル用**: `~/.kiro/agents/<agent-name>.json`

`_skippedClaudeRules` フィールドは情報提供用。Kiro は未知のフィールドを無視するため、そのまま保存しても問題ない。不要であれば削除を案内する。

## Permissions

このスキルは以下のツールを自動承認して使用する:

- `Bash(python3 *translate-permissions.py:*)` — 翻訳スクリプトの実行
- `Bash(python3 ~/.claude/plugins/cache/ikeisuke-skills/tools/*/skills/translate-permissions/*)` — プラグインキャッシュ経由での実行

スクリプトは `~/.claude/settings.json` および `.claude/settings*.json` を**読み取り専用**で解析する。ファイルの書き換えや外部通信は行わない。
