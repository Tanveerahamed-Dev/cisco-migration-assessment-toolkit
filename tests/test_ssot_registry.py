"""Integrity guard for the project-wide SSOT registry (docs/ssot.md).

The registry is the one index of *where the truth for any fact lives* -- it points to a federated
set of owners (cisco_toolkit/ssot.py, the snapshot, graphify, pyproject.toml, manifest.py, ...) and
its whole value is that those pointers are TRUE. A registry whose pointers have rotted (an owner file
renamed, a symbol removed, a snapshot key the engine no longer publishes, a broken cross-link) is
worse than none: it asserts "the truth is over there" when it isn't.

This is the mechanical enforcement the registry itself calls for (Law 1 / the "correspondence rules"
of ISO/IEC/IEEE 42010 applied to the index): every owner the registry names must resolve to something
that actually exists, checked in CI. It bites the moment a refactor moves an owner without updating
the map. It is deliberately structural -- it asserts on stable anchors (paths, symbol names, snapshot
keys, cross-links), never on prose that legitimately changes.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "ssot.md"
CONTRACT = ROOT / "docs" / "ssot-contract.md"
GRAPHIFY_IGNORE = ROOT / ".graphifyignore"


def _registry_text() -> str:
    assert REGISTRY.exists(), "docs/ssot.md (the project SSOT registry) is missing"
    return REGISTRY.read_text(encoding="utf-8")


def test_registry_exists_and_is_substantive():
    txt = _registry_text()
    assert len(txt) > 1500, "registry is suspiciously small -- likely truncated"
    # Its load-bearing sections must be present.
    for heading in ("The map", "live in two homes", "federation rule", "Adding a new source of truth"):
        assert heading in txt, f"registry is missing its '{heading}' section"


def test_registry_owner_files_all_exist():
    """Every owner FILE the registry leans on must resolve on disk."""
    # __init__.py holds __version__ but is referenced by SYMBOL, not filename (guarded below), so it
    # is existence-only; the rest must exist AND be cited by name (so dropping a row is caught too).
    must_exist = [
        "cisco_toolkit/ssot.py",
        "docs/ssot-contract.md",
        "cisco_toolkit/manifest.py",
        "cisco_toolkit/unknown_evidence.py",
        "cisco_toolkit/traffic_assurance.py",
        "CHANGELOG.md",
        "pyproject.toml",
        "cisco_toolkit/__init__.py",
        # the freshness guard: four registry rows cite it as their enforcement (2026-07-10)
        "tests/test_registry_freshness.py",
        # the DEC-007 holdout policy owner + its mechanics module (P1-2, 2026-07-10)
        "docs/quality/holdout-contract.md",
        "cisco_toolkit/holdout.py",
        # deliverable-set completeness: the row's enforcement IS this reconciler, so the row and
        # the guard have to fall together or not at all (2026-07-22)
        "tests/test_docmeta_cli_artifacts.py",
        # governed aggregate-only unknown-evidence owner + its privacy/totality reconciler
        "tests/test_unknown_evidence.py",
        "tests/test_traffic_assurance.py",
        "tests/test_traffic_assurance_excel.py",
        # Release 2.0 proof-carrying transition structural-contract owners.
        "cisco_toolkit/transition_contract.py",
        "cisco_toolkit/transition_pack.py",
        "cisco_toolkit/transition_verifier.py",
        "cisco_toolkit/transition_legacy.py",
        "cisco_toolkit/transition_dsl.py",
        "cisco_toolkit/transition_tcb_review.py",
        "cisco_toolkit/transition_runtime_closure.py",
        "cisco_toolkit/transition_runtime_discovery.py",
        "cisco_toolkit/_transition_runtime_debug.py",
        "cisco_toolkit/transition_workload_review.py",
    ]
    cited_by_name = [p for p in must_exist if not p.endswith("__init__.py")]
    txt = _registry_text()
    missing_on_disk = [p for p in must_exist if not (ROOT / p).exists()]
    assert not missing_on_disk, f"registry names owners that do not exist on disk: {missing_on_disk}"
    not_cited = [p for p in cited_by_name if p.rsplit("/", 1)[-1] not in txt]
    assert not not_cited, f"owner files exist but are not cited in the registry: {not_cited}"


def test_registry_owner_symbols_are_real():
    """The symbols the registry leans on (the assessment-facts contract, the version, the ledger)
    must exist in the code it points at -- import them / read them, don't trust the prose."""
    from cisco_toolkit import detector_schema, manifest, parse, ssot, traffic_assurance, unknown_evidence
    import cisco_toolkit

    assert hasattr(ssot, "CANONICAL_FACTS") and isinstance(ssot.CANONICAL_FACTS, dict)
    assert hasattr(ssot, "canonical_facts") and callable(ssot.canonical_facts)
    assert hasattr(ssot, "reconcile") and callable(ssot.reconcile)
    # the coverage/provenance-schema owners (J3/J2/J1) the registry gained on 2026-07-05 must resolve too,
    # else a refactor that moved one without updating docs/ssot.md would slip past this guard.
    assert hasattr(ssot, "compute_schema_census") and callable(ssot.compute_schema_census)
    assert hasattr(ssot, "compute_fact_lineage") and callable(ssot.compute_fact_lineage)
    assert hasattr(detector_schema, "compute_detector_schema") and callable(detector_schema.compute_detector_schema)
    assert hasattr(unknown_evidence, "compute_unknown_evidence") and callable(unknown_evidence.compute_unknown_evidence)
    assert unknown_evidence.SCHEMA == "unknown_evidence/1"
    assert unknown_evidence.EVENT_SCHEMA == "unknown_evidence_event/1"
    assert callable(traffic_assurance.assess_flow) and callable(traffic_assurance.assess_flows)
    assert callable(traffic_assurance.build_traffic_evidence_custody)
    assert traffic_assurance.TRAFFIC_ASSURANCE_SET_SCHEMA == "traffic_assurance_set/1"
    assert traffic_assurance.TRAFFIC_EVIDENCE_CUSTODY_SCHEMA == "traffic_evidence_custody/1"
    assert parse.FORWARDING_GATE_SYNTAX_REGISTRY
    assert len({row.family for row in parse.FORWARDING_GATE_SYNTAX_REGISTRY}) == len(
        parse.FORWARDING_GATE_SYNTAX_REGISTRY
    )
    assert isinstance(getattr(cisco_toolkit, "__version__", None), str), "schema __version__ owner is gone"
    # manifest.py is the hash-chained chain-of-custody ledger the registry cites for run provenance.
    assert hasattr(manifest, "GENESIS"), "manifest.py no longer exposes the hash-chain GENESIS"


def test_registry_transition_contract_owners_are_real_and_bounded():
    """The R2.0 row resolves to its owners and retains its non-promotion boundaries."""
    from cisco_toolkit import (
        _transition_runtime_debug,
        transition_contract,
        transition_dsl,
        transition_legacy,
        transition_pack,
        transition_runtime_closure,
        transition_runtime_discovery,
        transition_tcb_review,
        transition_verifier,
        transition_workload_review,
    )

    expected = {
        transition_contract: (
            "bind_transition_case_bytes",
            "validate_transition_case",
            "validate_qualification_denominator",
        ),
        transition_pack: (
            "bind_pack_manifest_bytes",
            "bind_tcb_manifest_bytes",
            "verify_qualification_evidence",
            "qcp_001_must_remain_experimental",
        ),
        transition_runtime_closure: (
            "validate_transition_runtime_closure_evidence",
            "bind_transition_runtime_closure_evidence_bytes",
            "verify_transition_runtime_closure_review",
            "require_verified_transition_runtime_closure_review",
        ),
        transition_runtime_discovery: (
            "RuntimeClosureDiscoverySubject",
            "CapturedIncompleteRuntimeClosureEvidence",
            "validate_windows_runtime_discovery_trace",
            "validate_windows_debug_runtime_discovery_trace",
            "validate_windows_debug_runtime_discovery_v3_trace",
            "validate_windows_debug_execution_environment_manifest",
            "validate_windows_debug_execution_environment_v3_manifest",
            "capture_windows_runtime_closure_incomplete",
            "capture_windows_debug_runtime_closure_incomplete",
            "capture_windows_debug_runtime_closure_v3_incomplete",
        ),
        _transition_runtime_debug: (
            "DebugEventCapture",
            "DebugEventRecord",
            "WindowsDebugEventSession",
        ),
        transition_verifier: (
            "verify_transition_case",
            "map_authoritative_gate",
            "compute_invalidation_receipt",
        ),
        transition_legacy: (
            "verify_release1_semantic_bundle",
            "adapt_release1_comparison_bytes",
            "replay_release1_comparison_bytes",
        ),
        transition_dsl: (
            "bind_packaged_dsl_prototype_bytes",
            "run_bound_pack_abi",
        ),
        transition_tcb_review: (
            "verify_tcb_budget_review_evidence",
        ),
        transition_workload_review: (
            "bind_transition_workload_evidence_bytes",
            "verify_transition_workload_review",
            "require_verified_transition_workload_review",
        ),
    }
    for module, names in expected.items():
        for name in names:
            assert callable(getattr(module, name, None)), f"{module.__name__}.{name} owner is missing"

    row = next(
        line
        for line in _registry_text().splitlines()
        if "Proof-carrying transition structural contract" in line
    )
    assets = (
        "cisco_toolkit/schemas/atlas-transition-contract-v1.schema.json",
        "cisco_toolkit/schemas/atlas-r2-structural-tcb-census-v1.schema.json",
        "cisco_toolkit/data/qcp-001.experimental.json",
        "cisco_toolkit/data/atlas-r2-structural-tcb-census.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-denominator.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-input.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-pack.experimental.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-program.v1.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-tcb.v2.json",
        "cisco_toolkit/data/atlas-r2-dsl-prototype-measurements.v1.json",
        "cisco_toolkit/schemas/atlas-r2-execution-evidence-v1.schema.json",
        "cisco_toolkit/schemas/atlas-r2-transition-runtime-closure-v2.schema.json",
        "cisco_toolkit/schemas/atlas-r2-transition-workload-review-v1.schema.json",
        "cisco_toolkit/data/atlas-r1-executable-bundle.json",
        "cisco_toolkit/data/atlas-r1-source-bundle.json",
        "cisco_toolkit/data/atlas-r1-retrospective-before.json",
        "cisco_toolkit/data/atlas-r1-retrospective-after.json",
        "cisco_toolkit/data/atlas-r1-retrospective-comparison.json",
    )
    for relative in assets:
        assert (ROOT / relative).is_file(), f"R2.0 SSOT asset is missing: {relative}"
        assert relative.rsplit("/", 1)[-1] in row, f"R2.0 SSOT row does not cite {relative}"

    for boundary in (
        "closed three-state vocabularies",
        "closed four-state vocabularies",
        "EXPERIMENTAL",
        "CONTRACT_ONLY",
        "REFERENCE_NOT_REWRITE",
        "AUDIT_ONLY",
        "null Release 2 gate",
        "no authenticated historical fixture",
        "same-checkout self-check only",
        "cannot execute QCP-001",
        "not a Wasm runtime",
        "sandbox claim",
        "PARTIAL_NONPORTABLE_PROTOTYPE",
        "COMPLETE_EXACT_RUNTIME_CLOSURE",
        "runtime-closure `/2` module and schema are protocol structure only",
        "Windows live discovery emits only non-authoritative `COLLECTED_INCOMPLETE` evidence",
        "no closure-capable collector, capture corpus, or authority",
        "No trust policy, reviewer key, signature, or signed closure-review receipt is bundled",
        "do not change the runtime-inventory `/1` roster",
        "freeze `/1` remains unchanged and blocked",
        "Representative-workload evidence is non-authoritative",
        "evidence state is never `ADEQUATE`",
        "No representative-workload corpus, reviewer key, trust policy, or signed review receipt is bundled",
        "existing freeze `/1` remains explicitly blocked",
        "does not make runtime inventory `COMPLETE`",
        "qualify a pack",
        "authorize promotion",
        "budgets, reviewed resource ceilings, independent review evidence, and selected commit remain pending/null",
        "No R2.1+ or Release 3 capability",
    ):
        assert boundary in row, f"R2.0 SSOT row lost boundary {boundary!r}"

    registry = " ".join(
        line.lstrip("> ").strip() for line in _registry_text().splitlines()
    )
    for runtime_closure_authority_boundary in (
        "review signature authenticates the canonical receipt, not its trust policy",
        "Every authority use must obtain the current canonical policy bytes",
        "digest argument proves only exact equality to the caller's selection",
        "cannot establish external selection",
        "policy issuer/namespace/succession",
        "reviewer-key identity/custody",
        "trusted time",
        "global freshness or anti-rollback",
        "artifact semantic truth",
        "real-world capture completeness",
        "Any authority gate must consume only that fresh return value",
        "independently compare and bind its `bindings_digest`, `policy_digest`, and `evaluated_at`",
        "gate-selected commit/tree, evidence digest and states, and mapped evidence digests",
        "a retained `.complete` value is historical state, not authority",
        "No such current policy, key, signature, or receipt is bundled",
    ):
        assert runtime_closure_authority_boundary in registry

    for workload_authority_boundary in (
        "workload-review `/1` signature authenticates the canonical receipt, not its replaceable trust policy",
        "current canonical workload-policy bytes and exact digest",
        "call `require_verified_transition_workload_review` again",
        "rejects an evaluation-time rollback",
        "current key authorization, subject authorization, receipt lifetime, and revocation",
        "cannot authenticate policy selection, succession, custody, trusted time, global anti-rollback",
        "must use only the fresh return value",
        "Retained `.adequate` is historical state, not authority",
        "No current workload policy, key, signature, receipt, or representative-workload corpus is bundled",
    ):
        assert workload_authority_boundary in registry

    for tcb_budget_authority_boundary in (
        "budget-review `/2` signature authenticates its canonical receipt, not the replaceable trust policy",
        "does not by itself make the signed budget decision current authority",
        "current canonical TCB-budget policy bytes and exact digest",
        "call `require_verified_tcb_budget_review` again",
        "rejects an evaluation-time rollback",
        "current key authorization, source-subject authorization, receipt lifetime, and revocation",
        "cannot authenticate policy selection, namespace or succession, custody, trusted time, global anti-rollback",
        "must use only the fresh return value",
        "serialized freeze retains the decision-time `review_trust_policy_digest`",
        "separately held current review is ephemeral authorization",
        "must never rewrite those historical bytes",
        "No current TCB-budget policy, key, signature, receipt, independently approved budget, or positive freeze is bundled",
    ):
        assert tcb_budget_authority_boundary in registry


def test_registry_windows_debug_v3_row_is_distinct_target_only_and_nonpromoting():
    lines = _registry_text().splitlines()
    v2 = next(
        line
        for line in lines
        if "Release 2.0 Windows debug-event capture tranche" in line
    )
    v3 = next(
        line
        for line in lines
        if "Release 2.0 Windows target-endpoint reconciliation tranche" in line
    )

    assert v2 != v3
    assert "(`/2`, incomplete only)" in v2
    assert "(`/3`, incomplete only)" in v3
    assert "capture_windows_debug_runtime_closure_incomplete" in v2
    assert "capture_windows_debug_runtime_closure_v3_incomplete" in v3

    v2_assets = (
        "atlas-r2-windows-debug-runtime-discovery-v2.schema.json",
        "atlas-r2-windows-execution-environment-manifest-v2.schema.json",
    )
    v3_assets = (
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v3.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v3.schema.json",
    )
    for basename in v2_assets:
        assert basename in v2
        assert basename not in v3
    for relative in v3_assets:
        assert (ROOT / relative).is_file(), f"R2.0 /3 SSOT asset is missing: {relative}"
        basename = relative.rsplit("/", 1)[-1]
        assert basename in v3
        assert basename not in v2

    for unchanged_v2_boundary in (
        "deliberately incomplete image-event observation",
        "event-stream continuity, start/end reconciliation",
        "OS loss counters remain null",
    ):
        assert unchanged_v2_boundary in v2

    for v3_boundary in (
        "sealed 12-artifact `/3` envelope",
        "target_start_end_snapshot_reconciled=true",
        "collector_sequence_kind=LOCAL_APPEND_ORDINAL",
        "collector_ledger_contiguous=true",
        "collector_sequence_gap_count=0",
        "event_stream_contiguous=false",
        "start_end_snapshot_reconciled=false",
        "os_event_sequence_available=false",
        "os_loss_counter_available=false",
        "OS/global loss counters remain null",
        "Endpoint equality cannot detect an omitted balanced load/unload pair",
        "Later target teardown image activity remains serialized and debug-projected but is outside END checkpoint reconciliation",
        "`LOAD_LIBRARY_AS_DATAFILE`",
        "Only `process_tree_captured_before_first_instruction_through_final_descendant` and `execution_environment_argv_cwd_and_inputs_bound` may be true",
        "Runtime inventory `/1` remains `PARTIAL_NONPORTABLE_PROTOTYPE`",
        "`/2` remains unchanged",
        "No budget, authority, signature, qualification, promotion, R2.1+, or Release 3 effect",
    ):
        assert v3_boundary in v3


def test_registry_windows_debug_v4_row_binds_only_stable_on_disk_bytes_and_stays_nonpromoting():
    lines = _registry_text().splitlines()
    v3 = next(
        line
        for line in lines
        if "Release 2.0 Windows target-endpoint reconciliation tranche" in line
    )
    v4 = next(
        line
        for line in lines
        if "Release 2.0 Windows debug-file identity/on-disk-byte tranche" in line
    )

    assert v3 != v4
    assert "(`/3`, incomplete only)" in v3
    assert "(`/4`, incomplete only)" in v4
    assert "capture_windows_debug_runtime_closure_v4_incomplete" in v4
    assert "validate_windows_debug_runtime_discovery_v4_trace" in v4
    assert "validate_windows_debug_execution_environment_v4_manifest" in v4

    v4_assets = (
        "cisco_toolkit/schemas/atlas-r2-windows-debug-runtime-discovery-v4.schema.json",
        "cisco_toolkit/schemas/atlas-r2-windows-execution-environment-manifest-v4.schema.json",
    )
    for relative in v4_assets:
        assert (ROOT / relative).is_file(), f"R2.0 /4 SSOT asset is missing: {relative}"
        basename = relative.rsplit("/", 1)[-1]
        assert basename in v4
        assert basename not in v3

    for v4_boundary in (
        "sealed 13-artifact `/4` envelope",
        "borrowed debug-event image-handle trace",
        "fixed capture fails closed unless every received CREATE_PROCESS or LOAD_DLL image row supplies a non-null debug-event `hFile`",
        "joins one-to-one by source debug sequence and mapping tokens",
        "borrows but never closes, retains, or transfers that handle",
        "`FILE_ID_INFO`",
        "exactly two equal SHA-256 whole-file reads from offset zero through that same handle",
        "Raw paths and filenames are not disclosed",
        "File identifiers are machine-local and can be reused over time",
        "protective guards only, never approved budgets",
        "stable handle-addressed **on-disk** bytes only",
        "does not prove mapped or loaded memory bytes",
        "Debug-event image handles can be null outside this fail-closed fixed capture",
        "persistent_file_identity_and_loaded_bytes_bound=false",
        "mapped_or_loaded_memory_bytes_bound=false",
        "event_stream_contiguous=false",
        "start_end_snapshot_reconciled=false",
        "Only `process_tree_captured_before_first_instruction_through_final_descendant` and `execution_environment_argv_cwd_and_inputs_bound` may be true",
        "Runtime inventory `/1` remains `PARTIAL_NONPORTABLE_PROTOTYPE`",
        "`/2` and `/3` remain unchanged",
        "No budget, authority, signature, qualification, promotion, R2.1+, or Release 3 effect",
    ):
        assert v4_boundary in v4


def test_registry_cited_snapshot_keys_are_published_by_the_engine():
    """The snapshot blocks the registry names as owners must be assigned by the engine source.
    Source-level guard (the blocks don't exist on every historical snapshot; the CONTRACT is the
    assignment in the producer). Matches the repo's existing source-grep guard pattern."""
    txt = _registry_text()
    engine = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="ignore")
    analyze = (ROOT / "cisco_toolkit" / "analyze.py").read_text(encoding="utf-8", errors="ignore")
    src = engine + "\n" + analyze
    for key in ("architecture_coverage", "cable_map", "coverage_matrix", "unknown_evidence", "design_blueprint",
                "traffic_assurance", "traffic_evidence_custody", "schema_census", "fact_lineage",
                "detector_schema"):
        assert key in txt, f"registry stopped citing the {key!r} owner path"
        assigned = re.search(rf'["\']{re.escape(key)}["\']\]\s*=', src)
        assert assigned, f"registry cites snap[{key!r}] but the engine source never assigns it"


def test_registry_and_contract_are_cross_linked_both_ways():
    """The umbrella registry and the assessment-facts contract must point at each other, so neither
    is orphaned when one moves (Law 1 -- one consistent structure)."""
    reg = _registry_text()
    con = CONTRACT.read_text(encoding="utf-8")
    assert "ssot-contract.md" in reg, "registry does not link down to the assessment-facts contract"
    assert "ssot.md" in con, "the assessment-facts contract does not link up to the umbrella registry"


def test_registry_names_the_core_federated_owners():
    """Coverage guard: the registry must still name each core domain owner token, so a future edit
    that silently drops a domain from the map is caught."""
    txt = _registry_text()
    for token in ("ssot.py", "graphify", "pyproject.toml", "__version__", "CHANGELOG.md",
                  "manifest.py", "AGENTS.md", "learnings.md", "CLAUDE.md"):
        assert token in txt, f"registry no longer names the '{token}' owner"


def test_arch_coverage_cached_counts_match_registry():
    """Reconcile guard for the architecture-coverage headline. The docs cache the fact ("N ...
    architecture-class detectors across M classes"); the in-code registry
    (`design_advisor._ARCH_COVERAGE_REGISTRY`) owns it. A cached count that drifts from its owner is
    the exact rot Law 1 exists to prevent — caught live 2026-07-10, when both docs still said 40/23
    while the registry held 46 probe-ids across 27 class axes. Asserts every doc that states the
    headline states the registry's numbers, and that the headline is still present at all (dropping
    the phrase entirely would silently retire this guard)."""
    from cisco_toolkit.design_advisor import _ARCH_COVERAGE_REGISTRY as reg
    detectors = sum(len(pids) for _axis, _label, _channel, pids in reg)
    classes = len({axis for axis, *_rest in reg})
    headline = re.compile(
        r"(\d+)\s+(?:coverage-honest\s+)?architecture-class\s+detectors\s+across\s+(\d+)\s+classes")
    for doc in (ROOT / "CLAUDE.md", ROOT / "docs" / "universal-architecture-coverage.md"):
        txt = doc.read_text(encoding="utf-8")
        hits = headline.findall(txt)
        assert hits, f"{doc.name} no longer states the coverage headline — reconcile it or update this guard"
        for n, m in hits:
            assert (int(n), int(m)) == (detectors, classes), (
                f"{doc.name} caches {n} detectors / {m} classes but the registry "
                f"(design_advisor._ARCH_COVERAGE_REGISTRY) holds {detectors} / {classes} — "
                "update the doc from the owner (a copy is a cache and must match)")


# --- Side engagements ---------------------------------------------------------------------------
#
# The pushable registry records fictional aliases and the ownership boundary, never real client
# names or owner-machine paths. The private inventory is the authority for resolving those aliases.

SIDE_ENGAGEMENT_ALIASES = [
    "Reference_DC_Design",
    "Reference_CCTV_PS_Proposal",
]


def test_side_engagement_row_cites_only_public_aliases():
    """The public registry retains ownership without publishing private on-disk pointers."""
    txt = _registry_text()
    not_cited = [alias for alias in SIDE_ENGAGEMENT_ALIASES if alias not in txt]
    assert not_cited == [], f"'Side engagements' row no longer cites: {not_cited}"


def test_side_engagement_row_omits_owner_machine_paths():
    row = next(
        line for line in _registry_text().splitlines()
        if "Side engagements" in line
    )
    assert "private inventory" in row
    assert not re.search(r"[A-Za-z]:[\\/]", row)


def test_graphify_ignore_uses_a_generic_private_engagement_pattern():
    txt = GRAPHIFY_IGNORE.read_text(encoding="utf-8")
    assert "*_DC_Design/" in txt


# --------------------------------------------------------- the reconcile guard must cover EVERY band
def test_every_lifecycle_band_the_producer_emits_has_a_raw_basis_guard():
    """`ssot._LIFECYCLE_BANDS` is the map from summary field -> the band reconcile() re-derives from
    `lifecycle_risk.per_device`. It listed four of the producer's FIVE bands; "Unknown" was missing.

    That omission was the worst possible one: `n_unknown` IS a registered CANONICAL_FACT, so it is
    published, cited and rendered as a headline -- but with no entry here it had NO raw-basis guard
    at all. The one canonical fact whose entire job is to say "not determined" was the only lifecycle
    fact nothing verified.

    This asserts COMPLETENESS against the producer's own vocabulary rather than a hand-kept list, so
    a new band added upstream cannot land here unguarded.
    """
    from cisco_toolkit import ssot
    from cisco_toolkit.analyze import _LIFECYCLE_BAND_RANK
    guarded = set(ssot._LIFECYCLE_BANDS.values())
    produced = set(_LIFECYCLE_BAND_RANK)
    assert produced - guarded == set(), (
        f"lifecycle band(s) with no reconcile guard: {sorted(produced - guarded)}")
    assert guarded - produced == set(), (
        f"reconcile guards a band the producer cannot emit: {sorted(guarded - produced)}")
    # every guarded field must also be a canonical fact or the guard has no published value to check
    assert "n_unknown" in ssot.CANONICAL_FACTS
    unknown_description = ssot.CANONICAL_FACTS["n_unknown"][1]
    assert "no exact EoX row matched" in unknown_description
    assert "source/date authority was withheld" in unknown_description


def _lc_snapshot(**summary):
    return {"lifecycle_risk": {"summary": dict(n_devices=3, **summary),
                               "per_device": [{"host": "a", "band": "Past-LDoS"},
                                              {"host": "b", "band": "Unknown"},
                                              {"host": "c", "band": "Unknown"}]}}


def test_reconcile_catches_a_falsified_n_unknown():
    """Measured before the fix: mutating summary.n_unknown from 2 to 99 returned reconcile() == []
    (silently accepted) while the same mutation to n_past_ldos was caught."""
    from cisco_toolkit import ssot
    assert ssot.reconcile(_lc_snapshot(n_past_ldos=1, n_unknown=2)) == [], "the truthful snapshot must be clean"
    v = ssot.reconcile(_lc_snapshot(n_past_ldos=1, n_unknown=99))
    assert v and any("n_unknown" in s for s in v), f"a falsified n_unknown was accepted: {v}"
    # NON-VACUITY: the sibling guard still works and the truthful case still passes, so this is not
    # an always-fire check.
    v2 = ssot.reconcile(_lc_snapshot(n_past_ldos=99, n_unknown=2))
    assert v2 and any("n_past_ldos" in s for s in v2), v2
