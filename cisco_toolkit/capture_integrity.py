"""Per-config-body capture-integrity guard (roadmap K1) — offline, read-only, coverage-honest.

`compute_collection_completeness` tiers a device by essential-command FILE PRESENCE, not body integrity
(analyze.py:1188). So a `show running-config` that returned *some* text but was cut off mid-stream — a
dropped session, paging not disabled, a wrong-mode CLI error — scores 'complete', and every finding
derived from it can silently pass. Oxidized's single most-reported real-world failure is exactly this
class (debug shows the full config; the store keeps only part).

This guard inspects each already-collected command body for truncation / pager / CLI-error signatures and
returns an `[INCOMPLETE]`/`error`/`empty` status with the tripwire it fired on — so a partial capture can
be made to ABSTAIN downstream (the absence-is-not-health rule) instead of being scored as healthy. Pure
text inspection; no device contact, no LLM.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# A pager prompt at the tail (paging not disabled / capture cut): '--More--', ' --More-- ',
# '--More(35%)--', '-- More --', '<--- More --->' — case-insensitive.
_PAGER_RE = re.compile(r"--\s*more\b.*?--|<-+\s*more\s*-+>", re.IGNORECASE)

# A genuine CLI error STARTS the line (e.g. '% Invalid input detected at ...'). Anchoring as a line-prefix
# avoids flagging the same phrase when it appears inside config DATA (a description / banner / ACL remark).
_CLI_ERRORS = ("% invalid input", "% incomplete command", "% ambiguous command", "% unknown command",
               "% type help", "% bad", "% authorization failed", "% error")


def _is_full_config_dump(command: str) -> bool:
    """True only for a BARE, full `show running-config` / `startup-config` (the kind that ends with 'end').
    A piped/scoped/interface-filtered dump emits only the matched lines (no 'end'), so it returns False."""
    c = (command or "").strip().lower()
    if "|" in c:
        return False
    if c in ("show run", "sh run"):
        return True
    for key in ("running-config", "startup-config"):
        if key in c:
            return c.split(key, 1)[1].strip() in ("", "all", "full", "view full")   # scope token => filtered, not full
    return False


def inspect_capture(command: str, body: str) -> Dict[str, Any]:
    """One collected command body -> {status, reason, evidence}.

    status: 'ok' | 'incomplete' (truncated/paginated) | 'error' (CLI error in capture) | 'empty'.
    Tuned against false positives (NX-OS/IOS-XR emit no terminating 'end'; a scoped/filtered dump has none;
    a pager/error phrase inside config DATA is not a real artifact) while still catching real truncation."""
    text = body or ""
    if not text.strip():
        return {"status": "empty", "reason": "no output captured", "evidence": ""}

    meaningful = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    last_few = meaningful[-5:]

    # A real pager prompt is the LAST thing a paginated capture printed — not mid-body banner/description text.
    if meaningful and _PAGER_RE.search(meaningful[-1]):
        return {"status": "incomplete", "reason": "pager artifact at the tail — paging not disabled or capture cut",
                "evidence": meaningful[-1].strip()[:120]}
    # A real CLI error begins the line.
    for ln in meaningful:
        low = ln.lstrip().lower()
        for marker in _CLI_ERRORS:
            if low.startswith(marker):
                return {"status": "error", "reason": "CLI error in capture: %s" % marker, "evidence": ln.strip()[:120]}

    if _is_full_config_dump(command):
        # NX-OS / IOS-XR 'show running-config' do NOT emit a column-0 'end' (that is an IOS/IOS-XE convention),
        # so only require 'end' for an IOS-style dump, and tolerate a trailing prompt echo after it.
        is_nxos = any(l.lstrip().lower().startswith(("!command:", "!running configuration", "!time:")) for l in meaningful)
        if not is_nxos and not any(l.strip().lower() == "end" for l in last_few):
            return {"status": "incomplete",
                    "reason": "IOS-style running-config has no terminating 'end' near the tail — body looks truncated",
                    "evidence": meaningful[-1].strip()[:120] if meaningful else ""}

    return {"status": "ok", "reason": "", "evidence": ""}


def compute_capture_integrity(host_cmd_bodies: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """Inspect every collected body -> {findings:[non-ok only], summary:{…}}.

    `host_cmd_bodies` is {host: {command: body_text}}. Returns one finding per non-ok body, each with a
    citation; the summary counts incomplete / error / empty and the number of distinct affected hosts.
    """
    findings: List[dict] = []
    affected: set = set()
    for host, cmds in (host_cmd_bodies or {}).items():
        for command, body in (cmds or {}).items():
            r = inspect_capture(command, body)
            if r["status"] == "ok":
                continue
            affected.add(host)
            findings.append({
                "host": host, "command": command, "status": r["status"], "reason": r["reason"],
                "evidence": r["evidence"], "citation": "%s::%s" % (host, command),
            })
    findings.sort(key=lambda f: ({"error": 0, "incomplete": 1, "empty": 2}.get(f["status"], 9), f["host"], f["command"]))
    summary = {
        "n_findings": len(findings),
        "n_incomplete": sum(1 for f in findings if f["status"] == "incomplete"),
        "n_error": sum(1 for f in findings if f["status"] == "error"),
        "n_empty": sum(1 for f in findings if f["status"] == "empty"),
        "n_hosts_affected": len(affected),
    }
    return {"findings": findings, "summary": summary}
