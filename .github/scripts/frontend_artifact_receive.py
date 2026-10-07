"""Hosted finite candidate/dist receipt and post-import comparison. DRAFT, not executed.

Only reviewed receiver-current code executes. Producer subject/archive code remains data.
Candidate policy is explicitly shared with the exact reviewed pure Node helper; archive,
source, API, patch and post-import checks below are separate, not an independent policy oracle.
"""
from __future__ import annotations

import hashlib
import http.client
import builtins
from contextlib import contextmanager
from importlib.machinery import ModuleSpec
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
import sys
import tempfile
import types
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
import zlib

REPO = "Tanveerahamed-Dev/cisco-migration-assessment-toolkit"
REPO_ID = 1259432553
WORKFLOW_ID = 292173399
WORKFLOW = ".github/workflows/webapp-ci.yml"
JOB_NAME = "Frontend test + type-check + build"
ADMISSION_BLOB = "1f178d00cb24ae06e9d4583b48155582963ae074"
PREP = ".github/scripts/frontend_dependency_prepare.mjs"
PREP_TEST = ".github/scripts/frontend_dependency_prepare.test.mjs"
BRIDGE = ".github/scripts/frontend_candidate_admit.mjs"
SELF = ".github/scripts/frontend_artifact_receive.py"
PLAN = ".github/frontend-dependency-plan.json"
PACKAGE = "webapp/frontend/package.json"
LOCK = "webapp/frontend/package-lock.json"
DIST = "webapp/frontend/dist/"
PREP_INPUTS = (PLAN, PACKAGE, LOCK, PREP, PREP_TEST, WORKFLOW)
DIST_PROCESSORS = (".github/scripts/frontend_build_handoff.py", ".github/scripts/verify_repository_privacy.py",
                   ".github/scripts/classify_webapp_ci_scope.py", WORKFLOW, "cisco_toolkit/distribution_verify.py")
MARKER_CLOSURE = (
    ("", "cisco_toolkit/__init__.py"),
    ("registry_integrity", "cisco_toolkit/registry_integrity.py"),
    ("eoldb", "cisco_toolkit/eoldb.py"),
    ("distribution_verify", "cisco_toolkit/distribution_verify.py"),
)
MARKER_IMPORTS = {
    "": {}, "registry_integrity": {},
    "eoldb": {"registry_integrity": frozenset(("MAX_MANIFEST_BYTES", "PackIntegrityError", "SOURCE_INVENTORY_RELATIVE_PATH", "source_freshness"))},
    "distribution_verify": {"registry_integrity": frozenset(("PackIntegrityError", "verify_retained_source_chain")),
                            "eoldb": frozenset(("verify_retained_eol_source_chain",))},
}
MAX_ARCHIVE = 128 * 1024 * 1024
MAX_TOTAL = 80 * 1024 * 1024
MAX_MEMBER = 64 * 1024 * 1024
MAX_JSON = 16 * 1024 * 1024
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\Z")


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_json(data, maximum=MAX_JSON):
    need(len(data) <= maximum, "JSON size bound exceeded")
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def constant(_):
        raise ValueError("Nonfinite JSON")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        need(depth <= 64 and count <= 250000, "JSON structure bound exceeded")
        if isinstance(item, dict):
            pending.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            pending.extend((v, depth + 1) for v in item)
        elif isinstance(item, float):
            need(math.isfinite(item), "Nonfinite JSON number")
    return value


def closed(value, keys, label):
    need(type(value) is dict and set(value) == set(keys), label + " keys are not closed")


def selector(value):
    need(type(value) is dict, "Selector must be an object")
    base = {"schema", "profile", "event", "source_sha", "head_sha", "base_sha", "run_id", "run_attempt",
            "job_id", "artifact_id", "artifact_sha256", "artifact_bytes", "npm_version"}
    extra = {"artifact_profile", "import_commit"} if value.get("profile") == "post-import" else set()
    closed(value, base | extra, "Selector")
    need(value["schema"] == "frontend-artifact-selection/1", "Unknown selector schema")
    profile = value.get("artifact_profile", value["profile"])
    need(profile in ("dependency-candidate", "frontend-dist"), "Unknown artifact profile")
    need(value["profile"] in ("dependency-candidate", "frontend-dist", "post-import"), "Unknown receiver profile")
    for key in ("source_sha", "head_sha"):
        need(type(value[key]) is str and HEX40.fullmatch(value[key]), "Invalid selected Git identity")
    need(value["event"] in ("workflow_dispatch", "pull_request"), "Unsupported event")
    if profile == "dependency-candidate":
        need(value["event"] == "workflow_dispatch", "Candidate preparation is manual-only")
    if value["event"] == "workflow_dispatch":
        need(value["base_sha"] is None and value["source_sha"] == value["head_sha"], "Manual source mismatch")
    else:
        need(type(value["base_sha"]) is str and HEX40.fullmatch(value["base_sha"]), "PR base missing")
    for key in ("run_id", "run_attempt", "job_id", "artifact_id"):
        need(type(value[key]) is int and 0 < value[key] < 2**53, "Invalid finite API identity")
    need(type(value["artifact_bytes"]) is int and 0 < value["artifact_bytes"] <= MAX_ARCHIVE, "Invalid archive bound")
    need(type(value["artifact_sha256"]) is str and HEX64.fullmatch(value["artifact_sha256"]), "Invalid expected archive digest")
    need(type(value["npm_version"]) is str and VERSION.fullmatch(value["npm_version"]), "Exact npm version required")
    if extra:
        need(type(value["import_commit"]) is str and HEX40.fullmatch(value["import_commit"]), "Invalid import Git identity")
    return profile


def safe_name(name, directory=False):
    need(type(name) is str and name.isascii() and 0 < len(name) <= 240, "Unsafe member name")
    if directory:
        need(name.endswith("/"), "Directory has no trailing slash")
        name = name[:-1]
    need(not name.startswith("/") and "\\" not in name and ":" not in name and "\x00" not in name,
         "Absolute or ambiguous member name")
    parts = name.split("/")
    need(all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) and p not in (".", "..") for p in parts), "Unsafe member segment")
    need(all(not p.endswith((".", " ")) for p in parts), "Windows alias member")
    reserved = {"con", "prn", "aux", "nul", *("com" + str(i) for i in range(1, 10)), *("lpt" + str(i) for i in range(1, 10))}
    need(all(p.split(".")[0].lower() not in reserved for p in parts), "Windows device alias")
    return name


def ordinary(path, maximum=MAX_MEMBER):
    path = Path(path)
    need(path.resolve() == path.absolute(), "Indirect ordinary file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum, "Nonordinary/oversized file")
        chunks = []
        total = 0
        while total <= maximum:
            block = os.read(fd, min(65536, maximum + 1 - total))
            if not block:
                break
            total += len(block)
            chunks.append(block)
        after = os.fstat(fd)
        need(total == before.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)
             == (before.st_size, before.st_mtime_ns, before.st_ctime_ns, 1), "File changed during bounded read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def write_new(path, data, maximum=MAX_MEMBER):
    path = Path(path)
    need(path.parent.resolve() == path.parent.absolute(), "Indirect output parent")
    need(len(data) <= maximum, "Output bound exceeded")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            need(count > 0, "Write stalled")
            view = view[count:]
    finally:
        os.close(fd)


def record(path, value):
    write_new(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


@contextmanager
def bound_marker_policy(root, admitted, expected_sha256):
    """Execute only the four admitted CURRENT project sources; not a Python sandbox.

    Standard-library imports retain their standard interpreter behavior. Project
    relatives have no filesystem, bytecode-cache or canonical-module-cache fallback.
    """
    paths = {path for _, path in MARKER_CLOSURE}
    need(type(admitted) is dict and type(expected_sha256) is dict and set(admitted) == paths
         and set(expected_sha256) == paths, "Marker closure census differs")
    need(sys.version_info[:2] == (3, 12), "Marker closure requires the reviewed Python 3.12 profile")
    for path in paths:
        data = admitted[path]
        need(type(data) is bytes and len(data) <= MAX_MEMBER and type(expected_sha256[path]) is str
             and HEX64.fullmatch(expected_sha256[path]) and digest(data) == expected_sha256[path],
             "Marker closure bytes differ from their admitted source")
    prefix = "_atlas_bound_marker_" + uuid.uuid4().hex
    need(not any(name == prefix or name.startswith(prefix + ".") for name in sys.modules), "Private marker namespace is not fresh")
    modules = {}
    loaded = set()
    owned_names = []
    original_import = builtins.__import__

    def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            caller_name = globals.get("__name__") if type(globals) is dict else None
            caller = next((key for key, module in modules.items() if module.__name__ == caller_name and module.__dict__ is globals), None)
            need(level == 1 and caller in MARKER_IMPORTS and name in MARKER_IMPORTS[caller]
                 and name in loaded and type(fromlist) in (tuple, list) and bool(fromlist)
                 and frozenset(fromlist) == MARKER_IMPORTS[caller][name], "Marker relative import escaped the admitted closure")
            module = modules[name]
            namespace = module.__dict__
            need(type(namespace) is dict and all(item in namespace for item in fromlist),
                 "Bound marker relative export is missing")
            return module
        need(type(name) is str and name.split(".", 1)[0] in sys.stdlib_module_names,
             "Marker absolute import is not standard library; no project fallback")
        return original_import(name, globals, locals, fromlist, 0)

    try:
        for suffix, path in MARKER_CLOSURE:
            name = prefix + ("." + suffix if suffix else "")
            module = types.ModuleType(name)
            module.__file__ = str(root / path)
            module.__package__ = prefix
            module.__spec__ = ModuleSpec(name, loader=None, is_package=not suffix)
            if not suffix:
                module.__path__ = ()  # No directory to search for another project sibling.
            module.__builtins__ = {**vars(builtins), "__import__": controlled_import}
            modules[suffix] = module
            sys.modules[name] = module
            owned_names.append(name)
            exec(compile(admitted[path], str(root / path), "exec", dont_inherit=True), module.__dict__)
            loaded.add(suffix)
            if suffix:
                setattr(modules[""], suffix, module)
        policy = modules["distribution_verify"]
        namespace = policy.__dict__
        need(type(namespace) is dict and all(name in namespace and callable(namespace[name])
             for name in ("_marker_patterns_for", "_client_marker_patterns")), "Canonical marker functions are missing")
        yield policy
    finally:
        # Only this invocation's fresh private names are removed. Canonical cisco_toolkit
        # entries, sys.path and unrelated/preexisting modules are never rewritten.
        for name in reversed(owned_names):
            sys.modules.pop(name, None)


def member_bytes(compressed, method, declared_size, declared_crc, remaining):
    """Check the raw span itself; ZipExtFile's declared-size cutoff is not codec EOF."""
    need(0 <= declared_size <= min(MAX_MEMBER, remaining), "ZIP expanded-size budget exceeded")
    if method == zipfile.ZIP_STORED:
        need(len(compressed) == declared_size, "STORED compressed/expanded sizes differ")
        contents = compressed
    else:
        need(method == zipfile.ZIP_DEFLATED, "Unsupported member codec")
        decoder = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            # One byte beyond the admitted declaration detects concealed expansion,
            # while bounding allocation even when the declaration deliberately lies.
            contents = decoder.decompress(compressed, declared_size + 1)
        except zlib.error as error:
            raise ValueError("Invalid raw DEFLATE stream") from error
        need(len(contents) == declared_size, "DEFLATE actual expansion differs from declared size")
        need(decoder.eof and decoder.unused_data == b"" and decoder.unconsumed_tail == b"",
             "DEFLATE compressed span is truncated, trailing, or contains another stream")
    need(len(contents) == declared_size and len(contents) <= remaining
         and zlib.crc32(contents) & 0xFFFFFFFF == declared_crc, "ZIP actual expanded bytes/CRC disagree")
    return contents


def zip_members(data):
    """No extraction: local/central layout, CRC, types, names and bounded contents checked."""
    need(22 <= len(data) <= MAX_ARCHIVE, "ZIP archive size invalid")
    end = struct.unpack("<4s4H2LH", data[-22:])
    need(end[0] == b"PK\x05\x06" and end[1:3] == (0, 0) and end[3] == end[4]
         and end[7] == 0 and end[5] + end[6] == len(data) - 22, "ZIP trailer/multidisk/extra data refused")
    files = {}
    names = set()
    directories = set()
    prefixes = {}
    intervals = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        need(0 < len(entries) <= 256 and len(entries) == end[4], "ZIP entry census invalid")
        for entry in entries:
            is_dir = entry.is_dir()
            name = safe_name(entry.filename, is_dir)
            folded = name.casefold()
            need(folded not in names, "Duplicate/casefold ZIP alias")
            names.add(folded)
            segments = name.split("/")
            for index in range(1, len(segments) + 1):
                prefix = "/".join(segments[:index])
                prefix_kind = "directory" if index < len(segments) or is_dir else "file"
                previous = prefixes.get(prefix.casefold())
                need(previous is None or previous == (prefix, prefix_kind), "ZIP implicit/explicit parent spelling or kind collides")
                prefixes[prefix.casefold()] = (prefix, prefix_kind)
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            need(kind in ((0, stat.S_IFDIR) if is_dir else (0, stat.S_IFREG)), "ZIP nonregular member")
            need(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                 and entry.flag_bits & ~0x808 == 0, "ZIP encrypted/unsupported flags or compression")
            need(0 <= entry.file_size <= MAX_MEMBER and entry.compress_size <= MAX_ARCHIVE, "ZIP member size invalid")
            need(entry.file_size <= max(1024 * 1024, entry.compress_size * 200), "ZIP expansion ratio exceeded")
            start = entry.header_offset
            need(0 <= start <= end[6] - 30, "ZIP local header outside member area")
            local = struct.unpack("<4s5H3L2H", data[start:start + 30])
            need(local[0] == b"PK\x03\x04" and local[2] == entry.flag_bits and local[3] == entry.compress_type,
                 "ZIP local/central method or flags disagree")
            name_start = start + 30
            local_name = data[name_start:name_start + local[9]].decode("utf-8" if entry.flag_bits & 0x800 else "cp437")
            need(local_name == entry.filename, "ZIP local/central names disagree")
            body = name_start + local[9] + local[10]
            for extra in (entry.extra, data[name_start + local[9]:body]):
                offset = 0
                while offset < len(extra):
                    need(offset + 4 <= len(extra), "Malformed ZIP extra header")
                    tag, length = struct.unpack("<2H", extra[offset:offset + 4])
                    need(tag != 1 and offset + 4 + length <= len(extra), "ZIP64 or malformed extra field refused")
                    offset += 4 + length
            finish = body + entry.compress_size
            need(finish <= end[6], "ZIP data overlaps directory")
            if entry.flag_bits & 8:
                if data[finish:finish + 4] == b"PK\x07\x08":
                    finish += 4
                need(finish + 12 <= end[6], "Missing ZIP descriptor")
                need(struct.unpack("<3L", data[finish:finish + 12]) == (entry.CRC, entry.compress_size, entry.file_size), "ZIP descriptor mismatch")
                finish += 12
            else:
                need(local[6:9] == (entry.CRC, entry.compress_size, entry.file_size), "ZIP local sizes/CRC disagree")
            intervals.append((start, finish))
            # Keep descriptors outside this exact declared compressed span. Decode
            # the span independently; a library reader may hide bytes past file_size.
            contents = member_bytes(data[body:body + entry.compress_size], entry.compress_type,
                                    entry.file_size, entry.CRC, MAX_TOTAL - total)
            if is_dir:
                need(entry.file_size == 0 and entry.compress_size == 0 and entry.CRC == 0, "Directory carries payload")
                directories.add(name)
                continue
            total += len(contents)
            files[name] = contents
    at = 0
    for start, finish in sorted(intervals):
        need(start == at and finish >= start, "ZIP overlapping/gapped/prepended member records")
        at = finish
    need(at == end[6], "ZIP unexplained member-area bytes")
    for name in files:
        need(not any(parent.as_posix() in files for parent in PurePosixPath(name).parents if parent.as_posix() != "."), "ZIP file/parent collision")
    parents = {p.as_posix() for name in files for p in PurePosixPath(name).parents if p.as_posix() != "."}
    need(directories <= parents, "ZIP orphan directory")
    return files


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def response(self, url, api=False):
        parsed = urllib.parse.urlsplit(url)
        need(parsed.scheme == "https" and not parsed.username and not parsed.password and parsed.port in (None, 443), "Unsafe response URL")
        headers = {"User-Agent": "atlas-hosted-frontend-receiver"}
        if api:
            need(parsed.netloc == "api.github.com" and parsed.path.startswith("/repos/" + REPO + "/"), "API origin escaped")
            headers.update({"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        else:
            need(parsed.hostname.endswith(".blob.core.windows.net") or parsed.hostname.endswith(".actions.githubusercontent.com"), "Unadmitted artifact redirect host")
        try:
            return self.opener.open(urllib.request.Request(url, headers=headers), timeout=60)
        except urllib.error.HTTPError as error:
            if error.code in (301, 302, 303, 307, 308):
                return error
            raise

    def api(self, tail):
        with self.response(f"https://api.github.com/repos/{REPO}/{tail}", True) as response:
            need(response.status == 200, "GitHub API response not successful")
            data = response.read(8 * 1024 * 1024 + 1)
            return parse_json(data, 8 * 1024 * 1024)

    def listing(self, tail, key):
        result = []
        total = None
        for page in range(1, 11):
            value = self.api(f"{tail}?per_page=100&page={page}")
            need(type(value.get("total_count")) is int and 0 <= value["total_count"] <= 1000 and type(value.get(key)) is list, "Unbounded API list")
            total = value["total_count"] if total is None else total
            need(value["total_count"] == total and len(value[key]) <= 100, "API list changed during pagination")
            result.extend(value[key])
            if len(value[key]) < 100 or len(result) == total:
                break
        need(len(result) == total and len({row.get("id") for row in result}) == total, "API list census incomplete/duplicated")
        return result

    def archive(self, selection, retained_path):
        url = f"https://api.github.com/repos/{REPO}/actions/artifacts/{selection['artifact_id']}/zip"
        for redirect in range(4):
            with self.response(url, redirect == 0) as response:
                if response.status in (301, 302, 303, 307, 308):
                    url = response.headers.get("Location", "")
                    continue
                need(response.status == 200, "Artifact response not successful")
                chunks = []
                size = 0
                try:
                    while size <= selection["artifact_bytes"]:
                        block = response.read(min(65536, selection["artifact_bytes"] + 1 - size))
                        if not block:
                            break
                        chunks.append(block)
                        size += len(block)
                except http.client.IncompleteRead as error:
                    chunks.append(error.partial[:selection["artifact_bytes"] + 1 - size])
                    raise
                finally:
                    data = b"".join(chunks)
                    # Preserve bounded wrong-digest/truncated responses as negative data too.
                    write_new(retained_path, data, MAX_ARCHIVE + 1)
                need(len(data) == selection["artifact_bytes"] and digest(data) == selection["artifact_sha256"], "API/archive size or digest mismatch")
                return data
        raise ValueError("Too many artifact redirects")


def snapshot(api, s, profile):
    run = api.api(f"actions/runs/{s['run_id']}")
    need(run.get("id") == s["run_id"] and run.get("workflow_id") == WORKFLOW_ID and run.get("path") == WORKFLOW
         and run.get("head_sha") == s["head_sha"] and run.get("event") == s["event"] and run.get("run_attempt") == s["run_attempt"]
         and run.get("status") == "completed" and run.get("conclusion") == "success", "Selected workflow is not exact terminal SUCCESS")
    for key in ("repository", "head_repository"):
        need(run.get(key, {}).get("full_name") == REPO and run[key].get("id") == REPO_ID, "Repository source mismatch")
    workflow = api.api(f"actions/workflows/{WORKFLOW_ID}")
    need(workflow.get("id") == WORKFLOW_ID and workflow.get("path") == WORKFLOW and workflow.get("state") == "active", "Workflow identity changed")
    jobs = api.listing(f"actions/runs/{s['run_id']}/attempts/{s['run_attempt']}/jobs", "jobs")
    chosen = [job for job in jobs if job.get("id") == s["job_id"]]
    need(len(chosen) == 1, "Selected job absent or duplicated")
    job = chosen[0]
    need(job.get("name") == JOB_NAME and job.get("head_sha") == s["head_sha"] and job.get("run_id") == s["run_id"]
         and job.get("run_attempt") == s["run_attempt"] and job.get("labels") == ["ubuntu-24.04"]
         and job.get("runner_group_name") == "GitHub Actions" and job.get("status") == "completed" and job.get("conclusion") == "success",
         "Selected frontend job identity/runtime/conclusion mismatch")
    required = ["Run npm run verify:node", "Test hosted dependency preparation refusals"]
    required += (["Prepare the reviewed dependency candidate without changing checkout", "Preserve dependency preparation candidates and failures"]
                 if profile == "dependency-candidate" else ["Run npm ci", "Run npm run api:check", "Run npm test",
                 "Bind immutable frontend inputs before the SPA build", "Run npm run build", "Verify privacy and capture the generated SPA for review",
                 "Preserve the source-bound SPA build handoff"])
    for name in required:
        rows = [row for row in job.get("steps", []) if row.get("name") == name]
        need(len(rows) == 1 and rows[0].get("status") == "completed" and rows[0].get("conclusion") == "success", "Required producer step not successful: " + name)
    artifacts = api.listing(f"actions/runs/{s['run_id']}/artifacts", "artifacts")
    prefix = "frontend-dependency-candidate" if profile == "dependency-candidate" else "frontend-dist-handoff"
    name = f"{prefix}-{s['head_sha']}-{s['run_id']}-{s['run_attempt']}"
    matches = [item for item in artifacts if item.get("id") == s["artifact_id"] or item.get("name") == name]
    need(len(matches) == 1, "Artifact selection ambiguous or missing")
    artifact = matches[0]
    need(artifact.get("id") == s["artifact_id"] and artifact.get("name") == name and artifact.get("expired") is False
         and artifact.get("size_in_bytes") == s["artifact_bytes"] and artifact.get("digest") == "sha256:" + s["artifact_sha256"], "Selected artifact identity changed")
    arun = artifact.get("workflow_run", {})
    need(arun.get("id") == s["run_id"] and arun.get("head_sha") == s["head_sha"]
         and arun.get("repository_id") == REPO_ID and arun.get("head_repository_id") == REPO_ID, "Artifact source binding mismatch")
    return {"run": run, "workflow": workflow, "jobs": jobs, "artifacts": artifacts}


def stable_api(value):
    run = value["run"]
    return {"run": {key: run.get(key) for key in ("id", "workflow_id", "path", "head_sha", "event", "run_attempt", "status", "conclusion")},
            "workflow": value["workflow"],
            "jobs": [{key: row.get(key) for key in ("id", "run_id", "run_attempt", "head_sha", "name", "labels", "status", "conclusion", "steps")} for row in sorted(value["jobs"], key=lambda r: r["id"])],
            "artifacts": [{key: row.get(key) for key in ("id", "name", "size_in_bytes", "digest", "expired", "workflow_run")} for row in sorted(value["artifacts"], key=lambda r: r["id"])]}


def clean_env():
    env = {"PATH": os.environ["PATH"], "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    if "HOME" in os.environ:
        env["HOME"] = os.environ["HOME"]
    return env


def git(root, *args, codes=(0,), maximum=MAX_MEMBER):
    result = subprocess.run(["git", "--no-optional-locks", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                             "-C", str(root), *args], capture_output=True, env=clean_env(), timeout=120, check=False)
    need(result.returncode in codes and len(result.stdout) <= maximum and len(result.stderr) <= MAX_JSON, "Git operation failed or exceeded bound: " + args[0])
    return result.stdout


def tree(root, commit, prefix):
    result = {}
    scope = () if prefix is None else ("--", prefix)
    for raw in git(root, "ls-tree", "-rz", commit, *scope).split(b"\0"):
        if not raw:
            continue
        header, path = raw.split(b"\t", 1)
        mode, kind, blob = header.decode().split(" ")
        path = path.decode("utf-8")
        safe_name(path)
        need(mode in ("100644", "100755") and kind == "blob", "Selected Git input is not ordinary source")
        result[path] = {"mode": mode, "blob": blob}
    return result


def blob(root, commit, path):
    size = int(git(root, "cat-file", "-s", commit + ":" + path))
    need(size <= MAX_MEMBER, "Git blob exceeds source bound")
    data = git(root, "cat-file", "blob", commit + ":" + path)
    need(len(data) == size, "Git blob size mismatch")
    return data


def admit_origin(origin):
    need(origin in (f"https://github.com/{REPO}", f"https://github.com/{REPO}.git"), "Unexpected Git origin")


def expectations(root, s, profile):
    # Source checkout is not executed. Fetch fixed repository objects only if not already present.
    admit_origin(git(root, "remote", "get-url", "origin").decode().strip())
    git(root, "fetch", "--no-tags", "--depth=1", "origin", s["source_sha"])
    # Raw commit headers retain parent identity even after a shallow exact-object fetch.
    headers = git(root, "cat-file", "commit", s["source_sha"]).split(b"\n\n", 1)[0].decode()
    parents = [line.removeprefix("parent ") for line in headers.splitlines() if line.startswith("parent ")]
    if s["event"] == "pull_request":
        need(parents == [s["base_sha"], s["head_sha"]], "Tested merge parents do not match selected base/head")
    universe = {}
    if profile == "dependency-candidate":
        for path in PREP_INPUTS:
            universe.update(tree(root, s["source_sha"], path))
        need(set(universe) == set(PREP_INPUTS), "Preparation source census incomplete")
    else:
        universe = {p: row for p, row in tree(root, s["source_sha"], "webapp/frontend").items() if not p.startswith(DIST)}
        for path in DIST_PROCESSORS:
            universe.update(tree(root, s["source_sha"], path))
        need(set(DIST_PROCESSORS) <= set(universe), "Dist processor census incomplete")
    data = {path: blob(root, s["source_sha"], path) for path in sorted(universe)}
    inputs = {path: {**universe[path], "bytes": len(content), "sha256": digest(content)} for path, content in data.items()}
    return {"commit": s["source_sha"], "tree": git(root, "rev-parse", s["source_sha"] + "^{tree}").decode().strip(), "inputs": inputs}, data


def source_record(expect):
    return {"commit": expect["commit"], "tree": expect["tree"], "inputs": {p: r["sha256"] for p, r in expect["inputs"].items()}}


def bridge(root, work, name, payload, evidence=None):
    payload_path = work / (name + "-payload.json")
    # Unlike sorted evidence records, this is a semantic input to JSON.stringify:
    # preserve the selected Git manifest's insertion order through the Node bridge.
    # Exact candidate bytes remain mandatory; do not canonicalize them to hide drift.
    write_new(payload_path, (json.dumps(payload, sort_keys=False, indent=2, allow_nan=False) + "\n").encode())
    env = clean_env() | {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted"}
    result = subprocess.run(["node", str(root / BRIDGE), str(payload_path)], capture_output=True, env=env, timeout=60, check=False)
    evidence = work if evidence is None else evidence
    write_new(evidence / (name + ".stdout.json"), result.stdout)
    write_new(evidence / (name + ".stderr.log"), result.stderr)
    need(result.returncode == 0 and len(result.stdout) <= MAX_JSON, "Reviewed current-code admission refused " + name)
    return parse_json(result.stdout)


def select_registry(root, work, sources):
    """Independent official data selection, completed before requesting artifact bytes."""
    plan = parse_json(sources[PLAN])
    closed(plan, {"schema", "changes"}, "Selected plan")
    need(plan["schema"] == "frontend-dependency-plan/1" and type(plan["changes"]) is list
         and 0 < len(plan["changes"]) <= 32, "Selected target census invalid")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    raw = []
    identities = set()
    observations = []
    for index, change in enumerate(plan["changes"], 1):
        closed(change, {"section", "name", "from", "to", "version"}, "Selected target")
        name = change["name"]
        need(type(name) is str and re.fullmatch(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", name)
             and type(change["version"]) is str and VERSION.fullmatch(change["version"]), "Invalid selected package identity")
        need(name not in identities, "Duplicate independently selected package")
        identities.add(name)
        url = "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="") + "/" + urllib.parse.quote(change["version"], safe="")
        # No GitHub token, proxy credential, auth header, redirect or artifact-derived URL.
        request = urllib.request.Request(url, headers={"User-Agent": "atlas-hosted-frontend-receiver", "Accept": "application/json"})
        with opener.open(request, timeout=60) as response:
            need(response.status == 200, "Exact registry version unavailable")
            data = response.read(2 * 1024 * 1024 + 1)
        write_new(work / f"registry-expected-{index:02d}.json", data)
        value = parse_json(data, 2 * 1024 * 1024)
        need(value.get("name") == name and value.get("version") == change["version"], "Independent registry identity differs")
        raw.append(value)
        observations.append({"name": name, "version": change["version"], "url": url, "bytes": len(data), "sha256": digest(data)})
    normalized = bridge(root, work, "independent-metadata", {"mode": "metadata", "plan": plan, "metadata": raw})["metadata"]
    record(work / "registry-expectations-before-receipt.json", {"observations": observations, "normalized": normalized})
    return normalized


def metadata_observations(plan, metadata_names, files, rows):
    need(len(rows) == len(metadata_names), "Metadata observation census differs")
    metadata = []
    for name, change, row in zip(metadata_names, plan["changes"], rows, strict=True):
        raw = files[name]
        need(row.get("file") == name and row.get("requested") == change and row.get("status") == 200
             and row.get("bytes") == len(raw) and row.get("sha256") == digest(raw)
             and row.get("url") == "https://registry.npmjs.org/" + urllib.parse.quote(change["name"], safe="") + "/" + urllib.parse.quote(change["version"], safe=""), "Exact metadata binding differs")
        metadata.append(parse_json(raw, 2 * 1024 * 1024))
    return metadata


def independent_metadata_match(admitted_metadata, expected_metadata):
    need(admitted_metadata == expected_metadata, "Artifact metadata/lock is not independently selected official metadata")


def command_records(commands, tool):
    need(type(commands) is list and len(commands) == 2, "Unexpected command census")
    need(type(tool.get("node")) is str and tool["node"].startswith("/") and tool["node"].endswith("/bin/node")
         and type(tool.get("npm_cli")) is str
         and tool["npm_cli"] == tool["node"].removesuffix("/bin/node") + "/lib/node_modules/npm/bin/npm-cli.js", "Preparation command tool path mismatch")
    for command, name in zip(commands, ("npm-version", "npm-lock-only"), strict=True):
        closed(command, {"name", "argv", "exit_code", "signal", "error"}, "Command record")
        need(type(command["name"]) is str and command["name"] == name
             and type(command["exit_code"]) is int and command["exit_code"] == 0
             and command["signal"] is None and command["error"] is None, "Preparation command did not report an exact normal zero exit")
        argv = command["argv"]
        need(type(argv) is list and all(type(arg) is str and 0 < len(arg) <= 4096
             and not any(ord(char) < 32 for char in arg) for arg in argv)
             and argv[:2] == [tool["node"], tool["npm_cli"]], "Preparation command argv type/tool mismatch")
        fixed = ["--registry=https://registry.npmjs.org/", "--git=/usr/bin/false", "--engine-strict", "--ignore-scripts",
                 "--audit=false", "--fund=false", "--update-notifier=false", "--fetch-retries=0", "--fetch-timeout=30000"]
        need(all(argv.count(flag) >= 1 for flag in fixed), "Preparation command safeguards missing")
        suffix = ["--version"] if name == "npm-version" else ["install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund", "--engine-strict",
                                                                   "--force=false", "--legacy-peer-deps=false", "--workspaces=false"]
        need(argv[-len(suffix):] == suffix, "Preparation command profile changed")
        options = argv[2:-len(suffix)]
        need(len(options) == 12 and options[0] == fixed[0] and options[4:] == fixed[1:], "Unexpected command options")
        need(options[1].startswith("--userconfig=/") and options[1].endswith("/config/user.npmrc")
             and options[2] == options[1].replace("--userconfig=", "--globalconfig=").replace("/user.npmrc", "/global.npmrc")
             and options[3] == "--cache=" + options[1].split("=", 1)[1].removesuffix("/config/user.npmrc") + "/cache", "Private npm config/cache paths differ")


def candidate(root, work, files, expect, sources, s, registry_expected, evidence):
    plan = parse_json(sources[PLAN])
    need(type(plan.get("changes")) is list and 0 < len(plan["changes"]) <= 32, "Plan target census invalid")
    metadata_names = [f"metadata/{i:02d}.json" for i in range(1, len(plan["changes"]) + 1)]
    required = {"preparation.json", "npm-version.stdout.log", "npm-version.stderr.log", "npm-lock-only.stdout.log", "npm-lock-only.stderr.log",
                "selected-metadata.json", "dependency-diff.json", "candidate.patch", "patch.stderr.log", "candidate/package.json", "candidate/package-lock.json", *metadata_names}
    need(set(files) == required, "Preparation member census incomplete or extended")
    receipt = parse_json(files["preparation.json"])
    closed(receipt, {"schema", "status", "errors", "commands", "selected_source", "metadata", "source_preserved", "candidate_admitted",
                     "qualification", "dependency_validation", "independent_custody", "review_required", "limits", "toolchain"}, "Preparation receipt")
    need(receipt["schema"] == "frontend-dependency-preparation/1" and receipt["status"] == "PREPARED_REVIEW_REQUIRED"
         and receipt["errors"] == [] and receipt["source_preserved"] is True and receipt["candidate_admitted"] is True
         and receipt["qualification"] is False and receipt["dependency_validation"] is False and receipt["independent_custody"] is False
         and receipt["review_required"] is True, "Preparation is incomplete, failed or promoting")
    selected = receipt["selected_source"]
    closed(selected, {"head", "tree", "inputs", "run_id", "run_attempt", "job", "runner_os", "runner_environment", "node"}, "Preparation source")
    expected_inputs = {p: {"sha256": r["sha256"], "bytes": r["bytes"], "git_blob": r["blob"]} for p, r in expect["inputs"].items()}
    need(selected.get("head") == expect["commit"] and selected.get("tree") == expect["tree"] and selected.get("inputs") == expected_inputs
         and str(selected.get("run_id")) == str(s["run_id"]) and str(selected.get("run_attempt")) == str(s["run_attempt"])
         and selected.get("job") == "frontend" and selected.get("runner_os") == "Linux"
         and selected.get("runner_environment") == "github-hosted" and selected.get("node") == "v24.19.0", "Preparation selected source/tool context differs")
    tool = receipt["toolchain"]
    closed(tool, {"node", "node_version", "npm_cli", "npm_version"}, "Preparation toolchain")
    need(tool.get("node_version") == "v24.19.0" and tool.get("npm_version") == s["npm_version"]
         and files["npm-version.stdout.log"].decode().strip() == s["npm_version"], "npm/Node identity not independently selected")
    command_records(receipt["commands"], tool)
    metadata = metadata_observations(plan, metadata_names, files, receipt["metadata"])
    payload = {"mode": "candidate", "plan": plan, "before_manifest": parse_json(sources[PACKAGE]), "before_lock": parse_json(sources[LOCK]),
               "candidate_manifest": parse_json(files["candidate/package.json"]), "candidate_lock": parse_json(files["candidate/package-lock.json"]), "metadata": metadata}
    # This is reviewed CURRENT helper code, pinned before archive receipt, never the subject helper.
    admission = bridge(root, work, "candidate-admission", payload, evidence)
    independent_metadata_match(admission["metadata"], registry_expected)
    need(admission["diff"] == parse_json(files["dependency-diff.json"]) and admission["metadata"] == parse_json(files["selected-metadata.json"])
         and admission["manifest_text"].encode() == files["candidate/package.json"], "Candidate/diff/metadata reconstruction differs")
    return {PACKAGE: files["candidate/package.json"], LOCK: files["candidate/package-lock.json"]}, files["candidate.patch"]


def dist(files, expect, s, patterns_for):
    need({"source-before.json", "handoff.json"} <= set(files), "Dist metadata absent")
    record_source = source_record(expect)
    need(parse_json(files["source-before.json"]) == record_source, "Dist initial source differs")
    handoff = parse_json(files["handoff.json"])
    closed(handoff, {"schema", "source", "members", "github_head", "run_id", "run_attempt", "node", "npm", "status", "release_authority", "final_source_rebuild_required"}, "Dist handoff")
    need(handoff["schema"] == "frontend_build_handoff/1" and handoff["source"] == record_source
         and handoff["github_head"] == s["head_sha"] and str(handoff["run_id"]) == str(s["run_id"])
         and str(handoff["run_attempt"]) == str(s["run_attempt"]) and handoff["node"] == "v24.19.0" and handoff["npm"] == s["npm_version"]
         and handoff["status"] == "GENERATED_INPUT_FOR_REVIEW_ONLY" and handoff["release_authority"] is False
         and handoff["final_source_rebuild_required"] is True, "Dist source/tool/nonpromotion binding differs")
    members = handoff["members"]
    need(type(members) is dict and 0 < len(members) <= 64 and "index.html" in members, "Dist member census invalid")
    need(set(files) == {"source-before.json", "handoff.json", *("dist/" + name for name in members)}, "Dist ZIP member closure differs")
    desired = {}
    total = 0
    for name, info in members.items():
        safe_name(name)
        need(PurePosixPath(name).suffix in (".html", ".js", ".css", ".svg", ".json", ".txt"), "Dist extension not admitted")
        closed(info, {"bytes", "sha256"}, "Dist member record")
        data = files["dist/" + name]
        need(type(info["bytes"]) is int and info["bytes"] == len(data) and info["sha256"] == digest(data), "Dist member bytes differ")
        total += len(data)
        text = data.decode("utf-8")
        need(not any(pattern.search(text) for pattern in patterns_for(DIST + name)), "Dist fails canonical marker policy")
        desired[DIST + name] = data
    parents = {p.as_posix() for name in members for p in PurePosixPath(name).parents if p.as_posix() != "."}
    need(total <= 64 * 1024 * 1024 and len(members) + len(parents) <= 128, "Dist producer bounds exceeded")
    return desired, None


def candidate_patch_paths(producer_patch):
    text = producer_patch.decode("utf-8")
    paths = re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.M)
    need(len(paths) == 2 and set(paths) == {(PACKAGE, PACKAGE), (LOCK, LOCK)}, "Candidate patch paths are not exact")
    need(not re.search(r"^(?:new file mode|deleted file mode|old mode|new mode|rename |copy |similarity |dissimilarity |GIT binary patch|Binary files)", text, re.M), "Candidate patch changes modes/types or uses binary/rename operations")


def patch(work, old, desired, producer_patch=None):
    repo = work / "patch-check"
    repo.mkdir(mode=0o700)
    template = work / "empty-git-template"
    template.mkdir(mode=0o700)
    git(repo, "init", "--quiet", "--template=" + str(template))
    for path, data in old.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        write_new(target, data)
    git(repo, "add", "--", "webapp/frontend")
    before_tree = git(repo, "write-tree").decode().strip()
    if producer_patch is not None:
        candidate_patch_paths(producer_patch)
        supplied = work / "producer.patch"
        write_new(supplied, producer_patch)
        git(repo, "apply", "--check", "--index", "--whitespace=nowarn", str(supplied))
        git(repo, "apply", "--index", "--whitespace=nowarn", str(supplied))
    else:
        for path in old:
            (repo / path).unlink()
        for path, data in desired.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            write_new(target, data)
        git(repo, "add", "-A", "--", "webapp/frontend/dist")
    # Inspect the WHOLE scratch index, not just the intended frontend subtree:
    # git apply also recognizes ordinary unified sections with no diff--git header.
    current = tree(repo, git(repo, "write-tree").decode().strip(), None)
    need(set(current) == set(desired) and all(row["mode"] == "100644" for row in current.values()), "Patch result path/mode census differs")
    # Include ignored/untracked worktree files and refuse links/special types.
    # Old known empty parents may remain after a dist deletion; no other directories
    # or files are admitted. Only Git's own freshly created internal directory is excluded.
    known_parents = {p.as_posix() for path in set(old) | set(desired)
                     for p in PurePosixPath(path).parents if p.as_posix() != "."}
    pending = [repo]
    actual_files = set()
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            info = path.lstat()
            relative = path.relative_to(repo).as_posix()
            if relative == ".git":
                need(stat.S_ISDIR(info.st_mode), "Scratch Git internals became indirect")
                continue
            if stat.S_ISDIR(info.st_mode):
                need(relative in known_parents, "Unexpected scratch worktree directory")
                pending.append(path)
            else:
                need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_mode & 0o111 == 0,
                     "Scratch worktree contains a nonordinary member or mode")
                need(relative in desired, "Unexpected scratch worktree file")
                actual_files.add(relative)
    need(actual_files == set(desired), "Scratch worktree result census differs")
    for path, data in desired.items():
        need(ordinary(repo / path) == data, "Patch result is not the admitted file bytes")
    return git(repo, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--binary", before_tree)


def post_import(root, s, profile, desired, sources):
    imported = s["import_commit"]
    need(imported == os.environ.get("GITHUB_SHA") and git(root, "rev-parse", "HEAD").decode().strip() == imported, "Import comparison is not current hosted exact source")
    expected_paths = {PACKAGE, LOCK} if profile == "dependency-candidate" else set(desired)
    actual = tree(root, imported, "webapp/frontend" if profile == "dependency-candidate" else DIST)
    if profile == "dependency-candidate":
        actual = {p: r for p, r in actual.items() if p in expected_paths}
    need(set(actual) == expected_paths and all(row["mode"] == "100644" for row in actual.values()), "Imported output path/mode census differs")
    for path, data in desired.items():
        need(blob(root, imported, path) == data, "Imported Git bytes differ from admitted artifact")
    changed = set(filter(None, git(root, "diff", "--name-only", s["source_sha"], imported, "--", "webapp/frontend").decode().splitlines()))
    old_paths = {PACKAGE, LOCK} if profile == "dependency-candidate" else set(tree(root, s["source_sha"], DIST))
    expected_changed = {path for path in old_paths | set(desired)
                        if path not in old_paths or path not in desired or blob(root, s["source_sha"], path) != desired[path]}
    need(changed == expected_changed, "Imported complete frontend change census differs")
    if profile == "frontend-dist":
        for path, data in sources.items():
            need(blob(root, imported, path) == data, "Dist import changed a non-dist producer input; rebuild from new source required")
    return {"import_commit": imported, "frontend_changed_paths": sorted(changed),
            "all_repository_changed_paths": git(root, "diff", "--name-only", s["source_sha"], imported).decode().splitlines(),
            "scope": "Imported bytes only; unrelated repository changes are not certified; final exact-source rebuild remains required"}


def main():
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
         and sys.platform == "linux", "Receiver execution is GitHub-hosted Linux only")
    need(len(sys.argv) == 1, "Receiver accepts no CLI paths/commands/URLs")
    root = Path(__file__).resolve().parents[2]
    selection_bytes = os.environ.get("FRONTEND_ARTIFACT_SELECTION", "").encode()
    s = parse_json(selection_bytes, 4096)
    profile = selector(s)
    temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    output = temp / "frontend-artifact-receive"
    need(not output.exists() and not output.is_relative_to(root), "Fresh external output required")
    output.mkdir(mode=0o700)
    record(output / "selector.json", s)
    result = {"schema": "frontend-artifact-receive/1", "status": "INCOMPLETE_OR_FAILED", "errors": [], "subject": s,
              "candidate_policy": "Shared reviewed current helper, not independent policy implementation",
              "compatibility": False, "dependency_validation": False, "acceptance": False, "release_authority": False,
              "current_source_ready": False, "final_source_rebuild_required": True}
    try:
        receiver_head = git(root, "rev-parse", "HEAD").decode().strip()
        need(receiver_head == os.environ.get("GITHUB_SHA") and HEX40.fullmatch(receiver_head), "Receiver source not current workflow SHA")
        need(git(root, "status", "--porcelain=v1", "--untracked-files=no") == b"", "Receiver checkout not clean")
        trusted_paths = (SELF, BRIDGE, PREP, *(path for _, path in MARKER_CLOSURE))
        receiver_inputs = {}
        receiver_sources = {}
        for path in trusted_paths:
            data = ordinary(root / path)
            need(data == blob(root, receiver_head, path), "Receiver-current source is not immutable Git")
            receiver_inputs[path] = digest(data)
            receiver_sources[path] = data
        need(git(root, "rev-parse", receiver_head + ":" + PREP).decode().strip() == ADMISSION_BLOB, "Pure admission helper changed; fresh review/pin required")
        need(os.environ.get("GITHUB_REPOSITORY") == REPO and os.environ.get("GITHUB_JOB") == "frontend"
             and re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ID", ""))
             and re.fullmatch(r"[1-9][0-9]*", os.environ.get("GITHUB_RUN_ATTEMPT", "")), "Receiver hosted context incomplete")
        result["receiver"] = {"commit": receiver_head, "inputs": receiver_inputs, "run_id": os.environ["GITHUB_RUN_ID"],
                              "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "job": os.environ["GITHUB_JOB"],
                              "python": sys.version, "platform": sys.platform}
        expect, sources = expectations(root, s, profile)
        record(output / "expected-source-before-receipt.json", expect)
        api = GitHub(os.environ["GH_TOKEN"])
        opening = snapshot(api, s, profile)
        record(output / "opening-api.json", opening)
        registry_expected = select_registry(root, output, sources) if profile == "dependency-candidate" else None
        # Git, API and independent registry expectations are durable BEFORE any ZIP bytes.
        archive = api.archive(s, output / "subject.zip")
        files = zip_members(archive)
        record(output / "member-observations.json", {p: {"bytes": len(b), "sha256": digest(b)} for p, b in sorted(files.items())})
        work = Path(tempfile.mkdtemp(prefix="frontend-receive-work-", dir=temp))
        if profile == "dependency-candidate":
            desired, supplied_patch = candidate(root, work, files, expect, sources, s, registry_expected, output)
            old = {p: sources[p] for p in (PACKAGE, LOCK)}
        else:
            policy_sources = {path: receiver_sources[path] for _, path in MARKER_CLOSURE}
            policy_expectations = {path: receiver_inputs[path] for _, path in MARKER_CLOSURE}
            with bound_marker_policy(root, policy_sources, policy_expectations) as policy:
                desired, supplied_patch = dist(files, expect, s, policy.__dict__["_marker_patterns_for"])
            old = {p: blob(root, s["source_sha"], p) for p in tree(root, s["source_sha"], DIST)}
        admitted_patch = patch(work, old, desired, supplied_patch)
        write_new(output / "admitted.patch", admitted_patch)
        record(output / "admitted-files.json", {p: {"bytes": len(b), "sha256": digest(b), "mode": "100644"} for p, b in desired.items()})
        if s["profile"] == "post-import":
            result["import"] = post_import(root, s, profile, desired, sources)
        closing = snapshot(api, s, profile)
        record(output / "closing-api.json", closing)
        need(stable_api(opening) == stable_api(closing), "Selected API identities changed during receipt")
        need(git(root, "rev-parse", "HEAD").decode().strip() == receiver_head
             and git(root, "status", "--porcelain=v1", "--untracked-files=no") == b"", "Receiver source changed")
        for path, sha in receiver_inputs.items():
            need(digest(ordinary(root / path)) == sha, "Receiver input changed during receipt")
        result["status"] = "IMPORTED_BYTES_MATCH_REBUILD_REQUIRED" if s["profile"] == "post-import" else "ADMITTED_EDIT_DATA_REVIEW_REQUIRED"
    except Exception as error:
        result["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        record(output / "result.json", result)
    print(result["status"] + "; no current-source readiness, dependency validation or release approval")
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
