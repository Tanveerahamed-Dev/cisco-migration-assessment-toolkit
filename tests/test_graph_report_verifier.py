from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.verify_graph_report import (
    KNOWN_EXTERNAL_REPORT_RESIDUALS,
    _parse_graph,
    _parse_labels,
    audit_graph_report,
    audit_graph_report_data as _audit_graph_report_data,
    partition_graph,
)


_AUTO_SIGNATURES = object()


def _membership_signatures(graph: dict) -> dict[int, str]:
    members: dict[int, list[str]] = {}
    for node in graph.get("nodes", []):
        if isinstance(node, dict):
            members.setdefault(node.get("community"), []).append(str(node.get("id")))
    signatures: dict[int, str] = {}
    for community, node_ids in members.items():
        digest = hashlib.sha256()
        for node_id in sorted(node_ids):
            digest.update(node_id.encode("utf-8", "replace"))
            digest.update(b"\x00")
        signatures[community] = digest.hexdigest()[:16]
    return signatures


def _write_membership_signatures(path: Path, graph: dict) -> None:
    path.write_text(
        json.dumps({str(key): value for key, value in _membership_signatures(graph).items()}),
        encoding="utf-8",
    )


def audit_graph_report_data(
    graph: dict,
    report_text: str,
    labels: dict[int, str],
    *,
    membership_signatures: object = _AUTO_SIGNATURES,
    min_community_size: int = 3,
):
    if membership_signatures is _AUTO_SIGNATURES:
        membership_signatures = _membership_signatures(graph)
    return _audit_graph_report_data(
        graph,
        report_text,
        labels,
        membership_signatures=membership_signatures,
        min_community_size=min_community_size,
    )


def _node(
    node_id: str,
    community: int,
    label: str,
    source_file: str = "",
    *,
    file_type: str = "code",
) -> dict:
    return {
        "id": node_id,
        "community": community,
        "label": label,
        "source_file": source_file,
        "file_type": file_type,
    }


def _base_graph() -> dict:
    # Community 0 is shown, 1 is positive-thin, and 2 is structural-only.
    return {
        "directed": False,
        "multigraph": False,
        "nodes": [
            _node("a", 0, "alpha"),
            _node("b", 0, "beta"),
            _node("c", 0, "gamma"),
            _node("d", 1, "delta"),
            _node("file", 2, "only.py", "src/only.py"),
        ],
        "links": [],
    }


def _labels() -> dict[int, str]:
    return {0: "Shown", 1: "Thin", 2: "Structural"}


def _report(
    *,
    shown: int = 1,
    thin: int = 1,
    headings: tuple[int, ...] = (0,),
    nav: tuple[str, ...] = ("Shown", "Thin"),
    minimum: int = 3,
    labels: dict[int, str] | None = None,
    include_import_cycles: bool = True,
) -> str:
    labels = labels or _labels()
    nav_lines = "\n".join(f"- {label}" for label in nav)
    heading_lines = "\n\n".join(
        f'### Community {community} - "{labels.get(community, "Foreign")}"\n\nNodes (3): example'
        for community in headings
    )
    import_cycles = "\n## Import Cycles\n- None detected.\n" if include_import_cycles else ""
    return f"""# Graph Report - fixture  (2026-08-12)

## Corpus Check
- fixture

## Summary
- 5 nodes · 0 edges · 3 communities ({shown} shown, {thin} thin omitted)

## Community Hubs (Navigation)
{nav_lines}

## God Nodes (most connected - your core abstractions)
- fixture

## Surprising Connections (you probably didn't know these)
- fixture
{import_cycles}

## Communities (3 total, {thin} thin omitted)

{heading_lines}

- **{thin} thin communities (<{minimum} nodes) omitted from report** — run `graphify query` to explore isolated nodes.
"""


def _single_community_report(*, label: str, edges: int, include_import_cycles: bool) -> str:
    report = _report(
        shown=1,
        thin=0,
        headings=(0,),
        nav=(label,),
        labels={0: label},
        include_import_cycles=include_import_cycles,
    )
    report = report.replace("- 5 nodes · 0 edges · 3 communities", f"- 3 nodes · {edges} edges · 1 communities", 1)
    report = report.replace("## Communities (3 total, 0 thin omitted)", "## Communities (1 total, 0 thin omitted)")
    report = report.replace(" (1 shown, 0 thin omitted)", "", 1)
    return report.replace(
        "\n- **0 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.",
        "",
        1,
    )


def test_exact_partition_and_report_pass():
    result = audit_graph_report_data(_base_graph(), _report(), _labels())

    assert result.status == "pass"
    assert result.error_codes == ()
    assert result.counts["communities_total"] == 3
    assert result.counts["communities_shown"] == 1
    assert result.counts["communities_thin"] == 1
    assert result.counts["communities_structural_only"] == 1


def test_membership_signatures_match_graphify_0947_sorted_ids_nul_sha256_first16():
    assert partition_graph(_base_graph()).membership_signatures == {
        0: "13e228567e8249fc",
        1: "4658d6abbbaf7748",
        2: "665b9b46b49bbf8a",
    }


def test_missing_decoded_membership_signature_fails_closed():
    result = audit_graph_report_data(
        _base_graph(),
        _report(),
        _labels(),
        membership_signatures=None,
    )

    assert result.error_codes == ("graph_report_label_membership_signature_missing",)


@pytest.mark.parametrize(
    "signatures",
    [
        {0: "0" * 16, 1: "1" * 16},
        {0: "G" * 16, 1: "1" * 16, 2: "2" * 16},
        {0: "0" * 15, 1: "1" * 16, 2: "2" * 16},
        {"0": "0" * 16, 1: "1" * 16, 2: "2" * 16},
    ],
)
def test_malformed_decoded_membership_signature_fails_closed(signatures):
    result = audit_graph_report_data(
        _base_graph(),
        _report(),
        _labels(),
        membership_signatures=signatures,
    )

    assert result.error_codes == ("graph_report_label_membership_signature_invalid",)


def test_stale_decoded_membership_signature_fails_closed():
    signatures = _membership_signatures(_base_graph())
    signatures[0] = "0" * 16

    result = audit_graph_report_data(
        _base_graph(),
        _report(),
        _labels(),
        membership_signatures=signatures,
    )

    assert result.error_codes == ("graph_report_label_membership_signature_mismatch",)


def test_structural_only_community_cannot_inflate_shown_count():
    result = audit_graph_report_data(_base_graph(), _report(shown=2), _labels())

    assert result.status == "block"
    assert result.error_codes == ("graph_report_summary_partition_mismatch",)


def test_arbitrary_shown_count_is_corruption_not_an_allowed_residual():
    result = audit_graph_report_data(_base_graph(), _report(shown=999), _labels())

    assert result.error_codes == ("graph_report_summary_partition_corrupt",)
    assert not set(result.error_codes) <= KNOWN_EXTERNAL_REPORT_RESIDUALS


def test_heading_identity_set_not_just_count_is_reconciled():
    result = audit_graph_report_data(_base_graph(), _report(headings=(9,)), _labels())

    assert result.status == "block"
    assert "graph_report_community_section_content_mismatch" in result.error_codes


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace("- 5 nodes", "- ,5 nodes", 1),
        lambda text: text.replace("- 5 nodes", "- 05 nodes", 1),
        lambda text: text.replace('### Community 0 - "Shown"', '### Community 0 - "', 1),
        lambda text: text.replace('### Community 0 - "Shown"', '### Community 00 - "Shown"', 1),
        lambda text: text.replace("- 5 nodes", "- 999 nodes - 0 edges - 3 communities\n- 5 nodes", 1),
        lambda text: text.replace(
            "- **1 thin communities",
            "- **999 thin communities (malformed)**\n- **1 thin communities",
            1,
        ),
        lambda text: text + '\n## Foreign\n### Community 0 - "Shown"\n',
        lambda text: text + "\n## Foreign\n- [[_COMMUNITY_Shown|Shown]]\n",
        lambda text: text.replace("## Summary", "## Summary lookalike", 1),
        lambda text: text.replace(
            "## Community Hubs (Navigation)",
            "## Community Hubs (Navigation) lookalike",
            1,
        ),
        lambda text: text + "\n##\tSummary\n",
        lambda text: text + "\n##  Community Hubs (Navigation)\n",
        lambda text: text + "\n##\tCommunities (3 total, 1 thin omitted)\n",
        lambda text: text + '\n###\tCommunity 999 - "spoof"\n',
        lambda text: text + "\n## Summary ##\n",
        lambda text: text + "\n  ## Summary\n",
        lambda text: text + "\n# Summary\n",
        lambda text: text + '\n#### Community 999 - "spoof"\n',
        lambda text: text + "\nSummary\n-------\n",
        lambda text: text + "\nSumm&#97;ry\n-------\n",
        lambda text: text + "\nSum<span></span>mary\n-------\n",
        lambda text: text + "\n<h2>Summary</h2>\n<p>999&nbsp;nodes</p>\n",
        lambda text: text + "\n## Summ&#97;ry\n",
        lambda text: text + "\n## Sum<span></span>mary\n",
        lambda text: text + "\n## **Summary**\n",
        lambda text: text + "\n## [Summary](x)\n",
        lambda text: text + "\n## `Summary`\n",
        lambda text: text + "\n> ## Summary\n",
        lambda text: text + "\n- ## Summary\n",
        lambda text: text + "\n>   > ## Summary\n",
        lambda text: text + "\n>\t## Summary\n",
        lambda text: text + "\n>## Summary\n",
    ],
)
def test_noncanonical_count_and_unterminated_heading_are_format_errors(mutation):
    result = audit_graph_report_data(_base_graph(), mutation(_report()), _labels())

    assert result.error_codes == ("graph_report_format_invalid",)


def test_owned_report_sections_cannot_be_reordered():
    report = _report()
    summary_start = report.index("## Summary")
    nav_start = report.index("## Community Hubs (Navigation)")
    communities_start = report.index("## Communities")
    prefix = report[:summary_start]
    summary = report[summary_start:nav_start]
    nav = report[nav_start:communities_start]
    remainder = report[communities_start:]

    result = audit_graph_report_data(_base_graph(), prefix + nav + summary + remainder, _labels())

    assert result.error_codes == ("graph_report_format_invalid",)


@pytest.mark.parametrize(
    "extra",
    [
        "# Graph Report - CORRUPT  (2026-08-12)",
        "## Corpus Check",
    ],
)
def test_canonical_headings_cannot_be_duplicated(extra):
    result = audit_graph_report_data(_base_graph(), _report() + "\n" + extra + "\n", _labels())

    assert result.error_codes == ("graph_report_format_invalid",)


@pytest.mark.parametrize(
    ("prefix", "suffix"),
    [
        ("<!--\n", "\n-->"),
        ("```text\n", "\n```"),
        ("~~~text\n", "\n~~~"),
        ("<div>\n", "\n</div>"),
        ("<pre>\n", "\n</pre>"),
        ("<script>\n", "\n</script>"),
        ("<style>\n", "\n</style>"),
        ("<textarea>\n", "\n</textarea>"),
        ("<?instruction\n", "\n?>"),
        ("<!DOCTYPE html>\n", ""),
        ("<![CDATA[\n", "\n]]>"),
        ("<x>\n", ""),
        ('<x a=">">\n', ""),
        ("<x a='<'>\n", ""),
    ],
)
def test_owned_sections_cannot_be_hidden_in_non_markdown_context(prefix, suffix):
    result = audit_graph_report_data(_base_graph(), prefix + _report() + suffix, _labels())

    assert result.error_codes == ("graph_report_format_invalid",)


def test_arbitrary_navigation_rewrite_is_corruption_not_known_residual():
    report = _report().replace("- Shown", "- Evil junk", 1)

    result = audit_graph_report_data(_base_graph(), report, _labels())

    assert "graph_report_navigation_content_corrupt" in result.error_codes
    assert not set(result.error_codes) <= KNOWN_EXTERNAL_REPORT_RESIDUALS


@pytest.mark.parametrize(
    "nav",
    [
        ("Thin", "Shown"),
        ("Shown", "Thin", "Extra"),
        ("[[ _COMMUNITY_Shown|Shown ]]", "Thin"),
        ("Shown trailing", "Thin"),
    ],
)
def test_plain_navigation_is_exact_and_ordered(nav):
    result = audit_graph_report_data(_base_graph(), _report(nav=nav), _labels())

    assert result.status == "block"
    assert result.error_codes == ("graph_report_navigation_content_corrupt",)


def test_long_visible_label_needs_no_exporter_filename_projection():
    label = "界" * 100
    nav = (label, "Thin")
    labels = {0: label, 1: "Thin", 2: "Structural"}

    result = audit_graph_report_data(_base_graph(), _report(nav=nav, labels=labels), labels)

    assert result.status == "pass"
    assert result.error_codes == ()


def test_nondefault_minimum_is_reconciled_without_hardcoded_three():
    report = _report(shown=0, thin=2, headings=(), minimum=4)

    result = audit_graph_report_data(_base_graph(), report, _labels(), min_community_size=4)

    assert result.error_codes == ()

    hardcoded_three = report.replace(
        "**2 thin communities (<4 nodes) omitted",
        "**1 thin communities (<4 nodes) omitted",
    )
    mismatch = audit_graph_report_data(_base_graph(), hardcoded_three, _labels(), min_community_size=4)
    assert mismatch.error_codes == ("graph_report_thin_omission_mismatch",)


def test_zero_thin_report_omits_parenthetical_and_thin_statement():
    graph = {
        "directed": False,
        "multigraph": False,
        "nodes": [_node("a", 0, "a"), _node("b", 0, "b"), _node("c", 0, "c")],
        "links": [],
    }
    report = _report(shown=1, thin=0, headings=(0,), nav=("Shown",), labels={0: "Shown"})
    report = report.replace("- 5 nodes", "- 3 nodes", 1).replace("3 communities", "1 communities", 1)
    report = report.replace("## Communities (3 total, 0 thin omitted)", "## Communities (1 total, 0 thin omitted)")
    report = report.replace(" (1 shown, 0 thin omitted)", "", 1)
    report = report.replace(
        "\n- **0 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.",
        "",
        1,
    )

    result = audit_graph_report_data(graph, report, {0: "Shown"})

    assert result.error_codes == ()


def test_all_structural_report_omits_navigation_and_thin_statement():
    graph = {
        "directed": False,
        "multigraph": False,
        "nodes": [_node("file", 0, "only.py", "src/only.py")],
        "links": [],
    }
    report = _report(shown=0, thin=0, headings=(), nav=(), labels={0: "Structural"})
    report = report.replace("- 5 nodes", "- 1 nodes", 1).replace("3 communities", "1 communities", 1)
    report = report.replace("## Communities (3 total, 0 thin omitted)", "## Communities (1 total, 0 thin omitted)")
    report = report.replace("## Community Hubs (Navigation)\n\n", "", 1)
    report = report.replace(" (0 shown, 0 thin omitted)", "", 1)
    report = report.replace(
        "\n- **0 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.",
        "",
        1,
    )

    result = audit_graph_report_data(graph, report, {0: "Structural"})

    assert result.error_codes == ()


@pytest.mark.parametrize(
    ("has_import_edge", "include_import_cycles", "expected_errors"),
    [
        (False, False, ()),
        (False, True, ("graph_report_format_invalid",)),
        (True, True, ()),
        (True, False, ("graph_report_format_invalid",)),
    ],
)
def test_import_cycles_section_is_present_iff_graph_has_code_or_import_edge(
    has_import_edge,
    include_import_cycles,
    expected_errors,
):
    graph = {
        "directed": False,
        "multigraph": False,
        "nodes": [
            _node("a", 0, "alpha", file_type="document"),
            _node("b", 0, "beta", file_type="document"),
            _node("c", 0, "gamma", file_type="document"),
        ],
        "links": (
            [{"source": "a", "target": "b", "relation": "imports"}]
            if has_import_edge
            else []
        ),
    }
    report = _single_community_report(
        label="Documents",
        edges=int(has_import_edge),
        include_import_cycles=include_import_cycles,
    )

    result = audit_graph_report_data(graph, report, {0: "Documents"})

    assert result.error_codes == expected_errors


def test_file_node_predicate_matches_graphify_0947_degree_and_qualified_suffix_semantics():
    graph = {
        "directed": False,
        "multigraph": False,
        "nodes": [
            _node("filename", 0, "module.py", "src/module.py"),
            _node("source_real", 1, "different", "src/module.py"),
            _node("method", 2, ".method()"),
            _node("degree_one", 3, "single()"),
            _node("degree_two", 4, "connected()"),
            _node("left", 5, "left"),
            _node("right", 6, "right"),
            _node("qualified", 7, "alpha/index.py", "src/alpha/index.py"),
            _node("full_path", 8, "src/beta/index.py", "src/beta/index.py"),
            _node("foreign_suffix", 9, "other/index.py", "src/alpha/index.py"),
            _node("windows_qualified", 10, "gamma/index.py", r"src\gamma\index.py"),
        ],
        "links": [
            {"source": "degree_one", "target": "left"},
            {"source": "degree_two", "target": "left"},
            {"source": "degree_two", "target": "right"},
        ],
    }

    partition = partition_graph(graph)

    assert partition.structural_only_ids == frozenset({0, 2, 3, 7, 8, 10})
    assert partition.thin_ids == frozenset({1, 4, 5, 6, 9})
    assert partition.shown_ids == frozenset()


def test_graphify_0947_file_predicate_does_not_normalize_a_trailing_separator():
    graph = {
        "directed": False,
        "multigraph": False,
        "nodes": [_node("file", 9, "only.py", "src/only.py/")],
        "links": [],
    }

    partition = partition_graph(graph)

    assert partition.thin_ids == frozenset({9})
    assert partition.structural_only_ids == frozenset()


def test_self_loop_contributes_degree_two_like_networkx_graph():
    graph = {
        "directed": False,
        "multigraph": False,
        "nodes": [_node("loop", 7, "loop()")],
        "links": [{"source": "loop", "target": "loop"}],
    }

    partition = partition_graph(graph)

    assert partition.thin_ids == frozenset({7})
    assert partition.structural_only_ids == frozenset()


@pytest.mark.parametrize("bad_community", [True, 1.0, "1", -1, 1 << 53])
def test_noncanonical_community_ids_fail_closed_without_echo(bad_community):
    graph = _base_graph()
    graph["nodes"][0]["community"] = bad_community
    marker = "PRIVATE_MARKER_DO_NOT_ECHO"
    graph["nodes"][0]["label"] = marker

    result = audit_graph_report_data(graph, _report(), _labels())

    rendered = json.dumps(result.as_dict(), sort_keys=True)
    assert result.status == "block"
    assert result.error_codes == ("graph_report_graph_invalid",)
    assert marker not in rendered


@pytest.mark.parametrize(
    "links",
    [
        [{"source": "a", "target": "missing"}],
        [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    ],
)
def test_dangling_and_duplicate_simple_edges_fail_closed(links):
    graph = _base_graph()
    graph["links"] = links

    result = audit_graph_report_data(graph, _report(), _labels())

    assert result.error_codes == ("graph_report_graph_invalid",)


def test_duplicate_json_keys_and_invalid_utf8_are_fixed_non_echo_blocks(tmp_path):
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "report.md"
    labels_path = tmp_path / ".graphify_labels.json"
    signatures_path = tmp_path / ".graphify_labels.json.sig"
    report_path.write_text(_report(), encoding="utf-8")
    labels_path.write_text(json.dumps(_labels()), encoding="utf-8")
    _write_membership_signatures(signatures_path, _base_graph())
    graph_path.write_text(
        '{"directed":false,"directed":false,"multigraph":false,"nodes":[],"links":[]}',
        encoding="utf-8",
    )
    duplicate_result = audit_graph_report(graph_path, report_path)
    graph_path.write_bytes(b"\xffPRIVATE_MARKER_DO_NOT_ECHO")
    utf8_result = audit_graph_report(graph_path, report_path)

    for result in (duplicate_result, utf8_result):
        rendered = json.dumps(result.as_dict(), sort_keys=True)
        assert result.error_codes == ("graph_report_graph_invalid",)
        assert "PRIVATE_MARKER_DO_NOT_ECHO" not in rendered


def test_huge_decimal_label_key_is_a_fixed_non_echo_block(tmp_path):
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "report.md"
    labels_path = tmp_path / ".graphify_labels.json"
    signatures_path = tmp_path / ".graphify_labels.json.sig"
    graph_path.write_text(json.dumps(_base_graph()), encoding="utf-8")
    report_path.write_text(_report(), encoding="utf-8")
    labels_path.write_text('{"' + ("9" * 5000) + '":"PRIVATE_MARKER"}', encoding="utf-8")
    _write_membership_signatures(signatures_path, _base_graph())

    result = audit_graph_report(graph_path, report_path)

    rendered = json.dumps(result.as_dict(), sort_keys=True)
    assert result.error_codes == ("graph_report_labels_invalid",)
    assert "PRIVATE_MARKER" not in rendered


@pytest.mark.parametrize(
    ("signature_payload", "expected_code"),
    [
        (None, "graph_report_label_membership_signature_missing"),
        ("{", "graph_report_label_membership_signature_invalid"),
        (
            json.dumps({"0": "0" * 16, "1": "1" * 16, "2": "2" * 16}),
            "graph_report_label_membership_signature_mismatch",
        ),
        (
            '{"0":"' + ("0" * 16) + '","0":"' + ("0" * 16)
            + '","1":"' + ("1" * 16) + '","2":"' + ("2" * 16) + '"}',
            "graph_report_label_membership_signature_invalid",
        ),
        (b"\xffPRIVATE_MARKER_DO_NOT_ECHO", "graph_report_label_membership_signature_invalid"),
    ],
)
def test_default_membership_signature_path_rejects_missing_malformed_and_stale_sidecars(
    tmp_path,
    signature_payload,
    expected_code,
):
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "report.md"
    labels_path = tmp_path / ".graphify_labels.json"
    signatures_path = tmp_path / ".graphify_labels.json.sig"
    graph_path.write_text(json.dumps(_base_graph()), encoding="utf-8")
    report_path.write_text(_report(), encoding="utf-8")
    labels_path.write_text(json.dumps(_labels()), encoding="utf-8")
    if isinstance(signature_payload, bytes):
        signatures_path.write_bytes(signature_payload)
    elif signature_payload is not None:
        signatures_path.write_text(signature_payload, encoding="utf-8")

    result = audit_graph_report(graph_path, report_path)

    assert result.error_codes == (expected_code,)
    assert "PRIVATE_MARKER_DO_NOT_ECHO" not in json.dumps(result.as_dict(), sort_keys=True)


def test_default_membership_signature_path_accepts_exact_sidecar(tmp_path):
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "report.md"
    labels_path = tmp_path / ".graphify_labels.json"
    signatures_path = tmp_path / ".graphify_labels.json.sig"
    graph_path.write_text(json.dumps(_base_graph()), encoding="utf-8")
    report_path.write_text(_report(), encoding="utf-8")
    labels_path.write_text(json.dumps(_labels()), encoding="utf-8")
    _write_membership_signatures(signatures_path, _base_graph())

    result = audit_graph_report(graph_path, report_path)

    assert result.status == "pass"


@pytest.mark.parametrize(
    "separator",
    ["\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"],
)
def test_non_markdown_unicode_line_separators_are_rejected(separator):
    result = audit_graph_report_data(_base_graph(), _report().replace("\n", separator), _labels())

    assert result.error_codes == ("graph_report_format_invalid",)


def test_crlf_is_accepted_as_canonical_platform_text_output():
    result = audit_graph_report_data(_base_graph(), _report().replace("\n", "\r\n"), _labels())

    assert result.error_codes == ()


@pytest.mark.parametrize(
    "mutated_name",
    ["report.md", ".graphify_labels.json", ".graphify_labels.json.sig"],
)
def test_group_read_rejects_a_cross_file_generation_mix(tmp_path, monkeypatch, mutated_name):
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "report.md"
    labels_path = tmp_path / ".graphify_labels.json"
    signatures_path = tmp_path / ".graphify_labels.json.sig"
    graph_path.write_text(json.dumps(_base_graph()), encoding="utf-8")
    report_path.write_text(_report(), encoding="utf-8")
    labels_path.write_text(json.dumps(_labels()), encoding="utf-8")
    _write_membership_signatures(signatures_path, _base_graph())
    mutated_path = tmp_path / mutated_name
    real_open = Path.open
    mutated = False

    class MutatingReader:
        def __init__(self, handle):
            self.handle = handle

        def fileno(self):
            return self.handle.fileno()

        def read(self, *args):
            nonlocal mutated
            if not mutated:
                mutated = True
                with open(mutated_path, "ab") as writer:  # noqa: PTH123 - deliberate race fixture
                    writer.write(b"\n")
            return self.handle.read(*args)

        def seek(self, *args):
            return self.handle.seek(*args)

        def close(self):
            return self.handle.close()

    def patched_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        return MutatingReader(handle) if self == graph_path else handle

    monkeypatch.setattr(Path, "open", patched_open)

    result = audit_graph_report(graph_path, report_path, labels_path=labels_path)

    assert result.error_codes == ("graph_report_input_unstable",)


def test_second_read_is_bounded_when_input_grows(tmp_path, monkeypatch):
    graph_path = tmp_path / "graph.json"
    report_path = tmp_path / "report.md"
    labels_path = tmp_path / ".graphify_labels.json"
    signatures_path = tmp_path / ".graphify_labels.json.sig"
    graph_path.write_text(json.dumps(_base_graph()), encoding="utf-8")
    report_path.write_text(_report(), encoding="utf-8")
    labels_path.write_text(json.dumps(_labels()), encoding="utf-8")
    _write_membership_signatures(signatures_path, _base_graph())
    real_open = Path.open

    class GrowingReader:
        def __init__(self, handle):
            self.handle = handle
            self.reread = False
            self.reread_calls = 0

        def fileno(self):
            return self.handle.fileno()

        def read(self, size=-1):
            if self.reread:
                self.reread_calls += 1
                return b"X" * size
            return self.handle.read(size)

        def seek(self, *args):
            self.reread = True
            return self.handle.seek(*args)

        def close(self):
            return self.handle.close()

    def patched_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        return GrowingReader(handle) if self == labels_path else handle

    monkeypatch.setattr(Path, "open", patched_open)

    result = audit_graph_report(graph_path, report_path, labels_path=labels_path)

    assert result.error_codes == ("graph_report_input_unstable",)


def test_escaped_surrogate_label_is_a_fixed_non_echo_block():
    labels = _labels()
    labels[0] = "PRIVATE_MARKER\ud800"

    result = audit_graph_report_data(_base_graph(), _report(), labels)

    rendered = json.dumps(result.as_dict(), sort_keys=True)
    assert result.error_codes == ("graph_report_labels_invalid",)
    assert "PRIVATE_MARKER" not in rendered


def test_deep_json_and_unstable_semantics_are_bounded():
    graph = _base_graph()
    nested: dict = {}
    cursor = nested
    for _ in range(65):
        cursor["x"] = {}
        cursor = cursor["x"]
    graph["extra"] = nested

    result = audit_graph_report_data(graph, _report(), _labels())

    assert result.error_codes == ("graph_report_graph_invalid",)


def test_flat_json_container_refuses_before_unbounded_stack_growth(monkeypatch):
    graph = _base_graph()
    graph["extra"] = [0, 1, 2]
    monkeypatch.setattr("tools.verify_graph_report.MAX_JSON_VALUES", 7)

    result = audit_graph_report_data(graph, _report(), _labels())

    assert result.error_codes == ("graph_report_graph_invalid",)


def test_lexical_graph_value_bound_runs_before_json_materialization(monkeypatch):
    payload = b'{"extra":[0,1,2]}'
    monkeypatch.setattr("tools.verify_graph_report.MAX_JSON_VALUES", 4)

    def must_not_decode(*_args, **_kwargs):
        raise AssertionError("json.loads must not run after lexical refusal")

    monkeypatch.setattr("tools.verify_graph_report.json.loads", must_not_decode)

    with pytest.raises(Exception) as caught:  # fixed internal refusal type is intentionally private
        _parse_graph(payload)
    assert str(caught.value) == "graph_report_graph_invalid"


def test_lexical_labels_value_bound_runs_before_json_materialization(monkeypatch):
    payload = b'{"0":"a","1":"b"}'
    monkeypatch.setattr("tools.verify_graph_report.MAX_JSON_VALUES", 3)

    def must_not_decode(*_args, **_kwargs):
        raise AssertionError("json.loads must not run after lexical refusal")

    monkeypatch.setattr("tools.verify_graph_report.json.loads", must_not_decode)

    with pytest.raises(Exception) as caught:  # fixed internal refusal type is intentionally private
        _parse_labels(payload, frozenset({0, 1}))
    assert str(caught.value) == "graph_report_labels_invalid"


@pytest.mark.parametrize(
    "payload",
    [
        b'{"value":' + (b"9" * 129) + b"}",
        b'{"value":"' + (b"x" * 129) + b'"}',
        b'{"value":[[[0]]]}',
    ],
)
def test_lexical_json_token_and_depth_caps_precede_decode(payload, monkeypatch):
    monkeypatch.setattr("tools.verify_graph_report.MAX_JSON_STRING_CHARS", 128)
    monkeypatch.setattr("tools.verify_graph_report.MAX_JSON_DEPTH", 3)

    with pytest.raises(Exception) as caught:  # fixed internal refusal type is intentionally private
        _parse_graph(payload)
    assert str(caught.value) == "graph_report_graph_invalid"


def test_report_line_cap_is_checked_before_split(monkeypatch):
    monkeypatch.setattr("tools.verify_graph_report.MAX_REPORT_LINES", 3)

    result = audit_graph_report_data(_base_graph(), "a\nb\nc\nd", _labels())

    assert result.error_codes == ("graph_report_format_invalid",)


def test_default_labels_path_derivation_is_total_and_non_echoing():
    result = audit_graph_report(Path("."), Path("PRIVATE_MARKER_DO_NOT_ECHO"))

    rendered = json.dumps(result.as_dict(), sort_keys=True)
    assert result.error_codes == ("graph_report_input_invalid",)
    assert "PRIVATE_MARKER_DO_NOT_ECHO" not in rendered


def test_guarded_producer_has_no_allowed_report_residuals():
    # Old or unguarded reports still receive the precise mismatch diagnostic,
    # but no report defect is accepted after the producer correction.
    assert KNOWN_EXTERNAL_REPORT_RESIDUALS == frozenset()


def test_invariant_guard_requires_report_and_audited_substantial_count():
    source = Path("tests/test_graph_invariants.py").read_text(encoding="utf-8")

    assert 'assert report.is_file(), "substantial graph has no regular GRAPH_REPORT.md derivative to audit"' in source
    assert 'result.counts.get("graph_nodes", 0) >= _SUBSTANTIAL_FLOOR' in source
