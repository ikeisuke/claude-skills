---
name: cross-platform-review
description: >
  Reviews shell scripts and config files for macOS / Linux (incl. WSL2)
  cross-platform compatibility. Triggers on "cross-platform-review",
  "クロスプラットフォームレビュー", "macOS Linux 互換", "両対応レビュー",
  "BSD GNU 差", or requests to audit dotfiles / setup scripts for portability.
  Catches portability issues that shellcheck / `bash -n` cannot (BSD vs GNU
  command flags, path differences, OS branching asymmetry).
argument-hint: "[--base {ref}] [--paths {glob}...]"
allowed-tools: Bash(git diff:*), Bash(git rev-parse:*), Bash(git show:*), Bash(git ls-files:*)
---

# Cross-Platform Review

シェルスクリプト・設定ファイルの **macOS と Linux (WSL2 含む) 両対応** をレビューする。
`shellcheck` や `bash -n` では検出できない「片方の OS でしか動かない / 挙動が変わる」コードを差分から検出し、互換性の指摘と修正案を提示する。

## チェックリスト

```
タスク進捗：
- [ ] Step 1: 差分取得（base ブランチとの比較 or 指定範囲）
- [ ] Step 2: 対象ファイルの抽出（.sh / .zsh / Brewfile / setup スクリプト等）
- [ ] Step 3: 観点リストに沿って差分を点検
- [ ] Step 4: 互換性問題と修正案を提示
```

## Step 1: 差分の取得

引数なしの場合は `main` との差分を対象にする。`--base <ref>` で比較ベースを変更可。

```bash
# デフォルト: main ブランチとの差分
git diff main...HEAD

# ベース指定
git diff <base>...HEAD

# 範囲指定（特定コミットのみレビュー）
git diff <ref>~..<ref>
```

リポジトリのデフォルトブランチが `main` 以外の場合は、`git symbolic-ref refs/remotes/origin/HEAD` で確認する。

## Step 2: 対象ファイルの抽出

差分から以下のパターンに該当するファイルを抽出する:

| カテゴリ | パターン |
|---------|---------|
| シェルスクリプト | `*.sh`, `*.bash`, `*.zsh` |
| シェル設定 | `.zshrc`, `.bashrc`, `.bash_profile`, `.zprofile`, `.zshenv` |
| zsh モジュール | `zsh/**/*.zsh` |
| パッケージ定義 | `Brewfile`, `Brewfile.local`, `Brewfile.lock.json` |
| セットアップ | `setup.sh`, `install.sh`, `bootstrap.sh`, `Makefile`（シェル呼び出しがある場合） |
| Git hooks | `.git/hooks/*`, `hooks/*` |

`--paths` 引数で対象を絞り込み可能（glob を渡す）。

抽出件数が 0 なら「シェル系の差分なし。レビュー不要」と表示して終了。

## Step 3: 観点リストに沿った点検

[references/checklist.md](references/checklist.md) のチェックリストに沿って各差分を点検する:

- **BSD / GNU コマンド差**（`sed`, `date`, `stat`, `mktemp`, `readlink`, `find`, `grep`, `awk`）
- **環境差**（パス、macOS 専用コマンド、Linux 専用コマンド、WSL2 特有処理）
- **Brewfile / setup スクリプト**（`OS.mac?` / `OS.linux?` ブロック対称性）
- **zsh モジュール構成**（`zsh/os/darwin.zsh` / `linux.zsh` 対称性、`$OSTYPE` 分岐の網羅）

各指摘には以下を付ける:

| 要素 | 内容 |
|------|------|
| 重要度 | `BLOCKER`（片方で動かない）/ `HIGH`（挙動差）/ `MED`（警告で済む）/ `LOW`（推奨） |
| ファイル + 行番号 | `path/to/file.sh:42` |
| 検出した観点 | 例: 「BSD `sed -i` には引数 `''` が必須」 |
| 修正案 | 互換性のあるコード例 |

## Step 4: 結果の提示

重要度別にまとめて出力:

```
Cross-Platform Review (base: main, 3 files):

BLOCKER (1):
  setup.sh:42  BSD sed -i には引数 '' が必須
    現状: sed -i 's/foo/bar/' file
    修正案: sed -i '' 's/foo/bar/' file   # macOS
            sed -i '' -e 's/foo/bar/' file # 両対応の安全策（GNU でも動く）

HIGH (2):
  zsh/os/darwin.zsh:15  Linux 側 (zsh/os/linux.zsh) に対応コード無し（非対称）
    ...

MED (1):
  Brewfile:8  if OS.mac? ブロックの追加項目に対応する OS.linux? エントリ無し
    ...

Summary: 1 blocker, 2 high, 1 med
```

指摘ゼロなら「Cross-Platform Review: 互換性問題は検出されませんでした」と表示。

## スコープ外

- 自動修正（指摘までで止める。ユーザーが手で修正する）
- macOS / Linux で実コマンドを動かす検証（観点ベースの静的レビュー）
- Windows ネイティブ環境（Cygwin / MSYS2 等）のサポート
- `shellcheck` / `bash -n` の代替（補完であって置換ではない）

## Examples

User: `/cross-platform-review`
→ `main` ブランチとの差分から対象ファイルを抽出し、BSD/GNU コマンド差・パス差・OS 分岐の対称性を点検。

User: `/cross-platform-review --base origin/main`
→ リモート main との差分を対象にレビュー。

User: `/cross-platform-review --paths 'setup.sh' 'Brewfile'`
→ 指定パターンに一致するファイルのみレビュー。

## Troubleshooting

### 観点リストの追加

実利用で見落としが見つかったら [references/checklist.md](references/checklist.md) に観点を追記する。観点リストは初期セットから始めて、運用で育てる。

### shellcheck / bash -n との関係

- `shellcheck` / `bash -n` は構文・典型バグを検出（OS 依存差は対象外）
- 本スキルは **OS 依存差** を検出（構文は対象外）
- 両方を CI に組み込むのが理想

## Rules

- 静的レビューに徹する。コマンドを実際に動かして検証しない。
- 修正案は **必ず両対応の例** を示す（macOS のみ / Linux のみの片対応コードは避ける）。
- 観点リストにない問題を見つけても指摘してよいが、再発防止のためレビュー後に [references/checklist.md](references/checklist.md) への追記を提案する。
