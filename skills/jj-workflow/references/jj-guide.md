# jj 詳細ガイド

## Table of Contents

- [概要](#概要)
- [核心概念](#核心概念)
  - [ワーキングコピー = コミット](#ワーキングコピー--コミット)
  - [Change ID vs Commit ID](#change-id-vs-commit-id)
  - [Immutable / Mutable コミット](#immutable--mutable-コミット)
  - [コンフリクトはファーストクラスオブジェクト](#コンフリクトはファーストクラスオブジェクト)
  - [bookmarkの設計思想](#bookmarkの設計思想)
- [推奨設定](#推奨設定)
- [前提条件](#前提条件)
  - [インストール](#インストール)
  - [co-locationモードの設定](#co-locationモードの設定)
- [Git / jj コマンド対照表](#git--jj-コマンド対照表)
- [よくあるミスと対処法](#よくあるミスと対処法)
  - [bookmarkを移動し忘れた](#bookmarkを移動し忘れた)
  - [immutableなコミットを変更しようとした](#immutableなコミットを変更しようとした)
  - [git操作との混在](#git操作との混在)
  - [pushが拒否された](#pushが拒否された)
- [参考リンク](#参考リンク)

## 概要

jj (Jujutsu) はGit互換の次世代バージョン管理システム。Gitリポジトリ上でco-locationモードとして動作し、`.jj/` ディレクトリを追加するだけで既存のGitリポジトリをそのまま使える。

主な特徴:
- Gitリポジトリとの完全な互換性（co-locationモード）
- ステージングエリア不要の直感的なワークフロー
- 安全な履歴編集（Change IDによる追跡）
- コンフリクトのファーストクラスサポート

## 核心概念

### ワーキングコピー = コミット

Gitではワーキングコピー（未コミットの変更）とコミットは別の概念だが、jjではワーキングコピー自体が常にコミット（`@`）として存在する。

```
Git:
  [ワーキングコピー] → git add → [ステージング] → git commit → [コミット]

jj:
  [ワーキングコピー = コミット(@)] → jj describe → [説明付きコミット]
                                    → jj new     → [新しい空のコミット(@)]
```

ファイルを編集するだけで変更は自動的にコミット `@` に反映される。`jj describe` でメッセージを付け、`jj new` で次の作業に移る。

### Change ID vs Commit ID

| | Change ID | Commit ID |
|---|---|---|
| 形式 | アルファベット小文字 (`kmysrlqp`) | 16進数 (`a1b2c3d4`) |
| 不変性 | rebase/amend しても変わらない | 内容変更で変わる |
| 用途 | リビジョン指定に推奨 | Git互換の識別子 |

Change IDはjj独自の概念で、コミットの「論理的な同一性」を保証する。`jj rebase` や `jj squash` でコミットの内容やハッシュが変わっても、Change IDは同じまま追跡できる。

### Immutable / Mutable コミット

jjはコミットを2種類に分類する:

- **Immutable**: 変更不可。`main` 等のリモート追跡bookmarkが指すコミットとその祖先。
- **Mutable**: 変更可能。ローカルの作業コミット。

`jj rebase` や `jj squash` はmutableなコミットにのみ適用できる。immutableなコミットを変更しようとするとエラーになる。

### コンフリクトはファーストクラスオブジェクト

Gitではコンフリクトは「解消するまでコミットできない」特殊な状態だが、jjではコンフリクトを含むコミットを普通に作成できる。

- コンフリクトが発生してもパニック不要
- コンフリクトを含んだまま他の作業に移れる
- 後から戻ってきて解消できる
- `jj status` でコンフリクトの有無を確認できる

### bookmarkの設計思想

jjのbookmarkはGitのブランチに相当するが、重要な違いがある:

- **Gitブランチ**: `git commit` すると自動的にブランチポインタが前進する
- **jj bookmark**: `jj new` してもbookmarkは動かない。明示的に `jj bookmark set` で移動する

この設計により、bookmarkの位置を常に意識的に管理できる。

手動で `jj bookmark set` する代わりに `jj bookmark advance` を使えば、bookmarkを最寄りの子孫リビジョンまで前進させられる:

```bash
jj bookmark advance <bookmark>   # bookmarkをデフォルトで@まで前進
```

対象や移動先は `revsets.bookmark-advance-from` / `revsets.bookmark-advance-to` で設定可能。

## 推奨設定

`~/.jjconfig.toml` に以下を追加すると便利:

```toml
[git]
auto-local-bookmark = true    # git push時にローカルbookmarkを自動作成
```

## 前提条件

### インストール

```bash
# macOS
brew install jj

# その他: https://docs.jj-vcs.dev/latest/install-and-setup/
```

### co-locationモードの設定

既存のGitリポジトリでjjを使い始める:

```bash
cd <git-repo>
jj git init --colocate    # .jj/ ディレクトリが作成される（v0.39+ではcolocateがデフォルト）
```

colocateモードでは `.jj/.gitignore` が自動生成され、`.jj/` 配下はgitに無視される。手動で `.gitignore` に追加する必要はない。

## Git / jj コマンド対照表

| 操作 | Git | jj |
|------|-----|-----|
| 初期化 | `git init` | `jj git init --colocate` |
| 状態確認 | `git status` | `jj status` |
| 差分表示 | `git diff` | `jj diff` |
| 履歴確認 | `git log` | `jj log` |
| コミット | `git add . && git commit -m "msg"` | `jj describe -m "msg" && jj new` |
| ブランチ作成 | `git checkout -b <name>` | `jj bookmark create <name>` |
| ブランチ切り替え | `git checkout <name>` | `jj new <name>` |
| ブランチ削除 | `git branch -d <name>` | `jj bookmark delete <name>` |
| ブランチ名変更 | `git branch -m <old> <new>` | `jj bookmark rename <old> <new>` |
| マージ | `git merge <branch>` | `jj new <rev1> <rev2>` (マージコミット作成) |
| リベース | `git rebase <base>` | `jj rebase -d <base>` |
| チェリーピック | `git cherry-pick <commit>` | `jj new <dest> && jj squash --from <source>` |
| リバート | `git revert <commit>` | `jj revert -r <rev> -d @` |
| スタッシュ | `git stash` | 不要（ワーキングコピー=コミットのため） |
| 取り消し | `git reflog` + `git reset` | `jj undo` / `jj op restore` |
| push | `git push` | `jj git push` |
| pull | `git pull` | `jj git fetch && jj rebase -d <bookmark>@origin` |
| リモート取得 | `git fetch` | `jj git fetch` |

## よくあるミスと対処法

### bookmarkを移動し忘れた

`jj describe && jj new` した後に `jj bookmark set` を忘れると、bookmarkが古い位置のまま残る。

```bash
jj log                                   # bookmarkの位置を確認
jj bookmark set <bookmark> -r <rev>      # 正しい位置に移動
```

### immutableなコミットを変更しようとした

リモート追跡bookmarkが指すコミットは変更できない。新しいコミットを作って作業する:

```bash
jj new <bookmark>    # bookmarkの先頭に新しいリビジョンを作成
```

### git操作との混在

co-locationモードでは `git commit` 等も使えるが、混在は避ける。jjコマンドに統一すること。
やむを得ずgitコマンドを使った場合:

```bash
jj git import    # Gitの変更をjjに取り込む
```

### pushが拒否された

リモートのbookmarkが進んでいる場合:

```bash
jj git fetch                                    # リモートの変更を取得
jj rebase -d <bookmark>@origin                  # リモートの先頭にリベース
jj git push --bookmark <bookmark>               # 再度push
```

## 参考リンク

- [jj公式ドキュメント](https://docs.jj-vcs.dev/)
- [jj GitHubリポジトリ](https://github.com/jj-vcs/jj)
- [Tutorial](https://docs.jj-vcs.dev/latest/tutorial/)
- [FAQ](https://docs.jj-vcs.dev/latest/FAQ/)
