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

import json
import os
import re
from typing import Any, Dict, List, Optional

# Live-collect sidecar (Plan A / Tier-2 #6): collect() persists {command: "timing_fallback"}
# per device dir for every capture that fell back to netmiko send_command_timing (prompt
# never confirmed -> completeness unproven). The offline loader builds cmd_to_file from
# KNOWN command names, so this sidecar can never be mistaken for a capture. Coverage-honest
# by construction: a collection with NO meta file (everything collected before this
# feature) simply makes no prompt-verification claim.
CAPTURE_META_FILENAME = "_capture_meta.json"

# A pager prompt at the tail (paging not disabled / capture cut): '--More--', ' --More-- ',
# '--More(35%)--', '-- More --', '<--- More --->' — case-insensitive.
_PAGER_RE = re.compile(r"--\s*more\b.*?--|<-+\s*more\s*-+>", re.IGNORECASE)

# A genuine CLI error STARTS the line (e.g. '% Invalid input detected at ...'). Anchoring as a line-prefix
# avoids flagging the same phrase when it appears inside config DATA (a description / banner / ACL remark).
_CLI_ERRORS = ("% invalid input", "% incomplete command", "% ambiguous command", "% unknown command",
               "% type help", "% bad", "% authorization failed", "% error",
               # authz denials the capture-integrity tripwire must also disclose (audit-6 coverage-honesty):
               # NX-OS RBAC banner + IOS/NX-OS per-command authz failure (neither starts with the existing
               # '% authorization failed' / '% error' markers). startswith-matched, so anchored + safe.
               "% permission denied for the role", "command authorization failed")


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


_STATUS_ORDER = {"error": 0, "incomplete": 1, "empty": 2, "unverified_prompt": 3}


def _finding(host: str, command: str, r: Dict[str, Any]) -> dict:
    return {"host": host, "command": command, "status": r["status"], "reason": r["reason"],
            "evidence": r["evidence"], "citation": "%s::%s" % (host, command)}


def _package(findings: List[dict]) -> Dict[str, Any]:
    """Shared result shape for both feed APIs: severity-sorted findings + summary."""
    findings.sort(key=lambda f: (_STATUS_ORDER.get(f["status"], 9), f["host"], f["command"]))
    summary = {
        "n_findings": len(findings),
        "n_incomplete": sum(1 for f in findings if f["status"] == "incomplete"),
        "n_error": sum(1 for f in findings if f["status"] == "error"),
        "n_empty": sum(1 for f in findings if f["status"] == "empty"),
        "n_unverified_prompt": sum(1 for f in findings if f["status"] == "unverified_prompt"),
        "n_hosts_affected": len({f["host"] for f in findings}),
    }
    return {"findings": findings, "summary": summary}


def load_capture_meta(dev_dir: str) -> Dict[str, str]:
    """The device dir's collection sidecar ({command: "timing_fallback"}), or {} when
    absent/corrupt — fail-soft: a broken sidecar never breaks analysis, it just means
    no prompt-verification claim can be made."""
    try:
        p = os.path.join(dev_dir or "", CAPTURE_META_FILENAME)
        if not os.path.isfile(p):
            return {}
        with open(p, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else {}
    except Exception:
        return {}


def compute_capture_integrity(host_cmd_bodies: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    """Inspect every collected body -> {findings:[non-ok only], summary:{…}}.

    `host_cmd_bodies` is {host: {command: body_text}}. Returns one finding per non-ok body, each with a
    citation; the summary counts each status class and the number of distinct affected hosts.
    """
    findings: List[dict] = []
    for host, cmds in (host_cmd_bodies or {}).items():
        for command, body in (cmds or {}).items():
            r = inspect_capture(command, body)
            if r["status"] != "ok":
                findings.append(_finding(host, command, r))
    return _package(findings)


def compute_capture_integrity_from_paths(
        host_cmd_paths: Dict[str, Dict[str, str]],
        host_cmd_meta: Optional[Dict[str, Dict[str, str]]] = None) -> Dict[str, Any]:
    """The widened pipeline feed (Plan A / Tier-2 #6): inspect EVERY collected capture —
    {host: {command: FILE_PATH}} (all_cmd_to_files), streamed ONE body at a time so the
    whole fleet's raw output (hundreds of MB) is never held in memory at once.

    A missing/unreadable file is SKIPPED (not-collected is Collection Completeness's
    domain — no verdict is fabricated about a body never seen). `host_cmd_meta`
    ({host: {command: "timing_fallback"}}, from the per-device sidecar) adds the
    weaker `unverified_prompt` finding for captures whose body LOOKS ok but whose
    prompt was never confirmed; a visibly-broken body keeps its stronger primary
    status. No meta -> no prompt claim (coverage-honest for older collections)."""
    findings: List[dict] = []
    meta_all = host_cmd_meta or {}
    for host, cmd_paths in (host_cmd_paths or {}).items():
        host_meta = meta_all.get(host) or {}
        for command, path in (cmd_paths or {}).items():
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    body = f.read()
            except Exception:
                continue                     # not collected/readable -> completeness's domain
            r = inspect_capture(command, body)
            if r["status"] != "ok":
                findings.append(_finding(host, command, r))
            elif host_meta.get(command) == "timing_fallback":
                findings.append(_finding(host, command, {
                    "status": "unverified_prompt",
                    "reason": "captured via the send_command_timing fallback — the device "
                              "prompt was never confirmed, so an ok-looking body may still "
                              "be silently truncated; treat as unproven-complete",
                    "evidence": "collection sidecar: timing_fallback",
                }))
    return _package(findings)
