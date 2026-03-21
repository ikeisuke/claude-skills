# Claude Code → Kiro マッピングルール

## ツール対応表

| Claude ルール | Kiro tool | `toolsSettings` キー | 備考 |
|---|---|---|---|
| `Glob` | `glob` | `glob.allowedPaths` / `deniedPaths` | |
| `Grep` | `grep` | `grep.allowedPaths` / `deniedPaths` | |
| `Read(path)` | `read` | `read.allowedPaths` / `deniedPaths` | |
| `Edit(path)` | `write` | `write.allowedPaths` / `deniedPaths` | |
| `Write(path)` | `write` | `write.allowedPaths` / `deniedPaths` | |
| `Bash(cmd)` | `shell` | `shell.allowedCommands` / `deniedCommands` | パターンは正規表現（後述） |
| `WebSearch` | `web_search` | — | 設定なし |
| `WebFetch` | `web_fetch` | `web_fetch.trusted` / `blocked` | 正規表現パターン |
| `WebFetch(domain:x)` | `web_fetch` | `web_fetch.trusted` | ドメインを正規表現に変換 |
| `Agent` | `use_subagent` | `subagent.trustedAgents` | |
| `mcp__srv__tool` | `@srv` | — | `allowedTools` に `@srv/tool` |
| `Skill(name)` | — | — | スキップ（Kiro は resources で管理） |

## allow / deny / ask の対応

| Claude カテゴリ | Kiro の扱い |
|---|---|
| `allow` | `tools` + `allowedTools` + `toolsSettings.*` で自動承認 |
| `deny` | Bash → `shell.deniedCommands`、ファイル系 → `*.deniedPaths`、WebFetch → `web_fetch.blocked` |
| `ask` | `tools` に含めるが `allowedTools`/`allowedCommands` には含めない |

## パターン変換ルール

### Bash パターン → shell コマンド正規表現

Kiro の `allowedCommands`/`deniedCommands` は **正規表現**（自動的に `\A` `\z` でアンカーされる。lookaround 不可）。
Claude のパターンは glob 形式なので変換が必要。

| Claude | Kiro | 変換ルール |
|--------|------|-----------|
| `git status *` | `git status .*` | `*` → `.*` |
| `git add:*` | `git add .*` | `:*` → ` .*` |
| `\\rm file` | `\\\\rm file` | バックスラッシュは正規表現でもエスケープが必要 |
| `ls -la` (exact) | `ls -la` | 完全一致（アンカー付き） |

### ファイルパス

| Claude | Kiro | 変換ルール |
|--------|------|-----------|
| `/**` | `**` | 先頭の `/` を除去（プロジェクト相対） |
| `/src/**` | `src/**` | 同上 |
| `///tmp/**` | `/tmp/**` | 三重スラッシュ → 絶対パス |
| `~/.ssh/**` | `~/.ssh/**` | そのまま保持（Kiro は `~/` パスをサポート） |

### MCP ツール名

- `mcp__serverName__toolName` → `@serverName/toolName`
- MCP サーバーの `mcpServers` 定義（command, args, env）は自動生成不可。手動で追加が必要。

### WebFetch ドメイン → web_fetch.trusted

- `WebFetch(domain:example.com)` → `trusted: [".*example\\.com.*"]`
- ドメインのドットは正規表現でエスケープする

## Kiro 固有の設定

Claude Code にない Kiro 固有の設定は、必要に応じて手動追加を案内する:

| 設定 | 説明 | 推奨 |
|------|------|------|
| `shell.autoAllowReadonly` | 読み取り専用コマンドを自動許可 | Claude の SAFE 分類コマンドが多い場合に `true` を提案 |
| `shell.denyByDefault` | allowedCommands 外を全拒否 | Claude で厳格な allow リストを使っている場合に `true` を提案 |
| `glob.allowReadOnly` / `grep.allowReadOnly` | 任意パスの検索を許可 | Claude で Glob/Grep がスコープなし allow の場合に `true` を提案 |

## エッジケース

- **重複パス**: 複数の Write/Edit ルールのパスは `allowedPaths` 配列に統合・重複除去。
- **MCP サーバー設定**: ツール参照（`@server/tool`）のみ生成。サーバー起動設定は別途必要。
- **ホームパス**: `Read(~/.ssh/**)` → `read.deniedPaths: ["~/.ssh/**"]` としてそのまま変換。Kiro は `~/` 表記をサポートする。
