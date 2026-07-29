"""Decision logic for .claude/hooks/vault-guard-bash.sh (P0-8 — ADR 0001, shell lane).

vault-guard.sh closes the Write|Edit|NotebookEdit lane of the two-store boundary
(docs/decisions/0001-two-store-knowledge-architecture.md: repo sessions NEVER write the
personal vault at C:\\Vaults\\brain). This module closes the *shell* lane: a Bash or
PowerShell tool call whose command string shows WRITE/DELETE intent against the vault
is blocked before it runs (previously `cat > /c/Vaults/brain/x`, tee/cp/mv/rm/sed -i,
Set-Content/Out-File/Remove-Item all bypassed the guard entirely).

Contract (pinned by tests/test_vault_guard_bash.py):
- classify(command) -> short reason string when the command must be BLOCKED, else None.
- main() reads the PreToolUse hook JSON on stdin and prints "BLOCK:<reason>" to stdout
  for a block, nothing otherwise. It NEVER raises and always exits 0 — any internal
  error means fail-open (the .sh wrapper only exits 2 on an explicit BLOCK verdict),
  so a hook bug can never wedge a turn.

Scope & honesty (declared, not hidden — session-handoff HR-005 residuals (a)/(b)):
- BEST-EFFORT string matching, not proof. The hard floor remains the default permission
  mode + human prompt (CLAUDE.md trust boundary).
- MEASURED residuals (2026-07-29, 82 candidate command strings driven through classify()):
  four spellings still pass, and they are the honest limit of string matching --
  (1) interpreter one-liners, `python -c "open('C:/Vaults/brain/x','w')"` and
  `node -e "...writeFileSync(...)"`: the write verb lives inside a quoted program, not
  in shell position; (2) `~/../../Vaults/brain/x`, which only reaches the vault when
  HOME sits exactly two levels under the drive root -- resolving it needs the
  environment, not the string; (3) base64 / -EncodedCommand payloads; (4) a path ACROSS separate
  tool calls (cd in one, a relative write in the next) -- this module sees one command
  string at a time and cannot hold shell state.
  NB the COMPOUND forms of the classic evasions do NOT pass, contrary to what this note
  claimed before it was tested: `cd /c/vaults/brain && cp x a.md` and
  `V=c:/vaults/brain; cp x $V/a.md` both BLOCK, because the recall-over-precision token
  rule only needs the path and a write verb to appear in the same string.
  Also REFUTED by measurement, not assumed: the Windows 8.3 short-name bypass
  (`C:\\VAULTS~1\\brain`). `Vaults` (6 chars) and `brain` (5) are already 8.3-legal, so the
  filesystem generates NO alias for either -- verified with `dir /x`, where a 16-char
  sibling got `VAULTS~1` and `Vaults` got a blank short-name column. There is no short
  spelling of this path to miss.
- Recall over precision INSIDE the gate: a command that both references the vault path
  and contains any write-capable token is blocked even if the write targets elsewhere
  (e.g. `diff /c/vaults/brain/a b && cp b /tmp/`) — split such commands to proceed.
  Commands that never mention the vault path are never touched.
- READS stay out of scope: `ls /c/Vaults/brain` passes this hook. ADR 0001's
  reads-not-granted rule remains prose, per the P0-8 task boundary.
"""
from __future__ import annotations

import json
import re
import sys

# The vault root in every spelling this repo has seen, after normalization (lowercase,
# backslashes -> slashes, runs of slashes collapsed). Three drive spellings cover them all:
#   c:  ->  C:\Vaults\brain, \\?\C:\Vaults\brain, \\.\C:\Vaults\brain
#   /c  ->  /c/vaults/brain (MSYS/Git-Bash), //c/..., and the tail of /cygdrive/c/...
#   c$  ->  the UNC ADMIN share \\host\C$\Vaults\brain, \\127.0.0.1\C$\..., and
#           \\?\UNC\host\C$\... (the host name collapses to a leading segment)
# The drive spelling is REQUIRED, deliberately. Matching a bare `/vaults/brain` would also
# catch any unrelated directory that happens to be named .../Vaults/brain — measured, not
# theorised: an earlier draft of this line blocked a scratch dir at
# <temp>/t83/Vaults/brain during this file's own test run. Over-blocking is the right
# side of the trade only while the block still means something.
# The trailing guard keeps siblings like C:\Vaults\brainstorm or brain-archive out.
_VAULT_BODY = r"(?:c:|c\$|/c)/vaults/brain"
_VAULT_RE = re.compile(_VAULT_BODY + r"(?![0-9a-z_-])")

# Redirection whose target lands in the vault: > >> 2> &> >| , with or without spaces
# or quotes before the path (`cat > /c/Vaults/brain/x`, `echo x>>c:/vaults/brain/log`).
_REDIR_RE = re.compile(r"(?:\d|&)?>{1,2}\|?\s*\S*?" + _VAULT_BODY)

# Write/delete-capable command words (unix, cmd.exe, PowerShell incl. common aliases).
# Matched as standalone words anywhere in a vault-referencing command — argument-position
# parsing of shell text is exactly where evasion lives, so precision is traded for recall
# (see module docstring). Read commands (ls/cat/grep/head/diff/...) are deliberately
# absent so vault reads pass.
_WRITE_TOKENS = (
    # unix / coreutils
    "rm", "rmdir", "unlink", "shred", "mv", "cp", "scp", "sftp", "install",
    "rsync", "dd", "tee", "touch", "truncate", "mkdir", "ln",
    # cmd.exe builtins / windows tools
    "del", "erase", "move", "copy", "xcopy", "robocopy", "md", "rd",
    "ren", "rename", "mklink",
    # PowerShell cmdlets (the spec'd Set-Content/Out-File/Remove-Item + same family)
    "set-content", "add-content", "clear-content", "out-file", "tee-object",
    "new-item", "remove-item", "move-item", "copy-item", "rename-item",
    "set-item", "export-csv", "export-clixml",
    # PowerShell aliases of the above with a single unambiguous meaning
    "ri", "ni", "sc", "clc", "cpi", "mi", "rni",
    # fetch-to-file: writes the vault AND egresses. `curl -o`, `wget -O`, `iwr -OutFile`.
    "curl", "wget", "invoke-webrequest", "iwr", "start-bitstransfer",
    # archive create/extract with a destination inside the vault
    "tar", "unzip", "7z", "7za", "expand-archive", "compress-archive",
    # in-place patching
    "patch",
    # VCS. `git` is listed WHOLE, not per-subcommand: `git -C <vault> checkout -- .`,
    # `clean -fdx`, `reset --hard` and `clone <vault>` each destroy or overwrite vault
    # content, and subcommand parsing of shell text is exactly the evasion surface this
    # module refuses to enter. Over-blocks `git -C <vault> log` (a read) — accepted, same
    # trade as the `diff ... && cp` case in the docstring; split the command to proceed.
    "git",
    # metadata / ACL writes (not content, but still a mutation of vault state)
    "attrib", "icacls", "takeown",
)
# Boundaries: no word char / dot / dash before (so `a.md`, `x-rm`, `scp` don't trip the
# shorter tokens they contain), no word char / dash after (so `rm` doesn't match inside
# `rmdir` — which has its own entry — but `rm.exe` still matches).
_TOKEN_RES = tuple(
    (tok, re.compile(r"(?<![\w.\-])" + re.escape(tok) + r"(?![\w\-])"))
    for tok in _WRITE_TOKENS
)

# Destructive intent carried by a FLAG rather than a command word. `find <vault> -delete`
# is the motivating case: the `del` token cannot match inside `-delete` because the token
# boundary deliberately excludes a leading dash (so `x-rm` does not trip `rm`).
_FLAG_WRITE_RE = re.compile(r"(?:^|\s)-{1,2}(?:delete|outfile|destinationpath)(?![\w\-])")

# sed writes only in-place; plain sed is a read. Loose on purpose: -i, -i.bak, -ri,
# --in-place[=.bak] all match (any dash-flag containing an i while sed is present).
_SED_RE = re.compile(r"(?<![\w.\-])sed(?![\w\-])")
_SED_INPLACE_RE = re.compile(r"(?:^|\s)-{1,2}[a-z]*i")

# `.` / `..` segment removal, applied as an ADDITIONAL candidate spelling (never in place
# of the raw one), so resolving dots can only ever ADD a block, never remove one.
# C:\Vaults\other\..\brain\x and C:\Users\..\Vaults\brain\x are the vault; the raw string
# does not contain the literal prefix, the resolved one does.
_DOT_SEG_RE = re.compile(r"/\.(?=/)")
_DOTDOT_SEG_RE = re.compile(r"/(?!\.\.?(?:/|$))[^/\s]+/\.\.(?=/|$)")


def _normalize(command):
    s = str(command or "").lower().replace("\\", "/")
    return re.sub(r"/{2,}", "/", s)  # \\?\C:\... and //c/... collapse onto the patterns


def _resolve_dots(s):
    """Collapse `/./` and `/<seg>/../` inside the command string. Bounded iteration —
    a pathological input can never spin."""
    out = s
    for _ in range(24):
        prev = out
        out = _DOTDOT_SEG_RE.sub("", _DOT_SEG_RE.sub("", out))
        if out == prev:
            break
    return out


def _classify_one(s):
    if not _VAULT_RE.search(s):
        return None
    if _REDIR_RE.search(s):
        return "output redirection into the vault"
    for tok, tok_re in _TOKEN_RES:
        if tok_re.search(s):
            return "write-capable command '%s' in a vault-referencing command" % tok
    if _FLAG_WRITE_RE.search(s):
        return "destructive flag (-delete/-OutFile/-DestinationPath) targeting the vault"
    if _SED_RE.search(s) and _SED_INPLACE_RE.search(s):
        return "in-place sed (-i) in a vault-referencing command"
    return None


def classify(command):
    """Return a short block reason when *command* shows write/delete intent against
    the vault, else None. Pure function on the command string — never executes it.

    Checked against BOTH the normalized command and its dot-resolved spelling; a hit in
    either blocks, so the extra spelling is strictly additive to recall."""
    s = _normalize(command)
    for cand in (s, _resolve_dots(s)):
        reason = _classify_one(cand)
        if reason:
            return reason
        if cand == s and _resolve_dots(s) == s:
            break  # no dots to resolve — don't re-scan the identical string
    return None


def main():
    try:
        data = json.load(sys.stdin)
        tool_input = data.get("tool_input") or {}
        reason = classify(tool_input.get("command"))
        if reason:
            sys.stdout.write("BLOCK:" + reason)
    except Exception:
        pass  # fail-open: print nothing, wrapper allows the call
    return 0


if __name__ == "__main__":
    sys.exit(main())
