---
name: jj-workflow
description: >
  jj(Jujutsu)でバージョン管理操作を実行する。jjが有効化されているco-locationモード環境で
  gitコマンドの代わりに使用。
argument-hint: [subcommand] [args]
allowed-tools: Bash(jj:*)
---

# jj Workflow Guide

## jjの核心

- **ワーキングコピー = コミット**: ファイルを編集した時点で自動的にコミット(`@`)に反映される。`git add` / ステージングは不要。
- **Change ID**: コミットを `rebase` や `squash` で書き換えても、Change ID は変わらない。履歴を安全に編集できる。
- **bookmark**: Gitのブランチに相当するが、コミット時に自動追従しない。明示的に `jj bookmark set` で移動するか、`jj bookmark advance` で前進させる。

## 基本ワークフロー

### 状況確認

```bash
jj log          # 履歴とbookmarkの位置を確認
jj status       # ワーキングコピーの変更内容
jj diff         # 差分表示
```

### 作業開始

```bash
jj new <bookmark>                  # bookmarkの先頭から新しいリビジョンを開始
jj bookmark create <bookmark>     # 新しいbookmarkを作成（必要な場合）
```

### コミット（3点セット）

ファイル編集後、以下の3ステップでコミットを確定する:

```bash
jj describe -m "コミットメッセージ"           # 現在のリビジョンに説明を付ける
jj new                                        # 新しい空のリビジョンを作成（作業を区切る）
jj bookmark set <bookmark> -r @-              # bookmarkを確定したコミットに移動
```

#### bookmark advance を使う方法（代替）

`jj bookmark advance` はbookmarkを最寄りのリビジョンまで前進させるコマンド。`bookmark set` の代わりに使える:

```bash
jj describe -m "コミットメッセージ"
jj new
jj bookmark advance <bookmark>                # bookmarkを@-（直前のコミット）に前進
```

### push

```bash
jj git push --bookmark <bookmark>    # 特定のbookmarkをpush
jj git push                          # 変更のあるすべてのbookmarkをpush
```

### 整理

```bash
jj abandon <change_id>    # 不要なリビジョンを破棄（空リビジョンの削除等）
jj squash                 # 現在のリビジョンを親にまとめる
jj squash --into <rev>    # 指定リビジョンにまとめる
```

## トラブルシューティング

### bookmarkが取り残された

```bash
jj log                                   # bookmarkの現在位置を確認
jj bookmark set <bookmark> -r <rev>      # 正しいリビジョンに移動
```

### 操作を取り消したい

```bash
jj undo              # 直前の操作を取り消す
jj op log            # 操作履歴を表示
jj op restore <id>   # 特定の操作時点に復元
```

### コンフリクトが発生した

jjではコンフリクトはコミットに記録される（ファーストクラスオブジェクト）。慌てず解消できる:

```bash
jj status            # コンフリクトのあるファイルを確認
# ファイルを編集してコンフリクトマーカーを解消
jj status            # 解消を確認（自動検知される）
```

## 参考

- [jj公式ドキュメント](https://docs.jj-vcs.dev/)
- [詳細ガイド: 概念解説 + コマンド対照表](references/jj-guide.md)
