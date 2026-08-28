"""Invariant guard for the graphify knowledge graph (``graphify-out/graph.json``).

Dimension-A gap (docs/architect-understanding-2026-07-10.md): the live graph - the tool CLAUDE.md
says to consult FIRST for codebase questions - had NO test validating its schema, its size, or the
central **AST-only / no-LLM-derived-nodes doctrine** (CLAUDE.md graphify section). ``test_doctrine_graph``
guards a *different* graph (the in-code doctrine/design_advisor projection), not this one. This closes
that gap: it makes the doctrine a RED test on the machine where the graph lives.

Coverage-honest by construction (the graph is gitignored / owner-machine-only - CLAUDE.md):
* graph unreachable (clean clone / CI) -> SKIP, never a fabricated pass;
* a degenerate/partial graph (the worktree trap - a linked worktree's own ``graphify update`` can
  leave a ~100-node stub) -> SKIP with the count stated, never a false FAIL;
* a SUBSTANTIAL graph (the real owner-machine build) -> the invariants are asserted.

The locator is reused from :func:`cisco_toolkit.d10_eval_set.find_graph_json` (one owner, DRY) - it is
already worktree-aware (resolves the main checkout via ``git rev-parse --git-common-dir``).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote

import pytest

from cisco_toolkit.d10_eval_set import find_graph_json, load_graph_settled
from tools.verify_graph_report import audit_graph_report

# A real graph is ~7.5k nodes; the degenerate worktree partials observed were ~76-122. This floor
# cleanly separates "the full owner-machine graph" (assert) from "a worktree stub" (skip) - it is a
# SKIP threshold, not an assertion, so the worktree trap can never turn into a red build.
_SUBSTANTIAL_FLOOR = 1000

# The AST-only doctrine, encoded as an ALLOWLIST (fail-closed): every node originates from the offline
# AST extractor (``ast``) or is an un-tagged structural node (``None`` - e.g. YAML-workflow / release
# nodes). Any OTHER ``_origin`` marker (an LLM/label/semantic origin) is a doctrine violation and must
# trip review. If a new *non-LLM* extractor is ever added, widen this set deliberately - never loosen
# it to silence a surprise. Owner of the doctrine: CLAUDE.md graphify section.
_ALLOWED_ORIGINS = {"ast", None}

# Installed Graphify 0.9.51 overrides .graphifyignore for its saved-memory corpus.  Keep that
# external residual exact and non-expanding until the producer makes explicit ignore/include
# rules authoritative over the special scan.  This is a reviewed BLOCK, never a clean claim.
_KNOWN_MEMORY_IGNORE_OVERRIDE_SOURCE_COUNT = 19
_KNOWN_MEMORY_IGNORE_OVERRIDE_SOURCE_DIGEST = "2e2f09009987f1c621d05602ba1716f95c80a903078654e83375fc569623628f"
_KNOWN_MEMORY_IGNORE_OVERRIDE_NODES = 90
_KNOWN_MEMORY_IGNORE_OVERRIDE_LINKS = 71
_KNOWN_MEMORY_NODE_RECORDS_DIGEST = "570c11be1d5c1dd9c775431b93bc1c742a1fda76c79d91df1b04c9aef8561515"
_KNOWN_MEMORY_EDGE_RECORDS_DIGEST = "c58f2673a86889f52bb1c4e7bdc045d0ff34340d0ed10df5e94ba074b78e9994"
_MEMORY_AST_NODE_KEYS = {
    "_origin",
    "community",
    "community_name",
    "file_type",
    "id",
    "label",
    "node_kind",
    "norm_label",
    "source_file",
    "source_location",
}
_MEMORY_FRONTMATTER_NODE_KEYS = _MEMORY_AST_NODE_KEYS | {"frontmatter"}
_MEMORY_LINK_KEYS = {
    "_origin",
    "confidence",
    "confidence_score",
    "relation",
    "source",
    "source_file",
    "source_location",
    "target",
    "weight",
}
_MEMORY_CLUSTER_DERIVED_KEYS = {"community", "community_name"}
_KNOWN_PRUNED_BUILD_SOURCES = {
    "master-reference/build/compress-projection.mjs",
    "master-reference/build/deployment-manifest.mjs",
    "master-reference/build/deterministic-gzip.mjs",
    "master-reference/build/finalize-deployment.mjs",
    "master-reference/build/gzip-contract.js",
    "master-reference/build/prepare-deployment.mjs",
    "master-reference/build/projection/README.md",
    "master-reference/build/projection/build.mjs",
    "master-reference/build/sites-vite-plugin.ts",
}
_MEMORY_IGNORE_OVERRIDE_CODE = "graph_corpus_memory_ignore_override"
_BUILD_DIRECTORY_PRUNE_CODE = "graph_corpus_authored_build_dir_pruned"

# The closed node-type enum and the edge-relation vocabulary the extractor emits (read from the live
# graph 2026-07-11). A test failure here means the schema grew - reconcile deliberately, don't paper over.
_KNOWN_FILE_TYPES = {"code", "rationale", "document", "concept"}
_KNOWN_RELATIONS = {
    "calls",
    "cites",
    "contains",
    "defines",
    "dynamic_import",
    "extends",
    "imports",
    "imports_from",
    "indirect_call",
    "inherits",
    "method",
    "rationale_for",
    "re_exports",
    "references",
    "uses",
}
_REVIEWED_RELATION_RECEIPTS = {
    "cites": (
        7,
        "96aaf88b2b57be58de4e7b06056dc3627b8be4280bd97411f4619005355bc67f",
    ),
    "dynamic_import": (
        3,
        "3d687feff00bbdd655be8a0e11b0ac66cf76e6fb6b32efc9297e0af2e872c4e8",
    ),
    "extends": (
        1,
        "d3b19fd1df648e6917c42d58ef04f77ceedc92926b43985e633c8e7a8ede3fc9",
    ),
}
_MAX_REVIEWED_RELATION_SOURCE_BYTES = 4 * 1024 * 1024
_REQUIRED_NODE_KEYS = {"id", "label", "file_type", "community", "source_file", "norm_label"}


def _load_graph():
    """The real graph as a dict, or a pytest SKIP - the coverage-honest gate every test shares."""
    path = find_graph_json()
    if not path:
        pytest.skip(
            "graph.json not reachable (clean clone / CI) - the graph is gitignored and "
            "owner-machine-only; invariants are checked where the graph lives"
        )
    graph, unsettled = load_graph_settled(path)
    if unsettled:
        # background git-hook rebuilds rewrite this file non-atomically under us; a torn read is a
        # spurious ERROR, not an invariant violation
        pytest.skip(f"graph.json could not be read as a settled whole: {unsettled}")
    n = len(graph.get("nodes", []))
    if n < _SUBSTANTIAL_FLOOR:
        pytest.skip(
            f"degenerate/partial graph ({n} nodes < {_SUBSTANTIAL_FLOOR}) - the worktree stub, "
            "not the full owner-machine graph; the real build is asserted on the main checkout"
        )
    return graph, path


def _normalized_path_slug(value: object) -> str:
    """Match Graphify's path-derived identifier shape without retaining the source path."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _iter_serialized_strings(value: object):
    """Yield every serialized string, including structural endpoint values and mapping keys."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_serialized_strings(key)
            yield from _iter_serialized_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_serialized_strings(item)


def _checkout_path_disclosure_count(graph: object, repo_root: Path | str) -> int:
    """Count path-derived disclosures without returning or echoing any private value."""
    root_slug = _normalized_path_slug(repo_root)
    if len(root_slug) < 12:
        return -1
    disclosures = 0
    for value in _iter_serialized_strings(graph):
        variants, decode_bound_exceeded = _decoded_text_variants(value)
        if decode_bound_exceeded or any(
            root_slug in _normalized_path_slug(candidate) for candidate in variants
        ):
            disclosures += 1
    return disclosures


def _decoded_text_variants(value: str) -> tuple[tuple[str, ...], bool]:
    """Return raw plus three decoded layers and whether another layer remains."""
    candidate = value
    variants = [candidate]
    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            return tuple(variants), False
        candidate = decoded
        variants.append(candidate)
    return tuple(variants), unquote(candidate) != candidate


def _is_win32_graph_output_component(value: str) -> bool:
    """Recognize the long directory name plus conservative Win32/DOS aliases."""
    normalized = value.split(":", 1)[0].rstrip(" .").casefold()
    return normalized == "graphify-out" or re.fullmatch(r"graphi~[0-9]+", normalized) is not None


def _graph_output_path_kind(value: object) -> str | None:
    """Classify a graph-output path as canonical, a disguised alias, or unrelated."""
    if not isinstance(value, str) or not value:
        return None
    variants, decode_bound_exceeded = _decoded_text_variants(value)
    for candidate in variants:
        slash_path = candidate.replace("\\", "/")
        parts = slash_path.split("/")
        has_win32_graph_output_component = any(_is_win32_graph_output_component(part) for part in parts)
        drive_relative_graph_output = bool(
            re.fullmatch(r"[A-Za-z]:.*", parts[0])
            and _is_win32_graph_output_component(parts[0][2:])
        )
        if not has_win32_graph_output_component and not drive_relative_graph_output:
            continue
        canonical = (
            candidate == value == slash_path
            and parts[0].casefold() == "graphify-out"
            and all(part not in {"", ".", ".."} for part in parts)
        )
        return "canonical" if canonical else "alias"
    return "alias" if decode_bound_exceeded else None


def _canonical_rows_digest(rows: list[str] | set[str]) -> str:
    payload = "\n".join(sorted(rows)) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_records_digest(records: list[dict], *, excluded_keys: set[str] | None = None) -> str:
    excluded = excluded_keys or set()
    rows = [
        json.dumps(
            {key: record[key] for key in sorted(record) if key not in excluded},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in records
    ]
    return _canonical_rows_digest(rows)


def _extends_edge_has_scalar_json_source(
    edge: object,
    repo_root: Path,
    tracked_sources: set[str],
) -> bool:
    """Accept only Graphify's top-level scalar JSON ``extends`` relation."""
    if not isinstance(edge, dict) or edge.get("relation") != "extends":
        return False
    source = edge.get("source_file")
    location = edge.get("source_location")
    target = edge.get("target")
    if (
        not isinstance(source, str)
        or not source.endswith(".json")
        or "\\" in source
        or source != posixpath.normpath(source)
        or source.startswith("/")
        or source not in tracked_sources
        or not isinstance(location, str)
        or (line_match := re.fullmatch(r"L([1-9][0-9]*)", location)) is None
        or not isinstance(target, str)
    ):
        return False

    root = repo_root.resolve()
    candidate = (root / Path(*source.split("/"))).resolve()
    try:
        candidate.relative_to(root)
        size = candidate.stat().st_size
    except (OSError, ValueError):
        return False
    if not candidate.is_file() or size > _MAX_REVIEWED_RELATION_SOURCE_BYTES:
        return False
    try:
        text = candidate.read_bytes().decode("utf-8", "strict")
    except (OSError, UnicodeDecodeError):
        return False

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    try:
        document = json.loads(text, object_pairs_hook=no_duplicates)
        lines = text.splitlines()
        line_number = int(line_match.group(1))
        if not 1 <= line_number <= len(lines):
            return False
        property_text = lines[line_number - 1].strip()
        if property_text.endswith(","):
            property_text = property_text[:-1]
        property_value = json.loads("{" + property_text + "}", object_pairs_hook=no_duplicates)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    if (
        not isinstance(document, dict)
        or not isinstance(property_value, dict)
        or set(property_value) != {"extends"}
        or not isinstance(property_value["extends"], str)
        or document.get("extends") != property_value["extends"]
    ):
        return False
    normalized_target = _normalized_path_slug(property_value["extends"])
    return bool(normalized_target) and target == f"ref_{normalized_target}"


def _invalid_structural_provenance_field_count(graph: dict) -> int:
    """Count non-string node provenance and edge provenance/endpoint fields."""
    node_values = (
        node.get(key) for node in graph["nodes"] for key in ("id", "source_file")
    )
    link_values = (
        link.get(key)
        for link in graph["links"]
        for key in ("source", "target", "source_file")
    )
    return sum(not isinstance(value, str) for value in node_values) + sum(
        not isinstance(value, str) for value in link_values
    )


def _memory_related_hyperedge_count(hyperedges: object, memory_node_ids: set[str]) -> int:
    if not isinstance(hyperedges, list):
        return -1
    return sum(
        any(
            value in memory_node_ids or _graph_output_path_kind(value) is not None
            for value in _iter_serialized_strings(hyperedge)
        )
        for hyperedge in hyperedges
    )


def _tracked_build_path_kind(value: object) -> str | None:
    """Recognize canonical and disguised aliases of every reviewed authored build source."""
    if not isinstance(value, str) or not value:
        return None
    expected = {source.casefold() for source in _KNOWN_PRUNED_BUILD_SOURCES}
    variants, decode_bound_exceeded = _decoded_text_variants(value)
    for candidate in variants:
        slash_path = candidate.replace("\\", "/")
        normalized = posixpath.normpath(slash_path).casefold()
        if any(normalized == source or normalized.endswith(f"/{source}") for source in expected):
            return "canonical" if candidate == value and value in _KNOWN_PRUNED_BUILD_SOURCES else "alias"
    return "alias" if decode_bound_exceeded else None


def _has_exact_build_component(value: object) -> bool:
    """Match the producer's case-sensitive directory-component noise rule on Git paths."""
    return isinstance(value, str) and "\\" not in value and "build" in value.split("/")


def _iter_structural_graph_strings(graph: dict):
    """Yield source fields and endpoint representations, excluding unrelated prose labels."""
    for node in graph.get("nodes", []):
        if isinstance(node, dict):
            yield from _iter_serialized_strings(node.get("source_file"))
    for link in graph.get("links", []):
        if isinstance(link, dict):
            for key in ("source", "target", "source_file"):
                yield from _iter_serialized_strings(link.get(key))
    yield from _iter_serialized_strings(graph.get("hyperedges", []))


def test_graph_schema_has_toplevel_keys():
    graph, _ = _load_graph()
    for key in ("nodes", "links", "built_at_commit", "directed", "multigraph"):
        assert key in graph, f"graph.json missing top-level key {key!r} - schema changed or file corrupt"


def test_built_at_commit_present():
    """The provenance stamp exists (freshness is *derivable*). Not asserted == HEAD: the Stop-hook
    refresh and a manual edit legitimately diverge; presence is the invariant, currency is advisory."""
    graph, _ = _load_graph()
    commit = graph.get("built_at_commit")
    assert isinstance(commit, str) and commit.strip(), "built_at_commit absent/empty - graph has no provenance stamp"


def test_every_node_has_required_keys():
    graph, _ = _load_graph()
    for node in graph["nodes"]:
        missing = _REQUIRED_NODE_KEYS - set(node)
        assert not missing, f"node {node.get('id', '?')!r} missing keys {missing} - node schema drift"


def test_no_llm_derived_nodes():
    """THE doctrine (CLAUDE.md): the graph is AST-only and contains NO LLM-derived nodes. A stray
    ``graphify label`` (or any LLM extractor) would plant nodes carrying a non-AST ``_origin`` - this
    is the guard that turns that from a silent provenance breach into a red build."""
    graph, _ = _load_graph()
    offenders = sorted({node.get("_origin") for node in graph["nodes"] if node.get("_origin") not in _ALLOWED_ORIGINS})
    assert not offenders, (
        f"non-AST node origin(s) {offenders} present - the AST-only / no-LLM-derived-nodes doctrine is "
        "violated (CLAUDE.md). If this is a NEW non-LLM extractor, widen _ALLOWED_ORIGINS deliberately; "
        "if it is an LLM origin, a forbidden `graphify label`-class node was planted."
    )


def test_graph_output_ingestion_is_only_the_reviewed_memory_override():
    """Bound Graphify 0.9.51's ignore override without promoting corpus/privacy closure."""
    graph, path = _load_graph()
    invalid_structural_fields = _invalid_structural_provenance_field_count(graph)
    if invalid_structural_fields:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph structural provenance field type changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    aliased_node_sources = sum(
        _graph_output_path_kind(node.get("source_file")) == "alias" for node in graph["nodes"]
    )
    if aliased_node_sources:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: noncanonical graph-output source count changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    output_endpoint_paths = sum(
        _graph_output_path_kind(node.get("id")) is not None for node in graph["nodes"]
    ) + sum(
        _graph_output_path_kind(link.get(key)) is not None
        for link in graph["links"]
        for key in ("source", "target")
    )
    if output_endpoint_paths:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output endpoint path count changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    output_nodes = [
        node
        for node in graph["nodes"]
        if _graph_output_path_kind(node.get("source_file")) == "canonical"
    ]
    output_sources = {node["source_file"] for node in output_nodes}
    if (
        len(output_sources) != _KNOWN_MEMORY_IGNORE_OVERRIDE_SOURCE_COUNT
        or _canonical_rows_digest(output_sources) != _KNOWN_MEMORY_IGNORE_OVERRIDE_SOURCE_DIGEST
    ):
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output source receipt changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    if len(output_nodes) != _KNOWN_MEMORY_IGNORE_OVERRIDE_NODES:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output node count changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    node_shapes = [set(node) for node in output_nodes]
    if (
        sum(shape == _MEMORY_AST_NODE_KEYS for shape in node_shapes) != 71
        or sum(shape == _MEMORY_FRONTMATTER_NODE_KEYS for shape in node_shapes) != 19
        or any(shape not in (_MEMORY_AST_NODE_KEYS, _MEMORY_FRONTMATTER_NODE_KEYS) for shape in node_shapes)
    ):
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output node key shape changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    if (
        _canonical_records_digest(output_nodes, excluded_keys=_MEMORY_CLUSTER_DERIVED_KEYS)
        != _KNOWN_MEMORY_NODE_RECORDS_DIGEST
    ):
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output node identity changed; "
            "reconcile the external residual",
            pytrace=False,
        )

    output_node_ids = {node.get("id") for node in output_nodes if isinstance(node.get("id"), str)}
    output_links = [
        link
        for link in graph["links"]
        if link.get("source") in output_node_ids
        or link.get("target") in output_node_ids
        or _graph_output_path_kind(link.get("source_file")) is not None
        or _graph_output_path_kind(link.get("source")) is not None
        or _graph_output_path_kind(link.get("target")) is not None
    ]
    if len(output_links) != _KNOWN_MEMORY_IGNORE_OVERRIDE_LINKS:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output edge count changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    if any(set(link) != _MEMORY_LINK_KEYS for link in output_links):
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output edge key shape changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    if _canonical_records_digest(output_links) != _KNOWN_MEMORY_EDGE_RECORDS_DIGEST:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output edge identity changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    memory_hyperedges = _memory_related_hyperedge_count(graph.get("hyperedges"), output_node_ids)
    if memory_hyperedges != 0:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph-output hyperedge count changed; "
            "reconcile the external residual",
            pytrace=False,
        )

    manifest = Path(path).with_name("manifest.json")
    if not manifest.is_file():
        pytest.fail(f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph manifest is absent", pytrace=False)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest_data, dict):
        pytest.fail(f"{_MEMORY_IGNORE_OVERRIDE_CODE}: graph manifest shape changed", pytrace=False)
    aliased_manifest_sources = sum(_graph_output_path_kind(source) == "alias" for source in manifest_data)
    if aliased_manifest_sources:
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: noncanonical manifest source count changed; "
            "reconcile the external residual",
            pytrace=False,
        )
    manifest_sources = {source for source in manifest_data if _graph_output_path_kind(source) == "canonical"}
    if (
        len(manifest_sources) != _KNOWN_MEMORY_IGNORE_OVERRIDE_SOURCE_COUNT
        or _canonical_rows_digest(manifest_sources) != _KNOWN_MEMORY_IGNORE_OVERRIDE_SOURCE_DIGEST
    ):
        pytest.fail(
            f"{_MEMORY_IGNORE_OVERRIDE_CODE}: manifest source receipt changed; "
            "reconcile the external residual",
            pytrace=False,
        )


def test_memory_residual_receipts_reject_substitution_extra_and_path_aliases():
    """Synthetic mutations prove the residual receipt cannot expand or substitute at equal counts."""
    baseline_sources = {
        "graphify-out/memory/example.md",
        "graphify-out/memory/other.md",
    }
    baseline_source_digest = _canonical_rows_digest(baseline_sources)
    assert _canonical_rows_digest(
        {"graphify-out/memory/example.md", "graphify-out/memory/substitute.md"}
    ) != baseline_source_digest
    assert _canonical_rows_digest(baseline_sources | {"graphify-out/memory/extra.md"}) != baseline_source_digest

    baseline_node = {
        "_origin": "ast",
        "community": 1,
        "community_name": "Memory",
        "file_type": "document",
        "id": "graphify_out_memory_example",
        "label": "Example",
        "node_kind": "section",
        "norm_label": "example",
        "source_file": "graphify-out/memory/example.md",
        "source_location": "L1",
    }
    assert set(baseline_node) == _MEMORY_AST_NODE_KEYS
    assert set({**baseline_node, "frontmatter": {"outcome": "useful"}}) == _MEMORY_FRONTMATTER_NODE_KEYS
    baseline_node_digest = _canonical_records_digest(
        [baseline_node], excluded_keys=_MEMORY_CLUSTER_DERIVED_KEYS
    )
    for substituted_node in (
        {**baseline_node, "id": "graphify_out_memory_substitute"},
        {**baseline_node, "label": "Substituted"},
        {**baseline_node, "source_location": "L2"},
    ):
        assert (
            _canonical_records_digest([substituted_node], excluded_keys=_MEMORY_CLUSTER_DERIVED_KEYS)
            != baseline_node_digest
        )
    assert (
        _canonical_records_digest(
            [baseline_node, {**baseline_node, "id": "graphify_out_memory_extra"}],
            excluded_keys=_MEMORY_CLUSTER_DERIVED_KEYS,
        )
        != baseline_node_digest
    )
    assert set({**baseline_node, "evil_key": "private"}) != _MEMORY_AST_NODE_KEYS

    baseline_edge = {
        "_origin": "ast",
        "confidence": "EXTRACTED",
        "confidence_score": 1.0,
        "relation": "contains",
        "source": baseline_node["id"],
        "source_file": baseline_node["source_file"],
        "source_location": "L2",
        "target": "graphify_out_memory_example_target",
        "weight": 1.0,
    }
    assert set(baseline_edge) == _MEMORY_LINK_KEYS
    baseline_edge_digest = _canonical_records_digest([baseline_edge])
    assert _canonical_records_digest([{**baseline_edge, "confidence": "INFERRED"}]) != baseline_edge_digest
    assert set({**baseline_edge, "evil_key": "private"}) != _MEMORY_LINK_KEYS
    assert _memory_related_hyperedge_count(
        [{"nested": {"endpoints": ["safe", baseline_node["id"]]}}], {baseline_node["id"]}
    ) == 1

    assert _graph_output_path_kind("graphify-out/memory/example.md") == "canonical"
    for structurally_invalid in (
        ["safe.md", "graphify-out/memory/hidden.md"],
        {"primary": "safe.md", "hidden": "graphify-out/memory/hidden.md"},
    ):
        assert (
            _invalid_structural_provenance_field_count(
                {
                    "nodes": [{"id": "safe_node", "source_file": structurally_invalid}],
                    "links": [
                        {
                            "source": "safe_node",
                            "target": "safe_target",
                            "source_file": structurally_invalid,
                        }
                    ],
                }
            )
            == 2
        )
    for alias in (
        "./graphify-out/memory/example.md",
        "graphify-out/../graphify-out/memory/example.md",
        "C:/private/graphify-out/memory/example.md",
        "graphify-out\\memory\\example.md",
        "graphify-out./memory/example.md",
        "graphify-out /memory/example.md",
        "graphify-out::$INDEX_ALLOCATION/memory/example.md",
        "graphify-out:$I30:$INDEX_ALLOCATION/memory/example.md",
        "GRAPHI~2/memory/example.md",
        "C:graphify-out\\memory\\example.md",
        "C:GRAPHI~2\\memory\\example.md",
        quote(quote("C:/private/graphify-out/memory/example.md", safe=""), safe=""),
        quote(quote(quote("C:/private/graphify-out/memory/example.md", safe=""), safe=""), safe=""),
    ):
        assert _graph_output_path_kind(alias) == "alias"


def test_authored_build_directory_pruning_is_the_reviewed_external_residual():
    """Pin Graphify 0.9.6's build-directory noise prune until upstream makes it overridable."""
    graph, path = _load_graph()
    repo_root = Path(path).resolve().parent.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.fail(f"{_BUILD_DIRECTORY_PRUNE_CODE}: tracked owner census unavailable", pytrace=False)
    tracked = {line for line in result.stdout.splitlines() if _has_exact_build_component(line)}
    if tracked != _KNOWN_PRUNED_BUILD_SOURCES:
        pytest.fail(
            f"{_BUILD_DIRECTORY_PRUNE_CODE}: tracked owner census changed; "
            "reconcile the reviewed residual",
            pytrace=False,
        )

    graph_path_kinds = [_tracked_build_path_kind(value) for value in _iter_structural_graph_strings(graph)]
    if any(kind is not None for kind in graph_path_kinds):
        pytest.fail(
            f"{_BUILD_DIRECTORY_PRUNE_CODE}: graph coverage or source alias changed; "
            "reconcile the reviewed residual",
            pytrace=False,
        )
    manifest_data = json.loads(Path(path).with_name("manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest_data, dict):
        pytest.fail(f"{_BUILD_DIRECTORY_PRUNE_CODE}: graph manifest shape changed", pytrace=False)
    manifest_path_kinds = [_tracked_build_path_kind(source) for source in manifest_data]
    if any(kind is not None for kind in manifest_path_kinds):
        pytest.fail(
            f"{_BUILD_DIRECTORY_PRUNE_CODE}: manifest coverage or source alias changed; "
            "reconcile the reviewed residual",
            pytrace=False,
        )


def test_build_residual_path_classifier_rejects_aliases():
    canonical = "master-reference/build/deterministic-gzip.mjs"
    assert _tracked_build_path_kind(canonical) == "canonical"
    for alias in (
        "./master-reference/build/deterministic-gzip.mjs",
        "MASTER-REFERENCE/BUILD/DETERMINISTIC-GZIP.MJS",
        "master-reference/build/../build/deterministic-gzip.mjs",
        "master-reference\\build\\deterministic-gzip.mjs",
        "C:/private/repo/master-reference/build/deterministic-gzip.mjs",
        quote(quote("C:/private/repo/master-reference/build/deterministic-gzip.mjs", safe=""), safe=""),
        quote(
            quote(quote("C:/private/repo/master-reference/build/deterministic-gzip.mjs", safe=""), safe=""),
            safe="",
        ),
    ):
        assert _tracked_build_path_kind(alias) == "alias"
    assert _tracked_build_path_kind("master-reference/app/builders.ts") is None
    assert _has_exact_build_component("other/build/owner.py")
    assert not _has_exact_build_component("other/Build/owner.py")

    structural_probe = {
        "nodes": [],
        "links": [{"source": "safe", "target": "safe", "source_file": canonical}],
        "hyperedges": [{"metadata": {"source_file": f"./{canonical}"}}],
    }
    assert sum(
        _tracked_build_path_kind(value) is not None for value in _iter_structural_graph_strings(structural_probe)
    ) == 2


def test_node_ids_do_not_embed_the_absolute_checkout_path():
    """No serialized graph field may carry the producer-slugged checkout identity."""
    graph, path = _load_graph()
    repo_root = Path(path).resolve().parent.parent
    disclosure_count = _checkout_path_disclosure_count(graph, repo_root)
    if disclosure_count < 0:
        pytest.fail("checkout path is too weak for a privacy-safe graph disclosure check", pytrace=False)
    if disclosure_count:
        pytest.fail(
            "the graph embeds its normalized absolute checkout path; "
            f"privacy-offending serialized occurrence count: {disclosure_count}",
            pytrace=False,
        )


def test_checkout_path_disclosure_counter_covers_nodes_links_and_hyperedges():
    """The pure privacy guard must cover every graph identifier/endpoint representation."""
    synthetic_root = "C:/Users/example/Desktop/private-checkout"
    root_slug = _normalized_path_slug(synthetic_root)
    graph = {
        "nodes": [{"id": f"{root_slug}_node"}, {"id": "safe_node"}],
        "links": [{"source": "safe_node", "target": f"{root_slug}_link_target"}],
        "hyperedges": [{"endpoints": ["safe_node", f"{root_slug}_hyperedge_target"]}],
        "metadata": {
            quote(quote(quote(synthetic_root, safe=""), safe=""), safe=""): "safe",
            quote(quote(quote(quote(synthetic_root, safe=""), safe=""), safe=""), safe=""): "safe",
        },
    }
    assert _checkout_path_disclosure_count(graph, synthetic_root) == 5


def test_percent_decoding_bound_inspects_third_layer_and_fails_closed_after_it():
    source = "C:/private/graphify-out/memory/example.md"
    triple_encoded = quote(quote(quote(source, safe=""), safe=""), safe="")
    quadruple_encoded = quote(triple_encoded, safe="")
    build_source = "C:/private/repo/master-reference/build/deterministic-gzip.mjs"
    quadruple_encoded_build = quote(quote(quote(quote(build_source, safe=""), safe=""), safe=""), safe="")

    triple_variants, triple_exceeded = _decoded_text_variants(triple_encoded)
    assert triple_variants[-1] == source
    assert not triple_exceeded
    _, quadruple_exceeded = _decoded_text_variants(quadruple_encoded)
    assert quadruple_exceeded
    assert _graph_output_path_kind(quadruple_encoded) == "alias"
    assert _tracked_build_path_kind(quadruple_encoded_build) == "alias"


def test_file_types_within_known_enum():
    graph, _ = _load_graph()
    seen = {node.get("file_type") for node in graph["nodes"]}
    unknown = seen - _KNOWN_FILE_TYPES
    assert not unknown, f"unknown node file_type(s) {unknown} - the node-type enum grew; reconcile intentionally"


def test_relation_kinds_within_known_vocabulary():
    graph, _ = _load_graph()
    seen = {edge.get("relation") for edge in graph["links"]}
    unknown = seen - _KNOWN_RELATIONS
    assert not unknown, f"unknown edge relation(s) {unknown} - the edge vocabulary grew; reconcile intentionally"


def test_reviewed_relation_receipts_are_exact_and_source_grounded():
    graph, path = _load_graph()
    repo_root = Path(path).resolve().parent.parent
    try:
        tracked_result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.fail("reviewed relation source census unavailable", pytrace=False)
    tracked_sources = set(tracked_result.stdout.split("\0"))
    tracked_sources.discard("")

    reviewed: dict[str, list[dict]] = {}
    for relation, (expected_count, expected_digest) in _REVIEWED_RELATION_RECEIPTS.items():
        edges = [edge for edge in graph["links"] if edge.get("relation") == relation]
        reviewed[relation] = edges
        if len(edges) != expected_count or _canonical_records_digest(edges) != expected_digest:
            pytest.fail(
                f"reviewed {relation} relation receipt changed; reconcile intentionally",
                pytrace=False,
            )

    extends_edges = reviewed["extends"]
    if len(extends_edges) != 1 or not _extends_edge_has_scalar_json_source(
        extends_edges[0],
        repo_root,
        tracked_sources,
    ):
        pytest.fail(
            "reviewed extends relation is not grounded in a canonical tracked scalar JSON property",
            pytrace=False,
        )


def test_extends_source_semantic_guard_accepts_scalar_and_rejects_aliases(tmp_path):
    source = tmp_path / "scalar.json"
    source.write_text(json.dumps({"extends": "./base.json"}, indent=2) + "\n", encoding="utf-8")
    edge = {
        "relation": "extends",
        "source_file": "scalar.json",
        "source_location": "L2",
        "target": "ref_base_json",
    }
    tracked = {"scalar.json"}

    assert _extends_edge_has_scalar_json_source(edge, tmp_path, tracked)
    for mutation in (
        {**edge, "relation": "calls"},
        {**edge, "source_file": "./scalar.json"},
        {**edge, "source_location": "L0"},
        {**edge, "source_location": "L2:1"},
        {**edge, "target": "ref_substitute"},
    ):
        assert not _extends_edge_has_scalar_json_source(mutation, tmp_path, tracked)


@pytest.mark.parametrize(
    ("array_key", "value"),
    [
        ("required", "phantom"),
        ("enum", "ghost"),
        ("include", "src"),
        ("extends", "base"),
    ],
)
def test_extends_source_semantic_guard_rejects_unrelated_json_arrays(tmp_path, array_key, value):
    source = tmp_path / "array.json"
    source.write_text(json.dumps({array_key: [value]}, indent=2) + "\n", encoding="utf-8")
    false_edge = {
        "relation": "extends",
        "source_file": "array.json",
        "source_location": "L2",
        "target": f"ref_{_normalized_path_slug(value)}",
    }

    assert not _extends_edge_has_scalar_json_source(false_edge, tmp_path, {"array.json"})


def test_graph_report_is_exact_or_only_has_reviewed_external_residuals():
    """Require an exact report audit from the guarded producer.

    The report remains a derivative, never the graph owner. The guarded 0.9.51
    producer corrects the structural-only summary partition, and the refreshed
    membership-signature sidecar binds saved labels to current communities.
    There are no allowed report residuals; every category is red.
    """
    _graph, path = _load_graph()
    report = Path(path).with_name("GRAPH_REPORT.md")
    assert report.is_file(), "substantial graph has no regular GRAPH_REPORT.md derivative to audit"

    result = audit_graph_report(path, report)

    assert result.counts.get("graph_nodes", 0) >= _SUBSTANTIAL_FLOOR, (
        "the stable graph/report/labels/signature snapshot became degenerate after the initial owner-machine check"
    )
    assert not result.error_codes, (
        "GRAPH_REPORT.md has an integrity failure; run "
        "`python -m tools.verify_graph_report graphify-out/graph.json "
        "graphify-out/GRAPH_REPORT.md` for the categorical receipt"
    )
