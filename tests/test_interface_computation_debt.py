"""ADR 0008: complete discovery, exact sites, immutable ceiling and shrinking history."""
import ast
import json
import os
import shutil
import subprocess

import pytest
import yaml

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


@pytest.mark.parametrize("ordinal", [True, 1.0, "1", 0, -1])
def test_callsite_occurrence_has_an_exact_integer_type(ordinal):
    site = sample_site()
    registry = guard.proposal([site])
    registry["sites"][0]["occurrence"] = ordinal
    with pytest.raises(ValueError, match="exact types"):
        guard.validate(registry, [site], [site])


@pytest.mark.parametrize("text", ['{"stage":"active","stage":"observation_required"}', '{"occurrence":NaN}', '{"occurrence":Infinity}'])
def test_ambiguous_registry_json_refuses(text):
    with pytest.raises(ValueError):
        guard.read_registry(text)


@pytest.mark.parametrize("text,rule", [
    ("def summarize(snap):\n return len(snap['devices'])\n", "aggregate"),
    ("def paint(health):\n return 'ok' if health >= 80 else 'bad'\n", "fact-threshold"),
    ("def walk(adj, queue):\n while queue:\n  queue.extend(adj[queue.pop()])\n", "graph-traversal"),
    ("def bands(rows):\n out = {}\n for row in rows:\n  out[row.band] = out.get(row.band, 0) + 1\n return out\n", "counter-update"),
    ("def f(xs):\n n = 0\n for x in xs:\n  n += 1\n return n\n", "counter-update"),
    ("def f(x):\n return 'ok' if x >= 80 else 'risk'\n", "fact-threshold"),
    ("def f(x):\n if x:\n  return 'NO-GO'\n return 'GO'\n", "fact-decision"),
])
def test_python_ast_catches_counts_bands_and_traversal(text, rule):
    assert any(row["rule"] == rule for row in guard.python_sites("webapp/backend/new.py", text))


def test_python_ast_fingerprint_has_a_fixed_cross_version_structure():
    expression = ast.parse("len(rows)").body[0].value
    expected = {"type": "Call", "fields": {
        "func": {"type": "Name", "fields": {"id": "len", "ctx": {"type": "Load", "fields": {}}}},
        "args": [{"type": "Name", "fields": {"id": "rows", "ctx": {"type": "Load", "fields": {}}}}]}}
    assert guard.ast_form(expression) == expected
    expression._fields = (*expression._fields, "future_optional_field")
    expression.future_optional_field = []
    assert guard.ast_form(expression) == expected
    expression.future_optional_field = [ast.Constant(1)]
    assert guard.ast_form(expression) != expected


@pytest.mark.parametrize("path", ["webapp/frontend/src/New.tsx", "atlas-scope/src/new.ts", "cisco_toolkit/blast_radius_explorer.html"])
@pytest.mark.parametrize("source,rule", [
    ("function answer(rows) { return rows.filter(r => r.band === 'Critical').length; }", "count"),
    ("const HEALTH_TONE = score => score >= 80 ? 'ok' : 'risk';", "fact-threshold"),
    ("function solve(adj, queue) { while(queue.length) { queue.push(...adj[queue.shift()]); } }", "graph-traversal"),
    ("function totals(rows) { return rows.reduce((n, row) => n + row.endpoints, 0); }", "aggregate"),
    ("function answer(rows) { return rows['length']; }", "count"),
    ("function f(xs) { let n = 0; xs.forEach(x => n++); return n; }", "counter-update"),
    ("function f(x) { return x >= 80 ? 'ok' : 'risk'; }", "fact-threshold"),
    ("function f(x, cutoff) { return x >= cutoff ? 'Critical' : 'Good'; }", "fact-decision"),
    ("function f(xs) { return new Set(xs).size; }", "count"),
    ("function f(x) { if (x) return 'NO-GO'; return 'GO'; }", "fact-decision"),
    ("const k = 'length'; function f(xs) { return xs[k]; }", "count"),
    ("const k = 'length'; function f(xs) { return xs[k]; } function other() { const k = 'unrelated'; return k; }", "count"),
    ("const k = 'len' + 'gth'; function f(xs) { return xs[k]; }", "count"),
    ("function f(xs) { return xs['len' + 'gth']; }", "count"),
    ("function f(xs) { const {length: n} = xs; return n; }", "count"),
    ("function f(xs) { const {'length': n} = xs; return n; }", "count"),
    ("function f(xs) { return Reflect.get(xs, 'length'); }", "count"),
])
def test_typescript_ast_and_html_scripts_catch_new_computations(parser, path, source, rule):
    text = f"<script>{source}</script>" if path.endswith("html") else source
    assert any(row["rule"] == rule for row in guard.scan({path: text}))


def test_lexical_tripwire_sees_generated_dynamic_code(parser):
    source = 'const template = "function walk(queue) { return queue.shift(); }";'
    assert any(row["rule"] == "graph-worklist" for row in guard.scan({"webapp/frontend/src/New.ts": source}))


def test_lexical_tripwire_sees_a_count_hidden_in_a_template(parser):
    source = 'const template = "function f(xs) { return xs.length; }";'
    assert any(row["rule"] == "raw-count" for row in guard.scan({"webapp/frontend/src/New.ts": source}))


@pytest.mark.parametrize("end", ["</script>", "</SCRIPT>", "</script\t\n bar>"])
def test_html_script_end_tags_preserve_all_following_scripts(parser, end):
    source = "<script>const first = 1;" + end + "<script>function f(rows) { return rows.length; }</script>"
    assert any(row["rule"] == "count" and row["symbol"] == "f" for row in guard.scan({"cisco_toolkit/blast_radius_explorer.html": source}))


def test_html_event_bodies_are_parsed_not_discarded(parser):
    source = '<button onclick="return rows[&quot;length&quot;]">x</button><script>const safe = 1;</script>'
    assert any(row["rule"] == "count" and row["symbol"].startswith("html_event_") for row in guard.scan({"cisco_toolkit/blast_radius_explorer.html": source}))


@pytest.mark.parametrize("source", [
    '<a href="javascript:rows[&quot;length&quot;]">x</a>',
    '<a href="javascript:rows%5B%22length%22%5D">x</a>',
    '<a href=" java&#9;script:rows[&quot;length&quot;]">x</a>',
    '<iframe srcdoc="&lt;button onclick=&quot;return rows[&amp;quot;length&amp;quot;]&quot;&gt;x&lt;/button&gt;"></iframe>',
])
def test_executable_html_attributes_cannot_hide_counts(parser, source):
    assert any(row["rule"] == "count" for row in guard.scan({"cisco_toolkit/blast_radius_explorer.html": source}))


@pytest.mark.parametrize("source", ['<script src="other.js"></script>', '<script/>return rows.length;', '<script>return rows.length;'])
def test_omitted_external_or_unclosed_script_sources_refuse(source):
    with pytest.raises(ValueError):
        guard.html_scripts(source)


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
    assert "cisco_toolkit/html.py" in sources
    assert "atlas-scope/tools/lib/compile-model.mjs" in sources
    assert "webapp/backend/engine.py" not in sources


@pytest.mark.parametrize("path", ["webapp/backend/new.py", "webapp/frontend/src/New.tsx", "atlas-scope/src/new.ts", "cisco_toolkit/new_report.py"])
def test_new_module_discovery_has_no_curated_file_list(tmp_path, monkeypatch, path):
    sources = {"cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.new_report')\n",
               path: "def f(rows):\n return len(rows)\n" if path.endswith("py") else "function f(rows) { return rows.length; }"}
    for name, text in sources.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "git", lambda *args: "\n".join(sources).encode())
    selected = guard.source_map()
    assert path in selected


def test_required_matrix_executes_the_guard_before_its_unchanged_complete_suite():
    workflow = yaml.safe_load((guard.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]
    guards = [(i, step) for i, step in enumerate(steps) if "pytest tests/test_interface_computation_debt.py" in step.get("run", "")]
    assert len(guards) == 1
    index, step = guards[0]
    assert "if" not in step and not step.get("continue-on-error", False)
    assert step["env"]["ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN"] == "1"
    assert any(s.get("run") == "npm ci" and s.get("working-directory") == "atlas-scope" for s in steps[:index])
    assert any("python -m pytest --durations=40" == s.get("run") for s in steps[index + 1:])
    assert any("test_pipeline_inprocess.py::test_pipeline_inprocess_builds_all_three_deliverables" in s.get("run", "") for s in steps[:index])
