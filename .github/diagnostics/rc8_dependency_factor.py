"""Standalone hosted dependency-factor admission; no project or parser imports.

Version restoration is not reconstruction of immutable historical wheel bytes.
Fingerprints cover installed RECORD-listed regular files, excluding .pyc only.
"""

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import sysconfig
from urllib.parse import unquote, urlsplit

SOURCES = {"8c4b87d8bc149a30fcd05f5efcd123856a2778e6": "aa003b01248588220d22face7e8218f96a9ada84",
           "a86ee3d7e7890a86cc2a0b5acb10d28562ef09ca": "95863e1d3e83c92cff25b7a012f00aed90a52205"}
FACTOR = "tree-sitter-scala"
VERSIONS = ("0.26.2", "0.26.3")
MAX_METADATA, MAX_FILE, MAX_TOTAL, MAX_FILES = 16 * 1024**2, 512 * 1024**2, 8 * 1024**3, 200_000
MANIFEST_KEYS = {"format", "python", "base_source", "base_tree", "historical_environment_sha256",
                 "comparison_environment_sha256", "historical_noneditable_rows", "factor", "editable",
                 "allowed_sources", "limits"}


class AdmissionRefusal(Exception):
    """Only fixed, source-authored reasons; never raw installer/input exception text."""


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9]+(?:[A-Za-z0-9._-]*[A-Za-z0-9])?", value) is None:
        raise AdmissionRefusal("invalid distribution name")
    return re.sub(r"[-_.]+", "-", value).lower()


def _digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AdmissionRefusal("invalid sha256")
    return value


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _identity(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
            metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def _regular(path, prefix):
    normalized = Path(os.path.abspath(path))
    if not normalized.is_relative_to(prefix) or normalized.resolve(strict=True) != normalized:
        raise AdmissionRefusal("redirected or external installed member")
    metadata = normalized.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise AdmissionRefusal("nonregular installed member")
    return normalized, metadata


def _read(path, prefix, maximum=MAX_METADATA):
    path, before = _regular(path, prefix)
    if before.st_size > maximum:
        raise AdmissionRefusal("metadata read bound")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            if _identity(os.fstat(stream.fileno())) != _identity(before):
                raise AdmissionRefusal("metadata identity changed")
            raw = stream.read(maximum + 1)
            if len(raw) != before.st_size or _identity(os.fstat(stream.fileno())) != _identity(before):
                raise AdmissionRefusal("metadata read changed")
        if _identity(path.lstat()) != _identity(before):
            raise AdmissionRefusal("metadata path changed")
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _host(arguments):
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Linux"
            or sys.platform != "linux" or sys.version_info[:3] != (3, 12, 15)
            or not sys.flags.isolated or not sys.dont_write_bytecode):
        raise AdmissionRefusal("hosted isolated Python required")
    if not any(line in ('ID=ubuntu', 'ID="ubuntu"') for line in Path("/etc/os-release").read_text().splitlines()):
        raise AdmissionRefusal("Ubuntu required")
    workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root = (workspace / "subject").resolve(strict=True)
    if arguments.subject.resolve(strict=True) != root or root != workspace / "subject":
        raise AdmissionRefusal("subject identity")
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    output = arguments.output.absolute()
    if (not output.is_relative_to(temporary) or output.resolve() != output
            or output.is_relative_to(root) or os.path.lexists(output)):
        raise AdmissionRefusal("fresh external runner receipt required")
    pip_report = arguments.pip_report.absolute()
    if not pip_report.is_relative_to(temporary) or pip_report.is_relative_to(root):
        raise AdmissionRefusal("external pip report required")
    return root, temporary, output


def _manifest(raw, version):
    manifest = json.loads(raw)
    if type(manifest) is not dict or set(manifest) != MANIFEST_KEYS:
        raise AdmissionRefusal("manifest schema")
    if (manifest["format"] != "atlas-rc8-dependency-factor/1" or manifest["python"] != "3.12.15"
            or manifest["allowed_sources"] != SOURCES
            or manifest["base_source"] != next(iter(SOURCES))
            or manifest["base_tree"] != SOURCES[manifest["base_source"]]
            or manifest["factor"] != {"name": FACTOR, "versions": list(VERSIONS), "historical_version": VERSIONS[0]}):
        raise AdmissionRefusal("manifest identity")
    for field in ("historical_environment_sha256", "comparison_environment_sha256"):
        _digest(manifest[field])
    rows = manifest["historical_noneditable_rows"]
    if type(rows) is not list or len(rows) != 105 or len(set(rows)) != 105:
        raise AdmissionRefusal("105 version rows required")
    expected = {}
    selected_rows = []
    for row in rows:
        if type(row) is not str or row.count("==") != 1:
            raise AdmissionRefusal("version row syntax")
        name, pinned = row.split("==")
        canonical = _canonical(name)
        if canonical in expected or not pinned or any(character.isspace() for character in pinned):
            raise AdmissionRefusal("version row ambiguity")
        if canonical == FACTOR:
            if pinned != VERSIONS[0]:
                raise AdmissionRefusal("historical factor version")
            pinned = version
        expected[canonical] = pinned
        selected_rows.append(name + "==" + pinned)
    if FACTOR not in expected or "pip" in expected or manifest["editable"] != {
        "name": "cisco-migration-assessment-toolkit", "version": "3.33.0rc7",
        "freeze_prefix": "-e git+https://github.com/Tanveerahamed-Dev/cisco-migration-assessment-toolkit@",
        "freeze_suffix": "#egg=cisco_migration_assessment_toolkit",
    }:
        raise AdmissionRefusal("editable or bootstrap policy")
    if manifest["limits"] != {"historical_wheel_bytes_available": False, "historical_pip_version_available": False,
                              "version_restoration_is_not_immutable_historical_environment": True,
                              "nonfactor_version_rows_matched": 104}:
        raise AdmissionRefusal("manifest evidence limits")
    return manifest, expected, selected_rows


def _source(root, source):
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_NO_REPLACE_OBJECTS="1")
    command = ["git", "--no-replace-objects", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root)]
    for suffix, expected in ((["rev-parse", "--show-toplevel"], str(root)),
                             (["rev-parse", "HEAD"], source), (["rev-parse", "HEAD^{tree}"], SOURCES[source])):
        result = subprocess.run(command + suffix, env=environment, capture_output=True, timeout=60, check=True)
        if result.stdout.decode("utf-8").strip() != expected:
            raise AdmissionRefusal("source guard")
    subprocess.run(command + ["diff", "--quiet", "HEAD", "--"], env=environment,
                   capture_output=True, timeout=60, check=True)
    return environment


def _no_project_or_parser_imports():
    if any(name == "COLLECT_PARSE_V3_23_0" or name.split(".", 1)[0] in ("cisco_toolkit", "webapp", "backend")
           or name == "tree_sitter" or name.startswith("tree_sitter_") for name in sys.modules):
        raise AdmissionRefusal("unexpected project or parser import")


def _wheel(report_raw, version):
    report = json.loads(report_raw)
    installations = report.get("install")
    if report.get("version") != "1" or type(installations) is not list or len(installations) != 1:
        raise AdmissionRefusal("one pip installation report required")
    entry = installations[0]
    metadata = entry.get("metadata", {})
    if (_canonical(metadata.get("name")) != FACTOR or metadata.get("version") != version
            or entry.get("requested") is not True or entry.get("is_direct") is not False):
        raise AdmissionRefusal("pip factor identity")
    download = entry.get("download_info", {})
    url = urlsplit(download.get("url", ""))
    if (url.scheme != "https" or url.netloc != "files.pythonhosted.org" or url.query or url.fragment
            or url.username is not None or url.password is not None):
        raise AdmissionRefusal("public wheel origin required")
    filename = unquote(url.path).rsplit("/", 1)[-1]
    pattern = r"tree_sitter_scala-" + re.escape(version) + r"-(?:[0-9][A-Za-z0-9_.]*-)?(cp[0-9.]+)-([A-Za-z0-9_.]+)-([A-Za-z0-9_.]+)\.whl"
    match = re.fullmatch(pattern, filename)
    if match is None or match[2] == "none" or match[3] == "any":
        raise AdmissionRefusal("binary factor wheel required")
    archive = download.get("archive_info", {})
    digest = _digest(archive.get("hashes", {}).get("sha256"))
    if "hash" in archive and archive["hash"] != "sha256=" + digest:
        raise AdmissionRefusal("conflicting wheel hashes")
    return {"name": FACTOR, "version": version, "reported_wheel_sha256": digest,
            "public_wheel_host": "files.pythonhosted.org", "binary_wheel": True}


def _installed(prefix):
    roots = sorted({Path(sysconfig.get_path(kind)).resolve(strict=True) for kind in ("purelib", "platlib")})
    installed = {}
    for root in roots:
        if not root.is_relative_to(prefix):
            raise AdmissionRefusal("site directory outside interpreter")
        for directory in sorted(root.iterdir()):
            if directory.name.endswith((".egg-info", ".egg-link", ".egg")):
                raise AdmissionRefusal("ambiguous legacy metadata")
            if not directory.name.endswith(".dist-info"):
                continue
            if directory.is_symlink() or not stat.S_ISDIR(directory.lstat().st_mode):
                raise AdmissionRefusal("regular metadata directory required")
            metadata = BytesParser().parsebytes(_read(directory / "METADATA", prefix))
            if len(metadata.get_all("Name", [])) != 1 or len(metadata.get_all("Version", [])) != 1:
                raise AdmissionRefusal("ambiguous distribution identity")
            name, version = _canonical(metadata["Name"]), metadata["Version"]
            stem = directory.name[:-len(".dist-info")]
            folder_name, folder_version = stem.rsplit("-", 1)
            if name in installed or folder_version != version:
                raise AdmissionRefusal("duplicate or mismatched distribution")
            if _canonical(folder_name) != name:
                raise AdmissionRefusal("metadata directory name")
            installed[name] = (version, directory, root)
    return installed


def _fingerprint(name, version, directory, root, prefix, owners, budget):
    record_path = directory / "RECORD"
    record = _read(record_path, prefix)
    entries, seen, excluded, verified, unhashed, binary = [], set(), 0, 0, 0, 0
    required = {directory / member for member in ("METADATA", "WHEEL", "RECORD")}
    for row in csv.reader(io.StringIO(record.decode("utf-8"), newline="")):
        if (len(row) != 3 or not row[0] or len(seen) >= MAX_FILES
                or Path(row[0]).is_absolute() or "\\" in row[0]):
            raise AdmissionRefusal("record schema or bound")
        path = Path(os.path.abspath(root / row[0]))
        if not path.is_relative_to(prefix) or path in seen or path in owners:
            raise AdmissionRefusal("record ownership ambiguity")
        seen.add(path)
        owners.add(path)
        if path.suffix == ".pyc":
            excluded += 1
            continue
        path, before = _regular(path, prefix)
        if before.st_size > MAX_FILE or budget[0] + before.st_size > MAX_TOTAL or budget[1] >= MAX_FILES:
            raise AdmissionRefusal("installed byte coverage bound")
        mode, value = row[1].split("=", 1) if "=" in row[1] else (None, None)
        if row[1] and mode not in ("sha256", "sha384", "sha512"):
            raise AdmissionRefusal("record hash algorithm")
        if (not row[1] or not row[2]) and path != record_path:
            raise AdmissionRefusal("unhashed regular member")
        if row[2] and int(row[2]) != before.st_size:
            raise AdmissionRefusal("record member size")
        sha = hashlib.sha256()
        check = hashlib.new(mode) if mode is not None else None
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        read_bytes, magic = 0, b""
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None
                if _identity(os.fstat(stream.fileno())) != _identity(before):
                    raise AdmissionRefusal("installed handle changed")
                while block := stream.read(1024 * 1024):
                    if not magic:
                        magic = block[:4]
                    read_bytes += len(block)
                    if read_bytes > before.st_size:
                        raise AdmissionRefusal("installed member grew")
                    sha.update(block)
                    if check is not None:
                        check.update(block)
                if read_bytes != before.st_size or _identity(os.fstat(stream.fileno())) != _identity(before):
                    raise AdmissionRefusal("installed bytes changed")
            if _identity(path.lstat()) != _identity(before):
                raise AdmissionRefusal("installed path changed")
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if check is not None:
            if base64.urlsafe_b64encode(check.digest()).decode("ascii").rstrip("=") != value:
                raise AdmissionRefusal("installed RECORD hash mismatch")
            verified += 1
        else:
            unhashed += 1
        budget[0] += read_bytes
        budget[1] += 1
        binary += path.suffix == ".so" and magic == b"\x7fELF"
        entries.append((path.relative_to(prefix).as_posix(), read_bytes, sha.hexdigest()))
    if not required.issubset(seen) or _read(record_path, prefix) != record:
        raise AdmissionRefusal("missing or changing RECORD closure")
    return {"name": name, "version": version, "files": len(entries), "bytes": sum(row[1] for row in entries),
            "excluded_pyc_record_entries": excluded, "record_verified_files": verified, "unhashed_record_files": unhashed,
            "elf_files": binary, "installed_sha256": _sha(_json_bytes(sorted(entries))), "record_sha256": _sha(record)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("subject", "manifest", "pip-report", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source", required=True, choices=tuple(SOURCES))
    parser.add_argument("--version", required=True, choices=VERSIONS)
    arguments = parser.parse_args()
    try:
        root, temporary, output = _host(arguments)
    except Exception:
        print('{"status":"host_guard_refused"}')
        return 1
    report = {"status": "dependency_admission_error", "stage": "manifest", "source": arguments.source,
              "tree": SOURCES[arguments.source], "factor": {"name": FACTOR, "version": arguments.version},
              "limits": {"historical_wheel_bytes_available": False, "historical_pip_version_available": False,
                         "version_restoration_not_immutable_historical_environment": True,
                         "coverage": "installed RECORD-listed regular files only; pyc excluded",
                         "editable_distribution_bytes_not_fingerprinted": True,
                         "unlisted_files_interpreter_os_and_native_runtime_outside_records_not_covered": True,
                         "pip_report_hash_not_independent_wheel_revalidation": True,
                         "no_project_parser_imports_or_gc_policy_changes": True,
                         "max_file_bytes": MAX_FILE, "max_total_bytes": MAX_TOTAL, "max_files": MAX_FILES}}
    try:
        _no_project_or_parser_imports()
        manifest_raw = arguments.manifest.read_bytes()
        manifest, expected, rows = _manifest(manifest_raw, arguments.version)
        report["manifest_sha256"] = _sha(manifest_raw)
        report["stage"] = "source_guard"
        environment = _source(root, arguments.source)
        report["stage"] = "pip_report"
        wheel = _wheel(_read(arguments.pip_report, temporary), arguments.version)
        prefix = Path(sys.prefix).resolve(strict=True)
        report["stage"] = "installed_version_inventory"
        installed = _installed(prefix)
        editable = manifest["editable"]
        if set(installed) != set(expected) | {editable["name"], "pip"}:
            raise AdmissionRefusal("installed distribution closure")
        if any(installed[name][0] != version for name, version in expected.items()):
            raise AdmissionRefusal("undeclared version drift")
        project_version, project_info, _ = installed[editable["name"]]
        direct = json.loads(_read(project_info / "direct_url.json", prefix))
        location = urlsplit(direct.get("url", ""))
        if (project_version != editable["version"] or direct.get("dir_info", {}).get("editable") is not True
                or location.scheme != "file" or location.netloc or location.query or location.fragment
                or Path(unquote(location.path)).resolve(strict=True) != root):
            raise AdmissionRefusal("editable project source")
        report["stage"] = "exact_freeze_rows"
        freeze = subprocess.run([sys.executable, "-I", "-B", "-m", "pip", "freeze"], env=environment,
                                capture_output=True, check=True, timeout=60).stdout.decode("utf-8").splitlines()
        editable_row = editable["freeze_prefix"] + arguments.source + editable["freeze_suffix"]
        if len(freeze) != 106 or sorted(freeze) != sorted([*rows, editable_row]):
            raise AdmissionRefusal("exact 106 freeze rows")
        report["stage"] = "record_byte_fingerprints"
        owners, budget, fingerprints = set(), [0, 0], []
        for name in sorted(set(expected) | {"pip"}):
            report["active_distribution"] = name  # already checked against the public allowlist
            version, directory, site = installed[name]
            fingerprints.append(_fingerprint(name, version, directory, site, prefix, owners, budget))
        factor = next(row for row in fingerprints if row["name"] == FACTOR)
        if factor["elf_files"] < 1:
            raise AdmissionRefusal("factor native payload missing")
        report["stage"] = "final_source_guard"
        _source(root, arguments.source)
        _no_project_or_parser_imports()
        report.update(status="dependency_versions_verified_and_bytes_fingerprinted", stage="complete",
                      factor=wheel, expected_noneditable_count=105, exact_freeze_count=106,
                      editable_source_verified=True, installed_distribution_count=len(installed),
                      bootstrap_pip=next(row for row in fingerprints if row["name"] == "pip"),
                      distributions=[row for row in fingerprints if row["name"] != "pip"],
                      nonfactor_installed_sha256=_sha(_json_bytes([row for row in fingerprints if row["name"] not in (FACTOR, "pip")])),
                      selected_version_rows_sha256=_sha(("\n".join(sorted(rows)) + "\n").encode("utf-8")),
                      fingerprinted_files=budget[1], fingerprinted_bytes=budget[0])
        report.pop("active_distribution", None)
        exit_code = 0
    except AdmissionRefusal as refusal:
        report["reason"] = refusal.args[0]
        exit_code = 1
    except OSError:
        report["reason"] = "missing_or_unreadable_input"
        exit_code = 1
    except Exception:
        exit_code = 1  # stage only; no raw package metadata, paths, pip output or exceptions
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, sort_keys=True, indent=2)
            stream.write("\n")
    except OSError:
        print('{"status":"receipt_write_refused"}')
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
