"""Ratchet a closed, named set of detected computation forms under ADR 0008.

This is not proof of absence of computation. Undetected forms require review,
not certification; class/closure discovery and harmless-edit controls bind the
specific syntactic forms this guard actually detects.
"""
import ast
from collections import Counter
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

import interface_computation_guard as guard
from interface_computation_lex import python_stream
from interface_computation_sources import DYNAMIC_IMPORT_ALLOWANCES, WRITER_TARGETS, compiled_coverage, dynamic_imports, module_roles, python_closure, role_required
from ssot_contract_guard import require_canonical_checks
from pytest_invocation_reader import pytest_invocations
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
    """Checks detected forms only; other computations are not certified absent."""
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


def test_merge_cannot_hide_a_removed_allowance_on_its_other_parent(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=Ratchet Test",
             "-c", "user.email=ratchet@example.invalid", "-c", "commit.gpgsign=false",
             "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", *args],
            check=True, capture_output=True, text=True).stdout.strip()

    git("init", "--initial-branch=keep")
    (tmp_path / "basis.txt").write_text("source ceiling\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Source ceiling")
    monkeypatch.setattr(guard, "ORIGIN", git("rev-parse", "HEAD"))
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    site = sample_site()
    registry_path = tmp_path / guard.REGISTRY
    registry_path.parent.mkdir(parents=True)
    retained = json.dumps(guard.proposal([site]))
    registry_path.write_text(retained, encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Admit one exact site")
    git("checkout", "-b", "remove")
    registry_path.write_text(json.dumps(guard.proposal([])), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Remove the site and allowance")
    removed = git("rev-parse", "HEAD")
    git("checkout", "keep")
    (tmp_path / "basis.txt").write_text("unrelated edit\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Advance the other parent")
    git("merge", "--no-ff", "--no-commit", "remove")
    registry_path.write_text(retained, encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Resurrect the allowance in a merge")
    assert removed in git("rev-list", "HEAD").splitlines()
    monkeypatch.setattr(guard, "source_map", lambda revision=None: {})
    monkeypatch.setattr(guard, "scan", lambda sources: [site])
    with pytest.raises(ValueError, match="reappeared"):
        guard.check()


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
    ("def f(rows):\n return all(row.ready for row in rows)\n", "aggregate"),
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
    ("function f(xs) { let n = 0; for (const x of xs) n = n + 1; return n; }", "counter-update"),
    ("function f(xs) { return xs.every(x => x.ready); }", "aggregate"),
    ("function f(xs) { return xs.some(x => x.n_fail); }", "aggregate"),
    ("function f(xs) { const out = {}; for (const x of xs) { const k = x.category; out[k] = (out[k] || 0) + 1; } return out; }", "indexed-counter-update"),
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


def test_static_count_property_aliases_cross_html_scripts(parser):
    source = "<script>const field = 'length';</script><script>function f(xs) { return xs[field]; }</script>"
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


@pytest.mark.parametrize("source", ['<a href="data:text/html,hidden-code">x</a>', '<a href="vbscript:MsgBox(1)">x</a>', '<a href="unknown-script:payload">x</a>'])
def test_unparsed_url_languages_cannot_escape_the_census(parser, source):
    with pytest.raises(subprocess.CalledProcessError) as refused:
        guard.scan({"cisco_toolkit/blast_radius_explorer.html": source})
    assert "Unsupported" in refused.value.stderr


@pytest.mark.parametrize("source", ['<script src="other.js"></script>', '<svg><script href="other.js"></script></svg>', '<script/>return rows.length;', '<script>return rows.length;'])
def test_omitted_external_or_unclosed_script_sources_refuse(parser, source):
    with pytest.raises(subprocess.CalledProcessError) as refused:
        guard.scan({"cisco_toolkit/blast_radius_explorer.html": source})
    assert any(word in refused.value.stderr for word in ("External", "Self-closing", "Unclosed"))


def test_renderer_without_computation_does_not_create_a_debt(parser):
    assert guard.scan({"webapp/frontend/src/New.tsx": "export function View({fact}) { return <span>{fact.value}</span>; }"}) == []


def test_engine_readiness_can_be_displayed_without_a_new_verdict_return(parser):
    assert guard.scan({"webapp/frontend/src/New.tsx": "export function View({fact}) { return <span>{fact.readiness}</span>; }"}) == []


def test_multiline_jsx_whitespace_masks_advance_and_inert_text_is_not_code(parser):
    source = """export function View({fact}) {
 return (
  <section>
   <span>{fact.value}</span>
   <p>len(rows) queue.pop()</p>
  </section>
 );
}
"""
    assert guard.scan({"webapp/frontend/src/New.tsx": source}) == []


def test_ast_parse_errors_fail_closed(parser, capsys):
    with pytest.raises(subprocess.CalledProcessError):
        guard.scan({"webapp/frontend/src/New.ts": "function broken( {"})
    assert "source parse failed" in capsys.readouterr().err


def test_new_canonical_fact_without_check_is_refuted(monkeypatch):
    snap = {"unowned": {"value": 12}}
    monkeypatch.setattr(ssot, "CANONICAL_FACTS", {"new_fact": ("unowned.value", "mutation negative")})
    with pytest.raises(AssertionError, match="no executed reconcile check"):
        require_canonical_checks(snap)


def test_source_discovery_includes_new_interface_modules_and_registry_writers(parser):
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
    assert "webapp/backend/engine.py" in sources  # mixed adapter stays interface pending extraction
    assert "COLLECT_PARSE_V3_23_0.py" in sources
    assert "cisco_toolkit/analyze.py" not in sources
    assert "cisco_toolkit/parse.py" not in sources
    assert "webapp/frontend/dist/index.html" in sources
    assert not any(path.endswith(".js") and "/dist/" in path for path in sources)
    assert "webapp/frontend/index.html" in sources
    assert "atlas-scope/index.html" in sources


@pytest.mark.parametrize("path", ["webapp/backend/new.py", "cisco_toolkit/new_report.py"])
def test_new_module_discovery_has_no_curated_file_list(tmp_path, monkeypatch, path):
    sources = {"cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.new_report')\n",
               "cisco_toolkit/new_report.py": "from webapp.backend.new import f\n",
               path: "def f(rows):\n return len(rows)\n"}
    for name, text in sources.items():
        if role_required(name) and "__atlas_role__" not in text and name + ".atlas-role" not in sources:
            text = '__atlas_role__ = "interface"\n' + text
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "git", lambda *args: ("\0".join(sources) + "\0").encode())
    selected = guard.source_map()
    assert path in selected


def source_fixture(tmp_path, monkeypatch, sources):
    for name, text in sources.items():
        if role_required(name) and "__atlas_role__" not in text and name + ".atlas-role" not in sources:
            text = '__atlas_role__ = "interface"\n' + text
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "git", lambda *args: ("\0".join(sources) + "\0").encode())


def refuse_unregistered(sources, rule=None):
    sites = guard.scan(sources)
    if rule:
        assert any(site["rule"] == rule for site in sites)
    with pytest.raises(ValueError, match="Unregistered"):
        guard.validate(guard.proposal([]), sites, [])


def test_unregistered_report_helper_is_discovered_and_refused(tmp_path, monkeypatch):
    """Full imports, not writer registration, bring a new helper into the named-form gate."""
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.writer')\n",
        "cisco_toolkit/writer.py": "from .report_metrics import answer\n",
        "cisco_toolkit/report_metrics.py": "def answer(rows):\n return len(rows)\n",
    })
    selected = guard.source_map()
    assert "cisco_toolkit/report_metrics.py" in selected
    refuse_unregistered(selected, "aggregate")


def test_moving_a_registered_computation_into_a_helper_and_removing_old_rows_refuses(tmp_path, monkeypatch):
    original = {"cisco_toolkit/writer.py": "def answer(rows):\n return len(rows)\n"}
    original_sites = guard.scan(original)
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.writer')\n",
        "cisco_toolkit/writer.py": "from .report_metrics import answer\n",
        "cisco_toolkit/report_metrics.py": original["cisco_toolkit/writer.py"],
    })
    current = guard.scan(guard.source_map())
    assert any(site["path"] == "cisco_toolkit/report_metrics.py" for site in current)
    with pytest.raises(ValueError, match="Unregistered"):
        guard.validate(guard.proposal([]), current, original_sites, [guard.proposal(original_sites)])
    with pytest.raises(ValueError, match="ceiling"):
        guard.validate(guard.proposal(current), current, original_sites)


@pytest.mark.parametrize("path", ["webapp/frontend/index.html", "atlas-scope/index.html", "other-client/entry.html", "client/entry with space.html", "client/é.html", "client/PREVIEW.HTML", "client/entry.htm", "client/ENTRY.HTM", "client/entry.xhtml", "client/ENTRY.XHTML", "client/entry.svg", "client/ENTRY.SVG"])
def test_entry_document_computation_is_discovered_and_refused(parser, tmp_path, monkeypatch, path):
    document = "<script>function answer(rows) { return rows.length; }</script>"
    if path.lower().endswith(".svg"):
        document = '<svg xmlns="http://www.w3.org/2000/svg">' + document + '</svg>'
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        path: document,
    })
    selected = guard.source_map()
    assert path in selected
    refuse_unregistered(selected, "count")


@pytest.mark.parametrize("suffix", ["htm", "xhtml", "svg"])
def test_alternate_browser_document_follows_its_local_script(parser, tmp_path, monkeypatch, suffix):
    path = "client/entry." + suffix
    document = '<script type="module" src="./answer.js"></script>'
    if suffix == "svg":
        document = '<svg xmlns="http://www.w3.org/2000/svg"><script href="./answer.js"></script></svg>'
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        path: document,
        "client/answer.js": "export const answer = rows => rows.length;",
    })
    selected = guard.source_map()
    assert {path, "client/answer.js"} <= set(selected)
    refuse_unregistered(selected, "count")


@pytest.mark.parametrize("document", [
    '<svg xmlns="http://www.w3.org/2000/svg"><script><![CDATA[function answer(rows) {return rows.length;}]]></script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="eval(source)"></svg>',
])
def test_svg_document_cdata_and_event_payloads_remain_executable_sources(parser, document):
    rows = guard.scan({"client/entry.svg": document})
    assert any(row["rule"] in {"count", "dynamic-code"} for row in rows)
    with pytest.raises(ValueError, match="Unregistered"):
        guard.validate(guard.proposal([]), rows, [])


def test_browser_module_closure_follows_reexports_and_an_out_of_project_helper(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        "client/index.html": '<script type="module" src="./main.ts"></script>',
        "client/main.ts": "export {answer} from '../shared/index';",
        "shared/index.ts": "export {answer} from './metrics';",
        "shared/metrics.ts": "export function answer(rows) { return rows.length; }",
    })
    selected = guard.source_map()
    assert {"client/index.html", "client/main.ts", "shared/index.ts", "shared/metrics.ts"} <= set(selected)
    refuse_unregistered(selected, "count")


def test_browser_alias_dependency_is_closed_without_a_src_prefix(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        "client/package.json": '{"name":"client","dependencies":{"vite":"1"}}',
        "client/tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"metrics":["../shared/metrics"]}}}',
        "client/index.html": '<script type="module" src="/main.ts"></script>',
        "client/main.ts": "export {answer} from 'metrics';",
        "shared/metrics.ts": "export function answer(a, b) { return a / b; }",
    })
    selected = guard.source_map()
    assert "shared/metrics.ts" in selected
    refuse_unregistered(selected, "ratio-arithmetic")


def test_relative_entry_script_and_template_import_reach_an_unregistered_helper(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        "client/index.html": '<script type="module" src="main.js"></script>',
        "client/main.js": "export const load = () => import(`../shared/metrics.js`);",
        "shared/metrics.js": "export function answer(rows) { return rows.length; }",
    })
    selected = guard.source_map()
    assert "shared/metrics.js" in selected
    refuse_unregistered(selected, "count")


def test_importlib_alias_reaches_an_unregistered_report_helper(tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.writer')\n",
        "cisco_toolkit/writer.py": "from importlib import import_module as load\nhelper = load('cisco_toolkit.report_metrics')\n",
        "cisco_toolkit/report_metrics.py": "def answer(rows):\n return len(rows)\n",
    })
    selected = guard.source_map()
    assert "cisco_toolkit/report_metrics.py" in selected
    refuse_unregistered(selected, "aggregate")


@pytest.mark.parametrize("load", [
    "import importlib\nhelper = importlib.import_module('.metrics', package='report_helpers')",
    "import importlib as il\nhelper = il.import_module('.metrics', 'report_helpers')",
    "from importlib import import_module as load\nhelper = load(name='.metrics', package='report_helpers')",
    "import importlib\nload = importlib.import_module\nhelper = load('..metrics', package='report_helpers.nested')",
    "import importlib\nhelper = getattr(importlib, 'import_module')('.metrics', 'report_helpers')",
])
def test_relative_importlib_writer_reaches_an_outside_role_helper_and_refuses_its_count(load, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.writer')",
        "cisco_toolkit/writer.py": load,
        "report_helpers/metrics.py": "def answer(rows):\n return len(rows)",
    })
    selected = guard.source_map()
    assert "report_helpers/metrics.py" in selected
    refuse_unregistered(selected, "aggregate")


def test_moving_a_registered_count_into_a_relative_dynamic_helper_does_not_remove_the_obligation(tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.writer')",
        "cisco_toolkit/writer.py": "def answer(rows):\n return len(rows)",
    })
    old = guard.scan(guard.source_map())
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.writer')",
        "cisco_toolkit/writer.py": "import importlib\nhelper = importlib.import_module('.metrics', package='report_helpers')",
        "report_helpers/metrics.py": "def answer(rows):\n return len(rows)",
    })
    current = guard.scan(guard.source_map())
    assert any(site["path"] == "report_helpers/metrics.py" and site["rule"] == "aggregate" for site in current)
    # Deleting all the old writer's allowances cannot admit the moved helper.
    with pytest.raises(ValueError, match="Unregistered"):
        guard.validate(guard.proposal([]), current, old)


@pytest.mark.parametrize("load", [
    "import importlib\nimportlib.import_module('.renderer', package='cisco_toolkit')",
    "from importlib import import_module as load\nload('.renderer', 'cisco_toolkit')",
])
def test_engine_relative_dynamic_import_must_fail_the_interface_direction_check(load):
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/renderer.py": '__atlas_role__ = "interface"\ndef answer(rows):\n return len(rows)',
        "cisco_toolkit/owner.py": '__atlas_role__ = "engine"\n' + load,
    }
    with pytest.raises(ValueError, match="Engine imports interface"):
        python_closure(sources, sources.__getitem__)


@pytest.mark.parametrize("role", ["engine", "interface"])
@pytest.mark.parametrize("call", [
    "importlib.import_module(name)",
    "importlib.import_module('report_helpers.' + suffix)",
    "importlib.import_module('.metrics', package=package)",
    "importlib.import_module('report_helpers.metrics', package=package)",
    "importlib.import_module('.metrics')",
    "importlib.import_module('...metrics', 'report_helpers')",
    "importlib.import_module(**arguments)",
    "__import__('report_helpers.metrics')",
    "builtins.__import__('report_helpers.metrics')",
    "importlib.util.spec_from_file_location('metrics', path)",
    "importlib.util.spec_from_loader('metrics', loader)",
    "importlib.util.module_from_spec(spec)",
    "spec.loader.exec_module(module)",
    "loader.load_module('report_helpers.metrics')",
    "make_loader().exec_module(module)",
    "make_loader().load_module('report_helpers.metrics')",
    "make_loader()[0].exec_module(module)",
    "getattr(make_loader(), 'exec_module')(module)",
    "importlib.machinery.SourceFileLoader('metrics', path)",
    "getattr(importlib, selector)(name)",
    "importlib.__dict__[selector](name)",
    "vars(importlib)[selector](name)",
    "list(map(importlib.import_module, names))",
    "callbacks = [importlib.import_module]",
])
def test_unresolved_dynamic_loads_are_refused_for_both_roles(role, call):
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/owner.py": '__atlas_role__ = ' + repr(role) + '\nimport importlib\nimport builtins\n' + call,
    }
    with pytest.raises(ValueError, match="Unresolved dynamic import"):
        python_closure(sources, sources.__getitem__)


@pytest.mark.parametrize("source", [
    "from builtins import __import__ as load\nload('helper')",
    "from importlib.util import spec_from_file_location as load\nload('helper', path)",
    "from importlib.machinery import SourceFileLoader as Load\nLoad('helper', path)",
    "import importlib\nload = importlib.import_module\nload(name)",
    "load = spec.loader.exec_module\nload(module)",
    "load = make_loader().exec_module\nload(module)",
    "load = getattr(make_loader(), 'exec_module')\nload(module)",
    "import importlib\nlookup = getattr\nload = lookup(importlib, selector)\nload(name)",
    "import importlib\nlookup = vars\nlookup(importlib)[selector](name)",
])
def test_aliases_do_not_hide_unresolved_dynamic_imports(source):
    with pytest.raises(ValueError, match="Unresolved dynamic import"):
        dynamic_imports("report_helpers/writer.py", ast.parse(source), ())


def test_an_exact_dynamic_allowance_adds_targets_and_cannot_cover_a_move_or_a_second_occurrence(monkeypatch):
    import interface_computation_sources as discovery
    allowance = (("cisco_toolkit/owner.py", "load", "importlib.import_module(name)", ("cisco_toolkit.renderer",)),)
    original = discovery.dynamic_imports
    monkeypatch.setattr(discovery, "dynamic_imports", lambda path, tree: original(path, tree, allowance))
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/renderer.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/owner.py": '__atlas_role__ = "engine"\nimport importlib\ndef load(name):\n return importlib.import_module(name)',
    }
    with pytest.raises(ValueError, match="Engine imports interface"):
        python_closure(sources, sources.__getitem__)
    source = sources["cisco_toolkit/owner.py"]
    assert original("cisco_toolkit/owner.py", ast.parse(source), allowance) == {"cisco_toolkit.renderer"}
    for path, changed in [
        ("elsewhere.py", source),
        ("cisco_toolkit/owner.py", source.replace("def load(", "def moved(")),
        ("cisco_toolkit/owner.py", source.replace("import_module(name)", "import_module(other)")),
        ("cisco_toolkit/owner.py", source + "\n importlib.import_module(name)"),
    ]:
        with pytest.raises(ValueError, match="Unresolved dynamic import"):
            original(path, ast.parse(changed), allowance)


def test_dynamic_allowances_are_exact_existing_calls_and_writer_targets_equal_the_registry():
    keys = set()
    for path, symbol, expression, targets in DYNAMIC_IMPORT_ALLOWANCES:
        key = (path, symbol, ast.dump(ast.parse(expression, mode="eval").body))
        assert key not in keys
        keys.add(key)
        tree = ast.parse((guard.ROOT / path).read_text(encoding="utf-8"))
        owners = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol]
        assert len(owners) == 1, (path, symbol)
        matches = [node for node in ast.walk(owners[0]) if isinstance(node, ast.Call) and ast.dump(node) == key[2]]
        assert len(matches) == 1, (path, symbol, expression)
        assert targets and all("*" not in target for target in targets)
    registry = ast.parse((guard.ROOT / "cisco_toolkit/docmeta.py").read_text(encoding="utf-8"))
    writers = {keyword.value.value for node in ast.walk(registry) if isinstance(node, ast.Call)
               for keyword in node.keywords if keyword.arg == "writer_module" and isinstance(keyword.value, ast.Constant) and keyword.value.value}
    assert set(WRITER_TARGETS) == writers


@pytest.mark.parametrize("allowance", DYNAMIC_IMPORT_ALLOWANCES,
                         ids=[path + "::" + symbol + "::" + expression for path, symbol, expression, _ in DYNAMIC_IMPORT_ALLOWANCES])
def test_every_reviewed_dynamic_allowance_has_exact_targets_and_refuses_a_changed_or_moved_call(allowance):
    path, symbol, expression, targets = allowance
    source = "import importlib\ndef " + symbol + "():\n " + expression
    assert dynamic_imports(path, ast.parse(source)) == set(targets)
    with pytest.raises(ValueError, match="Unresolved dynamic import"):
        dynamic_imports(path, ast.parse(source), ())
    changed = ast.parse(expression, mode="eval").body
    changed.args[0] = ast.Name(id="unreviewed_target", ctx=ast.Load())
    for other_path, other_source in [
        ("unreviewed/moved.py", source),
        (path, source.replace("def " + symbol + "(", "def unreviewed_symbol(")),
        (path, "import importlib\ndef " + symbol + "():\n " + ast.unparse(changed)),
        (path, source + "\n " + expression),
    ]:
        with pytest.raises(ValueError, match="Unresolved dynamic import"):
            dynamic_imports(other_path, ast.parse(other_source))


@pytest.mark.parametrize("allowance", DYNAMIC_IMPORT_ALLOWANCES,
                         ids=[path + "::" + symbol + "::" + expression for path, symbol, expression, _ in DYNAMIC_IMPORT_ALLOWANCES])
def test_every_dynamic_allowance_target_is_traversed_and_cannot_launder_an_engine_interface_edge(allowance, monkeypatch):
    import interface_computation_sources as discovery
    path, symbol, expression, targets = allowance
    original = discovery.dynamic_imports
    # Put the actual allowed call behind an unclassified helper. Only its source
    # path is remapped; the real allowance, resolver, target traversal and engine
    # direction checks are used. Even a nominal third-party target is traversed
    # when repository source exists for that name.
    monkeypatch.setattr(discovery, "dynamic_imports", lambda owner, tree: original(path if owner == "probe.py" else owner, tree))
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/allowance_owner.py": '__atlas_role__ = "engine"\nimport probe',
        "cisco_toolkit/forbidden_interface.py": '__atlas_role__ = "interface"',
        "probe.py": "import importlib\ndef " + symbol + "():\n " + expression,
    }
    for target in targets:
        target_path = target.replace(".", "/") + ".py"
        sources[target_path] = ('__atlas_role__ = "interface"' if role_required(target_path)
                                else "from cisco_toolkit.forbidden_interface import answer")
    with pytest.raises(ValueError, match="Engine imports interface"):
        python_closure(sources, sources.__getitem__)


def test_hosted_admission_removed_only_whole_paths_outside_the_interface_closure(parser):
    # This pins the specific admission, not the size of future registers. Later
    # work can keep shrinking. No application is imported or executed.
    before = json.loads(guard.git("show", "84b4d8070250234d76e7037b7915d33ab21d5633:" + guard.REGISTRY))
    after = json.loads(guard.git("show", "26b9a978728f72f648dd01ef3d60bd9cd2da114d:" + guard.REGISTRY))
    original = {guard.identity(row) for row in before["sites"]}
    retained = {guard.identity(row) for row in after["sites"]}
    assert retained <= original
    removed = [row for row in before["sites"] if guard.identity(row) not in retained]
    assert len(removed) == 9244
    assert Counter(row["path"].split("/", 1)[0] for row in removed) == {
        ".claude": 10, ".github": 1780, "embed_qbank.py": 7,
        "master-reference": 4652, "ollama_judge.py": 19, "ollama_recall.py": 21,
        "ollama_retrieval_judge.py": 8, "portable": 860, "research_lane": 148,
        "setup.py": 3, "tools": 1720, "webapp": 16,
    }
    selected = guard.source_map("26b9a978728f72f648dd01ef3d60bd9cd2da114d")
    removed_paths = {row["path"] for row in removed}
    assert removed_paths.isdisjoint(selected), "A live scanned module lost an allowance"
    assert not any(role_required(path) for path in removed_paths)


def test_static_import_aliases_and_inert_edits_keep_identical_targets():
    sources = [
        "import importlib\nimportlib.import_module('.metrics', package='report_helpers')",
        "import importlib as il\n# harmless\nil.import_module( '.metrics' , 'report_helpers' )",
        "from importlib import import_module as first\nsecond = first\nsecond(name='.metrics', package='report_helpers')",
    ]
    for source in sources:
        assert dynamic_imports("helper.py", ast.parse(source), ()) == {"report_helpers.metrics"}


def test_discovery_releases_input_trees_without_requiring_cyclic_gc():
    # Isolate GC state in a child. This neither collects/warm-ups the test suite
    # nor changes any cold-request performance gate. Execute the immutable prior
    # pure discovery module as a negative control, never an application module.
    probe = r'''
import ast
import gc
from pathlib import Path
import subprocess
import sys
import types
import weakref
sys.path.insert(0, str(Path.cwd() / "tests"))
from interface_computation_sources import dynamic_imports
prior_source = subprocess.check_output([
    "git", "show", "4e9b28f631231a21ec02e9d32ddb80a4a14629eb:tests/interface_computation_sources.py"
], text=True, encoding="utf-8")
prior = types.ModuleType("prior_discovery")
exec(compile(prior_source, "prior_discovery.py", "exec"), prior.__dict__)
class Witness:
    pass
def retained_by(discover):
    tree = ast.parse("import importlib\nvalue = 1\n")
    tree.lifetime_witness = Witness()
    witness = weakref.ref(tree.lifetime_witness)
    assert discover("probe.py", tree, ()) == set()
    del tree
    return witness() is not None
gc.disable()
assert retained_by(prior.dynamic_imports), "Negative control did not expose prior AST retention"
assert not retained_by(dynamic_imports), "Discovery retained an unreachable input AST"
print("prior AST retained; current AST released without cyclic GC")
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", probe], cwd=guard.ROOT,
                            capture_output=True, text=True, timeout=30, check=True)
    assert result.stdout.strip() == "prior AST retained; current AST released without cyclic GC"


def test_python_detector_releases_source_and_discarded_facts_without_cyclic_gc():
    # The prior local visitor class forms a type/closure cycle that captures
    # per-source buffers and facts. Keep this lifetime/parity probe isolated
    # from the main test process and every application timing measurement.
    probe = r'''
import gc
import json
from pathlib import Path
import subprocess
import sys
import types
import weakref
sys.path.insert(0, str(Path.cwd() / "tests"))
import interface_computation_guard as current
prior_source = subprocess.check_output([
    "git", "show", "453ed3b152bd64634299690a3a1bb9aecdaaa797:tests/interface_computation_guard.py"
], text=True, encoding="utf-8")
prior = types.ModuleType("prior_detector")
prior.__file__ = str(Path.cwd() / "tests/interface_computation_guard.py")
exec(compile(prior_source, prior.__file__, "exec"), prior.__dict__)
class Witness:
    pass
class SourceLines(list):
    pass
class Fingerprint(str):
    pass
def observe(detector):
    source_refs, fact_refs = [], []
    original_source, original_digest = detector.python_source, detector.digest
    def source(text):
        text, lines, offsets = original_source(text)
        tagged = SourceLines(lines)
        tagged.witness = Witness()
        source_refs.append(weakref.ref(tagged.witness))
        return text, tagged, offsets
    def digest(text):
        tagged = Fingerprint(original_digest(text))
        tagged.witness = Witness()
        fact_refs.append(weakref.ref(tagged.witness))
        return tagged
    detector.python_source, detector.digest = source, digest
    facts = detector.python_sites("probe.py", "def answer(rows):\n return len(rows)\n")
    assert facts and source_refs and fact_refs
    serialized = json.dumps(facts, sort_keys=True)
    retained_source = any(ref() is not None for ref in source_refs)
    del facts
    retained_facts = any(ref() is not None for ref in fact_refs)
    return serialized, retained_source, retained_facts
gc.disable()
before, after = observe(prior), observe(current)
assert before[0] == after[0], "Detector changed emitted fact identities or display evidence"
assert before[1:] == (True, True), "Negative control did not expose prior payload retention"
assert after[1:] == (False, False), "Detector retained source/discarded facts until cyclic GC"
print("identical facts; prior payloads retained; current payloads released without cyclic GC")
'''
    result = subprocess.run([sys.executable, "-I", "-B", "-c", probe], cwd=guard.ROOT,
                            capture_output=True, text=True, timeout=30, check=True)
    assert result.stdout.strip() == "identical facts; prior payloads retained; current payloads released without cyclic GC"


def test_glob_reaches_a_helper_outside_the_frontend_project(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        "client/index.html": '<script type="module" src="main.js"></script>',
        "client/main.js": "export const modules = import.meta.glob('../shared/*.js', {eager: true});",
        "shared/metrics.js": "export function answer(rows) { return rows.length; }",
    })
    selected = guard.source_map()
    assert "shared/metrics.js" in selected
    refuse_unregistered(selected, "count")


def test_alias_without_base_url_uses_its_declaring_configuration(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        "client/package.json": '{"name":"client","dependencies":{"vite":"1"}}',
        "client/tsconfig.json": '{"compilerOptions":{"paths":{"metrics":["../shared/metrics"]}}}',
        "client/index.html": '<script type="module" src="main.js"></script>',
        "client/main.js": "export {answer} from 'metrics';",
        "shared/metrics.ts": "export function answer(a, b) { return a / b; }",
    })
    selected = guard.source_map()
    assert "shared/metrics.ts" in selected
    refuse_unregistered(selected, "ratio-arithmetic")


def test_locked_transitive_npm_dependency_is_a_third_party_terminal(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        "client/package.json": '{"name":"client","dependencies":{"vite":"1"}}',
        "client/package-lock.json": '{"lockfileVersion":3,"packages":{"node_modules/browser-driver":{"version":"1","resolved":"https://registry.npmjs.org/browser-driver/-/browser-driver-1.tgz"}}}',
        "client/index.html": '<script type="module" src="main.js"></script>',
        "client/main.js": "import {driver} from 'browser-driver'; export const value = driver;",
    })
    selected = guard.source_map()
    assert "client/main.js" in selected
    assert guard.scan(selected) == []


def test_file_linked_npm_name_cannot_hide_a_repository_helper(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        "client/package.json": '{"name":"client","dependencies":{"vite":"1","helper-metrics":"file:../shared"}}',
        "client/package-lock.json": '{"lockfileVersion":3,"packages":{"node_modules/helper-metrics":{"resolved":"../shared","link":true}}}',
        "client/index.html": '<script type="module" src="main.js"></script>',
        "client/main.js": "export {answer} from 'helper-metrics';",
        "shared/package.json": '{"name":"metrics"}',
        "shared/index.js": "export function answer(rows) { return rows.length; }",
    })
    selected = guard.source_map()
    assert "shared/index.js" in selected
    refuse_unregistered(selected, "count")


def test_new_opaque_remote_script_source_cannot_silently_pass(parser):
    refuse_unregistered({"client/index.html": '<script src="https://cdn.example.invalid/analysis.js"></script>'}, "opaque-script-source")


def test_opaque_script_comment_edits_keep_the_same_source_identity(parser):
    before = '<script src="https://cdn.example.invalid/analysis.js"></script>'
    after = '<!-- inert len(rows) --><script src="https://cdn.example.invalid/analysis.js"></script>'
    one = guard.scan({"client/index.html": before})
    two = guard.scan({"client/index.html": after})
    assert [guard.identity(row) for row in one] == [guard.identity(row) for row in two]


@pytest.mark.parametrize("source,rule", [
    ("def f(value, limit):\n return value <= limit\n", "returned-comparison"),
    ("def f(n):\n return n == 0\n", "returned-comparison"),
    ("f = lambda value, limit: value <= limit\n", "returned-comparison"),
    ("def pct(a, b):\n return 100 * a / b\n", "ratio-arithmetic"),
    ("def pct(a, b):\n return a / b\n", "ratio-arithmetic"),
    ("def can_cut_over(value):\n return value\n", "verdict-symbol"),
    ("def _isReady(value):\n return value\n", "verdict-symbol"),
    ("def f(ready):\n return ready\n", "verdict-return"),
    ("def f():\n return True\n", "verdict-return"),
    ("def f():\n return 'approved'\n", "verdict-return"),
    ('def f(expr):\n return f"{eval(expr)}"\n', "dynamic-code"),
])
def test_named_python_normal_forms_refuse_new_sites(source, rule):
    """Refuse these named forms; do not certify unrecognized computation absent."""
    refuse_unregistered({"webapp/backend/new.py": source}, rule)


@pytest.mark.parametrize("source,rule", [
    ("export function canCutOver(n: number) { return n === 0; }", "returned-comparison"),
    ("function f(value, limit) { return value <= limit; }", "returned-comparison"),
    ("const f = (value, limit) => value <= limit;", "returned-comparison"),
    ("function pct(a, b) { return 100 * a / b; }", "ratio-arithmetic"),
    ("function pct(a, b) { return a / b; }", "ratio-arithmetic"),
    ("function canCutOver(value) { return value; }", "verdict-symbol"),
    ("function _isReady(value) { return value; }", "verdict-symbol"),
    ("function f(ready) { return ready; }", "verdict-return"),
    ("function f() { return false; }", "verdict-return"),
    ("function f() { return 'approved'; }", "verdict-return"),
])
def test_named_typescript_normal_forms_refuse_new_sites(parser, source, rule):
    """Refuse these named forms; other forms still require independent review."""
    refuse_unregistered({"webapp/frontend/new.ts": source}, rule)


@pytest.mark.parametrize("before,after", [
    ("def f(rows):\n return len(rows)\n", "# len(rows), queue.pop(), a >= 1\ndef f ( rows ):\n return len ( rows ) # sum(rows)\n"),
    ("def f(a, b):\n return a + b\n", "def f(a, b):\n # health queue visited len(rows)\n return a + b\n"),
    ("def f(rows):\n return len(rows)\n", "def f(rows):\n return len(\n # len(rows)\n rows\n )\n"),
    ('def f(rows):\n return len(f"""{rows}\nbody\n""")\n', 'def f(rows):\n # len(rows), queue.pop()\n return len ( f"""{rows}\nbody\n""" )\n'),
])
def test_python_ast_and_lexical_identities_survive_harmless_edits(before, after):
    one = guard.scan({"webapp/backend/new.py": before})
    two = guard.scan({"webapp/backend/new.py": after})
    assert [guard.identity(row) for row in one] == [guard.identity(row) for row in two]


def test_nested_format_spec_spans_are_masked_once_without_corrupting_indentation():
    source = "def f(value, width):\n text = f'{value:0{width}d}'\n def following(rows):\n  return len(rows)\n return text\n"
    tree = ast.parse(source)
    joined = [node for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)]
    assert len(joined) > 1
    outer = joined[0]
    for node in joined[1:]:
        # Some supported AST versions reuse the whole literal's span for a
        # format-spec JoinedStr. Exercise equal/overlapping spans everywhere.
        ast.copy_location(node, outer)
    actual = python_stream(source, tree)
    assert any(token[1] == "len" for token in actual)
    assert actual == python_stream(source, ast.parse(source))


def test_unicode_data_separators_do_not_shift_python_source_lines():
    source = "separators = '" + "\u2028\u2029" + "'\ndef f(value):\n text = f'{value:08d}'\n def following(rows):\n  return len(rows)\n return text\n"
    plain = source.replace("\u2028\u2029", "unicode-data")
    one = guard.scan({"webapp/backend/lines.py": source})
    two = guard.scan({"webapp/backend/lines.py": plain})
    assert any(site["rule"] == "aggregate" for site in one)
    assert [guard.identity(row) for row in one] == [guard.identity(row) for row in two]


@pytest.mark.parametrize("before,after", [
    ("function f(rows) { return rows.length; }", "// len(rows), queue.pop(), a >= 1\nfunction f ( rows ) { return rows /* len(rows) */ . length; }"),
    ("function f(a,b) { return a + b; }", "function f(a,b) { return a /* health queue visited */ + b; }"),
    ("function f(a,b) { return a > b; }", "function f(a,b) { return a /* 80 */ > b; }"),
])
def test_javascript_ast_and_lexical_identities_survive_harmless_edits(parser, before, after):
    one = guard.scan({"webapp/frontend/new.js": before})
    two = guard.scan({"webapp/frontend/new.js": after})
    assert [guard.identity(row) for row in one] == [guard.identity(row) for row in two]


def test_entry_comments_and_handler_spacing_do_not_change_identities(parser):
    before = '<button onclick="return rows.length">go</button><script>function f(rows) { return rows.length; }</script>'
    after = '<!-- len(rows), queue.pop() --><button onclick="return rows /* len(rows) */ . length">go</button><script>function f(rows) { /* queue.pop() */ return rows . length; }</script>'
    one = guard.scan({"client/index.html": before})
    two = guard.scan({"client/index.html": after})
    assert [guard.identity(row) for row in one] == [guard.identity(row) for row in two]


def test_generated_payloads_remain_inspected_while_their_comments_are_ignored(parser):
    before = 'const template = "function f(xs) { return xs.length; }";'
    after = 'const template = "function f(xs) { /* queue.pop() */ return xs . length; }";'
    one = guard.scan({"webapp/frontend/new.js": before})
    two = guard.scan({"webapp/frontend/new.js": after})
    assert any(row["rule"] == "raw-count" and row["symbol"] == "<generated-payload>" for row in one)
    assert [guard.identity(row) for row in one] == [guard.identity(row) for row in two]


@pytest.mark.parametrize("path,source", [
    ("webapp/backend/template.py", 'template = f"<script>function f(rows) {{ return rows.length + {extra}; }}</script>"\n'),
    ("webapp/frontend/template.js", 'const template = `<script>function f(rows) { return rows.length + ${extra}; }</script>`;'),
])
def test_interpolated_html_templates_remain_one_inspected_payload(parser, path, source):
    refuse_unregistered({path: source}, "raw-count")


def test_diagnostic_markup_is_recorded_opaque_without_becoming_an_entry_document(parser):
    source = 'def refusal(src):\n return f"<script src={src!r}> is not a module entry"\n'
    refuse_unregistered({"webapp/backend/template.py": source}, "opaque-generated-source")


def test_static_payload_code_is_still_inspected_beside_an_opaque_source(parser):
    source = 'const template = "<script src=missing.js></script><script>function f(rows) { return rows.length; }</script>";'
    sites = guard.scan({"webapp/frontend/template.js": source})
    assert any(site["rule"] == "opaque-generated-source" for site in sites)
    assert any(site["rule"] == "raw-count" and site["symbol"] == "<generated-payload>" for site in sites)


def test_unknown_historical_policy_cannot_reset_the_ceiling():
    site = sample_site()
    previous = {**guard.proposal([]), "schema": "interface-computation-debt/unknown"}
    with pytest.raises(ValueError, match="unauthorized"):
        guard.validate(guard.proposal([site]), [site], [site], [previous])


def test_v1_register_cannot_be_reintroduced_after_the_authorized_cutoff(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=Ratchet Test",
             "-c", "user.email=ratchet@example.invalid", "-c", "commit.gpgsign=false",
             "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", *args],
            check=True, capture_output=True, text=True).stdout.strip()

    git("init", "--initial-branch=keep")
    (tmp_path / "basis.txt").write_text("source ceiling\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Source ceiling")
    monkeypatch.setattr(guard, "ORIGIN", git("rev-parse", "HEAD"))
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    target = tmp_path / guard.REGISTRY
    target.parent.mkdir(parents=True)
    legacy = {**guard.proposal([]), "schema": "interface-computation-debt/1"}
    target.write_text(json.dumps(legacy), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Historical v1 proposal")
    monkeypatch.setattr(guard, "LEGACY_REGISTER_HEAD", git("rev-parse", "HEAD"))
    target.write_text(json.dumps({**legacy, "sites": [sample_site()]}), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Unapproved v1 reset")
    target.write_text(json.dumps(guard.proposal([])), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Return to current policy")
    monkeypatch.setattr(guard, "source_map", lambda revision=None: {})
    monkeypatch.setattr(guard, "scan", lambda sources: [])
    with pytest.raises(subprocess.CalledProcessError):
        guard.check()


def test_required_matrix_executes_the_guard_before_its_unchanged_complete_suite():
    workflow = yaml.safe_load((guard.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["test"]["steps"]
    guards = [(i, step) for i, step in enumerate(steps) if step.get("run") == "python -m pytest tests/test_interface_computation_debt.py"]
    assert len(guards) == 1
    index, step = guards[0]
    assert "if" not in step and not step.get("continue-on-error", False)
    assert step["env"]["ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN"] == "1"
    assert any(s.get("run") == "npm ci" and s.get("working-directory") == "atlas-scope" for s in steps[:index])
    # The complete default suite after the guard is its two passes (tests/test_ci_gates.py ::
    # test_every_parallel_suite_pass_has_its_serial_unshared_complement), both unconditional.
    later = {s.get("run"): s for s in steps[index + 1:]}
    for run in ('python -m pytest --durations=40 -n auto --dist=loadfile -m "not unshared"',
                "python -m pytest --durations=40 -m unshared"):
        assert run in later and "if" not in later[run], run
    assert any("test_pipeline_inprocess.py::test_pipeline_inprocess_builds_all_three_deliverables" in s.get("run", "") for s in steps[:index])
    synthetic = [(i, s) for i, s in enumerate(steps) if s.get("name") == "Synthetic detected-form refusal and stability controls"]
    assert len(synthetic) == 1
    synthetic_index, synthetic_step = synthetic[0]
    assert "if" not in synthetic_step and not synthetic_step.get("continue-on-error", False)
    assert synthetic_step["env"]["ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN"] == "1"
    observation = next(i for i, s in enumerate(steps) if s.get("name") == "Observe exact interface computation sites for review")
    assert synthetic_index < observation < index
    # The shared reader must see the actual file before a quoted -k expression;
    # no default-suite/Scope oracle obligation is invented by command spelling.
    assert pytest_invocations(synthetic_step["run"]) == [["tests/test_interface_computation_debt.py"]]
    assert any(s.get("run") == "npm ci" and s.get("working-directory") == "atlas-scope" for s in steps[:synthetic_index])


@pytest.mark.parametrize("declaration", ["", '__atlas_role__ = "other"',
    '__atlas_role__ = "engine" if choose else "interface"',
    '__atlas_role__ = "engine"\n__atlas_role__ = "interface"',
    'def f():\n global __atlas_role__\n __atlas_role__ = "engine"'])
@pytest.mark.parametrize("path", ["cisco_toolkit/new.py", "cisco_toolkit/nested/new.py", "webapp/backend/new.py", "COLLECT_PARSE_V3_23_0.py", "cisco_toolkit/NEW.PY", "WEBAPP/backend/new.Py"])
def test_every_owned_module_requires_exactly_one_literal_role(path, declaration):
    with pytest.raises(ValueError, match="exactly one literal"):
        module_roles([path], {path: declaration}.__getitem__)


def test_engine_owners_stop_interface_traversal_without_registering_their_computation():
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/renderer.py": '__atlas_role__ = "interface"\nfrom .analyze import compute',
        "cisco_toolkit/analyze.py": '__atlas_role__ = "engine"\nfrom .parse import load\ndef compute(rows):\n return len(rows)',
        "cisco_toolkit/parse.py": '__atlas_role__ = "engine"\ndef load():\n return []',
    }
    assert python_closure(sources, sources.__getitem__) == {"cisco_toolkit/docmeta.py", "cisco_toolkit/renderer.py"}


@pytest.mark.parametrize("edge", ["from .renderer import answer", "from . import renderer", "import cisco_toolkit.renderer", "from helper import answer", "from .ReNdErEr import answer"])
def test_engine_cannot_import_interface_directly_or_through_an_unregistered_helper(edge):
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/renderer.py": '__atlas_role__ = "interface"\ndef answer(rows):\n return len(rows)',
        "cisco_toolkit/analyze.py": '__atlas_role__ = "engine"\n' + edge,
        "helper.py": "from cisco_toolkit.renderer import answer",
    }
    with pytest.raises(ValueError, match="Engine imports interface"):
        python_closure(sources, sources.__getitem__)


@pytest.mark.parametrize("leaf", ["cisco_toolkit/report/__init__.py", "cisco_toolkit/Report/__INIT__.PY"])
def test_registered_package_initializer_is_a_writer_not_an_engine_terminal(leaf):
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"\nArtifactSpec(writer_module="cisco_toolkit.report")',
        leaf: '__atlas_role__ = "engine"\ndef render(rows):\n return len(rows)',
    }
    with pytest.raises(ValueError, match="writer cannot declare engine"):
        python_closure(sources, sources.__getitem__)


def test_windows_case_variant_helper_remains_in_the_full_report_closure(tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.writer')\n",
        "cisco_toolkit/writer.py": "from helpercase import answer\n",
        "HelperCase.PY": "def answer(rows):\n return len(rows)\n",
    })
    selected = guard.source_map()
    assert "HelperCase.PY" in selected
    refuse_unregistered(selected, "aggregate")


def test_windows_case_colliding_module_identities_refuse():
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "helpers/Twin.py": "value = 1",
        "helpers/twin.PY": "value = 2",
    }
    with pytest.raises(ValueError, match="Ambiguous Windows Python module"):
        python_closure(sources, sources.__getitem__)


@pytest.mark.parametrize("writer", ["ArtifactSpec(writer_module='cisco_toolkit.report')", ""])
def test_a_report_writer_cannot_hide_behind_engine_role(writer):
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"\n' + writer,
        "cisco_toolkit/report.py": '__atlas_role__ = "engine"\nimport openpyxl',
    }
    with pytest.raises(ValueError, match="writer cannot declare engine"):
        python_closure(sources, sources.__getitem__)


@pytest.mark.parametrize("path", ["new/dist/index.html", "new/dist/index.XHTML", "new/dist/icon.svg", "new/dist-hub/bundle.js", "webapp/frontend/dist-hub/app.js"])
def test_uncovered_checked_in_generated_entry_or_bundle_refuses(path):
    with pytest.raises(ValueError, match="no source-to-dist gate"):
        compiled_coverage([path], lambda name: "")


def test_compiled_exclusion_requires_the_named_enforced_build_comparison():
    names = ["webapp/frontend/dist/index.html", "webapp/frontend/dist/assets/app.js"]
    def read(path):
        return (guard.ROOT / path).read_text(encoding="utf-8")

    assert compiled_coverage(names, read) == set(names)
    for before, after in [
        ("Prove the SPA build reproduced the immutable source", "Removed gate"),
        ('      - name: Prove the SPA build reproduced the immutable source',
         '      - if: false\n        name: Prove the SPA build reproduced the immutable source'),
        ('          npm run build', '          echo build'),
        ('--allow-untracked-prefix webapp/frontend/node_modules', '--allow-untracked-prefix webapp/frontend/dist'),
    ]:
        def changed(path):
            text = read(path)
            return text.replace(before, after) if path.endswith("ci.yml") else text
        with pytest.raises(ValueError, match="source-to-dist gate"):
            compiled_coverage(names, changed)


def test_compiled_entry_inline_code_stays_scanned_but_covered_bundles_do_not(parser, tmp_path, monkeypatch):
    workflow = (guard.ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    helper = (guard.ROOT / ".github/scripts/verify_checkout_immutable.py").read_text(encoding="utf-8")
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": 'ARTIFACT_SPECS = ()',
        ".github/workflows/ci.yml": workflow,
        ".github/scripts/verify_checkout_immutable.py": helper,
        "webapp/frontend/dist/index.html": '<script src="assets/app.js"></script><script>function answer(rows) {return rows.length}</script>',
        "webapp/frontend/dist/assets/app.js": "throw new Error('compiled bytes verified by source-to-dist gate')",
    })
    selected = guard.source_map()
    assert "webapp/frontend/dist/assets/app.js" not in selected
    assert "webapp/frontend/dist/index.html" in selected
    refuse_unregistered(selected, "count")



def test_a_package_initializer_cannot_substitute_for_an_absent_registered_writer():
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"\nArtifactSpec(writer_module="cisco_toolkit.absent")',
        "cisco_toolkit/__init__.py": '__atlas_role__ = "engine"',
    }
    with pytest.raises(ValueError, match="writer source is absent"):
        python_closure(sources, sources.__getitem__)



def test_compiler_declared_build_output_without_a_byte_gate_refuses(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()",
        "new/tsconfig.json": '{"compilerOptions":{"outDir":"build"}}',
        "new/build/bundle.js": "export const minified = 1",
    })
    with pytest.raises(ValueError, match="no source-to-dist gate"):
        guard.source_map()


def test_authored_build_tools_are_scanned_instead_of_mistaken_for_compiled_output(parser, tmp_path, monkeypatch):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()",
        "client/package.json": '{"dependencies":{"vite":"1"}}',
        "client/build/tool.mjs": "export function answer(rows) { return rows.length }",
    })
    selected = guard.source_map()
    assert "client/build/tool.mjs" in selected
    refuse_unregistered(selected, "count")



def test_read_only_workbook_input_reader_remains_an_engine_owner():
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/ingestion.py": '__atlas_role__ = "engine"\nfrom openpyxl import load_workbook as read\n'
                                    'def ingest(path):\n book = read(path, read_only=True, data_only=True)\n return list(book)',
    }
    assert python_closure(sources, sources.__getitem__) == {"cisco_toolkit/docmeta.py"}


@pytest.mark.parametrize("body", [
    'book = load_workbook(path)',
    'book = load_workbook(path, read_only=False)',
    'book = load_workbook(path, read_only=flag)',
    'book = load_workbook(path, read_only=True, **options)',
    'book = load_workbook(path, read_only=True)\nbook.save(path)',
    'reader = load_workbook\nbook = reader(path, read_only=True)',
    'from openpyxl import Workbook\nbook = load_workbook(path, read_only=True)',
])
def test_report_library_use_without_the_closed_read_only_form_cannot_be_engine(body):
    sources = {
        "cisco_toolkit/docmeta.py": '__atlas_role__ = "interface"',
        "cisco_toolkit/hidden_report.py": '__atlas_role__ = "engine"\nfrom openpyxl import load_workbook\n' + body,
    }
    with pytest.raises(ValueError, match="writer cannot declare engine"):
        python_closure(sources, sources.__getitem__)



def test_every_observed_detector_has_identical_committed_and_executing_bytes():
    # Derive the byte-owner class from the observer's actual metadata producer;
    # a newly added detector cannot escape through a second hand-kept file list.
    owner = ast.parse((guard.DETECTOR_ROOT / "tests/interface_computation_guard.py").read_text(encoding="utf-8"))
    entries = [value for node in ast.walk(owner) if isinstance(node, ast.Dict)
               for key, value in zip(node.keys, node.values)
               if isinstance(key, ast.Constant) and key.value == "detectors"]
    assert len(entries) == 1 and isinstance(entries[0], ast.DictComp)
    paths = ast.literal_eval(entries[0].generators[0].iter)
    assert paths and len(paths) == len(set(paths))
    expected = {"text": "set", "eol": "lf", "filter": "unspecified",
                "ident": "unspecified", "working-tree-encoding": "unspecified"}
    for source in ((), ("--source=HEAD",)):
        raw = guard.git("check-attr", *source, "-z", *expected, "--", *paths).decode("utf-8").split("\0")
        assert raw.pop() == "" and len(raw) % 3 == 0
        attributes = {}
        for index in range(0, len(raw), 3):
            path, attribute, value = raw[index:index + 3]
            attributes.setdefault(path, {})[attribute] = value
        assert attributes == {path: expected for path in paths}
    for path in paths:
        assert (guard.DETECTOR_ROOT / path).read_bytes() == guard.git("cat-file", "blob", "HEAD:" + path), path



def test_module_owned_companions_preserve_the_same_mandatory_engine_interface_boundary():
    sources = {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()",
        "cisco_toolkit/docmeta.py.atlas-role": '{"role":"interface"}',
        "cisco_toolkit/owner.py": "def compute(rows):\n return len(rows)",
        "cisco_toolkit/owner.py.atlas-role": '{"role":"engine"}',
        "cisco_toolkit/renderer.py": "from .owner import compute",
        "cisco_toolkit/renderer.py.atlas-role": '{"role":"interface"}',
    }
    assert python_closure(sources, sources.__getitem__) == {"cisco_toolkit/docmeta.py", "cisco_toolkit/renderer.py"}
    sources["cisco_toolkit/owner.py"] = "from .renderer import compute"
    with pytest.raises(ValueError, match="Engine imports interface"):
        python_closure(sources, sources.__getitem__)


@pytest.mark.parametrize("metadata", ['{}', '{"role":"other"}', '{"role":true}',
    '{"role":"engine","extra":1}', '{"role":"engine","role":"interface"}'])
def test_module_companions_are_closed_and_cannot_hide_duplicate_or_ambiguous_roles(metadata):
    sources = {"cisco_toolkit/new.py": "", "cisco_toolkit/new.py.atlas-role": metadata}
    with pytest.raises(ValueError):
        module_roles(sources, sources.__getitem__)


def test_a_constant_and_companion_cannot_compete_for_the_module_role():
    sources = {"cisco_toolkit/new.py": '__atlas_role__ = "engine"',
               "cisco_toolkit/new.py.atlas-role": '{"role":"interface"}'}
    with pytest.raises(ValueError, match="exactly one literal"):
        module_roles(sources, sources.__getitem__)


@pytest.mark.parametrize("path", ["cisco_toolkit/removed.py.atlas-role", "outside/hidden.py.atlas-role"])
def test_orphan_or_unowned_module_companion_refuses(path):
    with pytest.raises(ValueError, match="Orphan or unowned"):
        module_roles([path], lambda name: '{"role":"engine"}')


def test_removing_a_companion_does_not_default_a_module_to_engine():
    with pytest.raises(ValueError, match="exactly one literal"):
        module_roles(["cisco_toolkit/new.py"], lambda name: "")


def test_registered_writers_cannot_hide_behind_an_engine_companion():
    sources = {
        "cisco_toolkit/docmeta.py": 'ArtifactSpec(writer_module="cisco_toolkit.report")',
        "cisco_toolkit/docmeta.py.atlas-role": '{"role":"interface"}',
        "cisco_toolkit/report.py": "def write_report_docx():\n return None",
        "cisco_toolkit/report.py.atlas-role": '{"role":"engine"}',
    }
    with pytest.raises(ValueError, match="writer cannot declare engine"):
        python_closure(sources, sources.__getitem__)



def test_initial_companion_migration_preserves_roles_and_frozen_application_bytes():
    legacy = "97813d794f8cb8d61b206ba49a52aa4f9142b8e6"
    foundation = "5f1e067c2cb57866b380ddc9426f7ee4e0f9f2fc"

    def declarations(revision):
        names, snapshot = guard.revision_sources(revision, roles_only=True)
        roles = module_roles(names, lambda path: snapshot[path].decode("utf-8"))
        return set(names), roles, snapshot

    _legacy_names, legacy_roles, _legacy_source = declarations(legacy)
    migrated_names, migrated_roles, migrated_source = declarations(guard.ROLE_ORIGIN)
    _foundation_names, foundation_source = guard.revision_sources(foundation, roles_only=True)
    assert migrated_roles == legacy_roles
    assert all(path + ".atlas-role" in migrated_names for path in migrated_roles)
    # The same exact byte assertion over immutable objects, without hundreds of
    # process launches. It does not freeze later application changes.
    for path in migrated_roles:
        assert migrated_source[path] == foundation_source[path], path



def test_v2_register_cannot_be_reintroduced_after_the_main_refresh_cutoff(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=Ratchet Test",
             "-c", "user.email=ratchet@example.invalid", "-c", "commit.gpgsign=false",
             "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", *args],
            check=True, capture_output=True, text=True).stdout.strip()

    git("init", "--initial-branch=keep")
    (tmp_path / "basis.txt").write_text("new main source ceiling\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "New source ceiling")
    monkeypatch.setattr(guard, "ORIGIN", git("rev-parse", "HEAD"))
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    target = tmp_path / guard.REGISTRY
    target.parent.mkdir(parents=True)
    legacy = {**guard.proposal([]), "schema": "interface-computation-debt/2"}
    target.write_text(json.dumps(legacy), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Historical pre-main v2 proposal")
    monkeypatch.setattr(guard, "LEGACY_V2_REGISTER_HEAD", git("rev-parse", "HEAD"))
    target.write_text(json.dumps(guard.proposal([])), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Current source-bound register")
    monkeypatch.setattr(guard, "source_map", lambda revision=None: {})
    monkeypatch.setattr(guard, "scan", lambda sources: [])
    assert guard.check() == 0  # authorized old policy is historical, not an exemption forever
    target.write_text(json.dumps(legacy), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Forbidden later v2 reset")
    target.write_text(json.dumps(guard.proposal([])), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Attempt to hide the reset")
    with pytest.raises(subprocess.CalledProcessError):
        guard.check()



@pytest.mark.parametrize("stage", ["observation_required", "disabled", None, 0])
def test_inactive_or_unknown_historical_stage_cannot_hide_a_removed_entry(stage):
    site = sample_site()
    prior = {**guard.proposal([]), "stage": stage}
    with pytest.raises(ValueError, match="unauthorized"):
        guard.validate(guard.proposal([site]), [site], [site], [prior])


def test_a_different_historical_source_origin_cannot_reset_the_ceiling():
    prior = {**guard.proposal([]), "origin": "b" * 40}
    with pytest.raises(ValueError, match="unauthorized"):
        guard.validate(guard.proposal([]), [], [], [prior])


@pytest.mark.parametrize("stage", ["observation_required", "disabled"])
def test_only_the_pinned_initial_observation_may_be_inactive_in_git_history(tmp_path, monkeypatch, stage):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Ratchet Test",
            "-c", "user.email=ratchet@example.invalid", "-c", "commit.gpgsign=false",
            "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", *args],
            check=True, capture_output=True, text=True).stdout.strip()

    git("init", "--initial-branch=main")
    (tmp_path / "basis.txt").write_text("Source ceiling\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "Source ceiling")
    monkeypatch.setattr(guard, "ORIGIN", git("rev-parse", "HEAD"))
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    target = tmp_path / guard.REGISTRY
    target.parent.mkdir(parents=True)

    def record(value, message):
        target.write_text(json.dumps(value), encoding="utf-8")
        git("add", ".")
        git("commit", "-m", message)

    record({**guard.proposal([]), "stage": "observation_required"}, "Initial empty capture")
    monkeypatch.setattr(guard, "LEGACY_V3_OBSERVATION_HEAD", git("rev-parse", "HEAD"))
    site = sample_site()
    record(guard.proposal([site]), "Admitted exact site")
    monkeypatch.setattr(guard, "source_map", lambda revision=None: {})
    monkeypatch.setattr(guard, "scan", lambda sources: [site])
    assert guard.check() == 1  # The genuine pinned bootstrap remains admissible.
    record({**guard.proposal([]), "stage": stage}, "Remove while attempting to disable")
    record(guard.proposal([site]), "Restore the removed allowance and active stage")
    if stage == "observation_required":
        with pytest.raises(subprocess.CalledProcessError):
            guard.check()
    else:
        with pytest.raises(ValueError, match="unauthorized"):
            guard.check()


def test_immutable_batch_source_reader_preserves_git_bytes_names_and_shared_blobs(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Snapshot Test",
            "-c", "user.email=snapshot@example.invalid", "-c", "commit.gpgsign=false",
            "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", *args],
            check=True, capture_output=True).stdout

    git("init", "--initial-branch=main")
    files = {"client/a with space.ts": b"export const count = 2;\n",
             "client/shared.ts": b"export const count = 2;\n",
             "client/ENTRY.XHTML": b"<script>const count = rows.length;</script>\n",
             "client/icon.svg": b'<svg xmlns="http://www.w3.org/2000/svg"/>\n',
             "cisco_toolkit/é.py": "value = 'é'\n".encode(),
             "helpers/Reader.PY": b"value = 1\n",
             "COLLECT_PARSE_V3_23_0.py": b"value = 1\n",
             "webapp/backend/Adapter.py": b"value = 1\n",
             "cisco_toolkit/é.py.atlas-role": b'{"role":"engine"}\n',
             "large-unrelated.json": b'{"not_a_source_input":true}\n'}
    for path, data in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    git("add", ".")
    git("commit", "-m", "Source snapshot")
    revision = git("rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    names, snapshot = guard.revision_sources(revision)
    assert set(names) == set(files)
    assert set(snapshot) == set(files) - {"large-unrelated.json"}
    for path in snapshot:
        assert snapshot[path] == git("cat-file", "blob", revision + ":" + path)
    role_names, role_snapshot = guard.revision_sources(revision, roles_only=True)
    assert role_names == names  # The complete name/orphan census is never narrowed.
    assert set(role_snapshot) == {"cisco_toolkit/é.py", "cisco_toolkit/é.py.atlas-role",
                                  "COLLECT_PARSE_V3_23_0.py", "webapp/backend/Adapter.py"}
    assert all(data == snapshot[path] for path, data in role_snapshot.items())
    # Immutable bytes never follow a dirty worktree or mutable timestamp cache.
    (tmp_path / "client/shared.ts").write_bytes(b"different worktree source\n")
    (tmp_path / "cisco_toolkit/é.py").write_bytes(b"different role source\n")
    assert guard.revision_sources(revision)[1] == snapshot
    assert guard.revision_sources(revision, roles_only=True)[1] == role_snapshot


@pytest.mark.parametrize("batch", [
    b"missing\n", b"b" * 40 + b" blob 1\nx\n", b"a" * 40 + b" tree 1\nx\n",
    b"a" * 40 + b" blob -1\nx\n", b"a" * 40 + b" blob 8\nx\n",
    b"a" * 40 + b" blob 1\nx!", b"a" * 40 + b" blob 1\nx\nextra",
])
def test_immutable_source_batch_rejects_object_and_framing_tampering(batch, monkeypatch):
    def git(*args, input=None):
        if args[0] == "ls-tree":
            return b"100644 blob " + b"a" * 40 + b"\tclient/main.ts\0"
        return batch
    monkeypatch.setattr(guard, "git", git)
    with pytest.raises(ValueError, match="immutable source batch"):
        guard.revision_sources("a" * 40)


def test_immutable_source_batch_does_not_follow_a_source_symlink(monkeypatch):
    monkeypatch.setattr(guard, "git", lambda *args, **kwargs: b"120000 blob " + b"a" * 40 + b"\tclient/main.ts\0")
    with pytest.raises(ValueError, match="nonregular"):
        guard.revision_sources("a" * 40)
