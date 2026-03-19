# ファイルツール・ワイルドカード・コンテキスト判定ルール

## File tool rules (Read / Edit / Write)

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

## Variable assignment commands

`VAR=$(command ...)` 形式のコマンドはパーミッションルールの `Bash(...)` 構文と括弧が衝突するため、ルールとして記述できない。
スクリプトは `$()` 内のコマンドを自動的に抽出してルール候補にする（例: `TMPFILE=$(mktemp /tmp/foo.XXXXX)` → `Bash(mktemp *)`）。

変数代入で始まるコマンドは個別ルールではカバーされないため、都度確認となる。

## Wildcard overmatch warning

`Bash(command *)` は全フラグ・引数を許可する。同一コマンドでも特定フラグで危険度が大きく変わるものがある。
このようなコマンドの場合、安全なサブコマンド/フラグだけを個別ルールにするか、ワイルドカードのリスクを明示すること。

危険フラグを持つコマンドの例:
- **`git -C`**: `git -C /path status` は SAFE だが `git -C /any/repo push --force` のように任意ディレクトリで破壊的操作が可能 → `Bash(git -C *)` は allow しない
- **`cd`**: 単体は SAFE だが `cd /tmp && rm -rf *` のようにチェインで危険なコマンドを実行可能 → `Bash(cd *)` は allow しない
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

### ask ルールの使用方針

**`ask` は単独で提案しない。** `allow` の広いルールに対する危険サブパターンのガードとしてのみ使う。

- **正しい使い方**: `allow: git push *` + `ask: git push --force *`（allow のガード）
- **誤った使い方**: `ask: rm *`（対応する allow がない単独の ask）

対応する `allow` がないコマンドは `ask` に入れず、デフォルトの確認動作に任せる。
広い `ask` ルールは、細かい `allow` ルールを意図せず上書きしてしまうリスクがある。

```json
{
  "permissions": {
    "deny": ["Bash(rm -rf /*)"],
    "ask": ["Bash(git branch -D *)", "Bash(git push --force *)"],
    "allow": ["Bash(git branch *)", "Bash(git push *)"]
  }
}
```

## Rules requiring contextual judgment

These need analysis of the actual usage examples:

- **`bash`/`sh`**: Risk depends entirely on what's being executed. Check examples.
- **`Edit`/`Write`**: Generally MED, but scope matters. Editing config files or CI pipelines is riskier than source code.
- **`npm run`/`cargo test`**: Usually MED (local), but scripts could have side effects.
- **`curl`/`wget`**: LOW for reads, but POST/PUT requests are higher risk.
- **Project-specific scripts**: Check examples to understand what they do.
- **Environment-prefixed commands** (e.g., `AWS_PROFILE=... *`): Evaluate the actual command being run.
