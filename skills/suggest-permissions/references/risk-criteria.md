# リスク評価基準

## 評価ディメンション

各ルール候補を以下の観点で評価する:

| Dimension | Question |
|-----------|----------|
| Reversibility | Can the action be undone? (undo-able = lower risk) |
| Scope of impact | Local only? Or affects remote/shared state? |
| Data safety | Can it delete, overwrite, or corrupt data? |
| Credential exposure | Could it leak secrets or tokens? |
| Network effects | Does it send data externally or modify remote systems? |

## リスクレベル

| Level | Criteria | Auto-approve? |
|-------|----------|---------------|
| SAFE | Read-only, no side effects, fully reversible | Recommend |
| LOW | Minor local side effects, easily reversible, no network | Recommend |
| MED | Local modifications, build/test, reversible with effort | User decides |
| HIGH | Remote effects, data deletion, credential risk, hard to reverse | Warn |

## Well-known classifications (追加分析不要)

- **SAFE**: `Glob`, `Grep`, `WebSearch`, `ls`, `cat`, `head`, `tail`, `wc`, `file`, `which`, `echo`, `date`, `pwd`, `find`, `grep`, `rg`, `diff`, `tree`, `jq`, `git status`, `git log`, `git diff`, `git show`, `git blame`
- **LOW**: `Agent`, `WebFetch`, `mkdir`, `mktemp`, `touch`, `sort`, `tar`, `curl`, `gh issue`(view/list only), `gh api`(GET only), `git tag`
- **MED**: `sed`, `awk`, `chmod`
- **HIGH**: `rm`, `cp`, `mv`, `rsync`, `git push`, `git reset --hard`, `git clean`, `gh pr create/merge/close`, `docker`, `kubectl`, `terraform`, `aws`, `sudo`, `ssh`, `kill`

## Never auto-allow（allow に入れてはいけないもの）

以下は使用頻度に関係なく `allow` に含めてはならない。`ask` または未設定（デフォルト確認）にすること。

**スクリプトインタプリタ** — 任意コード実行が可能:
- `node`, `python3`, `python`, `ruby`, `perl`, `bash`, `sh`, `deno`, `bun`

**シェル制御構文** — 任意コマンドのラッパーであり、中身の危険度を継承する:
- `for`, `if`, `while`, `case`, `eval`

**ファイル操作（スコープ限定なしの場合）** — プロジェクト外のファイルを上書き・削除するリスク:
- `cp`, `mv`, `rsync`（スコープを限定できる場合は個別ルールで対応。例: `\rm /tmp/*`）

**ディレクトリ移動・指定コマンド** — チェインや引数で任意のディレクトリでの操作が可能:
- `cd`（`cd /tmp && rm -rf *` のようにチェインで危険なコマンドを実行可能）
- `git -C`（`git -C /any/repo push --force` のように任意ディレクトリで破壊的 git 操作が可能）

これらがスクリプト出力に現れた場合は、自動的に ask を推奨し、allow には含めないこと。
