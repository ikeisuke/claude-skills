---
name: gh-api-fallback
description: >
  gh CLI サブコマンドがトークンスコープ不足で失敗した際に、
  gh api (REST/GraphQL) で代替する方法のリファレンス。
  Triggers on "gh-api-fallback", "gh api 代替", "gh コマンド失敗",
  "token scope error", "gh api workaround", "GraphQL mutation".
---

# gh API Fallback Guide

gh CLI のサブコマンド（`gh pr edit`, `gh pr ready` 等）は内部で GraphQL を使い、トークンに `read:org` / `read:discussion` スコープを要求する場合がある。`gh api` で REST/GraphQL を直接叩けば、`repo + workflow` スコープのみで動作する。

## When to Use

以下のようなエラーが出た場合にこのガイドを参照する:

- `HTTP 403` / `insufficient scopes`
- `Your token has not been granted the required scopes`
- `gh pr edit` / `gh pr ready` 等のサブコマンドが権限エラーで失敗

## General Pattern

1. 失敗したサブコマンドが何をしているか特定する（REST か GraphQL か）
2. `gh api` で対応するエンドポイントを直接呼ぶ
3. REST で対応できない操作（例: draft 状態の変更）は GraphQL mutation を使う

## Known Fallback Patterns

### PR 本文更新

**失敗するコマンド:**

```bash
gh pr edit {number} --body-file /tmp/pr-body.md
```

**代替 (REST PATCH):**

```bash
cat /tmp/pr-body.md | gh api repos/{owner}/{repo}/pulls/{number} -X PATCH -F body=@- --jq '.html_url'
```

### Draft PR → Ready for Review

**失敗するコマンド:**

```bash
gh pr ready {number}
```

REST API の PATCH で `draft=false` を送っても変更されない（REST API は draft フィールドの変更をサポートしない）。GraphQL mutation が必要。

**Step 1: node_id を取得**

```bash
gh api repos/{owner}/{repo}/pulls/{number} --jq '.node_id'
```

**Step 2: GraphQL mutation で Ready 化**

取得した node_id を `{NODE_ID}` に入れて実行:

```bash
gh api graphql -f query='mutation { markPullRequestReadyForReview(input: { pullRequestId: "{NODE_ID}" }) { pullRequest { isDraft } } }' --jq '.data.markPullRequestReadyForReview.pullRequest.isDraft'
```

戻り値が `false` なら成功。

### PR タイトル更新

```bash
gh api repos/{owner}/{repo}/pulls/{number} -X PATCH -f title="新しいタイトル" --jq '.html_url'
```

### PR ラベル追加

```bash
gh api repos/{owner}/{repo}/issues/{number}/labels -X POST -F "labels[]=bug" -F "labels[]=enhancement" --jq '.[].name'
```

### PR レビュアー追加

```bash
gh api repos/{owner}/{repo}/pulls/{number}/requested_reviewers -X POST -F "reviewers[]=username" --jq '.requested_reviewers[].login'
```

## Diagnosing Scope Errors

現在のトークンスコープを確認:

```bash
gh auth status
```

必要なスコープが不足している場合、`gh auth refresh -s read:org` でスコープを追加できるが、組織ポリシーで制限されている場合は `gh api` による直接呼び出しが唯一の手段となる。

## Examples

User: 「gh pr edit が 403 で失敗する」
→ Known Fallback Patterns から対応する REST API コマンドを提示。

User: "gh pr ready fails with scope error"
→ GraphQL mutation による Draft → Ready 手順を提示。

User: 「gh api 代替コマンドを教えて」
→ このガイド全体を参照して該当パターンを案内。

## Troubleshooting

### `gh api` でも 403 が出る

トークン自体に `repo` スコープがない可能性がある。`gh auth status` で確認し、`gh auth refresh -s repo` でスコープを追加する。

### GraphQL mutation が `null` を返す

node_id が正しいか確認する。Step 1 で取得した PR の node_id をそのまま使うこと。Issues の node_id とは異なる。

### `-F body=@-` でパイプが動作しない

stdin にデータが渡されていることを確認する。ファイルが空でないか、パイプの前段でエラーが出ていないかチェックする。

## Rules

- コマンド内で `$(...)` やバッククォートを使わない。パイプ (`|`) や中間ステップで代替する。
- `{owner}`, `{repo}`, `{number}` は実際の値に置き換えて使用する。
- REST で対応できない操作は GraphQL mutation を検討する。
- 新しい fallback パターンを発見した場合はこのスキルに追記する。
