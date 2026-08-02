"""KEV Phase-B — per-device upgrade targets: join PSIRT *fixed* releases to device *current* releases.

This module closes the Phase-B loop the KEV-remediation deliverables mark **parameter-pending**
(`docs/security/kev-remediation-nrfu-2026-07-07.md` UP-1/UP-2; `…-mop-2026-07-07.md` §6 `TARGET_RELEASE`).
Given the hash-checked intel feed's per-CVE ``fixed`` releases (from ``research_lane`` ⟶ :mod:`cisco_toolkit.intel_feed`),
the device roster (``devices[host].sw_version`` + the exposure groups in
``docs/security/kev-exposure-2026-07-07-devices.json``), and the CVE→exposure-group mapping (grounded in the
verified finding), it emits per-device ``{host, current, target, needs_upgrade}`` rows.

**Security-critical & conservative by mandate.** A *wrong* target is worse than none — it either leaves a
device vulnerable (target too low) or forces a needless/impossible upgrade (target on the wrong train). So the
comparator is **fail-closed** and **train-aware**:

* Cisco releases are compared **only within an identical train** (the same upgrade line). A rebuild bump on the
  device's own train (``6.0(2)N2(3)`` → ``6.0(2)N2(4)``; ``17.9.3`` → ``17.9.4a``) is a confident target.
* A fix that exists only on a *different* train (``03.06.06E`` device, fix on ``17.9.x``) is a **train
  migration** — a platform/design decision, not a mechanical bump — so the device is flagged
  ``needs_upgrade = "MANUAL-VERIFY"``, never auto-assigned a cross-train target.
* Any release string the parser does not recognize → ``MANUAL-VERIFY`` (never a naive string/tuple compare).
* No ``fixed`` intel for an applicable CVE (the current real state until the credential-gated openVuln sweep
  runs) → ``target = None``, ``needs_upgrade = "TARGET-PENDING"``. Absence is absence, never "already patched".

The version model is consistent with the engine's train taxonomy (:func:`cisco_toolkit.analyze._swrisk_train`)
but adds the *within-train ordering* that lifecycle-banding does not need. Pure-stdlib, deterministic, never
raises on bad input (it returns ``MANUAL-VERIFY``, the safe direction).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# --- CVE → exposure-group applicability (grounded in the verified finding) ----------------------------
# docs/security/kev-exposure-2026-07-07.md carved these out with platform-correctness (proposer≠verifier):
# the two KEV CVE families are IOS/IOS-XE, NOT NX-OS — the NX-OS members of the same engine screening-groups
# are *screening artifacts*, not CVE exposure. We encode that carve-out as data so the join stays honest.
#
# The hard platform gate is "exclude NX-OS" — reliable because the snapshot vocabulary is {ios, nxos}
# (kev-exposure header: "ios 198, nxos 105"); IOS-XE devices are labelled `ios`, so gating strictly on an
# 'ios-xe' string would wrongly drop every XE device. The finer classic-IOS-vs-IOS-XE correctness (does an
# IOS-XE-specific fix really apply to THIS box?) is left to the train-aware comparator: a classic-IOS release
# vs an IOS-XE fix is cross-train → MANUAL-VERIFY (a human confirms), never a silently-dropped or wrong target.
CVE_EXPOSURE_MAP: Dict[str, Dict[str, Any]] = {
    "CVE-2018-0171": {"group": "smart_install_flagged", "applies_to": ("ios", "ios-xe"),
                      "surface": "Smart Install (vstack)"},
    "CVE-2023-20198": {"group": "http_server_flagged", "applies_to": ("ios", "ios-xe"),
                       "surface": "IOS-XE Web UI (ip http server)"},
    "CVE-2023-20273": {"group": "http_server_flagged", "applies_to": ("ios", "ios-xe"),
                       "surface": "IOS-XE Web UI (ip http server)"},
}

# needs_upgrade sentinels — a tri-state+ field, NOT a bool (bool True/False are the confident answers).
MANUAL_VERIFY = "MANUAL-VERIFY"     # comparator uncertain — a human must pick the target (fail-closed)
TARGET_PENDING = "TARGET-PENDING"   # no fixed-version intel loaded for an applicable CVE (coverage-honest)
NOT_APPLICABLE = "NOT-APPLICABLE"   # CVE does not apply to this platform (positively confirmed)


# =====================================================================================================
# Part 1 — the Cisco version comparator (the hard, security-critical core)
# =====================================================================================================

@dataclass(frozen=True)
class CiscoVersion:
    """A parsed Cisco release. ``train_key`` identifies the *upgrade line* — two versions are directly
    comparable **iff** their ``train_key`` are equal; ``rebuild_key`` then orders within that line. This
    split is the whole safety story: we never compare ``rebuild_key`` across differing trains."""
    family: str                       # 'ios' | 'ios-xe' | 'nxos'
    train_key: Tuple[Any, ...]        # equal ⇒ same upgrade line (else: a migration, not a bump)
    rebuild_key: Tuple[Any, ...]      # within-train ordering; only meaningful when train_key matches
    normalized: str                   # canonical string form (for display / de-dup)
    raw: str = field(default="", compare=False)

    def same_train(self, other: "CiscoVersion") -> bool:
        return self.family == other.family and self.train_key == other.train_key


def _letter_rank(letter: str) -> int:
    """Rebuild sub-letter ordering: '' < 'a' < 'b' < …  (``17.3.4`` precedes the ``17.3.4a`` respin)."""
    letter = (letter or "").strip().lower()
    return (ord(letter) - ord("a") + 1) if len(letter) == 1 and letter.isalpha() else 0


def _rebuild_tuple(num: str, letter: str) -> Tuple[int, int]:
    return (int(num) if num and num.isdigit() else 0, _letter_rank(letter))


# Regexes are anchored + strict on purpose: an unrecognized shape must FALL THROUGH to None (→ MANUAL-VERIFY),
# never be force-fit. Each returns a CiscoVersion or None.

_RE_IOS_XE_1617 = re.compile(r"^(1[67])\.(\d{1,2})\.(\d{1,2})([a-z]?)$")            # 16.12.4 / 17.03.04 / 17.9.4a
_RE_IOS_XE_3X = re.compile(r"^0?3\.(\d{1,2})\.(\d{1,2})([a-z]?)\.?([a-zA-Z]{0,2})$")  # 03.06.06E / 03.11.03a.E
_RE_IOS_CLASSIC = re.compile(r"^(\d{1,2})\.(\d{1,2})\((\d{1,3})\)([A-Za-z]{1,4})(\d{0,3})([a-z]?)$")  # 15.2(2)E7
_RE_NXOS_PLAT = re.compile(r"^(\d{1,2})\.(\d{1,2})\((\d{1,3})\)([A-Za-z]+\d*)\((\d{1,3})([a-z]?)\)$")  # 6.0(2)N2(3)
_RE_NXOS_BARE = re.compile(r"^(\d{1,2})\.(\d{1,2})\((\d{1,3})([a-z]?)\)$")            # 9.3(10) / 9.3(7)


def _parse_ios_xe_1617(s: str) -> Optional[CiscoVersion]:
    m = _RE_IOS_XE_1617.match(s)
    if not m:
        return None
    major, minor, patch, letter = int(m[1]), int(m[2]), int(m[3]), m[4]
    return CiscoVersion("ios-xe", ("ios-xe", major, minor), _rebuild_tuple(str(patch), letter),
                        f"{major}.{minor}.{patch}{letter}", s)


def _parse_ios_xe_3x(s: str) -> Optional[CiscoVersion]:
    m = _RE_IOS_XE_3X.match(s)
    if not m:
        return None
    minor, rebuild, sub, train_letter = int(m[1]), int(m[2]), m[3], (m[4] or "E").upper()
    # 3.x epoch is numbered 03.MM.RR; the trailing letter (E=Enterprise, S=SP) is the sub-train. Keep it in
    # the train_key so 03.06.xxE and a hypothetical 03.06.xxS are (correctly) different upgrade lines.
    return CiscoVersion("ios-xe", ("ios-xe", 3, minor, train_letter), _rebuild_tuple(str(rebuild), sub),
                        f"03.{minor:02d}.{rebuild:02d}{sub}.{train_letter}", s)


def _parse_ios_classic(s: str) -> Optional[CiscoVersion]:
    m = _RE_IOS_CLASSIC.match(s)
    if not m:
        return None
    major, minor, build, letters, reb_num, reb_let = int(m[1]), int(m[2]), int(m[3]), m[4].upper(), m[5], m[6]
    # The maintenance branch is major.minor(build)+train-letters (e.g. 15.2(2)E). We deliberately do NOT
    # treat 15.2(2)E and 15.2(4)E as the same line — different (build) is a different branch → MANUAL-VERIFY.
    return CiscoVersion("ios", ("ios", major, minor, build, letters), _rebuild_tuple(reb_num, reb_let),
                        f"{major}.{minor}({build}){letters}{reb_num}{reb_let}", s)


def _parse_nxos(s: str) -> Optional[CiscoVersion]:
    m = _RE_NXOS_PLAT.match(s)
    if m:
        major, minor, maint, plat, reb, reb_let = int(m[1]), int(m[2]), int(m[3]), m[4].upper(), m[5], m[6]
        return CiscoVersion("nxos", ("nxos", major, minor, maint, plat), _rebuild_tuple(reb, reb_let),
                            f"{major}.{minor}({maint}){plat}({reb}{reb_let})", s)
    m = _RE_NXOS_BARE.match(s)
    if m:
        major, minor, reb, reb_let = int(m[1]), int(m[2]), m[3], m[4]
        return CiscoVersion("nxos", ("nxos", major, minor), _rebuild_tuple(reb, reb_let),
                            f"{major}.{minor}({reb}{reb_let})", s)
    return None


def _looks_nxos(s: str) -> bool:
    return bool(_RE_NXOS_PLAT.match(s) or _RE_NXOS_BARE.match(s))


def parse_version(raw: Any, *, platform_hint: Optional[str] = None) -> Optional[CiscoVersion]:
    """Parse a Cisco release string into a :class:`CiscoVersion`, or return ``None`` when the shape is not
    recognized (the caller treats ``None`` as MANUAL-VERIFY — the safe direction). ``platform_hint`` (the
    device's ``platform``: 'ios'/'ios-xe'/'nxos') disambiguates the two paren-bearing families
    (NX-OS ``6.0(2)N2(3)`` vs classic IOS ``15.2(2)E7``)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in ("(not captured)", "(unknown)"):
        return None
    p = (platform_hint or "").strip().lower()

    if p == "nxos":                                     # a platform hint is authoritative for the paren cases
        return _parse_nxos(s)
    if p in ("ios", "ios-xe", "iosxe", "ios xe"):
        return (_parse_ios_classic(s) or _parse_ios_xe_3x(s) or _parse_ios_xe_1617(s))

    # No usable hint: dispatch by structure. NX-OS's double-paren / bare-paren forms are distinctive; classic
    # IOS always carries train LETTERS after its single paren, so the two paren families don't collide.
    if _looks_nxos(s) and not _RE_IOS_CLASSIC.match(s):
        return _parse_nxos(s)
    return (_parse_ios_classic(s) or _parse_ios_xe_3x(s) or _parse_ios_xe_1617(s) or _parse_nxos(s))


def compare_same_train(a: CiscoVersion, b: CiscoVersion) -> Optional[int]:
    """Order two releases **on the same train**: -1 if a<b, 0 if equal, 1 if a>b. Returns ``None`` when they
    are NOT on the same train — the caller must not treat that as an ordering (it's a migration decision)."""
    if not a.same_train(b):
        return None
    return (a.rebuild_key > b.rebuild_key) - (a.rebuild_key < b.rebuild_key)


# =====================================================================================================
# Part 2 — the per-device target decision
# =====================================================================================================

def choose_target(current: Any, fixed: List[Any], *, platform_hint: Optional[str] = None) -> Dict[str, Any]:
    """Decide the upgrade target for ONE device against ONE CVE's ``fixed`` list.

    Returns ``{current, target, needs_upgrade, reason, same_train_fixes, cross_train_fixes,
    unparsed_fixes}`` where ``needs_upgrade`` ∈ ``{True, False, MANUAL_VERIFY, TARGET_PENDING}``:

    * ``True``  — current is behind the (single) same-train fix; ``target`` = that fix.
    * ``False`` — current already >= the (single) same-train fix; ``target`` = the met fix (for the record).
    * ``MANUAL_VERIFY`` — current unparseable; OR fixes exist but none is on the device's train (a migration);
      OR **>= 2 distinct fixed releases land on the device's own train** (ambiguous which is required — a MIN
      would under-target and leave it vulnerable, a MAX could force a needless upgrade, so neither is asserted);
      OR **any entry of the same ``fixed`` list is unrecognized** — it could be a same-train release ABOVE the
      one we can read, and asserting the readable one would ship a remediation MOP whose TARGET_RELEASE is
      still vulnerable. That is the module contract stated at the top of this file ("Any release string the
      parser does not recognize -> MANUAL-VERIFY"), applied to the ``fixed`` list and not only to ``current``.
    * ``TARGET_PENDING`` — no (parseable) fixed release supplied at all.

    Every unrecognized entry is DISCLOSED in ``unparsed_fixes`` (and named in ``reason``) — it is never
    silently dropped just because a sibling entry parsed.
    """
    cur = parse_version(current, platform_hint=platform_hint)
    fixed_list = [f for f in (fixed or []) if f]
    if not fixed_list:
        return _row(current, None, TARGET_PENDING, "no fixed-version intel for this CVE (sweep not run)")
    if cur is None:
        return _row(current, None, MANUAL_VERIFY,
                    f"current release {str(current)!r} not recognized by the comparator -- verify by hand",
                    )
    parsed_fixes = [(f, parse_version(f, platform_hint=platform_hint)) for f in fixed_list]
    unparsed = [str(f) for f, pv in parsed_fixes if pv is None]
    same_by_norm = {pv.normalized: pv for _, pv in parsed_fixes if pv is not None and pv.same_train(cur)}
    same_norms = sorted(same_by_norm)
    cross_train = sorted({pv.normalized for _, pv in parsed_fixes if pv is not None and not pv.same_train(cur)})

    if not same_by_norm:
        # Fixes exist but land on other trains (or none parsed) -> a migration / hand check, never a guess.
        why = ("no fix on the device's train -- the published fix is a different train (migration is a "
               "platform/design decision, not a mechanical upgrade)") if cross_train else \
              ("no fixed release could be parsed" + (f" ({', '.join(unparsed)})" if unparsed else ""))
        return _row(current, None, MANUAL_VERIFY, why, same_train=[], cross_train=cross_train,
                    unparsed=unparsed)

    if unparsed:
        # An entry of the SAME fixed list the comparator cannot read. It may well be a release on THIS
        # device's train and ABOVE the one that parsed (the openVuln feed mixes prose-y and per-platform
        # forms), so asserting the readable fix as the target would ship a TARGET_RELEASE that is still
        # vulnerable -- and the earlier code discarded it silently the moment any sibling parsed, which
        # also defeated the >=2-same-train-fixes ambiguity guard below. Fail closed, and NAME it.
        return _row(current, None, MANUAL_VERIFY,
                    f"{len(unparsed)} fixed release(s) not recognized by the comparator "
                    f"({', '.join(unparsed)}) alongside same-train fix(es) ({', '.join(same_norms)}) -- "
                    f"an unread entry could be a higher fix on this train; verify by hand",
                    same_train=same_norms, cross_train=cross_train, unparsed=unparsed)

    if len(same_by_norm) > 1:
        # >=2 DISTINCT fixed releases on the device's own train (e.g. a CVE re-referenced by an amended
        # advisory whose fixed list the feed unions). Asserting either bound is unsafe -> defer to a human.
        return _row(current, None, MANUAL_VERIFY,
                    f"{len(same_by_norm)} distinct fixed releases on the device's train "
                    f"({', '.join(same_norms)}) -- ambiguous which is required; verify by hand",
                    same_train=same_norms, cross_train=cross_train)

    only_fix = next(iter(same_by_norm.values()))               # the one unambiguous same-train fix
    cmp = compare_same_train(cur, only_fix)
    if cmp is not None and cmp >= 0:                            # current already at/above the fix -> patched
        return _row(current, cur.normalized, False,
                    f"current {cur.normalized} >= same-train fix {only_fix.normalized}",
                    same_train=same_norms, cross_train=cross_train)
    return _row(current, only_fix.normalized, True,
                f"current {cur.normalized} < same-train fix {only_fix.normalized}",
                same_train=same_norms, cross_train=cross_train)


def _row(current: Any, target: Optional[str], needs: Any, reason: str,
         same_train: Optional[List[str]] = None, cross_train: Optional[List[str]] = None,
         unparsed: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"current": (str(current) if current not in (None, "") else None), "target": target,
            "needs_upgrade": needs, "reason": reason,
            "same_train_fixes": same_train or [], "cross_train_fixes": cross_train or [],
            "unparsed_fixes": unparsed or []}


def _merge_host_decision(decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a host's per-CVE decisions into one upgrade target. The target must satisfy EVERY applicable
    CVE, so: if any CVE is MANUAL_VERIFY → the host is MANUAL_VERIFY (can't certify coverage); else if any is
    TARGET_PENDING → TARGET_PENDING; else target = the highest same-train first-fix across CVEs (the release
    that clears them all), and needs_upgrade = True iff any CVE needs it."""
    if not decisions:
        return _row(None, None, TARGET_PENDING, "no applicable CVE")
    if any(d["needs_upgrade"] == MANUAL_VERIFY for d in decisions):
        d = next(d for d in decisions if d["needs_upgrade"] == MANUAL_VERIFY)
        return {**d, "needs_upgrade": MANUAL_VERIFY}
    if any(d["needs_upgrade"] == TARGET_PENDING for d in decisions):
        d = next(d for d in decisions if d["needs_upgrade"] == TARGET_PENDING)
        return {**d, "needs_upgrade": TARGET_PENDING}
    # All confident (True/False). Pick the max target so it clears every CVE on the shared train.
    current = decisions[0]["current"]
    parsed = [parse_version(d["target"]) for d in decisions if d.get("target")]
    valid: List[CiscoVersion] = [t for t in parsed if t is not None]
    needs = any(d["needs_upgrade"] is True for d in decisions)
    if not valid:
        return {**decisions[0], "needs_upgrade": bool(needs)}
    # All these targets are on the device's train (they came from same-train first-fixes), so max is safe.
    best = max(valid, key=lambda v: v.rebuild_key)
    return _row(current, best.normalized, bool(needs),
                "aggregate of applicable CVEs (target clears the highest same-train first-fix)",
                same_train=sorted({s for d in decisions for s in d["same_train_fixes"]}),
                cross_train=sorted({s for d in decisions for s in d["cross_train_fixes"]}),
                unparsed=sorted({u for d in decisions for u in d.get("unparsed_fixes") or []}))


# =====================================================================================================
# Part 3 — the join: feed `fixed` × device current version × CVE→device mapping
# =====================================================================================================

def _platform_family(platform: Any) -> Optional[str]:
    """Coarse platform family for CVE-applicability gating — ``'nxos'`` | ``'ios'`` | ``None`` (unknown).

    NX-OS is the only family we positively EXCLUDE on (the KEV CVEs are IOS-family); ``ios`` / ``ios-xe`` /
    ``iosxe`` / ``"ios xe"`` all collapse to ``'ios'`` (the classic-vs-XE distinction is the *comparator's* job,
    not a hard drop). An empty string or the engine's ``'?'`` sentinel (``analyze.py`` sets
    ``"platform": platform or "?"``) → ``None`` = **unknown**, which must NOT be treated as not-applicable —
    "not observed" is never "not vulnerable". An unrecognized non-NX-OS token is likewise ``None`` (unknown),
    never a silent drop."""
    p = str(platform or "").strip().lower()
    if not p or p == "?":
        return None
    if "nx-os" in p or "nxos" in p or p == "nexus":
        return "nxos"
    if "ios" in p:                                             # ios, ios-xe, iosxe, "ios xe", "cisco ios"
        return "ios"
    return None


def _fixed_by_cve(advisories: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Collapse the loaded feed to ``{CVE: [fixed releases]}`` (union across advisory entries for that CVE).
    Only entries that actually carry a ``fixed`` list contribute — a KEV-only entry (no ``fixed``) does not
    fabricate one."""
    out: Dict[str, set] = {}
    for a in advisories or []:
        cve = a.get("id")
        fx = a.get("fixed")
        if not cve or not fx:
            continue
        fx = [fx] if isinstance(fx, str) else list(fx)
        out.setdefault(str(cve), set()).update(str(f).strip() for f in fx if str(f).strip())
    return {k: sorted(v) for k, v in out.items()}


def build_upgrade_targets(advisories: List[Dict[str, Any]], device_versions: Dict[str, Dict[str, Any]],
                          device_groups: Dict[str, Any], *,
                          cve_map: Optional[Dict[str, Dict[str, Any]]] = None,
                          feed_refusals: Optional[List[str]] = None) -> Dict[str, Any]:
    """Join the feed's per-CVE ``fixed`` releases to each affected device's current release.

    * ``advisories`` — verified feed entries (from :func:`cisco_toolkit.intel_feed.load_feeds`); ``fixed`` used.
    * ``device_versions`` — ``{host: {sw_version, platform, model?, train?, train_band?}}`` (see
      :func:`device_versions_from_snapshot` / :func:`device_versions_from_devices_json`).
    * ``device_groups`` — the exposure-group roster (``kev-exposure-*-devices.json``): ``{group: [hosts]}``.
    * ``cve_map`` — CVE→{group, applies_to, surface}; defaults to :data:`CVE_EXPOSURE_MAP`.

    Returns ``{rows, summary, coverage}``. ``rows`` is one aggregated ``{host, current, target,
    needs_upgrade, model, platform, cves, reason, …}`` per affected+version-known device.
    """
    cve_map = cve_map or CVE_EXPOSURE_MAP
    fixed_by_cve = _fixed_by_cve(advisories)

    # host -> list of per-CVE decisions (only for CVEs that apply to the host's platform)
    per_host_cves: Dict[str, List[str]] = {}
    per_host_decisions: Dict[str, List[Dict[str, Any]]] = {}
    na_hosts: Dict[str, List[str]] = {}                       # host -> CVEs skipped as not-applicable
    version_unknown: Dict[str, List[str]] = {}                # affected but no current version → not a row
    unknown_platform: set = set()

    for cve, spec in cve_map.items():
        group = str(spec.get("group") or "")
        # applicability is gated by FAMILY, not exact-string membership: the CVE applies to these families,
        # and we drop a host only when its family is POSITIVELY known and outside that set (i.e. NX-OS). An
        # unknown/'?' platform is never positively dropped — it flows through as applicable-but-flagged.
        applies_families = {f for f in (_platform_family(a) for a in spec.get("applies_to", ())) if f}
        hosts = device_groups.get(group) or []
        for host in hosts:
            meta = device_versions.get(host) or {}
            platform = str(meta.get("platform") or "").strip().lower()
            fam = _platform_family(platform)
            if fam is not None and applies_families and fam not in applies_families:
                na_hosts.setdefault(host, []).append(cve)     # positively-confirmed not-applicable (e.g. NX-OS)
                continue
            sw = str(meta.get("sw_version") or "").strip()
            if not sw or sw in ("(not captured)", "(unknown)"):
                version_unknown.setdefault(host, []).append(cve)  # coverage gap — cannot target without a version
                continue
            if fam is None:
                unknown_platform.add(host)                    # can't confirm applicability without a platform
            decision = choose_target(sw, fixed_by_cve.get(cve, []), platform_hint=platform or None)
            per_host_decisions.setdefault(host, []).append(decision)
            per_host_cves.setdefault(host, []).append(cve)

    rows: List[Dict[str, Any]] = []
    for host in sorted(per_host_decisions):
        meta = device_versions.get(host) or {}
        merged = _merge_host_decision(per_host_decisions[host])
        rows.append({
            "host": host, "model": meta.get("model") or None,
            "platform": (meta.get("platform") or None), "train": meta.get("train"),
            "train_band": meta.get("train_band"),
            "current": merged["current"], "target": merged["target"],
            "needs_upgrade": merged["needs_upgrade"], "reason": merged["reason"],
            "cves": sorted(per_host_cves[host]),
            "same_train_fixes": merged["same_train_fixes"], "cross_train_fixes": merged["cross_train_fixes"],
            "unparsed_fixes": merged.get("unparsed_fixes") or [],   # never silently dropped intel
        })
    rows.sort(key=lambda r: (_needs_rank(r["needs_upgrade"]), r["host"]))

    summary = {
        "n_rows": len(rows),
        "needs_upgrade": sum(1 for r in rows if r["needs_upgrade"] is True),
        "already_current": sum(1 for r in rows if r["needs_upgrade"] is False),
        "manual_verify": sum(1 for r in rows if r["needs_upgrade"] == MANUAL_VERIFY),
        "target_pending": sum(1 for r in rows if r["needs_upgrade"] == TARGET_PENDING),
        "not_applicable_hosts": len(na_hosts),
        "version_unknown_hosts": len(version_unknown),
        "cves_with_fixed": sorted(fixed_by_cve),
        "cves_without_fixed": sorted(c for c in cve_map if c not in fixed_by_cve),
    }
    coverage = {
        "not_applicable": {h: sorted(cves) for h, cves in sorted(na_hosts.items())},
        "version_unknown": {h: sorted(cves) for h, cves in sorted(version_unknown.items())},
        "unknown_platform": sorted(unknown_platform),
        "note": _coverage_note(summary, cve_map, feed_refusals),
        # Surfaced, never swallowed: a feed the intake REFUSED is not a feed that was absent.
        "feed_refusals": list(feed_refusals or ()),
    }
    return {"rows": rows, "summary": summary, "coverage": coverage}


def _needs_rank(needs: Any) -> int:
    return {True: 0, MANUAL_VERIFY: 1, TARGET_PENDING: 2, False: 3}.get(needs, 4)


def _coverage_note(summary: Dict[str, Any], cve_map: Dict[str, Any],
                   feed_refusals: Optional[List[str]] = None) -> str:
    if not summary["cves_with_fixed"]:
        # A REFUSED feed and an ABSENT feed produce the same empty advisory list, and this note used
        # to describe both as "the sweep has not run" — so a refused critical-RCE advisory read as a
        # lane nobody had wired yet. Say which one actually happened; the operator's next action is
        # completely different (fix the feed vs run the sweep).
        if feed_refusals:
            return ("no CVE carries a fixed-version because the intake REFUSED "
                    f"{len(feed_refusals)} feed(s) -- this is NOT an unrun sweep, and the advisories "
                    "in those feeds were never assessed: "
                    + "; ".join(feed_refusals[:3])
                    + ("; ..." if len(feed_refusals) > 3 else "")
                    + ". Every affected device is TARGET-PENDING, not 'already patched'.")
        return ("no CVE carries a fixed-version yet -- the credential-gated Cisco PSIRT/openVuln sweep "
                "(P5) has not run; every affected device is TARGET-PENDING, not 'already patched'.")
    parts = [f"{summary['needs_upgrade']} need upgrade", f"{summary['already_current']} already current",
             f"{summary['manual_verify']} MANUAL-VERIFY (cross-train/unparseable)",
             f"{summary['target_pending']} TARGET-PENDING (no fixed intel)"]
    return "; ".join(parts)


# =====================================================================================================
# Part 4 — device current-version extraction (two channels: snapshot preferred, devices-json fallback)
# =====================================================================================================

def device_versions_from_snapshot(snap: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract ``{host: {sw_version, model, platform, train, train_band}}`` from an engine snapshot —
    ``devices[host]`` for version/model/platform, ``software_risk.per_device[host]`` for train/train_band."""
    out: Dict[str, Dict[str, Any]] = {}
    devices = (snap or {}).get("devices") or {}
    if isinstance(devices, dict):
        for host, d in devices.items():
            if not isinstance(d, dict):
                continue
            out[host] = {"sw_version": d.get("sw_version"), "model": d.get("model"),
                         "platform": d.get("platform")}
    sr = ((snap or {}).get("software_risk") or {}).get("per_device") or []
    for d in sr if isinstance(sr, list) else []:
        if isinstance(d, dict) and d.get("host"):
            row = out.setdefault(d["host"], {})
            row.setdefault("sw_version", d.get("sw_version"))
            row.setdefault("platform", d.get("platform"))
            row["train"] = d.get("train")
            row["train_band"] = d.get("train_band")
    return out


_RE_DEVJSON_INLINE = re.compile(r"^(?P<host>.*?)\s*\[(?P<label>.+)\]\s*$")


def device_versions_from_devices_json(groups: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Recover device current-versions from the exposure-group JSON's ``replace_upgrade_train`` entries,
    which embed ``host [<train label> <version>]`` (e.g. ``"AS01-… [IOS XE 3.x 03.06.06E]"``). This is the
    fallback when the engine snapshot is not on disk (it is an engagement artifact, often gitignored). The
    platform is inferred from the train label (``NX-OS`` → nxos, ``IOS XE`` → ios-xe, else classic ios). Only
    ``replace_upgrade_train`` carries inline versions; other groups list bare hostnames (not derivable here)."""
    out: Dict[str, Dict[str, Any]] = {}
    for entry in (groups.get("replace_upgrade_train") or []):
        m = _RE_DEVJSON_INLINE.match(str(entry))
        if not m:
            out[str(entry).strip()] = {"sw_version": None, "platform": None}
            continue
        host = m.group("host").strip()
        label = m.group("label").strip()
        toks = label.split()
        version = toks[-1] if toks else ""
        train_label = " ".join(toks[:-1]) if len(toks) > 1 else label
        low = label.lower()
        platform = "nxos" if ("nx-os" in low or "nxos" in low) else ("ios-xe" if "xe" in low else "ios")
        out[host] = {"sw_version": version, "platform": platform, "train": train_label,
                     "train_band": "Replace/Upgrade"}
    return out


# =====================================================================================================
# Part 5 — render + CLI
# =====================================================================================================

def render(result: Dict[str, Any]) -> str:
    s, cov = result["summary"], result["coverage"]
    L = [f"KEV Phase-B upgrade targets -- {cov['note']}",
         f"  rows: {s['n_rows']}  |  need-upgrade: {s['needs_upgrade']}  already-current: {s['already_current']}"
         f"  MANUAL-VERIFY: {s['manual_verify']}  TARGET-PENDING: {s['target_pending']}"]
    if s["cves_without_fixed"]:
        L.append(f"  CVEs without a fixed-version in the feed: {', '.join(s['cves_without_fixed'])}")
    if cov["not_applicable"]:
        L.append(f"  not-applicable (platform-correct, positively confirmed): {len(cov['not_applicable'])} host(s)")
    if cov["version_unknown"]:
        L.append(f"  version-unknown (affected but no current version -> cannot target): "
                 f"{len(cov['version_unknown'])} host(s)")
    L.append("")
    for r in result["rows"]:
        nu = r["needs_upgrade"]
        tag = {True: "UPGRADE", False: "current", MANUAL_VERIFY: "MANUAL-VERIFY",
               TARGET_PENDING: "TARGET-PENDING"}.get(nu, str(nu))
        tgt = f" -> {r['target']}" if r["target"] else ""
        L.append(f"  [{tag:>14}] {r['host']}  ({r['current'] or '?'}{tgt})  {', '.join(r['cves'])}")
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI — read-only, no egress. Verify the intel feed, load the device roster, and print per-device
    upgrade targets::

        python -m cisco_toolkit.upgrade_targets [--intel-dir docs/intel] \
            [--devices docs/security/kev-exposure-2026-07-07-devices.json] [<snapshot.json>] [--json]

    With a snapshot, current-versions come from the snapshot (all groups). Without one, they come from the
    devices-json ``replace_upgrade_train`` inline versions (the coverage the committed repo can reproduce)."""
    import json
    import sys
    from cisco_toolkit.intel_feed import engagement_identifiers, load_feeds

    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    def _opt(name: str, default: str = "") -> str:
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    intel_dir = _opt("--intel-dir", "docs/intel")
    dev_json = _opt("--devices", "docs/security/kev-exposure-2026-07-07-devices.json")
    as_json = "--json" in argv
    snap_path = next((a for a in argv if not a.startswith("-")
                      and a not in (intel_dir, dev_json)), None)

    try:
        with open(dev_json, encoding="utf-8") as handle:
            groups = json.load(handle)
    except Exception as e:
        print(f"could not read device roster {dev_json!r}: {e!r}")
        return 2

    if snap_path:
        try:
            with open(snap_path, encoding="utf-8") as handle:
                snap = json.load(handle)
            device_versions = device_versions_from_snapshot(snap)
        except Exception as e:
            print(f"could not read snapshot {snap_path!r}: {e!r}")
            return 2
    else:
        snap = None
        device_versions = device_versions_from_devices_json(groups)

    denylist = engagement_identifiers(groups, snap)
    # Keep the REFUSALS, not just the advisories. Discarding them made a refused feed
    # indistinguishable from an absent one, and the renderer says "the credential-gated Cisco
    # PSIRT/openVuln sweep (P5) has not run" — so a refused critical-RCE advisory was reported as a
    # lane that was never wired. `self_healing.advisory_remediation` already surfaces `[REFUSED]`
    # lines; this was the single exit that dropped them.
    _feeds = load_feeds(intel_dir, forbidden=denylist, require_forbidden=True)
    advisories = _feeds.get("advisories", [])
    feed_refusals = [
        f"{r.get('feed', '?')}: {r.get('reason', 'refused')}"
        for r in (_feeds.get("refused") or [])
    ]
    result = build_upgrade_targets(advisories, device_versions, groups,
                                   feed_refusals=feed_refusals)
    print(json.dumps(result, indent=2, sort_keys=True) if as_json else render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
