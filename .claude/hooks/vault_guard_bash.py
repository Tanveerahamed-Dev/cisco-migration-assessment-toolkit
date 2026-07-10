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
- BEST-EFFORT string matching, not proof. Obfuscation evades it: shell variables
  (V=/c/vaults; ... $V/brain/x), base64/-EncodedCommand, interpreter one-liners
  (python -c "open('C:/Vaults/brain/x','w')"), git worktrees/aliases, relative paths
  after an earlier cd. The hard floor remains the default permission mode + human
  prompt (CLAUDE.md trust boundary).
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
# backslashes -> slashes, runs of slashes collapsed): c:/vaults/brain (also covers
# C:\Vaults\brain and \\?\C:\Vaults\brain) and /c/vaults/brain (MSYS/Git-Bash; also the
# tail of //c/... and /cygdrive/c/...). The trailing guard keeps siblings like
# C:\Vaults\brainstorm or brain-archive out.
_VAULT_RE = re.compile(r"(?:c:/|/c/)vaults/brain(?![0-9a-z_-])")

# Redirection whose target lands in the vault: > >> 2> &> >| , with or without spaces
# or quotes before the path (`cat > /c/Vaults/brain/x`, `echo x>>c:/vaults/brain/log`).
_REDIR_RE = re.compile(r"(?:\d|&)?>{1,2}\|?\s*\S*?(?:c:/|/c/)vaults/brain")

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
)
# Boundaries: no word char / dot / dash before (so `a.md`, `x-rm`, `scp` don't trip the
# shorter tokens they contain), no word char / dash after (so `rm` doesn't match inside
# `rmdir` — which has its own entry — but `rm.exe` still matches).
_TOKEN_RES = tuple(
    (tok, re.compile(r"(?<![\w.\-])" + re.escape(tok) + r"(?![\w\-])"))
    for tok in _WRITE_TOKENS
)

# sed writes only in-place; plain sed is a read. Loose on purpose: -i, -i.bak, -ri,
# --in-place[=.bak] all match (any dash-flag containing an i while sed is present).
_SED_RE = re.compile(r"(?<![\w.\-])sed(?![\w\-])")
_SED_INPLACE_RE = re.compile(r"(?:^|\s)-{1,2}[a-z]*i")


def _normalize(command):
    s = str(command or "").lower().replace("\\", "/")
    return re.sub(r"/{2,}", "/", s)  # \\?\C:\... and //c/... collapse onto the patterns


def classify(command):
    """Return a short block reason when *command* shows write/delete intent against
    the vault, else None. Pure function on the command string — never executes it."""
    s = _normalize(command)
    if not _VAULT_RE.search(s):
        return None
    if _REDIR_RE.search(s):
        return "output redirection into the vault"
    for tok, tok_re in _TOKEN_RES:
        if tok_re.search(s):
            return "write-capable command '%s' in a vault-referencing command" % tok
    if _SED_RE.search(s) and _SED_INPLACE_RE.search(s):
        return "in-place sed (-i) in a vault-referencing command"
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
