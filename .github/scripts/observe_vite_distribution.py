"""Hosted data-only inspection of the one selected Vite distribution; no approval."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import urllib.request

VERSION = "8.2.4"
METADATA = "https://registry.npmjs.org/vite/8.2.4"
TARBALL = "https://registry.npmjs.org/vite/-/vite-8.2.4.tgz"
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_MEMBER = 8 * 1024 * 1024
MAX_MEMBERS = 2048


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def strict_json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite JSON value")

    def finite_float(value):
        result = float(value)
        need(math.isfinite(result), "Nonfinite JSON number")
        return result

    need(len(raw) <= 2 * 1024 * 1024, "Oversized metadata")
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                      parse_constant=constant, parse_float=finite_float)


def checked_integrity(value: str) -> bytes:
    need(bool(re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", value)), "Noncanonical integrity")
    digest = base64.b64decode(value[7:], validate=True)
    need(len(digest) == 64 and base64.b64encode(digest).decode() == value[7:], "Invalid integrity")
    return digest


def selected_metadata(raw: bytes, expected: str) -> dict:
    checked_integrity(expected)
    value = strict_json(raw)
    need(isinstance(value, dict) and value.get("name") == "vite"
         and value.get("version") == VERSION, "Wrong package identity")
    dist = value.get("dist")
    need(isinstance(dist, dict) and dist.get("tarball") == TARBALL
         and dist.get("integrity") == expected, "Metadata differs from selected lock identity")
    return value


def raw_tar_names(expanded: bytes) -> list[tuple[str, bytes, int]]:
    """Admit plain POSIX USTAR only, before tarfile can normalize names/headers."""
    result = []
    offset = 0
    def field(raw):
        value, separator, remainder = raw.partition(b"\0")
        need(not separator or not remainder.strip(b"\0"), "Data after TAR field terminator")
        return value.decode("utf-8", errors="strict")
    while offset + 512 <= len(expanded) and expanded[offset:offset + 512] != b"\0" * 512:
        need(len(result) < MAX_MEMBERS, "Too many TAR entries")
        header = expanded[offset:offset + 512]
        need(header[257:265] == b"ustar" + b"\0" + b"00", "Only plain POSIX USTAR headers are admitted")
        kind = header[156:157]
        need(kind in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE), "Linked or special TAR entry")
        name = field(header[:100])
        prefix = field(header[345:500])
        name = prefix + "/" + name if prefix else name
        need(not name.endswith("//"), "Noncanonical TAR directory separator")
        need(not name.endswith("/") or kind == tarfile.DIRTYPE, "Noncanonical TAR regular-file separator")
        parsed = tarfile.TarInfo.frombuf(header, encoding="utf-8", errors="strict")
        need(parsed.sparse is None and parsed.type == kind, "Sparse or normalized TAR type")
        need(parsed.name == (name[:-1] if name.endswith("/") else name), "Normalized TAR path differs")
        need(0 <= parsed.size <= MAX_MEMBER, "Oversized or nonempty directory entry")
        result.append((name, kind, offset))
        offset += 512 + ((parsed.size + 511) // 512) * 512
        need(offset <= len(expanded), "Incomplete TAR payload")
    need(bool(result) and len(expanded) - offset >= 1024 and len(expanded) % 512 == 0
         and not expanded[offset:].strip(b"\0"), "Trailing or concatenated TAR data")
    return result


def inspect_tar(raw: bytes, expected: str) -> tuple[dict[str, bytes], list[dict]]:
    need(len(raw) <= MAX_ARCHIVE, "Oversized archive")
    need(hashlib.sha512(raw).digest() == checked_integrity(expected), "Tarball integrity mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(MAX_EXPANDED + 1)
        need(len(expanded) <= MAX_EXPANDED, "Oversized TAR expansion")
    physical = raw_tar_names(expanded)
    files: dict[str, bytes] = {}
    rows = []
    names: dict[str, str] = {}
    prefixes: dict[str, str] = {}
    kinds: dict[str, bool] = {}
    total = 0
    last_end = 0
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as archive:
        for member in archive:
            need(len(rows) < MAX_MEMBERS, "Too many TAR entries")
            raw_name, raw_type, raw_offset = physical[len(rows)]
            name = raw_name[:-1] if raw_name.endswith("/") else raw_name
            need(member.name == name and member.type == raw_type and member.offset == raw_offset,
                 "Physical and parsed TAR census differ")
            need(bool(name) and not any(ord(char) < 32 or ord(char) == 127 for char in name)
                 and "\\" not in name and ":" not in name and not name.startswith("/"), "Unsafe TAR path")
            parts = name.split("/")
            need(parts[0] == "package" and all(part not in ("", ".", "..") for part in parts), "Unsafe TAR root or segment")
            reserved = {"con", "prn", "aux", "nul", *("com" + str(i) for i in range(1, 10)), *("lpt" + str(i) for i in range(1, 10))}
            need(all(not part.endswith((".", " ")) and part.split(".")[0].casefold() not in reserved for part in parts), "Windows TAR path alias")
            need(PurePosixPath(name).as_posix() == name, "Noncanonical TAR path")
            key = name.casefold()
            need(key not in names, "Duplicate or case-aliased TAR entry")
            for index in range(1, len(parts) + 1):
                prefix = "/".join(parts[:index])
                need(prefix.casefold() not in prefixes or prefixes[prefix.casefold()] == prefix, "Case-aliased TAR path prefix")
                prefixes[prefix.casefold()] = prefix
            for index in range(1, len(parts)):
                parent = "/".join(parts[:index]).casefold()
                need(parent not in names or names[parent] == "/".join(parts[:index]), "Case-aliased TAR parent")
                need(parent not in kinds or kinds[parent], "File is used as TAR parent")
            need(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE), "Linked or special TAR entry")
            need(not member.linkname, "Unexpected TAR link target")
            need(member.sparse is None and not member.pax_headers, "Sparse or extended TAR member")
            need(not member.mode & 0o7000, "Special TAR permission bits")
            need(0 <= member.size <= MAX_MEMBER and (not member.isdir() or member.size == 0), "Oversized or nonempty directory entry")
            if member.isreg():
                need(not any(old.startswith(key + "/") for old in names), "File collides with TAR descendants")
            names[key] = name
            kinds[key] = member.isdir()
            row = {"name": name, "mode": member.mode, "bytes": member.size,
                   "kind": "directory" if member.isdir() else "file"}
            if member.isreg():
                total += member.size
                need(total <= MAX_EXPANDED, "Oversized members")
                stream = archive.extractfile(member)
                need(stream is not None, "Missing TAR bytes")
                data = stream.read(MAX_MEMBER + 1)
                need(len(data) == member.size, "Incomplete TAR member")
                files[name] = data
                row["sha256"] = hashlib.sha256(data).hexdigest()
            rows.append(row)
            last_end = member.offset_data + ((member.size + 511) // 512) * 512
    need(len(rows) == len(physical) and expanded[last_end:].strip(b"\0") == b"", "Trailing or concatenated TAR data")
    need("package/package.json" in files and any(name.startswith("package/dist/node/") for name in files), "Incomplete Vite distribution")
    package = strict_json(files["package/package.json"])
    need(package.get("name") == "vite" and package.get("version") == VERSION, "TAR package identity mismatch")
    return files, rows


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Registry redirect refused")


def output_path(temp_value: str, root: Path) -> Path:
    temp = Path(temp_value)
    need(temp.is_absolute() and stat.S_ISDIR(temp.lstat().st_mode)
         and temp.resolve(strict=True) == temp, "Runner temp must be an ordinary absolute directory")
    output = temp / "vite-distribution-observation"
    need(not output.is_relative_to(root.resolve(strict=True)), "Observer output must stay outside checkout")
    need(not output.exists(), "Observer output must be fresh")
    return output


def source_identity(root: Path, expected: str, script: Path) -> tuple[str, bytes, str]:
    def git(*arguments):
        return subprocess.check_output(["git", "--no-optional-locks", *arguments], cwd=root)
    source = git("rev-parse", "HEAD").decode().strip()
    need(re.fullmatch(r"[0-9a-f]{40}", source) is not None and source == expected, "Observer source mismatch")
    need(git("status", "--porcelain=v1", "--untracked-files=no") == b"", "Observer checkout must be clean")
    script_path = ".github/scripts/observe_vite_distribution.py"
    need(script.resolve() == (root / script_path).resolve(), "Unexpected observer source path")
    data = script.read_bytes()
    need(data == git("cat-file", "blob", source + ":" + script_path), "Observer script is not the selected Git blob")
    return source, data, git("rev-parse", source + ":" + script_path).decode().strip()


def fetch(url: str, limit: int) -> bytes:
    need(url in (METADATA, TARBALL), "Unselected URL")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json" if url == METADATA else "application/octet-stream"})
    with opener.open(request, timeout=30) as response:
        need(response.status == 200 and response.url == url, "Unexpected registry response")
        data = response.read(limit + 1)
        need(len(data) <= limit, "Oversized registry response")
        return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integrity", required=True, help="Previously selected candidate-lock SHA-512 SRI")
    args = parser.parse_args()
    checked_integrity(args.integrity)
    need(os.environ.get("GITHUB_ACTIONS") == "true"
         and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
         and os.environ.get("RUNNER_OS") == "Linux", "GitHub-hosted Linux required")
    need(not any(os.environ.get(key) for key in ("GH_TOKEN", "GITHUB_TOKEN", "NPM_TOKEN", "NODE_AUTH_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN")), "Package observation step must not hold credentials")
    root = Path(__file__).resolve().parents[2]
    source, script_bytes, script_blob = source_identity(root, os.environ.get("GITHUB_SHA", ""), Path(__file__))
    output = output_path(os.environ["RUNNER_TEMP"], root)
    output.mkdir(mode=0o700)
    record = {"schema": "vite_distribution_observation/1", "status": "INCOMPLETE",
              "source": source, "run_id": os.environ["GITHUB_RUN_ID"],
              "attempt": os.environ["GITHUB_RUN_ATTEMPT"], "job": os.environ["GITHUB_JOB"],
              "version": VERSION, "selected_integrity": args.integrity,
              "observer_blob": script_blob,
              "approval": False, "compatibility": False, "release_authority": False,
              "errors": []}
    def emit(name: str, raw: bytes) -> None:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    try:
        metadata = fetch(METADATA, 2 * 1024 * 1024)
        emit("metadata.json", metadata)
        selected_metadata(metadata, args.integrity)
        emit("selection-before.json", json.dumps(record, sort_keys=True).encode())
        raw = fetch(TARBALL, MAX_ARCHIVE)
        emit("vite-8.2.4.tgz", raw)
        files, rows = inspect_tar(raw, args.integrity)
        record["archive_sha256"] = hashlib.sha256(raw).hexdigest()
        record["members"] = rows
        hits = []
        for name, data in files.items():
            emit("distribution/" + name, data)
            if name.startswith("package/dist/node/") and name.endswith(".js"):
                for number, line in enumerate(data.decode("utf-8", errors="strict").splitlines(), 1):
                    if re.search(r"braces|disableGlobbing|chokidar", line, re.IGNORECASE):
                        hits.append({"path": name, "line": number, "text": line[:2000], "truncated": len(line) > 2000})
        emit("navigation-hits.json", json.dumps(hits, ensure_ascii=False).encode())
        need(source_identity(root, source, Path(__file__)) == (source, script_bytes, script_blob), "Observer checkout drift")
        record["status"] = "BYTES_CAPTURED_REVIEW_REQUIRED"
        record["limits"] = "Text hits are navigation, not proof of bundled-code absence, bounded behavior, safety, compatibility or external advisory review. All exact member bytes are preserved. No fetched package code was executed."
    except Exception as error:
        record["errors"].append(str(error))
        raise
    finally:
        emit("observation.json", json.dumps(record, indent=2, sort_keys=True).encode())
        print(json.dumps({"status": record["status"], "version": VERSION, "errors": record["errors"], "approval": False}))


if __name__ == "__main__":
    main()
