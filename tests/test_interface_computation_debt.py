"""ADR 0008: complete discovery, exact sites, immutable ceiling and shrinking history."""
import json
import os
import shutil
import subprocess

import pytest

import interface_computation_guard as guard
from ssot_contract_guard import require_canonical_checks
from cisco_toolkit import ssot


@pytest.fixture(scope="module")
def parser():
    # Coverage-only jobs do not install JS packages. Every required default matrix
    # leg installs this exact toolchain and sets REQUIRE_REAL_TOOLCHAIN=1; missing
    # parsing there is a failure. Python structural/monotonicity controls run everywhere.
    available = shutil.which("node") and (guard.ROOT / "atlas-scope/node_modules/typescript/package.json").is_file()
    if not available:
        if os.environ.get("ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN") == "1":
            pytest.fail("Required interface TypeScript AST detector cannot execute")
        pytest.skip("TypeScript AST census runs in all required default-suite matrix legs with the locked toolchain")
    return True


def test_current_interface_has_only_registered_exact_sites(parser):
    assert guard.check() >= 0


def test_registry_paths_and_symbols_are_closed_not_whole_file_exemptions():
    registry = json.loads((guard.ROOT / guard.REGISTRY).read_text(encoding="utf-8"))
    assert registry["stage"] == "active", "Hosted observations still require admission"
    assert registry["sites"]
    assert all(row["symbol"] and row["rule"] and len(row["fingerprint"]) == 64 and row["occurrence"] >= 1
               for row in registry["sites"])
    assert all("*" not in row["path"] for row in registry["sites"])
    if "def _count_by(" in (guard.ROOT / "webapp/backend/summary.py").read_text(encoding="utf-8"):
        assert any(row["path"] == "webapp/backend/summary.py" and row["symbol"] == "_count_by" for row in registry["sites"])
    if "function counterfactualFailure(" in (guard.ROOT / "webapp/frontend/src/components/TopologyGraph.tsx").read_text(encoding="utf-8"):
        assert any(row["path"] == "webapp/frontend/src/components/TopologyGraph.tsx" and row["symbol"] == "counterfactualFailure" for row in registry["sites"])
    retired = [row for row in registry["sites"] if row["disposition"] == "retired-with-surface"]
    assert any(row["path"].startswith("atlas-scope/") for row in retired)
    assert any(row["path"].endswith("blast_radius_explorer.html") for row in retired)


def sample_site():
    return {"path": "webapp/backend/new.py", "symbol": "summarize", "rule": "aggregate",
            "fingerprint": "a" * 64, "occurrence": 1}


def test_new_duplicate_and_duplicate_occurrence_are_rejected():
    site = sample_site()
    registry = guard.proposal([site])
    other = {**site, "occurrence": 2}
    with pytest.raises(ValueError, match="Unregistered"):
        guard.validate(registry, [site, other], [site])
    with pytest.raises(ValueError, match="ceiling"):
        guard.validate(guard.proposal([site, other]), [site, other], [site])


def test_removed_entry_cannot_be_restored_with_its_old_allowance():
    site = sample_site()
    previous = guard.proposal([])
    with pytest.raises(ValueError, match="reappeared"):
        guard.validate(guard.proposal([site]), [site], [site], [previous])
    guard.validate(previous, [], [site], [guard.proposal([site])])


def test_stale_allowance_and_reclassification_are_rejected():
    site = sample_site()
    with pytest.raises(ValueError, match="stale"):
        guard.validate(guard.proposal([site]), [], [site])
    registry = guard.proposal([site])
    registry["sites"][0]["disposition"] = "not-a-debt"
    with pytest.raises(ValueError, match="disposition"):
        guard.validate(registry, [site], [site])


@pytest.mark.parametrize("text,rule", [
    ("def summarize(snap):\n return len(snap['devices'])\n", "aggregate"),
    ("def paint(health):\n return 'ok' if health >= 80 else 'bad'\n", "fact-threshold"),
    ("def walk(adj, queue):\n while queue:\n  queue.extend(adj[queue.pop()])\n", "graph-traversal"),
    ("def bands(rows):\n out = {}\n for row in rows:\n  out[row.band] = out.get(row.band, 0) + 1\n return out\n", "counter-update"),
])
def test_python_ast_catches_counts_bands_and_traversal(text, rule):
    assert any(row["rule"] == rule for row in guard.python_sites("webapp/backend/new.py", text))


@pytest.mark.parametrize("path", ["webapp/frontend/src/New.tsx", "atlas-scope/src/new.ts", "cisco_toolkit/blast_radius_explorer.html"])
@pytest.mark.parametrize("source,rule", [
    ("function answer(rows) { return rows.filter(r => r.band === 'Critical').length; }", "count"),
    ("const HEALTH_TONE = score => score >= 80 ? 'ok' : 'risk';", "fact-threshold"),
    ("function solve(adj, queue) { while(queue.length) { queue.push(...adj[queue.shift()]); } }", "graph-traversal"),
    ("function totals(rows) { return rows.reduce((n, row) => n + row.endpoints, 0); }", "aggregate"),
    ("function answer(rows) { return rows['length']; }", "count"),
])
def test_typescript_ast_and_html_scripts_catch_new_computations(parser, path, source, rule):
    text = f"<script>{source}</script>" if path.endswith("html") else source
    assert any(row["rule"] == rule for row in guard.scan({path: text}))


def test_lexical_tripwire_sees_generated_dynamic_code(parser):
    source = 'const template = "function walk(queue) { return queue.shift(); }";'
    assert any(row["rule"] == "graph-worklist" for row in guard.scan({"webapp/frontend/src/New.ts": source}))


def test_renderer_without_computation_does_not_create_a_debt(parser):
    assert guard.scan({"webapp/frontend/src/New.tsx": "export function View({fact}) { return <span>{fact.value}</span>; }"}) == []


def test_ast_parse_errors_fail_closed(parser):
    with pytest.raises(subprocess.CalledProcessError):
        guard.scan({"webapp/frontend/src/New.ts": "function broken( {"})


def test_new_canonical_fact_without_check_is_refuted(monkeypatch):
    snap = {"unowned": {"value": 12}}
    monkeypatch.setattr(ssot, "CANONICAL_FACTS", {"new_fact": ("unowned.value", "mutation negative")})
    with pytest.raises(AssertionError, match="no executed reconcile check"):
        require_canonical_checks(snap)


def test_source_discovery_includes_new_interface_modules_and_registry_writers():
    # No curated list of current files is the scan denominator: new tracked and
    # nonignored modules under every interface root enter automatically.
    sources = guard.source_map()
    assert "webapp/backend/summary.py" in sources
    assert "webapp/frontend/src/pages/Snapshot.tsx" in sources
    assert "atlas-scope/src/forwarding/engine.ts" in sources
    assert "cisco_toolkit/blast_radius_explorer.html" in sources
    assert "cisco_toolkit/deck.py" in sources and "cisco_toolkit/excel.py" in sources
    assert "cisco_toolkit/mop.py" in sources
    assert "webapp/backend/engine.py" not in sources
