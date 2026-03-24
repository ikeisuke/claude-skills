---
name: session-title
description: >
  Sets terminal tab title and badge for session identification.
  Supports macOS (iTerm2, Terminal.app) and Linux/WSL2 (Windows Terminal, WezTerm).
  Triggers on "セッションタイトル", "set session title", "session-title",
  or requests to label the current terminal session.
  On unsupported OS, silently skipped.
argument-hint: "{label1} {label2} {label3}"
---

# Session Title

Set terminal tab title and badge to identify sessions.

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

## Supported Terminals

| Platform | Terminal | Tab Title | Badge |
|----------|----------|-----------|-------|
| macOS | iTerm2 | OSC escape sequence | iTerm2 escape sequence |
| macOS | Terminal.app | OSC escape sequence | Not supported |
| Linux/WSL2 | Windows Terminal | OSC escape sequence | Not supported |
| Linux/WSL2 | WezTerm | OSC escape sequence | iTerm2-compatible escape sequence |
| Any | Other | OSC escape sequence | Not supported |

Unsupported OS (not macOS/Linux): silently exits 0.
