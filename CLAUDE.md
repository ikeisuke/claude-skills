# claude-skills

## ブランチルール

main ブランチは直接 push 不可。変更は PR 経由でマージすること。

新しい feature/fix ブランチを作る前は **必ず `git checkout main && git pull --ff-only`** を挟むこと。別の feature ブランチを base にしたまま `git checkout -b` すると、別 PR の作業差分が新ブランチに混入し、PR レビューと履歴を汚す（実例: PR #33 に PR #32 の README コミットが意図せず含まれてマージされた）。

## バージョン管理

PRが main にマージされると、GitHub Actions が `.claude-plugin/marketplace.json` の `metadata.version` のパッチバージョンを自動で上げる。手動でのバージョン変更は不要。

## PR 前レビュー

PR を作成する前に、以下の2つのレビューを**並行**で実行すること:

1. `/review` — Claude Code 組み込みのコードレビュー
2. `codex review --base main` — Codex によるレビュー

レビュー指摘で修正を行った場合は、修正後に再度両方のレビューを並行で実行すること。P1 指摘がなくなるまで繰り返す。
