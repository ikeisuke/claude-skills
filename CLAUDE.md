# claude-skills

## ブランチルール

main ブランチは直接 push 不可。変更は PR 経由でマージすること。

## バージョン管理

PRが main にマージされると、GitHub Actions が `.claude-plugin/marketplace.json` の `metadata.version` のパッチバージョンを自動で上げる。手動でのバージョン変更は不要。
