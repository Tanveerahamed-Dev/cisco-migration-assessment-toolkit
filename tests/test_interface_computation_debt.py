"""Ratchet a closed, named set of detected computation forms under ADR 0008.

This is not proof of absence of computation. Undetected forms require review,
not certification; class/closure discovery and harmless-edit controls bind the
specific syntactic forms this guard actually detects.
"""
import ast
import json
import os
import shutil
import subprocess

import pytest
import yaml

import interface_computation_guard as guard
from interface_computation_lex import python_stream
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
    assert "webapp/backend/engine.py" in sources  # reached through registered report imports
    assert "webapp/frontend/index.html" in sources
    assert "atlas-scope/index.html" in sources


@pytest.mark.parametrize("path", ["webapp/backend/new.py", "cisco_toolkit/new_report.py"])
def test_new_module_discovery_has_no_curated_file_list(tmp_path, monkeypatch, path):
    sources = {"cisco_toolkit/docmeta.py": "ArtifactSpec(writer_module='cisco_toolkit.new_report')\n",
               "cisco_toolkit/new_report.py": "from webapp.backend.new import f\n",
               path: "def f(rows):\n return len(rows)\n"}
    for name, text in sources.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "git", lambda *args: ("\0".join(sources) + "\0").encode())
    selected = guard.source_map()
    assert path in selected


def source_fixture(tmp_path, monkeypatch, sources):
    for name, text in sources.items():
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


@pytest.mark.parametrize("path", ["webapp/frontend/index.html", "atlas-scope/index.html", "other-client/entry.html", "client/entry with space.html", "client/é.html", "client/PREVIEW.HTML"])
def test_entry_document_computation_is_discovered_and_refused(parser, tmp_path, monkeypatch, path):
    source_fixture(tmp_path, monkeypatch, {
        "cisco_toolkit/docmeta.py": "ARTIFACT_SPECS = ()\n",
        path: "<script>function answer(rows) { return rows.length; }</script>",
    })
    selected = guard.source_map()
    assert path in selected
    refuse_unregistered(selected, "count")


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
    guards = [(i, step) for i, step in enumerate(steps) if "pytest tests/test_interface_computation_debt.py" in step.get("run", "")]
    assert len(guards) == 1
    index, step = guards[0]
    assert "if" not in step and not step.get("continue-on-error", False)
    assert step["env"]["ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN"] == "1"
    assert any(s.get("run") == "npm ci" and s.get("working-directory") == "atlas-scope" for s in steps[:index])
    assert any("python -m pytest --durations=40" == s.get("run") for s in steps[index + 1:])
    assert any("test_pipeline_inprocess.py::test_pipeline_inprocess_builds_all_three_deliverables" in s.get("run", "") for s in steps[:index])
    synthetic = [(i, s) for i, s in enumerate(steps) if s.get("name") == "Synthetic detected-form refusal and stability controls"]
    assert len(synthetic) == 1
    synthetic_index, synthetic_step = synthetic[0]
    assert "if" not in synthetic_step and not synthetic_step.get("continue-on-error", False)
    assert synthetic_step["env"]["ATLAS_SCOPE_REQUIRE_REAL_TOOLCHAIN"] == "1"
    observation = next(i for i, s in enumerate(steps) if s.get("name") == "Observe exact interface computation sites for review")
    assert synthetic_index < observation < index
    assert any(s.get("run") == "npm ci" and s.get("working-directory") == "atlas-scope" for s in steps[:synthetic_index])
