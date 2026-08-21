"""Derive a dashboard summary from a raw engine snapshot.

This is a *read-only projection* of the snapshot the engine already computed — it never re-runs
analysis. It rolls the headline numbers (re-using the engine's own `_trend_point`) plus the
breakdowns the cockpit needs: health bands, punch-list by severity/category, keystone devices by
blast radius, readiness, and which detail sections actually carry data (so the UI hides empty tabs).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import engine  # noqa: F401  (also bootstraps sys.path for the cisco_toolkit import below)
from . import protocol_portfolio
from cisco_toolkit import registry_integrity

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Info"]
_SEV_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}
BANDS = ["Excellent", "Good", "Fair", "Poor", "Critical"]


def _as_list(v: Any) -> List[Any]:
    """Coerce a snapshot section to a list. `(snap.get(k) or [])` only guards falsy values; a truthy
    NON-list (an int/str/dict in a malformed or hostile upload) would flow into a list-comprehension and
    raise TypeError -- summarize() runs on every upload, so that escapes as an HTTP 500. Returning [] for a
    non-list degrades gracefully, honouring this function's `Every field degrades gracefully` contract."""
    return v if isinstance(v, list) else []


def _hkey(v: Any) -> Any:
    """A HASHABLE form of a snapshot leaf that is about to be used as a dict key or as the left operand
    of an `in <dict>` / `<dict>.get(...)` lookup.

    The container and per-element guards above check the SHAPE of a section; this guards the LEAF. A
    dict/list where a label is expected (`severity`, `readiness`) is unhashable, and `_SEV_RANK.get(...)`
    / `... in readiness` then raises `TypeError: unhashable type: 'dict'` -- an unhandled HTTP 500. This
    is not academic: `_keystones` is the shared choke point behind THREE unauthenticated read routes
    (summarize -> the dashboard, cutover.build_plan -> /cutover, execution.start_run -> /executions), and
    the snapshot is STORED, so the same upload re-crashes every later read of it.

    Anything already hashable passes through UNCHANGED (real labels are untouched, so no count, order or
    lookup over valid data changes); only an unhashable dict/list is stringified, which no canonical label
    matches -- so it degrades to 'unknown', exactly as an unrecognised string already does."""
    try:
        hash(v)
        return v
    except TypeError:
        return str(v)

# Detail sections the web UI can render as tabs, in display order. (key, human label)
SECTION_LABELS: List[tuple] = [
    ("punchlist", "Punch-list"),
    ("device_dossiers", "Risk register"),     # NEW-V3.23.174 (per-asset compound-risk register)
    ("health_scores", "Health scores"),
    ("failure_impact", "Failure impact"),
    ("link_centrality", "Chokepoints"),
    ("causality", "Causality"),
    ("cross_layer", "Cross-layer"),
    ("migration_readiness", "Readiness"),
    ("wave_sequencing", "Wave sequencing"),
    ("application_intelligence", "Application domains"),
    ("segmentation", "Segmentation"),
    # Release-1 Protocol Assurance is synthesized from the exact persisted snapshot blob at read
    # time.  It is always available as a coverage-honest receipt, including when every family is
    # not verified; the count is the closed executable profile set, never the capability catalog.
    (protocol_portfolio.SECTION_KEY, "Protocol Assurance"),
    ("protocol_health", "Protocols"),
    ("multicast_intelligence", "Multicast / timing"),
    ("remediation_plan", "Remediation"),
    ("validation_plan", "Validation plan"),
    ("golden_drift", "Config drift"),
    # NEW (orchestration-peer wave): the three always-on engines the pipeline now emits. Each is a dict
    # {findings|features:[...], summary} so _section_index counts its inner list (an empty/clean section
    # hides its own tab, the platform convention). capture_integrity with zero findings = a clean estate.
    ("feature_compliance", "Feature compliance"),   # I2 — golden-drift decomposed per policy area
    ("acl_line_reachability", "ACL shadow"),         # G1 — offline ACL line-reachability / shadow proof
    ("capture_integrity", "Capture integrity"),      # K1 — truncation / pager / CLI-error guard
    # the four OPT-IN engines (present only when a flag supplies their input, so a default run hides them):
    ("state_assertions", "State assertions"),        # A1 — declarative check-pack (--assert-pack)
    ("path_intents", "Path intents"),                # G3 — named REACHES/ISOLATED intents (--path-intents)
    ("external_reconcile", "SoT reconcile"),         # B  — declared inventory vs observed (--import-inventory)
    ("whatif", "Failure what-if"),                   # G4 — failure-injection scenarios (--scenario); a LIST
    # NEW-V3.23.176: the V3.23.164-.167 NOS analytic quartet landed after this list was
    # authored and was unreachable from the web platform (neither tab nor whitelist) --
    # the one-source-of-truth audit's only real gap.
    ("syslog_intelligence", "Syslog"),
    ("qos_audit", "QoS posture"),
    ("software_risk", "Software risk"),
    ("platform_health", "Platform health"),
    ("capacity", "Capacity"),
    ("endpoint_identity", "Endpoints"),
    ("lifecycle_risk", "Lifecycle / EoL"),
    ("collection_completeness", "Collection completeness"),
    # Plan A / Tier-1 #3: the zero-parse yield ledger (cmdio.parse_yield_report, published in every
    # snapshot). Lives under the Collection Completeness sheet in the workbook -- same adjacency here.
    # Dict {summary, per_parser, events, events_truncated}: _section_index counts `events` (its first
    # inner list), so a run where every content-bearing command parsed hides the tab (the platform
    # convention) -- telemetry about the PARSER, never a device verdict.
    ("parse_yield", "Parse yield"),
]


def _count_by(items: List[dict], key: str, order: List[str] | None = None) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        v = str(it.get(key, "") or "—")
        out[v] = out.get(v, 0) + 1
    if order:
        ordered = {k: out.get(k, 0) for k in order if k in out}
        for k, v in out.items():  # any value not in the canonical order, appended
            ordered.setdefault(k, v)
        return ordered
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _keystones(snap: Dict[str, Any], top: int = 8) -> List[Dict[str, Any]]:
    """The few devices the fleet most depends on, by migration blast radius.

    Prefer the engine's own executive-brief keystones; else derive from failure_impact
    (stranded endpoints, severity), which is always present."""
    eb = snap.get("executive_brief")
    eb = eb if isinstance(eb, dict) else {}      # a truthy non-dict section must not raise (malformed upload)
    # Validate each ELEMENT is a dict, not just the container: a keystones list carrying a non-dict (a bare
    # string/int in a malformed or hostile upload) is otherwise returned verbatim, and a read route then does
    # k.get("host") on it -> AttributeError -> an unhandled HTTP 500 on /graph (app.py builds its keystone list
    # from this projection). Filtering to dicts degrades gracefully; an all-garbage list falls through to
    # failure_impact below, honouring summarize()'s `Every field degrades gracefully` contract.
    ks = [k for k in eb["keystones"] if isinstance(k, dict)] if isinstance(eb.get("keystones"), list) else []
    if ks:
        return ks[:top]
    fi = [r for r in _as_list(snap.get("failure_impact")) if isinstance(r, dict)]
    # fail-soft: a malformed stranded (the JSON Infinity a raw int() would 500 on) degrades to 0 in the sort
    # key -- this runs on EVERY unauthenticated snapshot upload (POST /snapshots -> summarize).
    fi.sort(key=lambda r: (_SEV_RANK.get(_hkey(r.get("severity", "")), 99),
                           -engine.as_num(r.get("stranded"))))
    return [{
        "host": r.get("host", ""),
        "severity": r.get("severity", ""),
        "stranded": r.get("stranded", 0),
        "vlans_impacted": r.get("vlans_impacted", 0),
        "detail": r.get("detail", ""),
    } for r in fi[:top]]


def _section_index(snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Which detail sections carry data + a count, for tab visibility."""
    out = []
    for key, label in SECTION_LABELS:
        if key == protocol_portfolio.SECTION_KEY:
            out.append({
                "key": key,
                "label": label,
                "count": protocol_portfolio.supported_family_count(),
            })
            continue
        v = snap.get(key)
        if isinstance(v, list):
            count = len(v)
        elif isinstance(v, dict):
            # dict sections: count the most meaningful list inside, else number of keys
            inner = next((x for x in v.values() if isinstance(x, list)), None)
            count = len(inner) if inner is not None else len(v)
        else:
            count = 0
        if count:
            out.append({"key": key, "label": label, "count": count})
    return out


_REQUIRED_DATA_AUTHORITIES = ("oui", "ports", "eol")
SNAPSHOT_PROVENANCE_KEY = "_assesshub_provenance"
LOCAL_ENGINE_ORIGIN = "local-engine"
DIRECT_UPLOAD_ORIGIN = "direct-upload"
VERIFICATION_CONTRACT_VERSION = 3


def snapshot_verification(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Coverage-honest trust state for an engine or uploaded snapshot.

    ``verified`` is intentionally a narrow claim: the server must have stamped the snapshot as the
    result of a locally executed engine run, every required authority must carry the current explicit
    ``source_authoritative: true`` contract, and no analysis phase may have failed.  Client-uploaded
    booleans remain self-reported evidence, never a server attestation.
    """
    provenance_raw = snap.get(SNAPSHOT_PROVENANCE_KEY)
    provenance = provenance_raw if isinstance(provenance_raw, dict) else {}
    origin = provenance.get("origin")
    if origin not in {LOCAL_ENGINE_ORIGIN, DIRECT_UPLOAD_ORIGIN}:
        origin = "legacy-or-unknown"
    locally_attested = origin == LOCAL_ENGINE_ORIGIN
    run_integrity_raw = provenance.get("integrity_verified")
    run_integrity = (
        "verified" if run_integrity_raw is True
        else "failed" if run_integrity_raw is False
        else "unknown"
    )

    integrity_raw = snap.get("assessment_integrity")
    integrity = integrity_raw if isinstance(integrity_raw, dict) else {}
    failed_raw = integrity.get("failed_phases")
    malformed_integrity = failed_raw not in (None, []) and not isinstance(failed_raw, list)
    failed_phases = [
        str(value)[:160]
        for value in (failed_raw if isinstance(failed_raw, list) else [])
        if str(value).strip()
    ][:100]

    authorities_raw = snap.get("data_authorities")
    authorities = authorities_raw if isinstance(authorities_raw, dict) else {}
    missing: List[str] = []
    non_authoritative: List[str] = []
    integrity_failed: List[str] = []
    integrity_unknown: List[str] = []
    for name in _REQUIRED_DATA_AUTHORITIES:
        health = authorities.get(name)
        if not isinstance(health, dict) or "source_authoritative" not in health:
            missing.append(name)
            continue
        # Was `source_authoritative is not True`, which reads the port pack's HONEST mixed-pack
        # false as total registry failure. Effect measured on the real sample snapshot: status
        # "partial", verified false, reason "Known non-source-authoritative data packs: ports."
        # -> VerificationStatus.tsx renders a role="alert" telling the reader not to treat the
        # snapshot as a complete verified assessment, on EVERY healthy run. The §5.2 scoped-
        # authority fix reached serve.py and the engine self-test and missed this exit.
        # One shared predicate now, so the next consumer cannot disagree with the others.
        if not registry_integrity.pack_is_usable(health):
            non_authoritative.append(name)
        if health.get("integrity_verified") is False:
            integrity_failed.append(name)
        elif health.get("integrity_verified") is not True:
            integrity_unknown.append(name)

    reasons: List[str] = []
    if not locally_attested:
        reasons.append(
            "Snapshot origin was not a locally executed engine run; authority fields are "
            "self-reported and cannot establish verified coverage."
        )
    if run_integrity == "unknown":
        reasons.append(
            "Producer run integrity is unknown; no current positive completion attestation was "
            "persisted for this snapshot."
        )
    elif run_integrity == "failed":
        reasons.append(
            "Producer run integrity failed; this snapshot cannot support a verified claim."
        )
    if failed_phases:
        reasons.append(
            f"{len(failed_phases)} analysis phase(s) failed; empty or absent results are not "
            "evidence of health."
        )
    if malformed_integrity:
        reasons.append("assessment_integrity.failed_phases is malformed and cannot be trusted.")
    if missing:
        reasons.append(
            "Missing current source-authority evidence for: " + ", ".join(missing) + "."
        )
    if non_authoritative:
        reasons.append(
            "Known non-source-authoritative data packs: " + ", ".join(non_authoritative) + "."
        )
    if integrity_failed:
        reasons.append(
            "Data-pack byte/schema integrity failed for: " + ", ".join(integrity_failed) + "."
        )
    if integrity_unknown:
        reasons.append(
            "Data-pack integrity is unknown for: " + ", ".join(integrity_unknown) + "."
        )

    if (
        not locally_attested
        or run_integrity != "verified"
        or malformed_integrity
        or missing
        or integrity_unknown
    ):
        status = "unverified"
    elif failed_phases or non_authoritative or integrity_failed:
        status = "partial"
    else:
        status = "verified"
    labels = {
        "verified": "Verified coverage",
        "partial": "Partial coverage",
        "unverified": "Unverified coverage",
    }
    return {
        "contract_version": VERIFICATION_CONTRACT_VERSION,
        "origin": origin,
        "integrity_status": run_integrity,
        "status": status,
        "label": labels[status],
        "verified": status == "verified",
        "coverage_honest": True,
        "reasons": reasons,
        "failed_phases": failed_phases,
        "missing_authorities": missing,
        "non_authoritative_authorities": non_authoritative,
        "integrity_failed_authorities": integrity_failed,
        "integrity_unknown_authorities": integrity_unknown,
    }


# The lifecycle bands the engine publishes as a DETERMINATION. `compute_lifecycle_risk`
# (cisco_toolkit/analyze.py, _LIFECYCLE_BAND_RANK) emits exactly Past-LDoS / Near-LDoS / Past-EoS / Active
# when it could decide, plus "Unknown" when no exact EoX row matched or retained source/date authority
# was insufficient to support a date band.
#
# review r8 F4 -- STRUCTURAL INVERSION. This used to be a regex over not-assessed SPELLINGS
# (unknown|undetermined|insufficient data|n/a|...). That is this repo's most recurrent defect shape: a
# hand-maintained list of NAMES standing in for the class it means. The most likely FUTURE spelling is the
# one nobody wrote down -- and under a spelling list it fell through to "assessed" and was banked as
# health. Classifying against the KNOWN-GOOD vocabulary inverts the default in the safe direction: any
# band this projection does not recognise is NOT ASSESSED, so an unanticipated band is DISCLOSED rather
# than silently counted clean. (CLAUDE.md guardrail 3 -- "not observed" never becomes "healthy".)
_ASSESSED_BANDS = frozenset(("past-ldos", "near-ldos", "past-eos", "active"))


def _is_assessed_band(name: Any) -> bool:
    """True only for a band name the engine emits as a lifecycle DETERMINATION.

    Everything else -- today's "Unknown", a future "Undetermined"/"Not assessed", a typo, a band added by
    a newer engine than this projection knows about -- is not-assessed. Over-disclosure is the safe
    direction here; the reverse is false health."""
    return str(name).strip().lower() in _ASSESSED_BANDS


def _int0(v: Any) -> int:
    """A census count coerced to a non-negative int; anything non-numeric (a malformed upload) is 0."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return max(0, v)
    if isinstance(v, float):
        return max(0, int(v)) if v == v and v not in (float("inf"), float("-inf")) else 0
    try:
        return max(0, int(str(v).strip()))
    except Exception:
        return 0


def _census_int(v: Any) -> Optional[int]:
    """A census count if the value is USABLE as one, else ``None`` -- "no basis", never a silent 0.

    The sibling of `_int0` for the one place the difference matters: deciding whether a figure was
    MEASURED. `_int0` is a renderer's coercion -- it must always yield a number -- but using it to
    answer "did the producer report this?" turns every malformed value into a confident zero, and a
    zero that means "not measured" reading as "nothing wrong" is the exact false-health class this
    module's lifecycle projection exists to close. `None` here is honest ignorance; the caller
    discloses it rather than counting it as a clean result.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float):
        return int(v) if (v == v and v not in (float("inf"), float("-inf")) and v >= 0) else None
    try:
        parsed = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _lifecycle(lr: Dict[str, Any]) -> Dict[str, Any]:
    """Project the engine's hardware-lifecycle census for the dashboard.

    HISTORY (audit U1-1, CRITICAL false-health): this projected exactly three named rollups --
    past_eos / near_eos / past_ldos -- and DROPPED `n_unknown`, the count of devices whose platform
    had no exact EoX row or whose matched row lacked retained source/date authority. An all-Unknown
    fleet therefore serialised to
    `{"past_eos":0,"near_eos":0,"past_ldos":0}`, BYTE-IDENTICAL to a fully-assessed all-Active fleet:
    the browser was structurally incapable of disclosing the gap because the gap never crossed the
    API boundary. The whole `by_band` census now crosses it, so a band the projection does not know
    by name still reaches the UI, and `unknown` is summed over the NOT-ASSESSED CLASS (above)
    rather than off the single `n_unknown` key."""
    _bb = lr.get("by_band")
    by_band: Dict[str, int] = ({str(k): _int0(v) for k, v in _bb.items()}
                               if isinstance(_bb, dict) else {})
    # bands OUTSIDE the engine's assessed vocabulary -- structural, see _is_assessed_band()
    gap_bands = sorted(k for k in by_band if not _is_assessed_band(k))
    derived = sum(by_band[k] for k in gap_bands)

    # SSOT (review r8 F2/F3): `lifecycle_risk.summary.n_unknown` is the OWNER of "how many assets could
    # not be lifecycle-assessed" (docs/ssot.md -- read a fact from its owner; a copy is a cache and must
    # cite the owner). This used to read the owner ONLY when `by_band` was empty and otherwise RE-DERIVE
    # the count by classifying band-name strings, i.e. it ignored the canonical field exactly when that
    # field was best evidenced; and the `if not by_band and not n_unknown:` line that followed was dead,
    # the preceding ternary having already handled it. Owner first, classification as a labelled
    # FALLBACK, and `unknown_source` names which read produced this row's figure.
    # Keyed on whether the owner's value is USABLE, not on whether the key is PRESENT. `_int0` maps
    # null / a string / a dict / a negative to 0, so `"n_unknown" in lr` accepted a malformed value as
    # a measurement of zero: the row then read "assessed, nothing undetermined" off a section that had
    # measured nothing. That is the same fail-open this projection was changed to close, one layer in.
    # An unusable value is NO BASIS -- identical to the key being absent -- and is named as such below.
    owner: Optional[int] = _census_int(lr.get("n_unknown"))
    if owner is None:
        n_unknown = derived
        source = "derived:by_band — owner field lifecycle_risk.summary.n_unknown is absent"
    elif derived > owner:
        # The owner's own census carries not-assessed bands its count does not cover (a newer engine
        # emitting a band this projection has never seen). FAIL CLOSED on the larger gap and name both
        # figures, so the disclosure is never smaller than the evidence in front of us.
        n_unknown = derived
        source = (f"lifecycle_risk.summary.n_unknown={owner}, RAISED to {derived} by by_band band(s) "
                  f"outside the engine's assessed vocabulary: {', '.join(gap_bands)}")
    else:
        n_unknown = owner
        source = "lifecycle_risk.summary.n_unknown"

    n_devices = _int0(lr.get("n_devices")) or sum(by_band.values())
    # Was there any basis at all for counting un-assessed assets? A section publishing neither a band
    # census nor the owner field gives none -- and a 0 that means "NOT MEASURED" must not read as
    # "nothing wrong" (review r8 F6, the silence-as-health half of U1-1). Fail CLOSED: no basis == gap.
    measured = bool(by_band) or owner is not None
    return {
        "past_eos": lr.get("n_past_eos", ""),
        "near_eos": lr.get("n_near", ""),      # canonical Near-LDoS count (was a non-existent n_near_eos -> always blank)
        "past_ldos": lr.get("n_past_ldos", ""),
        "active": lr.get("n_active", ""),
        # --- the coverage-honest half the UI could not previously see ---
        "unknown": n_unknown,
        # provenance of the figure above: the owner's own value, and which read produced `unknown`
        "unknown_reported": owner if owner is not None else "",
        "unknown_source": source,
        "n_devices": n_devices,
        "by_band": by_band,
        "not_assessed_bands": gap_bands,
        # False == the section gave NO basis to count un-assessed assets; `unknown` is then 0 because
        # nothing was measured, not because nothing is wrong.
        "coverage_measured": measured,
        # True == at least one asset's support state was NOT determined, OR nothing was measurable at
        # all. An empty lifecycle risk list is then a COVERAGE GAP, not a clean fleet, and the UI must
        # say so.
        "coverage_gap": bool(n_unknown > 0 or not measured),
        "assessed": max(0, n_devices - n_unknown) if measured else 0,
    }


def summarize(snap: Dict[str, Any]) -> Dict[str, Any]:
    """Headline + breakdowns used by the dashboard cards. Every field degrades gracefully."""
    hs = [r for r in _as_list(snap.get("health_scores")) if isinstance(r, dict)]
    pl = [r for r in _as_list(snap.get("punchlist")) if isinstance(r, dict)]
    mr = [r for r in _as_list(snap.get("migration_readiness")) if isinstance(r, dict)]
    # isinstance-guard, not `or {}`: a TRUTHY non-dict 'devices' (an int in a malformed/hostile upload) survives
    # `or {}` and 500s the eagerly-evaluated `len(...)` default below -- and summarize() runs on EVERY upload
    # (POST /snapshots) and on the /snapshots/{id} read (freshen), so that TypeError escapes as an HTTP 500.
    _dev = snap.get("devices")
    n_devices = len(_dev) if isinstance(_dev, dict) else 0

    try:
        head = engine.trend_point(snap)  # re-use the engine's headline extractor
    except Exception:
        head = {}                        # a malformed upload must degrade, not 500 the dashboard summary

    readiness = {"READY": 0, "CAUTION": 0, "NOT READY": 0}
    for r in mr:
        rd = _hkey(r.get("readiness"))     # an unhashable dict/list readiness label must not 500 the `in`
        if rd in readiness:
            readiness[rd] += 1

    _lr = snap.get("lifecycle_risk")
    _lrs = (_lr if isinstance(_lr, dict) else {}).get("summary")    # a truthy NON-dict summary (e.g. an older
    lr = _lrs if isinstance(_lrs, dict) else {}                     # engine's "not computed" string) must not 500

    return {
        "version": snap.get("script_version", ""),
        # Provenance of THIS projection (the engine build that computed it), distinct from `version`
        # (the snapshot's own collection-time script_version). A cached summary whose stamp trails the
        # running engine is recomputed on read so the headline cards never disagree with a live
        # section tab (app._summary_freshened).
        "engine_schema": engine.ENGINE_SCHEMA_VERSION,
        "n_switches": head.get("n_switches", n_devices),
        "avg_health": head.get("avg_health", ""),
        "bands": _count_by(hs, "band", BANDS),
        # n_critical must reconcile with the bands chart (both from health_scores): trend_point can silently
        # yield 0 when executive_brief is a corrupt non-dict (the try/except above swallows the AttributeError),
        # contradicting the bands chart on the SAME screen -- fall back to the band count (audit-5 cross-artifact #4).
        "n_critical": head.get("n_critical") if isinstance(head.get("n_critical"), int)
        else _count_by(hs, "band", BANDS).get("Critical", 0),
        "punchlist": {
            "total": len(pl),
            "by_severity": _count_by(pl, "severity", SEVERITY_ORDER),
            "by_category": _count_by(pl, "category"),
            "crit_high": head.get("n_crit_high", 0),
        },
        "readiness": readiness,
        "keystones": _keystones(snap),
        "lifecycle": _lifecycle(lr) if lr else {},
        "verification": snapshot_verification(snap),
        "sections": _section_index(snap),
    }
