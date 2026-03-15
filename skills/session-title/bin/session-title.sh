#!/bin/bash
# Session Title Script (macOS only)
# Sets terminal tab title and iTerm2 badge for session identification.
# Uses osascript (Apple Events) - requires macOS.
# On non-macOS, silently exits 0.
# Usage: session-title.sh <label1> <label2> <label3>
# Always exits 0 (non-blocking).

# macOS check
if [ "$(uname -s)" != "Darwin" ]; then
  exit 0
fi

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

# --- Set title based on terminal ---
case "${TERM_PROGRAM:-}" in
  iTerm.app)
    # Tab title and badge via escape sequences to parent TTY
    # (osascript targets the "current" focused tab, not necessarily this session's tab)
    PARENT_TTY=$(get_parent_tty)
    if [ -n "$PARENT_TTY" ] && [ -w "$PARENT_TTY" ]; then
      # Tab title via standard escape sequence
      printf '\033]0;%s\007' "$TITLE" > "$PARENT_TTY" 2>/dev/null
      # Badge via iTerm2 proprietary escape sequence
      BADGE=$(printf '%s' "$TITLE" | base64 | tr -d '\r\n')
      printf "\033]1337;SetBadgeFormat=%s\007" "$BADGE" > "$PARENT_TTY" 2>/dev/null
    fi
    ;;
  Apple_Terminal)
    # Tab title via escape sequence to parent TTY (avoids front-window mismatch)
    PARENT_TTY=$(get_parent_tty)
    if [ -n "$PARENT_TTY" ] && [ -w "$PARENT_TTY" ]; then
      printf '\033]0;%s\007' "$TITLE" > "$PARENT_TTY" 2>/dev/null
    fi
    ;;
  *)
    # Fallback: write escape sequence to parent TTY
    PARENT_TTY=$(get_parent_tty)
    if [ -n "$PARENT_TTY" ] && [ -w "$PARENT_TTY" ]; then
      printf '\033]0;%s\007' "$TITLE" > "$PARENT_TTY" 2>/dev/null
    fi
    ;;
esac

exit 0
