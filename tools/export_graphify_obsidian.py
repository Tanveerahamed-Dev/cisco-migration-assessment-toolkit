"""Export a relocatable Graphify vault with path-independent note names.

Graphifyy 0.9.51 sizes note stems from the absolute destination path.  That keeps
individual writes below legacy MAX_PATH, but gives the same graph different names
and wikilinks at different roots.  This tracked wrapper fixes the naming plan first,
builds in isolation, validates the complete member set against the destination, and
only then publishes into a fresh target directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unicodedata
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


CONTRACT = "atlas.graphify-obsidian-portable/1"
NAMING_CONTRACT = "stable-node-id-sha256-v1"
GRAPHIFY_VERSION = "0.9.51"
GRAPHIFY_SOURCE_SHA256 = {
    "graphify/export.py": "573079762778f191aceb500598bdc23d7142efd6a21ba881bb7d424334a83f67",
    "graphify/paths.py": "a03668a7a47ff5915f9489c98cfc9f4dddd23a7ed6628bd3ee33904b8a50c8c0",
}
STEM_BYTES = 120
NODE_ID_SUFFIX_HEX = 16
MAX_WINDOWS_PATH_CHARS = 259
RECEIPT_NAME = "atlas-obsidian-receipt.json"
_EXPORT_LOCK = threading.Lock()

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE = re.compile(r'[\\/*?:"<>|#^[\]]')
_WORD = re.compile(r"\w", flags=re.UNICODE)


class ObsidianExportError(RuntimeError):
    """The portable vault could not be produced without ambiguity or drift."""


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest_object(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _cap_utf8(value: str, limit: int) -> str:
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ObsidianExportError("graph node identity or label is not valid Unicode") from exc
    if len(raw) <= limit:
        return value
    return raw[:limit].decode("utf-8", errors="ignore").rstrip(" .")


def _safe_label(label: object) -> str:
    value = unicodedata.normalize("NFC", str(label))
    value = _UNSAFE.sub("", _CONTROL.sub(" ", value)).strip().rstrip(" .")
    value = re.sub(r"\.(?:md|mdx|qmd|markdown)$", "", value, flags=re.IGNORECASE)
    if value.startswith(".") and _WORD.search(value.lstrip(".")):
        value = "dot-" + value.lstrip(".")
    if not _WORD.search(value):
        value = "unnamed"
    return value


def stable_node_name(node_id: object, label: object) -> str:
    """Return one readable, bounded stem whose identity never depends on a root path."""
    identity = str(node_id)
    if not identity:
        raise ObsidianExportError("graph node id is empty")
    try:
        identity_bytes = identity.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ObsidianExportError("graph node identity or label is not valid Unicode") from exc
    suffix = hashlib.sha256(identity_bytes).hexdigest()[:NODE_ID_SUFFIX_HEX]
    base_limit = STEM_BYTES - len(suffix) - 2
    base = _cap_utf8(_safe_label(label), base_limit) or "unnamed"
    return f"{base}--{suffix}"


def obsidian_name_plan(nodes: Iterable[tuple[object, object]]) -> dict[str, str]:
    """Plan all node stems from stable identity and label, independent of iteration and root."""
    plan: dict[str, str] = {}
    used: dict[str, str] = {}
    material = sorted(((str(node_id), label) for node_id, label in nodes), key=lambda row: row[0])
    for node_id, label in material:
        if node_id in plan:
            raise ObsidianExportError(f"duplicate graph node id: {node_id}")
        name = stable_node_name(node_id, label)
        folded = name.casefold()
        prior = used.get(folded)
        if prior is not None and prior != node_id:
            raise ObsidianExportError(f"stable node-name collision: {prior} and {node_id}")
        used[folded] = node_id
        plan[node_id] = name
    return plan


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ObsidianExportError(f"unsafe vault member: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ObsidianExportError(f"unsafe vault member: {value!r}")
    return value


def preflight_target(
    target: str | Path,
    relative_members: Iterable[str],
    *,
    windows: bool | None = None,
) -> None:
    """Reject an unsupported destination before creating the target or any member."""
    root = str(target)
    members = [_safe_relative(str(member)) for member in relative_members]
    if len(members) != len(set(member.casefold() for member in members)):
        raise ObsidianExportError("vault member names collide under case-folding")
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return
    separator = "\\" if "\\" in root or re.match(r"^[A-Za-z]:", root) else os.sep
    base = root.rstrip("\\/")

    def windows_units(value: str) -> int:
        return len(value.encode("utf-16-le")) // 2

    too_long = [
        member
        for member in members
        if windows_units(base + separator + member.replace("/", separator))
        > MAX_WINDOWS_PATH_CHARS
    ]
    if too_long:
        raise ObsidianExportError(
            "target root is too deep for the fixed portable naming contract; "
            f"first unsupported member: {too_long[0]}"
        )


def _regular_file_rows(root: Path, *, exclude: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        if path.is_symlink():
            raise ObsidianExportError(f"vault contains a symbolic link: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ObsidianExportError(f"vault contains a non-regular member: {relative}")
        before = path.stat()
        value = path.read_bytes()
        after = path.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise ObsidianExportError(f"vault member changed while read: {relative}")
        rows.append({"path": _safe_relative(relative), "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()})
    folded = [row["path"].casefold() for row in rows]
    if len(folded) != len(set(folded)):
        raise ObsidianExportError("vault contains case-fold-colliding members")
    return rows


def _stable_input_bytes(path: Path, what: str) -> bytes:
    metadata = path.lstat()
    reparse = int(getattr(metadata, "st_file_attributes", 0)) & int(
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if path.is_symlink() or reparse or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ObsidianExportError(f"{what} must be a physical single-link regular file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        value = stream.read()
        after = os.fstat(stream.fileno())
    final = path.lstat()
    identities = {
        (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        for item in (metadata, opened, after, final)
    }
    if len(identities) != 1 or len(value) != final.st_size:
        raise ObsidianExportError(f"{what} changed while read")
    return value


def _load_reviewed_graphify():
    cached = sorted(
        name for name in sys.modules if name == "graphify" or name.startswith("graphify.")
    )
    if cached:
        raise ObsidianExportError(
            "Graphify modules were cached before source verification: " + ", ".join(cached)
        )
    try:
        observed_version = metadata.version("graphifyy")
    except metadata.PackageNotFoundError as exc:
        raise ObsidianExportError("reviewed graphifyy distribution is not installed") from exc
    if observed_version != GRAPHIFY_VERSION:
        raise ObsidianExportError(
            f"graphifyy {observed_version} is not the reviewed {GRAPHIFY_VERSION} release"
        )
    distribution = metadata.distribution("graphifyy")
    reviewed_paths = {
        relative: Path(distribution.locate_file(relative)).resolve(strict=True)
        for relative in GRAPHIFY_SOURCE_SHA256
    }
    for relative, expected in GRAPHIFY_SOURCE_SHA256.items():
        observed = hashlib.sha256(reviewed_paths[relative].read_bytes()).hexdigest()
        if observed != expected:
            raise ObsidianExportError(f"reviewed Graphify source identity changed: {relative}")
    export = importlib.import_module("graphify.export")
    paths = importlib.import_module("graphify.paths")
    loaded = {
        "graphify/export.py": Path(export.__file__).resolve(strict=True),
        "graphify/paths.py": Path(paths.__file__).resolve(strict=True),
    }
    if loaded != reviewed_paths:
        raise ObsidianExportError("loaded Graphify modules do not match the pre-import reviewed paths")
    return export


def _worker_export(request_path: Path) -> int:
    """Execute the reviewed Graphify modules in a fresh isolated interpreter."""
    try:
        request = json.loads(request_path.read_text(encoding="utf-8", errors="strict"))
        export = _load_reviewed_graphify()
        graph, communities, _ = _load_graph(Path(request["graph"]).resolve(strict=True))
        labels = _labels(
            Path(request["labels"]).resolve(strict=True) if request.get("labels") else None
        )
        node_plan = request["node_plan"]
        if not isinstance(node_plan, Mapping):
            raise ObsidianExportError("worker node-name plan is invalid")
        original_budget = export.stem_filename_budget
        original_dedup = export._dedup_node_filenames

        def fixed_budget(_output_dir, *, reserve=0, limit=200):
            return max(16, min(int(limit), STEM_BYTES - int(reserve)))

        def fixed_node_plan(_graph, _safe_name):
            return dict(node_plan)

        try:
            export.stem_filename_budget = fixed_budget
            export._dedup_node_filenames = fixed_node_plan
            staging = Path(request["staging"])
            note_count = export.to_obsidian(graph, communities, str(staging), labels)
            export.to_canvas(
                graph,
                communities,
                str(staging / "graph.canvas"),
                labels,
                node_filenames=node_plan,
            )
        finally:
            export.stem_filename_budget = original_budget
            export._dedup_node_filenames = original_dedup
        Path(request["result"]).write_bytes(_canonical_json({"note_count": note_count}))
    except (KeyError, OSError, UnicodeError, ValueError, ObsidianExportError) as exc:
        print(f"graphify-obsidian worker: REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


def _load_graph_bytes(raw: bytes):
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObsidianExportError("graph input is not strict UTF-8 JSON") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("nodes"), list):
        raise ObsidianExportError("graph input is missing its node denominator")
    node_ids = []
    for node in payload["nodes"]:
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str) or not node["id"]:
            raise ObsidianExportError("graph node id must be one nonempty string")
        node_ids.append(node["id"])
    if len(node_ids) != len(set(node_ids)):
        raise ObsidianExportError("graph input contains duplicate node ids")
    try:
        from networkx.readwrite import json_graph
    except ImportError as exc:
        raise ObsidianExportError(
            "the reviewed Graphify runtime dependency networkx is unavailable"
        ) from exc
    graph = json_graph.node_link_graph(payload, edges="links")
    communities: dict[int, list[str]] = {}
    for node_id, data in sorted(graph.nodes(data=True), key=lambda row: str(row[0])):
        cid = data.get("community")
        if isinstance(cid, int) and cid >= 0:
            communities.setdefault(cid, []).append(str(node_id))
    communities = {cid: sorted(members) for cid, members in sorted(communities.items())}
    return graph, communities, hashlib.sha256(raw).hexdigest()


def _load_graph(graph_path: Path):
    return _load_graph_bytes(_stable_input_bytes(graph_path, "graph input"))


def _labels_bytes(raw: bytes | None) -> dict[int, str]:
    if raw is None:
        return {}
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObsidianExportError("community-label input is invalid") from exc
    if not isinstance(value, Mapping):
        raise ObsidianExportError("community-label input must be an object")
    result: dict[int, str] = {}
    for key, label in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"0|[1-9]\d*", key):
            raise ObsidianExportError("community-label key is not a canonical integer")
        try:
            cid = int(key)
        except (TypeError, ValueError) as exc:
            raise ObsidianExportError("community-label key is not an integer") from exc
        if cid < 0 or cid in result or not isinstance(label, str) or not label.strip():
            raise ObsidianExportError("community-label entry is invalid")
        result[cid] = label
    return dict(sorted(result.items()))


def _labels(path: Path | None) -> dict[int, str]:
    return _labels_bytes(
        _stable_input_bytes(path, "community-label input") if path is not None else None
    )


def export_portable_vault(
    graph_path: str | Path,
    target: str | Path,
    *,
    labels_path: str | Path | None = None,
) -> dict[str, Any]:
    graph_file = Path(graph_path).resolve(strict=True)
    target_path = Path(target).resolve(strict=False)
    if target_path.exists():
        raise ObsidianExportError("target vault must not already exist")
    labels_file = Path(labels_path).resolve(strict=True) if labels_path else None
    graph_raw = _stable_input_bytes(graph_file, "graph input")
    labels_raw = (
        _stable_input_bytes(labels_file, "community-label input") if labels_file else None
    )
    graph, communities, graph_sha256 = _load_graph_bytes(graph_raw)
    _labels_bytes(labels_raw)
    node_plan = obsidian_name_plan(
        (node_id, data.get("label", node_id)) for node_id, data in graph.nodes(data=True)
    )

    with tempfile.TemporaryDirectory(prefix="atlas-obsidian-portable-") as temporary:
        temporary_path = Path(temporary)
        staging = temporary_path / "vault"
        frozen_graph = temporary_path / "graph.json"
        frozen_graph.write_bytes(graph_raw)
        frozen_labels = temporary_path / "labels.json" if labels_raw is not None else None
        if frozen_labels is not None:
            frozen_labels.write_bytes(labels_raw)
        result_path = temporary_path / "worker-result.json"
        request_path = temporary_path / "worker-request.json"
        request_path.write_bytes(_canonical_json({
            "graph": str(frozen_graph),
            "labels": str(frozen_labels) if frozen_labels else None,
            "staging": str(staging),
            "result": str(result_path),
            "node_plan": node_plan,
        }))
        worker_environment = dict(os.environ)
        worker_environment.pop("PYTHONPATH", None)
        worker_environment.pop("PYTHONHOME", None)
        with _EXPORT_LOCK:
            worker = subprocess.run(
                [sys.executable, "-I", str(Path(__file__).resolve()), "--worker", str(request_path)],
                env=worker_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                check=False,
            )
        if worker.returncode or not result_path.is_file():
            detail = (worker.stdout + worker.stderr)[-1200:].strip()
            raise ObsidianExportError(f"isolated Graphify export failed: {detail}")
        worker_result = json.loads(result_path.read_text(encoding="utf-8", errors="strict"))
        note_count = worker_result.get("note_count")
        if not isinstance(note_count, int) or note_count < 0:
            raise ObsidianExportError("isolated Graphify worker result is invalid")

        rows = _regular_file_rows(staging)
        member_digest = _digest_object(rows)
        receipt = {
            "schema": CONTRACT,
            "naming_contract": NAMING_CONTRACT,
            "graph_sha256": graph_sha256,
            "labels_sha256": (
                hashlib.sha256(labels_raw).hexdigest() if labels_raw is not None else None
            ),
            "graphify_version": GRAPHIFY_VERSION,
            "graphify_source_sha256": dict(sorted(GRAPHIFY_SOURCE_SHA256.items())),
            "stem_bytes": STEM_BYTES,
            "node_count": graph.number_of_nodes(),
            "community_count": len(communities),
            "note_count": note_count,
            "member_count_excluding_receipt": len(rows),
            "member_digest_excluding_receipt": member_digest,
            "absolute_root_embedded": False,
            "receipt_self_excluded": RECEIPT_NAME,
        }
        (staging / RECEIPT_NAME).write_bytes(_canonical_json(receipt))
        final_rows = _regular_file_rows(staging)
        preflight_target(target_path, (row["path"] for row in final_rows))

        forbidden = [str(staging), str(target_path)]
        for path in staging.rglob("*"):
            if not path.is_file():
                continue
            value = path.read_bytes()
            if any(token and token.encode("utf-8") in value for token in forbidden):
                raise ObsidianExportError("vault embeds an absolute staging or target root")

        if _stable_input_bytes(graph_file, "graph input") != graph_raw:
            raise ObsidianExportError("graph input changed during isolated export")
        if labels_file is not None and (
            _stable_input_bytes(labels_file, "community-label input") != labels_raw
        ):
            raise ObsidianExportError("community-label input changed during isolated export")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        # Each process owns a unique same-volume directory. A fixed `.gvin` let one failed
        # concurrent exporter delete another exporter's in-progress files in its cleanup path.
        incoming: Path | None = None
        incoming_identity = None
        try:
            incoming = Path(tempfile.mkdtemp(prefix=".gvin-", dir=target_path.parent))
            incoming_identity = incoming.stat()
            preflight_target(incoming, (row["path"] for row in final_rows))
            shutil.copytree(staging, incoming, dirs_exist_ok=True)
            copied_rows = _regular_file_rows(incoming)
            if copied_rows != final_rows:
                raise ObsidianExportError("published vault staging copy changed bytes")
            os.replace(incoming, target_path)
        except Exception:
            if incoming is not None and incoming_identity is not None and incoming.exists():
                observed = incoming.stat()
                if (observed.st_dev, observed.st_ino) == (
                    incoming_identity.st_dev,
                    incoming_identity.st_ino,
                ):
                    shutil.rmtree(incoming)
            raise
    return receipt


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if len(argv) == 2 and argv[0] == "--worker":
        return _worker_export(Path(argv[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", required=True, help="exact graph.json input")
    parser.add_argument("--labels", help="optional .graphify_labels.json")
    parser.add_argument("--dir", required=True, help="fresh output vault directory")
    args = parser.parse_args(argv)
    try:
        receipt = export_portable_vault(args.graph, args.dir, labels_path=args.labels)
    except (OSError, ObsidianExportError) as exc:
        print(f"graphify-obsidian: REFUSED: {exc}")
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
