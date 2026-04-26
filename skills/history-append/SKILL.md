---
name: history-append
description: >
  Generates and inserts changelog entries into HISTORY.md / CHANGELOG.md from
  git diff --staged. Triggers on "history-append", "履歴追記", "changelog 追記",
  "HISTORY.md 更新", or requests to append a changelog entry before commit.
  User-only: invoke explicitly via /history-append; not auto-invoked by the model.
argument-hint: "[--commit {ref}] [--file {path}]"
disable-model-invocation: true
allowed-tools: Bash(git diff:*), Bash(git log:*), Bash(git show:*), Bash(git rev-parse:*), Bash(date:*), Read
---

# History Append

`HISTORY.md` / `CHANGELOG.md` への変更履歴追記を半自動化する。
`git diff --staged`（または `--commit` で指定したコミット範囲）から変更内容を抽出し、
リポジトリで採用されているフォーマットに沿った追記候補を生成・挿入する。

## チェックリスト

```
タスク進捗：
- [ ] Step 1: 入力ソース確認（staged 差分 or 指定コミット）
- [ ] Step 2: 対象ファイル検出（HISTORY.md / CHANGELOG.md）
- [ ] Step 3: フォーマット推定
- [ ] Step 4: 追記候補生成
- [ ] Step 5: 挿入位置決定 + ユーザー承認
- [ ] Step 6: ファイル書き込み
```

## Step 1: 入力ソースの取得

引数なしの場合は `git diff --staged` を読む。`--commit <ref>` 指定時は `git show <ref>` または `git diff <ref>~..<ref>` を使う。

```bash
git diff --staged
# or
git diff --staged --stat   # ファイル単位の概要
```

**失敗モード**:

| 状態 | 挙動 |
|------|------|
| `git diff --staged` が空 | 「staged 差分がありません。`git add` してから再実行してください」と表示して終了 |
| Git リポジトリでない | 「Git リポジトリではありません」と表示して終了 |
| `--commit` 引数の ref が無効 | エラー内容を提示して終了 |

## Step 2: 対象ファイルの検出

引数 `--file <path>` が指定されていればそれを使う。されていなければ以下の順で検索:

1. リポジトリルート直下の `HISTORY.md`
2. リポジトリルート直下の `CHANGELOG.md`
3. （見つからなければ）「履歴ファイルが見つかりません。新規作成しますか？（HISTORY.md / CHANGELOG.md / カスタムパス）」とユーザーに確認

リポジトリルートは `git rev-parse --show-toplevel` で取得する。

## Step 3: フォーマットの推定

対象ファイルの先頭 30〜50 行を読んで以下を推定:

### 日付見出しの形式
- `## YYYY-MM-DD` — 日付ベース
- `## [version]` / `## [v1.2.3] - YYYY-MM-DD` — Keep a Changelog 系
- `## v1.2.3` — バージョンタグ系

### 区切り粒度（`###` の対象）
直近のセクションを 1〜2 個サンプルとして読み、`###` がどの粒度で区切られているかを判定:
- ファイルパス（例: `### src/foo.py`）
- カテゴリ（例: `### Added`, `### Changed`, `### Fixed`）
- 機能名（例: `### Auth`）
- 自由記述（区切りなし、本文中に箇条書き）

### 並び順
- 先頭が直近の日付/バージョン → **新しい順**（先頭に挿入）
- 末尾が直近 → **古い順**（末尾に追記）

ファイル内に Keep a Changelog のヘッダ（`# Changelog\n\nAll notable changes...`）があれば Keep a Changelog 形式と判断する。

### 推定失敗時のデフォルト

先頭数十行で形式を確定できなければ、以下のデフォルトを提案してユーザー確認を取る:

- 日付見出し: `## YYYY-MM-DD`（今日の日付）
- 区切り粒度: ファイルパス
- 並び順: 新しい順

## Step 4: 追記候補の生成

`git diff --staged` の各ファイル変更を分析して候補を生成する:

### 各 `###` ブロックの構造

| 要素 | 内容 |
|------|------|
| 見出し | 推定した粒度に従う（ファイル名 / カテゴリ / 機能名） |
| 「何を変更したか」 | diff から抽出（追加/削除/修正/リネーム等の事実） |
| 「なぜ変更したか」 | コミットメッセージ・コード内コメント・引数で渡された context から推定。不明なら「（要追記）」マーカーを置く |

### スタイルの追従

既存セクションをサンプルに、以下のスタイル要素を踏襲する:

- 箇条書き記号（`-` / `*`）
- 文末スタイル（句点あり/なし、英語の場合は ピリオド/なし）
- 文体（「〜した」「〜する」「〜を追加」等）
- インデント幅

### 候補の例（日付見出し + ファイル名区切り + 新しい順）

```markdown
## YYYY-MM-DD

### skills/example/SKILL.md

- スキルの初版を追加。
- フォーマット推定と挿入ロジックを明文化。

### .claude-plugin/marketplace.json

- 新スキルを skills 配列に登録。
```

`YYYY-MM-DD` は実行日を `date +%Y-%m-%d` で取得して埋める。

## Step 5: 挿入位置の決定 + ユーザー承認

並び順に従って挿入位置を決める:

| 並び順 | 挿入位置 |
|--------|---------|
| 新しい順 | 既存セクションの直前（ファイル先頭のヘッダ部の直後） |
| 古い順 | ファイル末尾 |

### 同日（同バージョン）セクションが既存の場合

直近のセクション見出しが今日の日付（または対象バージョン）と一致する場合、新規 `## YYYY-MM-DD` を作らず、既存セクションに `###` ブロックを **マージ** することを提案する。

例:
- 既存に当日日付のセクション (`## YYYY-MM-DD`) がある → 同セクション内に新規 `### ...` ブロックを追加
- 同名 `### ファイル名` が既存 → 箇条書きを追加するか別ブロックにするかユーザーに確認

### 承認フロー

書き込み前に必ずユーザーに承認を取る:

1. 推定したフォーマット（日付見出し形式、区切り粒度、並び順）を 1 行で示す
2. 生成した追記候補（差分ブロック全体）を提示
3. 挿入位置（行番号 / 既存セクションへのマージか）を示す
4. 「この内容で書き込みますか？（yes / 修正案 / no）」を尋ねる

**拒否時はファイルに一切触れない**（部分書き込みもしない）。

## Step 6: ファイル書き込み

承認後、Edit/Write ツールで対象ファイルを更新する。書き込み後に以下を表示:

- 更新したファイルパス
- 挿入した行範囲
- 「`git add <file>` で staging に含めることを忘れないでください」のリマインダー

## スコープ外

- リポジトリのコミット規約（Conventional Commits 等）の自動推定・適用
- 自動 commit / push（書き込みまでで止める）
- 多言語対応（既存ファイルの言語に従う。明示的な言語切替はしない）
- バージョン番号のインクリメント（Keep a Changelog 形式でも `[Unreleased]` の文言などは触らない）

## Examples

User: `/history-append`
→ staged 差分から HISTORY.md / CHANGELOG.md を検出、フォーマット推定、追記候補を生成して承認待ち。

User: `/history-append --commit HEAD~1..HEAD`
→ 直前 1 コミットの差分を対象に追記候補を生成。

User: `/history-append --file docs/CHANGELOG.md`
→ 指定パスのファイルを対象にする。

## Troubleshooting

### `git diff --staged` が空

`git add` でファイルを staging に含めてから再実行する。`--commit <ref>` を使えば任意のコミット範囲も対象にできる。

### フォーマット推定がブレる

既存ファイルの先頭セクションが乱雑だと推定精度が落ちる。手動でフォーマットを指定したい場合は、生成された候補を承認時に修正してから書き込む。

### 同日セクションが既存

「マージする / 新規セクションを作る」のいずれかをユーザー判断で選ぶ。デフォルトはマージ。

## Rules

- 書き込み前に必ずユーザー承認を取る。承認なしの書き込みは禁止。
- 既存ファイルの内容を破壊的に書き換えない（追記のみ）。改行コード・末尾改行は既存に合わせる。
- `git add` / `git commit` は実行しない（スキルのスコープ外）。
- 推定の根拠（どの既存セクションをサンプルにしたか）を 1 行でユーザーに示す。
- `Edit` / `Write` ツールは `allowed-tools` に含めない。Step 6 の書き込み時に標準の permission prompt を経由させ、ユーザー承認の最終ゲートとして機能させるための設計。Step 5 の口頭承認 + Step 6 の permission prompt の二重ガードで誤書き込みを防ぐ。
