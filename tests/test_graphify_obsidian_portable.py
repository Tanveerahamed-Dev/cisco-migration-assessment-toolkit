from __future__ import annotations

import builtins
import hashlib
import json
import os
import sys
import types
from pathlib import Path

import pytest

from tools import export_graphify_obsidian as subject


def _ledger(root: Path) -> list[tuple[str, str]]:
    return [
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def test_name_plan_is_identity_bound_and_root_independent() -> None:
    nodes = [
        ("node-a", "Same label"),
        ("node-b", "same label"),
        ("node-c", "NUL/CON:*?<>|"),
        ("node-d", " شبكة " + "x" * 400),
    ]
    expected = subject.obsidian_name_plan(nodes)
    assert expected == subject.obsidian_name_plan(reversed(nodes))
    assert len({name.casefold() for name in expected.values()}) == len(nodes)
    assert all(len(name.encode("utf-8")) <= subject.STEM_BYTES for name in expected.values())
    assert all("/" not in name and "\\" not in name for name in expected.values())

    # Drive/root spelling is deliberately not an input to the plan. Both roots accept the same
    # members; an unsupported deep root refuses rather than silently choosing shorter names.
    members = [f"{name}.md" for name in expected.values()]
    subject.preflight_target(r"C:\short\vault", members, windows=True)
    subject.preflight_target(r"D:\a-materially-longer\portable\vault", members, windows=True)
    with pytest.raises(subject.ObsidianExportError, match="too deep"):
        subject.preflight_target("Z:\\" + "deep\\" * 55 + "vault", members, windows=True)
    with pytest.raises(subject.ObsidianExportError, match="too deep"):
        subject.preflight_target("C:\\" + "😀" * 100, members, windows=True)
    with pytest.raises(subject.ObsidianExportError, match="too deep"):
        subject.preflight_target("C:\\" + "x" * 53, ["😀" * 100 + ".md"], windows=True)


def test_duplicate_node_id_is_refused() -> None:
    with pytest.raises(subject.ObsidianExportError, match="duplicate graph node id"):
        subject.obsidian_name_plan([("same", "one"), ("same", "two")])
    duplicate_graph = json.dumps({
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": "same"}, {"id": "same"}],
        "links": [],
    }).encode()
    with pytest.raises(subject.ObsidianExportError, match="duplicate node ids"):
        subject._load_graph_bytes(duplicate_graph)


def test_valid_graph_without_optional_networkx_is_a_controlled_refusal(monkeypatch) -> None:
    real_import = builtins.__import__

    def without_networkx(name, *args, **kwargs):
        if name == "networkx" or name.startswith("networkx."):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_networkx)
    valid_graph = json.dumps({
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [{"id": "one"}],
        "links": [],
    }).encode()
    with pytest.raises(subject.ObsidianExportError, match="networkx is unavailable"):
        subject._load_graph_bytes(valid_graph)


@pytest.mark.parametrize("node_id,label", [("bad\ud800", "label"), ("node", "bad\udfff")])
def test_lone_surrogate_is_a_controlled_refusal(node_id: str, label: str) -> None:
    with pytest.raises(subject.ObsidianExportError, match="valid Unicode"):
        subject.stable_node_name(node_id, label)


def test_reviewed_loader_refuses_cached_module_objects(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "graphify", types.ModuleType("graphify"))
    monkeypatch.setitem(sys.modules, "graphify.export", types.ModuleType("graphify.export"))
    with pytest.raises(subject.ObsidianExportError, match="cached before source verification"):
        subject._load_reviewed_graphify()


def test_noncanonical_aliasing_community_label_key_is_refused() -> None:
    with pytest.raises(subject.ObsidianExportError, match="canonical integer"):
        subject._labels_bytes(b'{"1":"one","01":"alias"}')


def test_exact_graphify_export_replays_at_different_root_lengths(tmp_path: Path) -> None:
    pytest.importorskip("graphify")
    graph = {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "node-a", "label": "A" * 40, "file_type": "code", "community": 0},
            {"id": "node-b", "label": "a" * 40, "file_type": "code", "community": 0},
            {"id": "node-c", "label": "شبكة/edge", "file_type": "document", "community": 1},
        ],
        "links": [
            {"source": "node-a", "target": "node-b", "relation": "calls", "confidence": "EXTRACTED"},
            {"source": "node-b", "target": "node-c", "relation": "references", "confidence": "EXTRACTED"},
        ],
    }
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"0": "Core", "1": "Edge"}), encoding="utf-8")
    first = tmp_path / "v"
    second = tmp_path / "unicode-مسار" / "longer-root" / "vault"

    one = subject.export_portable_vault(graph_path, first, labels_path=labels)
    two = subject.export_portable_vault(graph_path, second, labels_path=labels)

    assert one == two
    assert _ledger(first) == _ledger(second)
    assert one["naming_contract"] == subject.NAMING_CONTRACT
    assert one["absolute_root_embedded"] is False
    combined = b"".join(path.read_bytes() for path in first.rglob("*") if path.is_file())
    assert str(first).encode("utf-8") not in combined
    assert str(second).encode("utf-8") not in combined


@pytest.mark.skipif(os.name != "nt", reason="legacy Windows path ceiling")
def test_unsupported_deep_target_writes_no_target(tmp_path: Path) -> None:
    pytest.importorskip("graphify")
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        json.dumps({"directed": False, "multigraph": False, "graph": {}, "nodes": [
            {"id": "node", "label": "x" * 300, "community": 0}
        ], "links": []}),
        encoding="utf-8",
    )
    target = tmp_path / ("deep" * 45) / "vault"
    with pytest.raises(subject.ObsidianExportError, match="too deep"):
        subject.export_portable_vault(graph_path, target)
    assert not target.exists()


def test_incoming_preflight_failure_removes_only_owned_temporary_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pytest.importorskip("graphify")
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        json.dumps({
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [{"id": "node", "label": "node", "community": 0}],
            "links": [],
        }),
        encoding="utf-8",
    )
    target = tmp_path / "vault"
    original = subject.preflight_target

    def fail_incoming(candidate, members, **kwargs):
        if Path(candidate).name.startswith(".gvin-"):
            raise subject.ObsidianExportError("injected incoming preflight failure")
        return original(candidate, members, **kwargs)

    monkeypatch.setattr(subject, "preflight_target", fail_incoming)
    with pytest.raises(subject.ObsidianExportError, match="injected"):
        subject.export_portable_vault(graph_path, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".gvin-*"))


def test_source_swap_during_worker_export_is_refused_without_publishing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pytest.importorskip("graphify")
    graph_path = tmp_path / "graph.json"

    def graph(label: str) -> str:
        return json.dumps({
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [{"id": "stable-id", "label": label, "community": 0}],
            "links": [],
        })

    graph_path.write_text(graph("A"), encoding="utf-8")
    target = tmp_path / "vault"
    original_run = subject.subprocess.run

    def swap_then_run(*args, **kwargs):
        graph_path.write_text(graph("B"), encoding="utf-8")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(subject.subprocess, "run", swap_then_run)
    with pytest.raises(subject.ObsidianExportError, match="changed during isolated export"):
        subject.export_portable_vault(graph_path, target)
    assert not target.exists()
