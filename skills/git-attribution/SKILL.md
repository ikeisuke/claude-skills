---
name: git-attribution
description: >
  Manage Claude Code's git attribution (Co-Authored-By) settings per repository.
  Use when the user says "署名有効化", "enable attribution", "Claude署名", "git-attribution",
  or wants to toggle Claude's commit/PR attribution in the current repository's .claude/settings.json.
  Also use when the user asks about the current attribution status.
---

# Git Attribution Manager

Manage Claude Code attribution in `.claude/settings.json` per repository.
Global settings have attribution disabled. This skill enables it at the repo level.

## Check status

Read `.claude/settings.json` in the current repo. Report whether attribution is enabled or inherited from global (disabled).

## Enable

Merge into repo's `.claude/settings.json` (create if missing, preserve existing keys):

```json
{
  "attribution": {
    "commit": "default",
    "pr": "default"
  }
}
```

`"default"` restores Claude Code's standard Co-Authored-By trailer and PR link.

## Disable

Set to empty strings in repo's `.claude/settings.json`:

```json
{
  "attribution": {
    "commit": "",
    "pr": ""
  }
}
```

## Rules

- Never modify `~/.claude/settings.json` (global).
- Preserve all existing keys when updating.
- Create `.claude/` directory and `settings.json` if missing.
- After any change, show the updated attribution section.
