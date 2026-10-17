#!/usr/bin/env bash
# Diagnostic-only outer watchdog. Original command argv and gates stay intact.
bounded() {
  local rc8_remaining
  rc8_remaining=$(( ATLAS_DIAGNOSTIC_DEADLINE - $(date +%s) - 5 ))
  if (( rc8_remaining <= 0 )); then
    echo 'Diagnostic deadline exhausted before command' >&2
    return 124
  fi
  timeout --signal=TERM --kill-after=5s "${rc8_remaining}s" "$@"
}

arm_action() {
  local rc8_minutes
  rc8_minutes=$(( (ATLAS_DIAGNOSTIC_DEADLINE - $(date +%s) - 10) / 60 ))
  if (( rc8_minutes < 1 )); then
    echo 'Insufficient diagnostic budget before setup action' >&2
    return 124
  fi
  if (( rc8_minutes > 5 )); then rc8_minutes=5; fi
  echo "ATLAS_SETUP_MINUTES=${rc8_minutes}" >> "$GITHUB_ENV"
}
