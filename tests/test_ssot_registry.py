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
import os
import pathlib
import re
import subprocess

import pytest

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
        "CHANGELOG.md",
        "pyproject.toml",
        "cisco_toolkit/__init__.py",
        # the freshness guard: four registry rows cite it as their enforcement (2026-07-10)
        "tests/test_registry_freshness.py",
        # the DEC-007 holdout policy owner + its mechanics module (P1-2, 2026-07-10)
        "docs/quality/holdout-contract.md",
        "cisco_toolkit/holdout.py",
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
    from cisco_toolkit import ssot, manifest, detector_schema
    import cisco_toolkit

    assert hasattr(ssot, "CANONICAL_FACTS") and isinstance(ssot.CANONICAL_FACTS, dict)
    assert hasattr(ssot, "canonical_facts") and callable(ssot.canonical_facts)
    assert hasattr(ssot, "reconcile") and callable(ssot.reconcile)
    # the coverage/provenance-schema owners (J3/J2/J1) the registry gained on 2026-07-05 must resolve too,
    # else a refactor that moved one without updating docs/ssot.md would slip past this guard.
    assert hasattr(ssot, "compute_schema_census") and callable(ssot.compute_schema_census)
    assert hasattr(ssot, "compute_fact_lineage") and callable(ssot.compute_fact_lineage)
    assert hasattr(detector_schema, "compute_detector_schema") and callable(detector_schema.compute_detector_schema)
    assert isinstance(getattr(cisco_toolkit, "__version__", None), str), "schema __version__ owner is gone"
    # manifest.py is the hash-chained chain-of-custody ledger the registry cites for run provenance.
    assert hasattr(manifest, "GENESIS"), "manifest.py no longer exposes the hash-chain GENESIS"


def test_registry_cited_snapshot_keys_are_published_by_the_engine():
    """The snapshot blocks the registry names as owners must be assigned by the engine source.
    Source-level guard (the blocks don't exist on every historical snapshot; the CONTRACT is the
    assignment in the producer). Matches the repo's existing source-grep guard pattern."""
    txt = _registry_text()
    engine = (ROOT / "COLLECT_PARSE_V3_23_0.py").read_text(encoding="utf-8", errors="ignore")
    analyze = (ROOT / "cisco_toolkit" / "analyze.py").read_text(encoding="utf-8", errors="ignore")
    src = engine + "\n" + analyze
    for key in ("architecture_coverage", "cable_map", "coverage_matrix", "design_blueprint",
                "schema_census", "fact_lineage", "detector_schema"):
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
                  "manifest.py", "MEMORY.md", "CLAUDE.md"):
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


# --- Side engagements (the 2026-07-06 rot class: a pointer to a file that never migrated) ---------
#
# The 'Side engagements' row points OUTSIDE the tracked tree at untracked local artifacts
# (.gitignore `[HISTORY-REDACTED]_*` keeps client deliverables out of git by design). Until 2026-07-06 the row
# pointed at `[HISTORY-REDACTED]/ssot.py` -- a module that was never tracked in this repo's history and never
# migrated from the old laptop -- and none of the guards above covered the row, so the registry
# asserted "the truth is over there" about a path that existed nowhere. Three layers close that
# class: a citation guard (runs everywhere), an existence guard (owner machine only -- the
# artifacts deliberately exist on no other checkout), and a regression pin on the old pointer.

SIDE_ENGAGEMENT_POINTERS = [
    # deliverables + their generator scripts (HLD/LLD/MOP/NRFU/NIP docx+pdf, build_hld_*.py)
    "[HISTORY-REDACTED]_DC_Design",
    # the engagement record: what changed in the current HLD and why
    "[HISTORY-REDACTED]_DC_Design/HLD_v7_1_CHANGES.md",
    # CRD + BOQ live at the repo root (untracked)
    "[HISTORY-REDACTED]_DC_Network_CRD_v1.1.docx",
    "[HISTORY-REDACTED]_BOQ.xlsx",
]


def _main_checkout_root() -> pathlib.Path:
    """The side-engagement artifacts are UNTRACKED, so they exist only in the MAIN checkout -- a
    linked worktree under .claude/worktrees/ has none (the graphify-out/ trap again; mirrors
    .claude/hooks/session-brief.sh :: _main_root). `git rev-parse --git-common-dir` is the main
    .git from any worktree ('.git', relative, in the main checkout itself). Fail-open to ROOT."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        git_dir = pathlib.Path(out)
        if not git_dir.is_absolute():
            git_dir = (ROOT / git_dir).resolve()
        if git_dir.name == ".git" and git_dir.parent.is_dir():
            return git_dir.parent
    except Exception:
        pass
    return ROOT


def test_side_engagement_row_cites_the_on_disk_record():
    """Citation guard (runs EVERYWHERE -- needs no artifacts): the row must name each real on-disk
    pointer, so dropping or renaming one in the registry is caught even on checkouts that don't
    carry the files (hosted CI, fresh clones, worktrees)."""
    txt = _registry_text()
    not_cited = [p for p in SIDE_ENGAGEMENT_POINTERS if p.rsplit("/", 1)[-1] not in txt]
    assert not_cited == [], f"'Side engagements' row no longer cites: {not_cited}"
    # The second engagement in the row must stay on the map. Existence is deliberately NOT
    # asserted for it: the dir was not found on this machine on 2026-07-06 and the row says so.
    assert "[HISTORY-REDACTED]_[HISTORY-REDACTED]_CCTV_PS_Proposal" in txt, "the [HISTORY-REDACTED] CCTV side engagement fell off the map"


@pytest.mark.skipif(bool(os.environ.get("CI")),
                    reason="hosted CI clones never carry the untracked side-engagement artifacts "
                           "(.gitignore `[HISTORY-REDACTED]_*`) -- only the owner machine can verify existence")
def test_side_engagement_pointers_exist_on_owner_machine():
    """Existence guard (owner machine only): every [HISTORY-REDACTED] pointer the registry names must resolve
    on disk under the MAIN checkout. This is the check that was missing while the row pointed at
    the never-migrated [HISTORY-REDACTED]/ssot.py. Failing here after a machine migration is the guard WORKING:
    bring the artifacts over from the old machine, or repoint the row at what actually exists."""
    main_root = _main_checkout_root()
    missing = [p for p in SIDE_ENGAGEMENT_POINTERS if not (main_root / p).exists()]
    assert missing == [], (
        f"docs/ssot.md points at side-engagement artifacts that do not exist under {main_root}: "
        f"{missing} -- restore them or repoint the 'Side engagements' row (and keep "
        f"SIDE_ENGAGEMENT_POINTERS in this test in sync)"
    )


def test_registry_never_points_at_the_never_migrated_[HISTORY-REDACTED]_module():
    """Regression pin (runs EVERYWHERE, incl. hosted CI): docs/ssot.md and .graphifyignore both
    claimed `[HISTORY-REDACTED]/ssot.py` was the Qatar DC SSOT; `git log --all` shows that path was never
    tracked here, and it exists nowhere on this machine (verified 2026-07-06 -- it never migrated
    off the old laptop). Neither pointer file may claim it again. If the module is ever genuinely
    restored, repoint the row AND retire this pin."""
    for path, label in ((REGISTRY, "docs/ssot.md"), (GRAPHIFY_IGNORE, ".graphifyignore")):
        txt = path.read_text(encoding="utf-8")
        assert "[HISTORY-REDACTED]/ssot.py" not in txt, (
            f"{label} points at [HISTORY-REDACTED]/ssot.py again -- that module never existed in this repo; "
            f"either it was truly restored (then update this pin) or the 2026-07-06 rot is back"
        )
