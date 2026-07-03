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
    from cisco_toolkit import ssot, manifest
    import cisco_toolkit

    assert hasattr(ssot, "CANONICAL_FACTS") and isinstance(ssot.CANONICAL_FACTS, dict)
    assert hasattr(ssot, "canonical_facts") and callable(ssot.canonical_facts)
    assert hasattr(ssot, "reconcile") and callable(ssot.reconcile)
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
    for key in ("architecture_coverage", "cable_map", "coverage_matrix", "design_blueprint"):
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
