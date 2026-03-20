---
name: session-title
description: >
  macOS専用: Sets terminal tab title and iTerm2 badge for session identification.
  Triggers on "セッションタイトル", "set session title", "session-title",
  or requests to label the current terminal session. Requires macOS (uses osascript).
  On non-macOS, silently skipped.
argument-hint: "{label1} {label2} {label3}"
---

# Session Title (macOS)

Set terminal tab title and iTerm2 badge to identify sessions.

## Usage

Run the bundled script with up to 3 labels. The title is displayed as `label1 / label2 / label3`.

```bash
bash skills/session-title/bin/session-title.sh "ProjectName" "Task" "Branch"
```

Determine labels from context:
- **label1**: Project or repo name (directory name as fallback)
- **label2**: Current task or phase
- **label3**: Branch name or other identifier

All arguments must be quoted. On error, skip silently (never block workflow).

## Supported Terminals (macOS only)

| Terminal | Tab Title | Badge |
|----------|-----------|-------|
| iTerm2 | TTY escape sequence | iTerm2 escape sequence |
| Terminal.app | osascript | Not supported |
| Other (macOS) | TTY escape sequence | Not supported |

Non-macOS environments: silently exits 0.
