"""Generate a public code-position sidecar on guarded hosted source, without exec.

This standalone process ends before the target pytest child. No AST, code object
or source literal is transported to that child; only primitive public positions.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import types
import warnings

SOURCE = "8c4b87d8bc149a30fcd05f5efcd123856a2778e6"
TREE = "aa003b01248588220d22face7e8218f96a9ada84"
FORMAT = "atlas-rc8-frame-manifest/1"
COMPILER = sys.version
ROOTS = ("cisco_toolkit/", "collector/", "webapp/backend/", "webapp/tests/", "portable/", "tests/")
ROOT_FILES = ("conftest.py", "COLLECT_PARSE_V3_23_0.py")
COMPILE_FLAGS = {"mode": "exec", "dont_inherit": True, "optimize": 0}
ENCODINGS = ("utf-8", "ascii")
_COOKIE = re.compile(br"^[ \t\f]*\#.*?coding[:=][ \t]*([-_.a-zA-Z0-9]+)")
_COMPILE = compile
LIMITS = {"max_files": 10_000, "max_positions": 250_000, "max_file_bytes": 4_194_304,
          "max_total_source_bytes": 268_435_456, "max_manifest_bytes": 33_554_432}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _ordinary(path, directory=False):
    metadata = path.lstat()
    if (path.resolve(strict=True) != path or stat.S_ISLNK(metadata.st_mode)
            or (not stat.S_ISDIR(metadata.st_mode) if directory else not stat.S_ISREG(metadata.st_mode))):
        raise ValueError("ordinary path required")
    if not directory and metadata.st_nlink != 1:
        raise ValueError("single file link required")
    return metadata


def _environment():
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_NO_REPLACE_OBJECTS="1",
                       GIT_TERMINAL_PROMPT="0", GIT_ATTR_NOSYSTEM="1")
    return environment


def _git(root, *arguments, data=None):
    result = subprocess.run(["git", "--no-pager", "--no-replace-objects", "-c", "core.hooksPath=/dev/null",
                             "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                             "-c", "core.attributesFile=/dev/null", "-C", str(root), *arguments],
                            env=_environment(), input=data, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError("Git refused")
    return result.stdout


def _text(root, *arguments):
    return _git(root, *arguments).decode("utf-8").strip()


def _host(subject, output):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or sys.platform != "linux" or sys.implementation.name != "cpython"
            or sys.version_info[:3] != (3, 12, 15) or sys.flags.optimize != 0
            or not sys.flags.isolated or not sys.flags.dont_write_bytecode):
        raise ValueError("host refused")
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"')
               for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines()):
        raise ValueError("Ubuntu required")
    root = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True) / "subject"
    if subject.absolute() != root or subject.resolve(strict=True) != root:
        raise ValueError("fresh subject required")
    _ordinary(root, directory=True)
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    _ordinary(temporary, directory=True)
    receipt = output.with_name("frame-manifest-receipt.json")
    if (output.name != "frame-manifest.json" or output.absolute() != output.resolve()
            or not output.is_relative_to(temporary) or output.is_relative_to(root)
            or os.path.lexists(output) or os.path.lexists(receipt)):
        raise ValueError("fresh external output required")
    _ordinary(output.parent, directory=True)
    github_output = Path(os.environ["GITHUB_OUTPUT"])
    _ordinary(github_output)
    if not github_output.is_relative_to(temporary):
        raise ValueError("runner output refused")
    return root, receipt, github_output


def _guard(root):
    git = root / ".git"
    for path, directory in ((git, True), (git / "index", False), (git / "objects", True), (git / "config", False)):
        _ordinary(path, directory)
    # No local includes/filters are needed in the fresh source checkout. Reject
    # them rather than allowing external config/code while inspecting Git state.
    config = (git / "config").read_text(encoding="utf-8")
    if re.search(r"(?mi)^\s*\[\s*(?:include|includeif|filter)(?:\s|\])", config):
        raise ValueError("external Git config refused")
    if any(os.path.lexists(path) for path in (
        git / "index.lock", git / "objects/info/alternates", git / "info/grafts", git / "info/sparse-checkout",
    )):
        raise ValueError("Git indirection refused")
    for arguments, expected in (
        (("--show-toplevel",), root), (("--absolute-git-dir",), git),
        (("--path-format=absolute", "--git-common-dir"), git),
        (("--path-format=absolute", "--git-path", "index"), git / "index"),
    ):
        if Path(_text(root, "rev-parse", *arguments)).resolve() != expected:
            raise ValueError("Git location refused")
    if (_text(root, "rev-parse", "--show-object-format") != "sha1"
            or _text(root, "rev-parse", "HEAD") != SOURCE or _text(root, "rev-parse", "HEAD^{tree}") != TREE
            or _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored")):
        raise ValueError("clean source refused")
    if any(row and not row.startswith(b"H ") for row in _git(root, "ls-files", "-v", "-z").split(b"\0")):
        raise ValueError("hidden index state refused")


def _selected(root):
    selected, total = [], 0
    for row in _git(root, "ls-tree", "-r", "-l", "-z", "--full-tree", SOURCE).split(b"\0"):
        if not row:
            continue
        metadata, relative_raw = row.split(b"\t", 1)
        relative = relative_raw.decode("utf-8")
        if not relative.endswith(".py") or not (relative in ROOT_FILES or relative.startswith(ROOTS)):
            continue
        parts = relative.split("/")
        if (not 0 < len(relative) <= 1024 or relative.startswith("/")
                or any(part in ("", ".", "..") for part in parts) or "\\" in relative):
            raise ValueError("public path refused")
        mode, kind, blob, size = metadata.split()
        if mode != b"100644" or kind != b"blob" or len(blob) != 40:
            raise ValueError("regular source blob required")
        length = int(size)
        total += length
        if (length > LIMITS["max_file_bytes"] or total > LIMITS["max_total_source_bytes"]
                or len(selected) >= LIMITS["max_files"]):
            raise ValueError("source cap refused")
        selected.append((relative, blob.decode("ascii"), length))
    if not selected:
        raise ValueError("empty source selection refused")
    return selected, total


def _blobs(root, selected):
    query = "".join(blob + "\n" for _relative, blob, _length in selected).encode("ascii")
    raw = _git(root, "cat-file", "--batch", data=query)
    offset = 0
    for relative, blob, length in selected:
        end = raw.index(b"\n", offset)
        if raw[offset:end] != f"{blob} blob {length}".encode("ascii"):
            raise ValueError("source blob header refused")
        offset = end + 1
        value = raw[offset:offset + length]
        offset += length
        if len(value) != length or raw[offset:offset + 1] != b"\n":
            raise ValueError("source blob length refused")
        offset += 1
        yield relative, value
    if offset != len(raw):
        raise ValueError("source blob trailer refused")


def _source_text(raw):
    # Inspect at most two lines of the already 4MiB-bounded input, without
    # tokenize/codec lookup or any source-selected encoding import.
    bom = raw.startswith(b"\xef\xbb\xbf")
    payload = raw[3:] if bom else raw
    encoding = "utf-8"
    for line in payload.split(b"\n", 2)[:2]:
        match = _COOKIE.match(line)
        if match is None:
            continue
        spelling = match[1].decode("ascii").lower().replace("_", "-")
        if spelling in ("utf-8", "utf8"):
            encoding = "utf-8"
        elif spelling in ("ascii", "us-ascii"):
            encoding = "ascii"
        else:
            raise ValueError("unsupported source encoding refused")
        break
    if bom and encoding != "utf-8":
        raise ValueError("source encoding conflict refused")
    return payload.decode(encoding, errors="strict")


def _positions(raw, filename, remaining):
    # Compiler diagnostics are source-bearing. Count warnings privately and
    # never emit error messages, source text, filenames or const values.
    text = _source_text(raw)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            code = _COMPILE(text, filename, "exec", dont_inherit=True, optimize=0)
    except SyntaxError:
        return "syntax_refused", [], 0
    except Warning:
        return "syntax_refused", [], 1
    positions, stack, traversed = set(), [code], 0
    current = None
    try:
        while stack:
            current = stack.pop()
            if type(current) is not types.CodeType:
                raise ValueError("exact compiler code required")
            traversed += 1
            if traversed > remaining:
                raise ValueError("position cap refused")
            name, qualname, line = current.co_name, current.co_qualname, current.co_firstlineno
            if (type(name) is not str or type(qualname) is not str or type(line) is not int
                    or not 0 < len(name) <= 1024 or not 0 < len(qualname) <= 4096 or not 0 <= line <= 10_000_000):
                raise ValueError("compiler metadata refused")
            positions.add((name, qualname, line))
            for constant in current.co_consts:
                if type(constant) is types.CodeType:
                    stack.append(constant)
        return "compiled", [list(position) for position in sorted(positions)], 0
    finally:
        code = current = None
        stack.clear()


def _manifest(root):
    selected, total = _selected(root)
    files, count, syntax, warnings_count = [], 0, 0, 0
    for relative, raw in _blobs(root, selected):
        path = root / relative
        before = _ordinary(path)
        with path.open("rb") as stream:
            actual = stream.read(LIMITS["max_file_bytes"] + 1)
        after = _ordinary(path)
        if (actual != raw or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("physical source differs from regular Git blob")
        status, positions, warned = _positions(raw, str(path), LIMITS["max_positions"] - count)
        count += len(positions)
        syntax += status == "syntax_refused"
        warnings_count += warned
        files.append({"relative": relative, "sha256": _sha(raw), "positions": positions, "status": status})
    document = {"format": FORMAT, "source": SOURCE, "tree": TREE, "compiler": COMPILER,
                "files": files, "limits": LIMITS, "compile_flags": COMPILE_FLAGS,
                "public_roots": list(ROOTS), "root_files": list(ROOT_FILES), "encodings": list(ENCODINGS)}
    encoded = (json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > LIMITS["max_manifest_bytes"]:
        raise ValueError("manifest byte cap refused")
    return encoded, {"files": len(files), "positions": count, "syntax_refusals": syntax,
                     "source_bytes": total, "compiler_warning_exception_refusals": warnings_count}


def _write_new(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("output type refused")
        while raw:
            written = os.write(descriptor, raw)
            if written <= 0:
                raise OSError("output refused")
            raw = raw[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _outputs(path, digest):
    _ordinary(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("runner output type refused")
        pending = f"frame_sidecar_sha256={digest}\n".encode("ascii")
        while pending:
            written = os.write(descriptor, pending)
            if written <= 0:
                raise OSError("runner output refused")
            pending = pending[written:]
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        root, receipt_path, github_output = _host(arguments.subject, arguments.output)
    except Exception:
        print('{"status":"host_guard_refused"}')
        return 1
    report = {"status": "manifest_refused", "stage": "source_guard_before", "source": SOURCE,
              "tree": TREE, "compiler": COMPILER,
              "helper_sha256": _sha(Path(__file__).resolve(strict=True).read_bytes()),
              "no_intentional_project_execution_or_import": True, "no_target_child_ast_or_code_objects": True,
              "compile_audit_hooks_may_observe_source_and_filename": True,
              "external_native_audit_hooks_unenumerated": True,
              "syntax_refused_includes_compiler_warning_refusals": True}
    try:
        _guard(root)
        report["source_guard_before"] = "pass"
        report["stage"] = "compile_public_source"
        encoded, counts = _manifest(root)
        report.update(counts)
        report["stage"] = "source_guard_after"
        _guard(root)
        report["source_guard_after"] = "pass"
        report["stage"] = "write_sidecar"
        _write_new(arguments.output, encoded)
        digest = _sha(encoded)
        report.update(sidecar_sha256=digest, manifest_bytes=len(encoded))
        report["stage"] = "emit_digest"
        _outputs(github_output, digest)
        report.update(status="generated", stage="complete")
        exit_code = 0
    except Exception:
        exit_code = 1  # no exception messages, source text or machine paths
    try:
        _write_new(receipt_path, (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    except Exception:
        print('{"status":"receipt_write_refused"}')
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
