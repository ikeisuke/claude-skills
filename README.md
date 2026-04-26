# claude-skills

Custom skills for [Claude Code](https://claude.com/claude-code).

## Installation

```
/plugin marketplace add ikeisuke/claude-skills
/plugin install tools@ikeisuke-skills
```

## Skills

| Skill | Description |
|-------|-------------|
| [cross-platform-review](./skills/cross-platform-review/) | Review shell scripts and config files for macOS / Linux (incl. WSL2) cross-platform compatibility |
| [gh-api-fallback](./skills/gh-api-fallback/) | Reference for substituting `gh api` (REST/GraphQL) when `gh` subcommands fail due to insufficient token scopes |
| [git-attribution](./skills/git-attribution/) | Manage Claude Code's git attribution (Co-Authored-By) per repository |
| [history-append](./skills/history-append/) | Generate and insert changelog entries into HISTORY.md / CHANGELOG.md from `git diff --staged` |
| [jj-workflow](./skills/jj-workflow/) | jj (Jujutsu) version control workflow guide for co-location mode |
| [session-title](./skills/session-title/) | Set terminal tab title and badge for session identification (macOS / Linux / WSL2) |
| [skill-lint](./skills/skill-lint/) | Check skills against official best practices and report violations |
| [suggest-permissions](./skills/suggest-permissions/) | Suggest permission auto-approval rules with deep argument/flag analysis and risk assessment |
| [translate-permissions](./skills/translate-permissions/) | Translate Claude Code permission settings to Kiro CLI custom agent configuration |
