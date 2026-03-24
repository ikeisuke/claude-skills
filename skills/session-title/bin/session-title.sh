#!/bin/bash
# Session Title Script (macOS / Linux / WSL2)
# Sets terminal tab title and badge for session identification.
# Supported: iTerm2, Terminal.app, Windows Terminal, WezTerm, and other
# terminals that accept OSC escape sequences.
# Usage: session-title.sh <label1> <label2> <label3>
# Always exits 0 (non-blocking).

# Only macOS and Linux are supported
OS="$(uname -s)"
case "$OS" in
  Darwin|Linux) ;;
  *) exit 0 ;;
esac

LABEL1="${1:-}"
LABEL2="${2:-}"
LABEL3="${3:-}"

if [ -z "$LABEL1" ]; then
  exit 0
fi

# Build title from non-empty labels
TITLE="$LABEL1"
[ -n "$LABEL2" ] && TITLE="$TITLE / $LABEL2"
[ -n "$LABEL3" ] && TITLE="$TITLE / $LABEL3"

# --- Find parent TTY device ---
get_parent_tty() {
  local pid=$$
  while [ "$pid" -gt 1 ]; do
    local tty_name
    tty_name=$(ps -p "$pid" -o tty= 2>/dev/null | tr -d ' ')
    if [ -n "$tty_name" ] && [ "$tty_name" != "??" ]; then
      echo "/dev/$tty_name"
      return 0
    fi
    pid=$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d ' ')
    [ -z "$pid" ] && break
  done
  return 1
}

# --- Determine TTY device ---
PARENT_TTY=$(get_parent_tty)
# Fallback to /dev/tty (controlling terminal of the current process)
if [ -z "$PARENT_TTY" ] || [ ! -w "$PARENT_TTY" ]; then
  if [ -w /dev/tty ]; then
    PARENT_TTY=/dev/tty
  fi
fi

# --- Set title ---
if [ -n "$PARENT_TTY" ] && [ -w "$PARENT_TTY" ]; then
  # Tab title via standard escape sequence
  printf '\033]0;%s\007' "$TITLE" > "$PARENT_TTY" 2>/dev/null

  # iTerm2 badge (WezTerm does not support SetBadgeFormat)
  if [ "${TERM_PROGRAM:-}" = "iTerm.app" ]; then
    BADGE_TEXT="$LABEL1"
    [ -n "$LABEL2" ] && BADGE_TEXT="$BADGE_TEXT
$LABEL2"
    [ -n "$LABEL3" ] && BADGE_TEXT="$BADGE_TEXT
$LABEL3"
    BADGE=$(printf '%s' "$BADGE_TEXT" | base64 | tr -d '\r\n')
    printf "\033]1337;SetBadgeFormat=%s\007" "$BADGE" > "$PARENT_TTY" 2>/dev/null
  fi
fi

exit 0
