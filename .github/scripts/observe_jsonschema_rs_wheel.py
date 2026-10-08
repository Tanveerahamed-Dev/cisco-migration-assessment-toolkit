"""Fixed hosted jsonschema-rs wheel DATA observation; no installation or package execution."""
from __future__ import annotations

import base64
import csv
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib

VERSION = "0.58.5"
FILENAME = "jsonschema_rs-0.58.5-cp310-abi3-win_amd64.whl"
WHEEL_SHA256 = "f1e7d341ba53fc112a5c645f5f71834d9418f360c1d6f422c8c5314e95a65717"
METADATA_URL = "https://pypi.org/pypi/jsonschema-rs/0.58.5/json"
UPSTREAM_COMMIT = "13ab58cf82ab0ae5192762efbfc2850078ccff7a"
LICENSE_URL = f"https://raw.githubusercontent.com/Stranger6667/jsonschema/{UPSTREAM_COMMIT}/LICENSE"
DIST_INFO = "jsonschema_rs-0.58.5.dist-info/"
REQUIRED = (DIST_INFO + "METADATA", DIST_INFO + "WHEEL", DIST_INFO + "RECORD", DIST_INFO + "sboms/jsonschema-py.cyclonedx.json")
SELF = ".github/scripts/observe_jsonschema_rs_wheel.py"
TEST = "tests/test_jsonschema_rs_observation.py"
WORKFLOW = ".github/workflows/webapp-ci.yml"
INPUTS = (SELF, TEST, WORKFLOW, ".github/scripts/classify_webapp_ci_scope.py",
          "portable/atlas_bundle.py", "portable/windows-x64-requirements.lock",
          "portable/third-party-license-fallbacks.json", "portable/third-party-licenses/jsonschema-rs-LICENSE")
MAX_ARCHIVE = 32 * 1024 * 1024
MAX_MEMBER = 32 * 1024 * 1024
MAX_TOTAL = 96 * 1024 * 1024
MAX_JSON = 8 * 1024 * 1024
MAX_FILES = 256


class Refused(ValueError):
    """Fixed diagnostic codes only; do not echo package data or host paths in errors."""


def need(ok, code):
    if not ok:
        raise Refused(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_data(raw):
    need(len(raw) <= MAX_JSON, "JSON_TOO_LARGE")
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "JSON_DUPLICATE_KEY")
            result[key] = value
        return result
    def invalid(_):
        raise Refused("JSON_NONFINITE")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        need(count <= 250000 and depth <= 64, "JSON_STRUCTURE_BOUND")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            need(item == item and abs(item) != float("inf"), "JSON_NONFINITE")
    return value


def selected_distribution(metadata):
    need(type(metadata) is dict and type(metadata.get("info")) is dict and type(metadata.get("urls")) is list,
         "PYPI_METADATA_SHAPE")
    info = metadata["info"]
    need(info.get("name") == "jsonschema-rs" and info.get("version") == VERSION, "PYPI_PACKAGE_IDENTITY")
    need(0 < len(metadata["urls"]) <= 128 and all(type(row) is dict for row in metadata["urls"]), "PYPI_FILE_CENSUS")
    rows = [row for row in metadata["urls"] if row.get("filename") == FILENAME]
    need(len(rows) == 1, "PYPI_TARGET_NOT_UNIQUE")
    row = rows[0]
    need(row.get("packagetype") == "bdist_wheel" and row.get("yanked") is False
         and type(row.get("size")) is int and 0 < row["size"] <= MAX_ARCHIVE
         and type(row.get("digests")) is dict and row["digests"].get("sha256") == WHEEL_SHA256,
         "PYPI_TARGET_IDENTITY")
    public_url(row.get("url"), "files.pythonhosted.org")
    parsed = urllib.parse.urlsplit(row["url"])
    need(parsed.path.startswith("/packages/") and parsed.path.rsplit("/", 1)[-1] == FILENAME
         and re.fullmatch(r"/[A-Za-z0-9_./-]+", parsed.path)
         and all(part not in ("", ".", "..") for part in parsed.path[1:].split("/")), "PYPI_TARGET_URL_PATH")
    return {"filename": FILENAME, "url": row["url"], "bytes": row["size"], "sha256": WHEEL_SHA256,
            "upload_time": row.get("upload_time_iso_8601"), "requires_python": row.get("requires_python"),
            "metadata_url": METADATA_URL}


def public_url(url, host):
    need(type(url) is str and len(url) <= 2048, "URL_TYPE_OR_BOUND")
    parsed = urllib.parse.urlsplit(url)
    need(parsed.scheme == "https" and parsed.netloc == host and parsed.hostname == host
         and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment,
         "URL_ORIGIN_REFUSED")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused("HTTP_REDIRECT_REFUSED")


def fetch(url, host, maximum):
    public_url(url, host)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "Atlas-fixed-wheel-data-observer", "Accept-Encoding": "identity"})
    with opener.open(request, timeout=60) as response:
        need(response.status == 200 and response.geturl() == url
             and response.headers.get("Content-Encoding", "identity") == "identity", "HTTP_RESPONSE_REFUSED")
        length = response.headers.get("Content-Length")
        if length is not None:
            need(length.isdecimal() and int(length) <= maximum, "HTTP_LENGTH_BOUND")
        raw = response.read(maximum + 1)
        need(len(raw) <= maximum and (length is None or len(raw) == int(length)), "HTTP_BODY_BOUND_OR_TRUNCATED")
        return raw


def safe_name(name):
    need(type(name) is str and 0 < len(name) <= 512 and re.fullmatch(r"[A-Za-z0-9_./-]+", name), "WHEEL_NAME_REFUSED")
    need(not name.startswith("/") and all(part not in ("", ".", "..") for part in name.split("/")), "WHEEL_PATH_REFUSED")
    need(name == "jsonschema_rs" or name.startswith("jsonschema_rs/")
         or name == DIST_INFO[:-1] or name.startswith(DIST_INFO), "WHEEL_NAMESPACE_REFUSED")
    return name


def extra_fields(raw):
    offset = 0
    while offset < len(raw):
        need(offset + 4 <= len(raw), "ZIP_EXTRA_TRUNCATED")
        kind, size = struct.unpack_from("<HH", raw, offset)
        offset += 4
        need(kind != 1 and offset + size <= len(raw), "ZIP64_OR_EXTRA_REFUSED")
        offset += size


def expanded(span, method, size, crc):
    need(0 <= size <= MAX_MEMBER, "ZIP_MEMBER_BOUND")
    if method == zipfile.ZIP_STORED:
        need(len(span) == size, "ZIP_STORED_SIZE")
        data = span
    else:
        need(method == zipfile.ZIP_DEFLATED, "ZIP_CODEC_REFUSED")
        reader = zlib.decompressobj(-zlib.MAX_WBITS)
        data = reader.decompress(span, size + 1)
        need(reader.eof and not reader.unused_data and not reader.unconsumed_tail and len(data) == size,
             "ZIP_DEFLATE_SPAN_OR_SIZE")
    need(len(data) == size and zlib.crc32(data) & 0xFFFFFFFF == crc, "ZIP_ACTUAL_LENGTH_OR_CRC")
    return data


def wheel_members(raw):
    """Closed classic ZIP layout, read as bounded bytes only; never extract or load it."""
    need(len(raw) <= MAX_ARCHIVE and len(raw) >= 22, "ZIP_ARCHIVE_BOUND")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = sorted(archive.infolist(), key=lambda info: info.header_offset)
        need(0 < len(infos) <= MAX_FILES and archive.comment == b"", "ZIP_CENSUS_OR_COMMENT")
        signature, disk, central_disk, disk_count, count, central_size, central_offset, comment = struct.unpack("<4s4H2IH", raw[-22:])
        need(signature == b"PK\x05\x06" and disk == central_disk == comment == 0 and disk_count == count == len(infos)
             and central_offset == archive.start_dir and central_offset + central_size == len(raw) - 22, "ZIP_CENTRAL_CLOSURE")
        files, inventory, prefixes, seen = {}, [], {}, set()
        end, total = 0, 0
        for index, info in enumerate(infos):
            need(info.header_offset == end and info.orig_filename == info.filename, "ZIP_LOCAL_LAYOUT_OR_NUL_NAME")
            directory = info.is_dir()
            name = safe_name(info.filename[:-1] if directory else info.filename)
            need(name not in seen, "ZIP_DUPLICATE_MEMBER")
            seen.add(name)
            parts = name.split("/")
            for depth in range(1, len(parts) + 1):
                prefix = "/".join(parts[:depth])
                kind = "directory" if depth < len(parts) or directory else "file"
                prior = prefixes.get(prefix.casefold())
                need(prior is None or prior == (prefix, kind), "ZIP_PREFIX_COLLISION")
                prefixes[prefix.casefold()] = (prefix, kind)
            mode = info.external_attr >> 16
            need(stat.S_IFMT(mode) in ((0, stat.S_IFDIR) if directory else (0, stat.S_IFREG))
                 and not info.external_attr & 0x400 and (directory or not info.external_attr & 0x10), "ZIP_NONORDINARY_MEMBER")
            need(info.compress_type in (0, 8) and info.flag_bits & ~0x80E == 0 and info.flag_bits & 1 == 0,
                 "ZIP_CODEC_OR_FLAGS")
            extra_fields(info.extra)
            need(end + 30 <= central_offset, "ZIP_LOCAL_HEADER_BOUND")
            local = struct.unpack_from("<4s5H3I2H", raw, end)
            sig, version, flags, method, _time, _date, crc, compressed_size, size, name_size, extra_size = local
            need(sig == b"PK\x03\x04" and version <= 20 and flags == info.flag_bits and method == info.compress_type,
                 "ZIP_LOCAL_HEADER_IDENTITY")
            start = end + 30
            next_header = infos[index + 1].header_offset if index + 1 < len(infos) else central_offset
            need(start + name_size + extra_size <= next_header, "ZIP_LOCAL_NAME_BOUND")
            encoded = info.filename.encode("utf-8" if flags & 0x800 else "cp437")
            need(raw[start:start + name_size] == encoded, "ZIP_LOCAL_NAME_DIFFERS")
            extra_fields(raw[start + name_size:start + name_size + extra_size])
            start += name_size + extra_size
            end = start + info.compress_size
            need(end <= next_header, "ZIP_COMPRESSED_SPAN_BOUND")
            if flags & 8:
                need(crc in (0, info.CRC) and compressed_size in (0, info.compress_size) and size in (0, info.file_size), "ZIP_STREAMED_HEADER")
                descriptor = raw[end:next_header]
                expected = struct.pack("<III", info.CRC, info.compress_size, info.file_size)
                need(descriptor in (expected, b"PK\x07\x08" + expected), "ZIP_DESCRIPTOR_DIFFERS")
                end = next_header
            else:
                need((crc, compressed_size, size) == (info.CRC, info.compress_size, info.file_size)
                     and end == next_header, "ZIP_LOCAL_SIZES_OR_GAP")
            total += info.file_size
            need(total <= MAX_TOTAL and (not directory or info.file_size == 0), "ZIP_EXPANSION_BOUND")
            data = expanded(raw[start:start + info.compress_size], method, info.file_size, info.CRC)
            inventory.append({"path": name, "kind": "directory" if directory else "file", "bytes": len(data), "sha256": sha(data)})
            if not directory:
                files[name] = data
        return files, inventory


def wheel_evidence(files):
    need(set(REQUIRED) <= set(files), "WHEEL_METADATA_MEMBER_MISSING")
    need(all(len(files[name]) <= MAX_JSON for name in REQUIRED), "WHEEL_TEXT_BOUND")
    metadata = BytesParser(policy=policy.default).parsebytes(files[REQUIRED[0]])
    wheel = BytesParser(policy=policy.default).parsebytes(files[REQUIRED[1]])
    need(not metadata.defects and not wheel.defects, "WHEEL_EMAIL_METADATA_INVALID")
    names = metadata.get_all("Name", [])
    need(len(names) == 1 and re.sub(r"[-_.]+", "-", str(names[0]).casefold()) == "jsonschema-rs"
         and metadata.get_all("Version") == [VERSION], "WHEEL_PACKAGE_IDENTITY")
    need(wheel.get_all("Wheel-Version") == ["1.0"] and wheel.get_all("Root-Is-Purelib") == ["false"]
         and wheel.get_all("Tag") == ["cp310-abi3-win_amd64"], "WHEEL_PLATFORM_IDENTITY")
    records = {}
    for row in csv.reader(io.StringIO(files[REQUIRED[2]].decode("utf-8"), newline=""), strict=True):
        need(len(records) < MAX_FILES and len(row) == 3 and row[0] not in records, "WHEEL_RECORD_ROW")
        safe_name(row[0])
        records[row[0]] = row[1:]
    need(set(records) == set(files) and records[REQUIRED[2]] == ["", ""], "WHEEL_RECORD_CENSUS")
    licenses = sorted(name for name in files if "/licenses/" in name or name.rsplit("/", 1)[-1].casefold().startswith(
        ("license", "licence", "copying", "notice", "copyright")))
    selected = [*REQUIRED, *licenses]
    selected = list(dict.fromkeys(selected))
    for name in files:
        if name == REQUIRED[2]:
            continue  # RECORD's required empty self hash/size is explicit, never called verified.
        encoded, size = records[name]
        need(size.isascii() and size.isdecimal() and int(size) == len(files[name]), "WHEEL_RECORD_SIZE")
        algorithm, separator, encoded_hash = encoded.partition("=")
        need(separator == "=" and algorithm in ("sha256", "sha384", "sha512"), "WHEEL_RECORD_HASH_ALGORITHM")
        expected = base64.urlsafe_b64encode(hashlib.new(algorithm, files[name]).digest()).decode().rstrip("=")
        need(encoded_hash == expected, "WHEEL_RECORD_DIGEST")
    sbom = json_data(files[REQUIRED[-1]])
    need(type(sbom) is dict and sbom.get("bomFormat") == "CycloneDX" and type(sbom.get("specVersion")) is str
         and type(sbom.get("components", [])) is list, "UPSTREAM_SBOM_SHAPE")
    return {"metadata_name": metadata["Name"], "metadata_version": metadata["Version"], "wheel_tags": wheel.get_all("Tag"),
            "license_declaration": metadata.get("License-Expression") or metadata.get("License"),
            "declared_license_files": metadata.get_all("License-File", []), "wheel_license_members": licenses,
            "wheel_license_status": "PRESENT_REVIEW_REQUIRED" if licenses else "ABSENT_REVIEW_REQUIRED",
            "record_verified_members": sorted(name for name in files if name != REQUIRED[2]),
            "record_self_digest": "intentionally empty; not verified by self-reference",
            "sbom": {"path": REQUIRED[-1], "bytes": len(files[REQUIRED[-1]]), "sha256": sha(files[REQUIRED[-1]]),
                     "spec_version": sbom["specVersion"], "component_count": len(sbom.get("components", []))}}, selected


def ordinary(path):
    need(path.resolve() == path.absolute(), "SOURCE_PATH_INDIRECT")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= MAX_MEMBER, "SOURCE_FILE_BOUND_OR_KIND")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(MAX_MEMBER + 1)
        after = os.fstat(fd)
        need(len(raw) == before.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)
             == (before.st_size, before.st_mtime_ns, before.st_ctime_ns, 1), "SOURCE_CHANGED_DURING_READ")
        return raw
    finally:
        os.close(fd)


def source_identity(root):
    expected = os.environ.get("EXPECTED_SOURCE_COMMIT", "")
    need(re.fullmatch(r"[0-9a-f]{40}", expected) and expected == os.environ.get("GITHUB_SHA"), "SOURCE_SELECTION_REQUIRED")
    def git(*args):
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args], capture_output=True, timeout=30, check=False)
        need(result.returncode == 0 and len(result.stdout) <= MAX_MEMBER, "SOURCE_GIT_READ")
        return result.stdout
    need(git("rev-parse", "HEAD").decode().strip() == expected and git("status", "--porcelain=v1", "--untracked-files=no") == b"", "SOURCE_NOT_CLEAN_SELECTED_HEAD")
    inputs = {}
    for path in INPUTS:
        raw = ordinary(root / path)
        mode = git("ls-tree", expected, "--", path).split(b" ", 1)[0]
        need(mode in (b"100644", b"100755"), "SOURCE_GIT_MODE")
        need(raw == git("cat-file", "blob", expected + ":" + path), "SOURCE_INPUT_DIFFERS_FROM_GIT")
        inputs[path] = {"bytes": len(raw), "sha256": sha(raw), "git_mode": mode.decode(),
                        "git_blob": git("rev-parse", expected + ":" + path).decode().strip()}
    return {"commit": expected, "tree": git("rev-parse", "HEAD^{tree}").decode().strip(), "inputs": inputs}


def write_new(path, raw):
    need(path.parent.resolve() == path.parent.absolute() and len(raw) <= MAX_JSON, "OUTPUT_BOUND_OR_PARENT")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(raw)
    finally:
        os.close(fd)


def record(path, value):
    write_new(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def main():
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
         and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and os.environ.get("RUNNER_OS") == "Linux"
         and os.environ.get("GITHUB_JOB") == "frontend", "HOSTED_MANUAL_OBSERVER_ONLY")
    need(len(sys.argv) == 1, "NO_OBSERVER_PATH_OR_TARGET_ARGUMENTS")
    root = Path(__file__).resolve().parents[2]
    output = Path(os.environ["RUNNER_TEMP"]).absolute() / "jsonschema-rs-observation"
    need(not output.exists() and output.parent.resolve() == output.parent and not output.is_relative_to(root), "FRESH_PRIVATE_OUTPUT_REQUIRED")
    output.mkdir(mode=0o700)
    result = {"status": "INCOMPLETE_OR_FAILED", "source": None, "errors": [], "run_id": os.environ["GITHUB_RUN_ID"],
              "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "job": os.environ["GITHUB_JOB"], "package_executed": False,
              "review_required": True, "compatibility": False, "release_authority": False,
              "limits": "Upstream wheel data and declaration capture, not linked-Rust-component verification, individual component license closure, native runtime qualification, source-to-binary provenance or legal/release approval."}
    before = None
    try:
        before = source_identity(root)
        result["source"] = before
        record(output / "source-before.json", before)
        metadata = fetch(METADATA_URL, "pypi.org", MAX_JSON)
        write_new(output / "pypi-version.json", metadata)
        selected = selected_distribution(json_data(metadata))
        record(output / "selection-before-wheel.json", {"source": before, "selected": selected})
        archive = fetch(selected["url"], "files.pythonhosted.org", MAX_ARCHIVE)
        need(len(archive) == selected["bytes"] and sha(archive) == WHEEL_SHA256, "WHEEL_ARCHIVE_IDENTITY")
        result["archive"] = {**selected, "observed_sha256": sha(archive)}
        files, inventory = wheel_members(archive)
        record(output / "wheel-inventory.json", {"archive": result["archive"], "members": inventory})
        evidence, selected_names = wheel_evidence(files)
        members = []
        result["wheel_evidence"] = evidence
        result["plaintext_members"] = members
        for index, name in enumerate(selected_names):
            # Fixed output names: wheel paths never select filesystem destinations.
            raw = files[name]
            raw.decode("utf-8", errors="strict")
            emitted = f"member-{index:02d}.txt"
            write_new(output / emitted, raw)
            members.append({"wheel_path": name, "output": emitted, "bytes": len(raw), "sha256": sha(raw)})
        license_text = fetch(LICENSE_URL, "raw.githubusercontent.com", 64 * 1024)
        license_text.decode("utf-8", errors="strict")
        write_new(output / "upstream-LICENSE.txt", license_text)
        result["upstream_license"] = {"url": LICENSE_URL, "commit": UPSTREAM_COMMIT, "bytes": len(license_text), "sha256": sha(license_text),
                                      "scope": "separate upstream-source text; no binary/source equivalence or transitive license claim"}
    except Refused as error:
        result["errors"].append(str(error))
    except Exception:
        result["errors"].append("UNCLASSIFIED_OBSERVATION_FAILURE")
    finally:
        try:
            after = source_identity(root)
            need(before is not None and after == before, "CLOSING_SOURCE_DRIFT")
            result["source_after"] = after
        except Exception:
            result["errors"].append("CLOSING_SOURCE_BINDING_FAILED")
        if not result["errors"]:
            result["status"] = "WHEEL_MATERIALS_OBSERVED_REVIEW_REQUIRED"
        record(output / "result.json", result)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
