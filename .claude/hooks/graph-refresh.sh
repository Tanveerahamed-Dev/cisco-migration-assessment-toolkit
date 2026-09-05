#!/usr/bin/env bash
# Stop hook — keep the graphify knowledge graph fresh.
# If repository state or committed HEAD changed since the last clean receipt, run
# one guarded `graphify update .`
# (AST-only, no API cost) so codebase queries stay accurate. This is MAINTENANCE,
# not a gate: it ALWAYS exits 0 (fail-open) — a stale or un-updatable graph must
# never block a turn. The guard itself fails closed before graph mutation unless
# the reviewed Graphifyy 0.9.51 JSON extractor can be corrected in memory.
set -u

# Git environment overrides can redirect identity reads. The tracked guard owns
# all Git execution; this shell finds only a direct .git directory by walking
# physical parents and never invokes Git itself.
for _name in $(compgen -e); do
  case "${_name^^}" in GIT_*) unset "$_name" ;; esac
done

TIMEOUT=$(command -v timeout || true)
if [ -z "$TIMEOUT" ]; then
  echo "graph-refresh: timeout is unavailable; graph not mutated because the single-worker refresh cannot be bounded — allowing stop (fail-open)." >&2
  exit 0
fi

repo_root=$(pwd -P 2>/dev/null || true)
if [ -z "$repo_root" ]; then
  echo "graph-refresh: physical working directory is unavailable; graph not mutated and may be stale — allowing stop (fail-open)." >&2
  exit 0
fi
while :; do
  if [ -e "$repo_root/.git" ] || [ -L "$repo_root/.git" ]; then
    if [ ! -d "$repo_root/.git" ] || [ -L "$repo_root/.git" ]; then
      echo "graph-refresh: direct repository root is unavailable; graph not mutated and may be stale — allowing stop (fail-open)." >&2
      exit 0
    fi
    break
  fi
  parent=${repo_root%/*}
  [ -n "$parent" ] || parent=/
  if [ "$parent" = "$repo_root" ]; then
    echo "graph-refresh: repository root is unavailable; graph not mutated and may be stale — allowing stop (fail-open)." >&2
    exit 0
  fi
  repo_root=$parent
done
cd "$repo_root" || exit 0

# Nothing to update if the graph was never built.
[ -f graphify-out/graph.json ] || exit 0

# Resolve an interpreter only when the tracked guard's full probe passes. `command -v
# python` alone accepts the Microsoft Store stub; a bare import probe would also accept
# the reviewed version with the faulty extractor still active.
RUNNER="$PWD/tools/graphify_guarded.py"
if [ ! -f "$RUNNER" ]; then
  echo "graph-refresh: tools/graphify_guarded.py is missing; graph not mutated and may be stale — allowing stop (fail-open)." >&2
  exit 0
fi

PY=""
if [ -f graphify-out/.graphify_python ]; then
  _p=$(head -c 512 graphify-out/.graphify_python 2>/dev/null | tr -d '\r\n')
  if [ -n "$_p" ] && [ -x "$_p" ] && "$TIMEOUT" --kill-after=2s 15s "$_p" -I -B "$RUNNER" --probe >/dev/null 2>&1; then
    PY="$_p"
  fi
fi
for _c in python python3; do
  [ -n "$PY" ] && break
  _p=$(command -v "$_c" 2>/dev/null) || continue
  if "$TIMEOUT" --kill-after=2s 15s "$_p" -I -B "$RUNNER" --probe >/dev/null 2>&1; then PY="$_p"; break; fi
done
if [ -z "$PY" ] && command -v py >/dev/null 2>&1; then
  for _v in -3.12 -3; do
    _p=$("$TIMEOUT" --kill-after=2s 15s py "$_v" -I -c "import sys; print(sys.executable)" 2>/dev/null) || continue
    if [ -n "$_p" ] && [ -x "$_p" ] && "$TIMEOUT" --kill-after=2s 15s "$_p" -I -B "$RUNNER" --probe >/dev/null 2>&1; then
      PY="$_p"; break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "graph-refresh: guard probe failed (requires graphifyy 0.9.51 and json_config.py SHA-256 d15ea6d9b48cc71e73615c44c72808562ad4a1dbc82d5a340e3ad0c2fb4fc945); graph not mutated and may be stale — allowing stop (fail-open)." >&2
  exit 0
fi

# Derive HEAD and clean/dirty state only through the guarded Git boundary. The
# third field binds the exact bounded porcelain bytes used for endpoint drift
# comparison; malformed or unsafe Git/index/filter/submodule state fails open
# here without running Graphify.
if ! identity=$("$TIMEOUT" --kill-after=2s 15s "$PY" -I -B "$RUNNER" --identity 2>/dev/null); then
  echo "graph-refresh: guarded repository identity is unavailable; graph not mutated and may be stale — allowing stop (fail-open)." >&2
  exit 0
fi
IFS=$'\t' read -r head state status_digest extra <<< "$identity"
if [[ ! "$head" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] || \
   [[ "$state" != clean && "$state" != dirty ]] || \
   [[ ! "$status_digest" =~ ^[0-9a-f]{64}$ ]] || [ -n "${extra:-}" ]; then
  echo "graph-refresh: guarded repository identity is malformed; graph not mutated and may be stale — allowing stop (fail-open)." >&2
  exit 0
fi

RECEIPT="$PWD/graphify-out/.guarded_refresh.json"
LOCK="$PWD/graphify-out/.guarded_refresh.lock"
LOCK_OWNER=""

# Serialize the full pending -> producer -> endpoint check -> complete transaction,
# not merely Graphify's inner graph write. A live/current lock is fail-open/no-mutation.
# A transaction older than ten minutes (well beyond every inner/outer deadline) is
# moved aside before recovery; owner tokens prevent an older shell's EXIT trap from
# removing a successor's lock (ABA), while the producer's OS lock prevents overlap.
if ! mkdir "$LOCK" 2>/dev/null; then
  now=$(date +%s 2>/dev/null || echo 0)
  lock_mtime=$(stat -c %Y "$LOCK" 2>/dev/null || echo "$now")
  lock_age=$((now - lock_mtime))
  if [ "$now" -gt 0 ] && [ "$lock_age" -gt 600 ]; then
    stale_lock="$LOCK.stale.$$.$now"
    # Move an expired object out of the lock name, but never dereference or
    # delete beneath it: ignored output may contain a hostile symlink/junction.
    mv "$LOCK" "$stale_lock" 2>/dev/null || true
  fi
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "graph-refresh: another guarded refresh owns the receipt transaction; graph not mutated — allowing stop (fail-open)." >&2
    exit 0
  fi
fi
lock_now=$(date +%s 2>/dev/null || echo 0)
LOCK_OWNER="$$:$lock_now:$head"
if ! printf '%s %s\n' "$$" "$LOCK_OWNER" > "$LOCK/owner"; then
  rmdir "$LOCK" 2>/dev/null || true
  echo "graph-refresh: could not record lock ownership; graph not mutated — allowing stop (fail-open)." >&2
  exit 0
fi
log=""
cleanup() {
  [ -n "$log" ] && rm -f "$log"
  if [ -f "$LOCK/owner" ] && IFS=' ' read -r _ cleanup_owner < "$LOCK/owner" && \
     [ "$cleanup_owner" = "$LOCK_OWNER" ]; then
    rm -f "$LOCK/owner" 2>/dev/null || true
    rmdir "$LOCK" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# A complete clean receipt is the only no-op state. A dirty receipt deliberately
# never suppresses a later clean refresh at the same HEAD (edit -> refresh -> revert).
if [ "$state" = clean ]; then
  "$TIMEOUT" --kill-after=2s 15s "$PY" -I -B "$RUNNER" --receipt-status "$RECEIPT" "$head" clean \
    >/dev/null 2>&1
  [ "$?" -eq 0 ] && exit 0
fi

# Mark pending before Graphify can replace any output. Timeout/failure leaves this
# marker intact, so a later Stop retries instead of trusting ambiguous partial state.
"$TIMEOUT" --kill-after=2s 15s "$PY" -I -B "$RUNNER" --receipt-pending "$RECEIPT" "$head" "$state" \
  >/dev/null 2>&1
if [ "$?" -ne 0 ]; then
  echo "graph-refresh: could not record pending refresh; graph not mutated — allowing stop (fail-open)." >&2
  exit 0
fi

if ! log=$(mktemp 2>/dev/null); then
  echo "graph-refresh: could not create a private update log; graph not mutated — allowing stop (fail-open)." >&2
  exit 0
fi

# Bound the run so a slow rebuild can never wedge the turn.
"$TIMEOUT" --kill-after=5s 180s "$PY" -I -B "$RUNNER" update . >"$log" 2>&1
rc=$?

if [ "$rc" -ne 0 ]; then
  echo "graph-refresh: guarded 'graphify update .' exited $rc (graph may be stale) — allowing stop (fail-open)." >&2
  if [ -s "$log" ]; then
    echo "graph-refresh: bounded producer log tail follows:" >&2
    tail -c 2048 "$log" 2>/dev/null | sed 's/^/graph-refresh: | /' >&2 || true
  fi
  exit 0
fi

# Finalize only if the hook observes the same guarded identity at both endpoints. This
# does not exclude an external writer changing and restoring bytes during extraction;
# the receipt is local bookkeeping, not a signed source-to-output attestation.
if ! after_identity=$("$TIMEOUT" --kill-after=2s 15s "$PY" -I -B "$RUNNER" --identity 2>/dev/null); then
  echo "graph-refresh: refresh finished but repository state could not be re-read; receipt remains pending — allowing stop (fail-open)." >&2
  exit 0
fi
if [ "$after_identity" != "$identity" ]; then
  echo "graph-refresh: repository changed during refresh; receipt remains pending for the next Stop — allowing stop (fail-open)." >&2
  exit 0
fi
"$TIMEOUT" --kill-after=2s 15s "$PY" -I -B "$RUNNER" --receipt-complete "$RECEIPT" "$head" "$state" \
  >/dev/null 2>&1
if [ "$?" -ne 0 ]; then
  echo "graph-refresh: refresh finished but its receipt could not be finalized; the next Stop will retry — allowing stop (fail-open)." >&2
fi
exit 0
