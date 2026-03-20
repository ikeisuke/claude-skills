# Claude Code → Kiro マッピングルール

## ツール対応表

| Claude ルール | Kiro `tools` | `allowedTools` | `toolsSettings` | 備考 |
|---|---|---|---|---|
| `Glob` | `read` | — | — | 暗黙的に read に含まれる |
| `Grep` | `read` | — | — | 暗黙的に read に含まれる |
| `Read(path)` | `read` | — | — | Kiro は read に allowedPaths なし |
| `Edit(path)` | `write` | — | `write.allowedPaths` | |
| `Write(path)` | `write` | — | `write.allowedPaths` | |
| `Bash(cmd)` | `shell` | — | `shell.allowedCommands` / `deniedCommands` | |
| `mcp__srv__tool` | `@srv` | `@srv/tool` | — | MCP サーバー定義は手動追加が必要 |
| `WebSearch` | — | — | — | スキップ |
| `WebFetch` | — | — | — | スキップ |
| `Agent` | — | — | — | スキップ |
| `Skill(name)` | — | — | — | スキップ（Kiro は resources で管理） |

## allow / deny / ask の対応

| Claude カテゴリ | Kiro の扱い |
|---|---|
| `allow` | `tools` + `allowedTools`（自動承認） |
| `deny` | Bash → `shell.deniedCommands`、ファイル系 → スキップ |
| `ask` | `tools` に含めるが `allowedTools` には含めない |

## パターン変換ルール

### Bash パターン

- `git add:*` → `git add *` — コロン区切りをスペースに変換
- `git status *` → `git status *` — そのまま
- `\\rm file` → `\\rm file` — エスケープはそのまま保持

### ファイルパス

- `/**` → `**` — 先頭の `/` を除去（プロジェクト相対）
- `/src/**` → `src/**` — 同上
- `///tmp/**` → `/tmp/**` — 三重スラッシュ → 絶対パス
- `~/.ssh/**` → スキップ — ホームディレクトリ相対は変換不可

### MCP ツール名

- `mcp__serverName__toolName` → `@serverName/toolName`
- MCP サーバーの `mcpServers` 定義（command, args, env）は自動生成不可。手動で追加が必要。

## エッジケース

- **deny のファイルルール**: Kiro に `deniedPaths` は存在しない。`Read(.env)` の deny は変換不可。
- **home パスの deny**: `Read(~/.ssh/**)` は Kiro に対応なし。エージェントプロンプトで制限を記述する運用を推奨。
- **重複パス**: 複数の Write/Edit ルールのパスは `allowedPaths` 配列に統合・重複除去。
- **MCP サーバー設定**: ツール参照（`@server/tool`）のみ生成。サーバー起動設定は別途必要。
