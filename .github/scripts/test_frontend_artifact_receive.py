"""Pure adversarial fixture tests for hosted execution only. No archive/network intake."""
import copy
import base64
import io
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import re
import stat
import struct
import tempfile
import sys
import types
import unittest
from unittest.mock import patch
import zipfile
import zlib

import frontend_artifact_receive as receive

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
    raise RuntimeError("Receiver tests execute only on GitHub-hosted runners")


def selected():
    return {"schema": "frontend-artifact-selection/1", "profile": "dependency-candidate", "event": "workflow_dispatch",
            "source_sha": "1" * 40, "head_sha": "1" * 40, "base_sha": None, "run_id": 100, "run_attempt": 1,
            "job_id": 200, "artifact_id": 300, "artifact_sha256": "a" * 64, "artifact_bytes": 600, "npm_version": "11.17.0"}


def archive(entries, compression=zipfile.ZIP_STORED):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as stream:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            info.external_attr = mode << 16
            stream.writestr(info, data)
    return output.getvalue()


def raw_deflate(data):
    codec = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return codec.compress(data) + codec.flush()


def declared_archive(compressed, method, declared_size, declared_crc, descriptor=False):
    """One raw member with independently chosen declarations; no ZipFile rewrite."""
    name = b"fixture.json"
    flags = 8 if descriptor else 0
    local = struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, flags, method, 0, 33,
                        0 if descriptor else declared_crc, 0 if descriptor else len(compressed),
                        0 if descriptor else declared_size, len(name), 0) + name + compressed
    if descriptor:
        local += b"PK\x07\x08" + struct.pack("<3L", declared_crc, len(compressed), declared_size)
    central = struct.pack("<4s6H3L5H2L", b"PK\x01\x02", (3 << 8) | 20, 20, flags, method, 0, 33,
                          declared_crc, len(compressed), declared_size, len(name), 0, 0, 0, 0,
                          (stat.S_IFREG | 0o644) << 16, 0) + name
    return local + central + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, len(central), len(local), 0)


def api_fixture(s):
    repo = {"full_name": receive.REPO, "id": receive.REPO_ID}
    run = {"id": s["run_id"], "workflow_id": receive.WORKFLOW_ID, "path": receive.WORKFLOW, "head_sha": s["head_sha"],
           "event": s["event"], "run_attempt": s["run_attempt"], "status": "completed", "conclusion": "success",
           "repository": repo, "head_repository": repo}
    step_names = ["Run npm run verify:node", "Test hosted dependency preparation refusals",
                  "Prepare the reviewed dependency candidate without changing checkout", "Preserve dependency preparation candidates and failures"]
    job = {"id": s["job_id"], "name": receive.JOB_NAME, "head_sha": s["head_sha"], "run_id": s["run_id"], "run_attempt": 1,
           "labels": ["ubuntu-24.04"], "runner_group_name": "GitHub Actions", "status": "completed", "conclusion": "success",
           "steps": [{"name": name, "status": "completed", "conclusion": "success"} for name in step_names]}
    item = {"id": s["artifact_id"], "name": f"frontend-dependency-candidate-{s['head_sha']}-100-1",
            "expired": False, "size_in_bytes": s["artifact_bytes"], "digest": "sha256:" + s["artifact_sha256"],
            "workflow_run": {"id": 100, "head_sha": s["head_sha"], "repository_id": receive.REPO_ID, "head_repository_id": receive.REPO_ID}}
    workflow = {"id": receive.WORKFLOW_ID, "path": receive.WORKFLOW, "state": "active"}
    class API:
        def api(self, tail):
            return workflow if tail.startswith("actions/workflows/") else run
        def listing(self, tail, key):
            return [job] if key == "jobs" else [item]
    return API(), run, job, item


class SelectorTests(unittest.TestCase):
    def test_observed_checkout_origin_and_git_suffix_are_the_only_admitted_forms(self):
        receive.admit_origin(f"https://github.com/{receive.REPO}")
        receive.admit_origin(f"https://github.com/{receive.REPO}.git")
        for origin in (f"https://github.com/{receive.REPO}.git/", f"https://github.com/{receive.REPO}?x=1",
                       f"https://name:secret@github.com/{receive.REPO}", f"https://github.com/{receive.REPO}-other",
                       "https://github.com/elsewhere/project.git"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                receive.admit_origin(origin)

    def test_manual_and_pr_profiles_are_distinct(self):
        s = selected()
        self.assertEqual(receive.selector(s), "dependency-candidate")
        s.update(profile="frontend-dist", event="pull_request", source_sha="2" * 40, base_sha="3" * 40)
        self.assertEqual(receive.selector(s), "frontend-dist")
        s.update(profile="post-import", artifact_profile="frontend-dist", import_commit="4" * 40)
        self.assertEqual(receive.selector(s), "frontend-dist")

    def test_unknown_keys_types_and_unbound_tools_fail(self):
        mutations = [lambda s: s.update(url="https://example.invalid"), lambda s: s.update(run_id=True),
                     lambda s: s.update(run_attempt=0), lambda s: s.update(source_sha="main"),
                     lambda s: s.update(artifact_bytes=receive.MAX_ARCHIVE + 1), lambda s: s.update(npm_version="latest"),
                     lambda s: s.update(head_sha="2" * 40), lambda s: s.update(base_sha="3" * 40),
                     lambda s: s.update(profile="dependency-candidate", event="pull_request", base_sha="3" * 40)]
        for mutate in mutations:
            s = selected()
            mutate(s)
            with self.subTest(s=s), self.assertRaises(ValueError):
                receive.selector(s)

    def test_duplicate_and_nonfinite_json_fail(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":1,"\\u0061":2}', b'{"a":NaN}', b'{"a":1e999}', b'{}tail'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                receive.parse_json(raw)


class ZipTests(unittest.TestCase):
    def test_raw_stored_and_deflated_spans_include_streamed_and_empty_controls(self):
        for data in (b"ab", b"", b'{"ordinary":true}'):
            for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                compressed = data if method == zipfile.ZIP_STORED else raw_deflate(data)
                for descriptor in (False, True):
                    with self.subTest(data=data, method=method, descriptor=descriptor):
                        raw = declared_archive(compressed, method, len(data), zlib.crc32(data), descriptor)
                        self.assertEqual(receive.zip_members(raw), {"fixture.json": data})

    def test_stored_and_deflated_underreported_size_with_correct_prefix_crc_refuse(self):
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            compressed = b"ab" if method == zipfile.ZIP_STORED else raw_deflate(b"ab")
            for descriptor in (False, True):
                with self.subTest(method=method, descriptor=descriptor), self.assertRaises(ValueError):
                    receive.zip_members(declared_archive(compressed, method, 1, zlib.crc32(b"a"), descriptor))

    def test_deflate_true_eof_and_single_stream_are_required(self):
        complete = raw_deflate(b"abc")
        for malformed in (complete[:-1], complete + b"trailing", complete + raw_deflate(b"second"), b"\xff\xff"):
            with self.subTest(compressed=malformed), self.assertRaises(ValueError):
                receive.zip_members(declared_archive(malformed, zipfile.ZIP_DEFLATED, 3, zlib.crc32(b"abc")))

    def test_oversized_actual_expansion_stops_at_declared_budget_plus_one(self):
        compressed = raw_deflate(b"a" * 4096)
        # The declared prefix fits the lowered bound and has its correct CRC;
        # actual codec output must not be mistaken for that prefix alone.
        with patch.object(receive, "MAX_MEMBER", 8), self.assertRaises(ValueError):
            receive.zip_members(declared_archive(compressed, zipfile.ZIP_DEFLATED, 8, zlib.crc32(b"a" * 8)))

    def test_actual_crc_and_remaining_total_budget_are_required(self):
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            compressed = b"ab" if method == zipfile.ZIP_STORED else raw_deflate(b"ab")
            with self.subTest(method=method), self.assertRaises(ValueError):
                receive.zip_members(declared_archive(compressed, method, 2, zlib.crc32(b"xy")))
            with self.subTest(method=method), patch.object(receive, "MAX_TOTAL", 1), self.assertRaises(ValueError):
                receive.zip_members(declared_archive(compressed, method, 2, zlib.crc32(b"ab")))

    def test_empty_directory_and_empty_regular_member_are_not_skipped_payload_checks(self):
        raw = archive([("empty/", b"", stat.S_IFDIR | 0o755), ("empty/member.json", b"", stat.S_IFREG | 0o644)])
        self.assertEqual(receive.zip_members(raw), {"empty/member.json": b""})
        for payload in (b"x", b"ab"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                receive.zip_members(archive([("empty/", payload, stat.S_IFDIR | 0o755), ("empty/member.json", b"", stat.S_IFREG | 0o644)]))

    def test_ordinary_closed_zip_roundtrips_as_data(self):
        raw = archive([("source-before.json", b"{}", stat.S_IFREG | 0o644), ("dist/index.html", b"hello", stat.S_IFREG | 0o644)])
        self.assertEqual(receive.zip_members(raw), {"source-before.json": b"{}", "dist/index.html": b"hello"})

    def test_deflated_data_roundtrips(self):
        raw = archive([("candidate/package.json", b'{"private":true}', stat.S_IFREG | 0o644)], zipfile.ZIP_DEFLATED)
        self.assertEqual(receive.zip_members(raw)["candidate/package.json"], b'{"private":true}')

    def test_normal_streamed_data_descriptor_roundtrips(self):
        class Nonseekable(io.BytesIO):
            def seek(self, *args):
                raise io.UnsupportedOperation("streamed fixture")
        output = Nonseekable()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            info = zipfile.ZipInfo("streamed.json")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            stream.writestr(info, b'{"streamed":true}')
        self.assertEqual(receive.zip_members(output.getvalue()), {"streamed.json": b'{"streamed":true}'})

    def test_paths_types_and_aliases_refuse(self):
        for name, mode in [("../escape", stat.S_IFREG), ("/absolute", stat.S_IFREG), ("C:/drive", stat.S_IFREG),
                           ("dist\\windows", stat.S_IFREG), ("dist/con.txt", stat.S_IFREG), ("dist/link.js", stat.S_IFLNK),
                           ("dist/pipe", stat.S_IFIFO), ("dist/asset.", stat.S_IFREG)]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                receive.zip_members(archive([(name, b"payload", mode | 0o644)]))
        raw = archive([("A.json", b"{}", stat.S_IFREG | 0o644), ("a.json", b"{}", stat.S_IFREG | 0o644)])
        with self.assertRaises(ValueError):
            receive.zip_members(raw)

    def test_prefix_trailer_crc_and_local_name_corruption_refuse(self):
        raw = archive([("known.json", b"fixture-body", stat.S_IFREG | 0o644)])
        for altered in (b"junk" + raw, raw + b"junk", raw.replace(b"fixture-body", b"fixture-BODY", 1),
                        raw.replace(b"known.json", b"other.json", 1)):
            with self.subTest(size=len(altered)), self.assertRaises((ValueError, zipfile.BadZipFile)):
                receive.zip_members(altered)

    def test_orphan_directory_and_file_parent_collision_refuse(self):
        for rows in [[("empty/", b"", stat.S_IFDIR | 0o755), ("ok.txt", b"x", stat.S_IFREG | 0o644)],
                     [("dist", b"x", stat.S_IFREG | 0o644), ("dist/file.js", b"x", stat.S_IFREG | 0o644)]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                receive.zip_members(archive(rows))

    def test_implicit_parent_casefold_and_file_kind_collisions_refuse_in_both_orders(self):
        for first, second in [("dist/A/x.js", "dist/a/y.js"), ("dist/A", "dist/a/y.js")]:
            for names in [(first, second), (second, first)]:
                with self.subTest(names=names), self.assertRaises(ValueError):
                    receive.zip_members(archive([(name, b"x", stat.S_IFREG | 0o644) for name in names]))

    def test_forced_zip64_is_a_documented_refusal_not_a_partial_decode(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as stream:
            info = zipfile.ZipInfo("small.json")
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            with stream.open(info, "w", force_zip64=True) as member:
                member.write(b"{}")
        with self.assertRaises(ValueError):
            receive.zip_members(data.getvalue())


class ApiTests(unittest.TestCase):
    def test_finite_exact_profile_passes(self):
        s = selected()
        api, _, _, _ = api_fixture(s)
        result = receive.snapshot(api, s, "dependency-candidate")
        self.assertEqual(result["jobs"][0]["id"], 200)

    def test_current_run_retry_fail_skip_source_and_artifact_drift_fail(self):
        cases = [("run", "run_attempt", 2), ("run", "conclusion", "failure"), ("run", "head_sha", "b" * 40),
                 ("job", "labels", ["self-hosted"]), ("job", "conclusion", "skipped"),
                 ("artifact", "expired", True), ("artifact", "size_in_bytes", 601), ("artifact", "digest", "sha256:" + "b" * 64)]
        for target, key, value in cases:
            s = selected()
            api, run, job, artifact = api_fixture(s)
            {"run": run, "job": job, "artifact": artifact}[target][key] = value
            with self.subTest(target=target, key=key), self.assertRaises(ValueError):
                receive.snapshot(api, s, "dependency-candidate")

    def test_required_step_skipped_is_not_a_pass(self):
        s = selected()
        api, _, job, _ = api_fixture(s)
        job["steps"][2]["conclusion"] = "skipped"
        with self.assertRaises(ValueError):
            receive.snapshot(api, s, "dependency-candidate")

    def test_storage_request_never_inherits_github_authorization(self):
        client = receive.GitHub("synthetic-test-token")
        seen = []
        class Opener:
            def open(self, request, timeout):
                seen.append(request)
                return None
        client.opener = Opener()
        client.response(f"https://api.github.com/repos/{receive.REPO}/actions/artifacts/1/zip", True)
        client.response("https://productionresultsfixture.blob.core.windows.net/archive?signature=fixture", False)
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer synthetic-test-token")
        self.assertIsNone(seen[1].get_header("Authorization"))
        for url in ("https://other.invalid/archive", "http://productionresultsfixture.blob.core.windows.net/archive",
                    "https://name:secret@productionresultsfixture.blob.core.windows.net/archive"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.response(url, False)

    def test_list_census_rejects_missing_and_duplicate_rows(self):
        for rows, total in [([{"id": 1}], 2), ([{"id": 1}, {"id": 1}], 2)]:
            client = receive.GitHub("not-used")
            client.api = lambda tail: {"total_count": total, "jobs": rows}
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                client.listing("actions/runs/1/jobs", "jobs")


class PatchAndImportTests(unittest.TestCase):
    def simple_patch(self):
        before = {receive.PACKAGE: b'{"version":"1.0.0"}\n', receive.LOCK: b'{"lockfileVersion":3}\n'}
        after = {receive.PACKAGE: b'{"version":"2.0.0"}\n', receive.LOCK: b'{"lockfileVersion":3,"changed":true}\n'}
        sections = []
        for path in (receive.PACKAGE, receive.LOCK):
            sections.append(f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n"
                            + "-" + before[path].decode() + "+" + after[path].decode())
        return before, after, "".join(sections).encode()

    def test_real_temporary_git_accepts_the_exact_two_file_patch(self):
        before, after, raw = self.simple_patch()
        with tempfile.TemporaryDirectory(prefix="receiver-patch-positive-") as temporary:
            work = Path(temporary)
            admitted = receive.patch(work, before, after, raw)
            self.assertEqual(set(re.findall(rb"^diff --git a/(\S+) b/\S+$", admitted, re.M)),
                             {receive.PACKAGE.encode(), receive.LOCK.encode()})
            for path, expected in after.items():
                self.assertEqual((work / "patch-check" / path).read_bytes(), expected)

    def test_real_temporary_git_refuses_headerless_unified_addition_outside_frontend(self):
        before, after, raw = self.simple_patch()
        malicious = raw + b"--- /dev/null\n+++ b/outside.txt\n@@ -0,0 +1 @@\n+unrequested\n"
        receive.candidate_patch_paths(malicious)  # The original two-header precheck alone does not see this section.
        with tempfile.TemporaryDirectory(prefix="receiver-patch-negative-") as temporary:
            work = Path(temporary)
            with self.assertRaisesRegex(ValueError, "Patch result path/mode census differs"):
                receive.patch(work, before, after, malicious)
            # Prove the real Git application reached the full-result guard; the
            # unrequested effect stays inside this disposable scratch repository.
            self.assertEqual((work / "patch-check/outside.txt").read_bytes(), b"unrequested\n")

    def test_only_exact_candidate_patch_paths_without_mode_or_binary_headers(self):
        raw = (f"diff --git a/{receive.PACKAGE} b/{receive.PACKAGE}\n"
               f"diff --git a/{receive.LOCK} b/{receive.LOCK}\n").encode()
        receive.candidate_patch_paths(raw)  # Header admission only; real Git syntax/apply is a separate hosted step.
        for altered in (raw + b"new mode 120000\n", raw + b"GIT binary patch\n",
                        raw + b"diff --git a/extra b/extra\n", raw.replace(receive.PACKAGE.encode(), b"outside.json")):
            with self.subTest(raw=altered), self.assertRaises(ValueError):
                receive.candidate_patch_paths(altered)

    def test_post_import_checks_bytes_modes_and_complete_frontend_delta(self):
        s = selected() | {"profile": "post-import", "artifact_profile": "dependency-candidate", "import_commit": "4" * 40}
        before = {receive.PACKAGE: b"old-package", receive.LOCK: b"old-lock"}
        desired = {receive.PACKAGE: b"new-package", receive.LOCK: b"new-lock"}
        imported = dict(desired)
        modes = {p: {"mode": "100644", "blob": "5" * 40} for p in desired}
        changed = list(desired)
        def fake_git(root, *args, **kwargs):
            if args[0] == "rev-parse":
                return s["import_commit"].encode()
            if args[-1] == "webapp/frontend":
                return ("\0".join(changed) + "\0").encode()
            return ("\0".join(changed + ["docs/NOW.md"]) + "\0").encode()
        def fake_blob(root, sha, path):
            return (imported if sha == s["import_commit"] else before)[path]
        with patch.dict(os.environ, {"GITHUB_SHA": s["import_commit"]}), patch.object(receive, "git", fake_git), \
                patch.object(receive, "tree", lambda *args: modes), patch.object(receive, "blob", fake_blob):
            result = receive.post_import(None, s, "dependency-candidate", desired, {})
            self.assertIn("docs/NOW.md", result["all_repository_changed_paths"])
            imported[receive.LOCK] = b"different-lock"
            with self.assertRaisesRegex(ValueError, "Imported Git bytes"):
                receive.post_import(None, s, "dependency-candidate", desired, {})
            imported[receive.LOCK] = desired[receive.LOCK]
            changed.append("webapp/frontend/src/unrequested.ts")
            with self.assertRaisesRegex(ValueError, "change census"):
                receive.post_import(None, s, "dependency-candidate", desired, {})
            changed.pop()
            modes[receive.PACKAGE]["mode"] = "120000"
            with self.assertRaisesRegex(ValueError, "path/mode census"):
                receive.post_import(None, s, "dependency-candidate", desired, {})


class RealGitPostImportTests(unittest.TestCase):
    def git(self, root, *args):
        return receive.git(root, "-c", "user.name=Receiver Fixture", "-c", "user.email=receiver@example.invalid",
                           "-c", "commit.gpgsign=false", *args)

    def fixture(self, root, mutation=None):
        self.git(root, "init", "--quiet")
        self.git(root, "config", "core.autocrlf", "false")
        self.git(root, "config", "core.fileMode", "true")
        self.git(root, "config", "diff.renames", "true")
        prefix = receive.DIST
        old_topology = b"".join(f"export const topology{index} = {index};\n".encode() for index in range(100))
        old_graph = b"".join(f"export const graph{index} = {index};\n".encode() for index in range(100))
        before = {
            prefix + "index.html": b'<script src="assets/main-old.js"></script>\n',
            prefix + "assets/shell.css": b"body { color: black; }\n",
            prefix + "assets/topology-old.js": old_topology,
            prefix + "assets/graph-old.js": old_graph,
            prefix + "assets/main-old.js": b'const legacy = "' + b"A" * 2048 + b'";\n',
        }
        # Different repeated bytes alone did not keep Git at the intended two
        # renames. Make the new main larger than
        # twice EVERY old family member, excluding all such 50% rename pairs by
        # size while retaining the two deliberately high-similarity chunk pairs.
        new_main = b'const future = "' + b"Z" * (2 * max(map(len, before.values())) + 1) + b'";\n'
        self.assertTrue(all(len(new_main) > 2 * len(data) for data in before.values()),
                        "replacement main must be outside the 50% rename size bound for every old member")
        desired = {
            prefix + "index.html": b'<script src="assets/main-new.js"></script>\n',
            prefix + "assets/shell.css": before[prefix + "assets/shell.css"],
            prefix + "assets/topology-new.js": old_topology.replace(b"topology99 = 99", b"topology99 = 100"),
            prefix + "assets/graph-new.js": old_graph.replace(b"graph99 = 99", b"graph99 = 100"),
            prefix + "assets/main-new.js": new_main,
        }
        sources = {receive.PACKAGE: b'{"name":"fixture"}\n', receive.LOCK: b'{"packages":{}}\n',
                   "webapp/frontend/src/view.ts": b"export const fixture = true;\n",
                   ".github/scripts/frontend_build_handoff.py": b"# fixture processor input\n"}
        for path, data in (before | sources).items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.git(root, "add", "--all")
        self.git(root, "commit", "--quiet", "-m", "producer fixture")
        source = self.git(root, "rev-parse", "HEAD").decode().strip()
        for path in before:
            (root / path).unlink()
        for path, data in desired.items():
            (root / path).write_bytes(data)
        unrelated = "docs/line\nwith\ttab.md"
        (root / unrelated).parent.mkdir(parents=True)
        (root / unrelated).write_bytes(b"unrelated review note\n")
        if mutation == "extra-dist":
            (root / (prefix + "assets/extra.js")).write_bytes(b"unrequested\n")
        elif mutation == "leftover":
            (root / (prefix + "assets/topology-old.js")).write_bytes(old_topology)
        elif mutation == "changed-bytes":
            (root / (prefix + "assets/graph-new.js")).write_bytes(b"wrong admitted bytes\n")
        elif mutation == "mode":
            (root / (prefix + "assets/graph-new.js")).chmod(0o755)
        elif mutation == "extra-frontend":
            (root / "webapp/frontend/src/unrequested.ts").write_bytes(b"unrequested frontend source\n")
        elif mutation == "producer-input":
            (root / ".github/scripts/frontend_build_handoff.py").write_bytes(b"# changed processor input\n")
        self.git(root, "add", "--all")
        self.git(root, "commit", "--quiet", "-m", "import fixture")
        imported = self.git(root, "rev-parse", "HEAD").decode().strip()
        s = selected() | {"profile": "post-import", "artifact_profile": "frontend-dist", "source_sha": source,
                          "head_sha": source, "import_commit": imported}
        expected_changes = {path for path in before.keys() | desired.keys() if before.get(path) != desired.get(path)}
        return s, desired, sources, expected_changes, unrelated

    def test_actual_five_file_dist_import_counts_seven_paths_even_when_git_detects_two_renames(self):
        with tempfile.TemporaryDirectory(prefix="receiver-dist-renames-") as temporary:
            root = Path(temporary)
            s, desired, sources, expected_changes, unrelated = self.fixture(root)
            self.assertEqual(len(desired), 5)
            self.assertEqual(len(expected_changes), 7)
            rename_display = self.git(root, "diff", "--name-status", "-z", "--find-renames=50%",
                                      s["source_sha"], s["import_commit"], "--", "webapp/frontend")
            self.assertEqual(sum(re.fullmatch(rb"R[0-9]{3}", token) is not None for token in rename_display.split(b"\0")), 2)
            old_names = self.git(root, "diff", "--name-only", s["source_sha"], s["import_commit"], "--", "webapp/frontend")
            self.assertEqual(len(old_names.decode().splitlines()), 5, "the old display-based census must actually lose rename source paths")
            with patch.dict(os.environ, {"GITHUB_SHA": s["import_commit"]}):
                result = receive.post_import(root, s, "frontend-dist", desired, sources)
            self.assertEqual(result["frontend_changed_paths"], sorted(expected_changes))
            self.assertEqual(set(result["all_repository_changed_paths"]), expected_changes | {unrelated})
            self.assertEqual(len(result["all_repository_changed_paths"]), 8)
            self.assertIn("unrelated repository changes are not certified", result["scope"])

    def test_real_dist_import_still_refuses_extra_leftover_bytes_modes_and_source_drift(self):
        for mutation, refusal in (("extra-dist", "path/mode census"), ("leftover", "path/mode census"),
                                  ("changed-bytes", "Imported Git bytes"), ("mode", "path/mode census"),
                                  ("extra-frontend", "change census"), ("producer-input", "non-dist producer input")):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(prefix="receiver-dist-refusal-") as temporary:
                root = Path(temporary)
                s, desired, sources, _, _ = self.fixture(root, mutation)
                with patch.dict(os.environ, {"GITHUB_SHA": s["import_commit"]}), self.assertRaisesRegex(ValueError, refusal):
                    receive.post_import(root, s, "frontend-dist", desired, sources)

    def test_changed_path_decoder_refuses_incomplete_empty_and_duplicate_nul_frames(self):
        for raw in (b"one\n", b"one\0\0", b"one\0one\0"):
            with self.subTest(raw=raw), patch.object(receive, "git", return_value=raw), self.assertRaises(ValueError):
                receive.changed_git_paths(None, "before", "after")


class CommandReceiptTests(unittest.TestCase):
    def fixture(self):
        tool = {"node": "/opt/hostedtoolcache/node/24.19.0/x64/bin/node", "node_version": "v24.19.0",
                "npm_cli": "/opt/hostedtoolcache/node/24.19.0/x64/lib/node_modules/npm/bin/npm-cli.js", "npm_version": "11.17.0"}
        private = "/tmp/frontend-dependency-scratch-fixture"
        options = ["--registry=https://registry.npmjs.org/", "--userconfig=" + private + "/config/user.npmrc",
                   "--globalconfig=" + private + "/config/global.npmrc", "--cache=" + private + "/cache",
                   "--git=/usr/bin/false", "--engine-strict", "--ignore-scripts", "--audit=false", "--fund=false",
                   "--update-notifier=false", "--fetch-retries=0", "--fetch-timeout=30000"]
        rows = []
        for name, suffix in [("npm-version", ["--version"]), ("npm-lock-only", ["install", "--package-lock-only", "--ignore-scripts", "--no-audit",
                             "--no-fund", "--engine-strict", "--force=false", "--legacy-peer-deps=false", "--workspaces=false"])]:
            rows.append({"name": name, "argv": [tool["node"], tool["npm_cli"], *options, *suffix],
                         "exit_code": 0, "signal": None, "error": None})
        return rows, tool

    def test_genuine_shaped_exact_zero_exit_command_records_pass(self):
        rows, tool = self.fixture()
        receive.command_records(rows, tool)

    def test_false_exit_missing_and_extra_fields_are_refused(self):
        for index in (0, 1):
            for value in (False, True, "0", 0.0, None, 1):
                rows, tool = self.fixture()
                rows[index]["exit_code"] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                    receive.command_records(rows, tool)
            for key in ("name", "argv", "exit_code", "signal", "error"):
                rows, tool = self.fixture()
                del rows[index][key]
                with self.subTest(index=index, missing=key), self.assertRaises(ValueError):
                    receive.command_records(rows, tool)
            rows, tool = self.fixture()
            rows[index]["extra"] = "unreviewed"
            with self.subTest(index=index, extra=True), self.assertRaises(ValueError):
                receive.command_records(rows, tool)

    def test_wrong_types_census_options_and_private_path_relationship_are_refused(self):
        changes = [lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0])), lambda rows: rows.reverse(),
                   lambda rows: rows[0].update(argv="node npm --version"), lambda rows: rows[0]["argv"].append(False),
                   lambda rows: rows[0].update(signal="SIGTERM"), lambda rows: rows[0].update(error="failed"),
                   lambda rows: rows[0]["argv"].__setitem__(5, "--cache=/somewhere-else/cache"),
                   lambda rows: rows[1]["argv"].__setitem__(-2, "--legacy-peer-deps=true")]
        for mutate in changes:
            rows, tool = self.fixture()
            mutate(rows)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                receive.command_records(rows, tool)


class IndependentRegistryTests(unittest.TestCase):
    def test_matching_independently_selected_metadata_passes(self):
        selected_metadata = {"fixture": {"name": "fixture", "version": "1.0.0", "license": "MIT",
                                         "dist": {"integrity": "independently-selected-sri"}}}
        receive.independent_metadata_match(copy.deepcopy(selected_metadata), selected_metadata)

    def test_forged_selfconsistent_raw_summary_lock_triad_does_not_choose_its_own_expectation(self):
        original_sri = "sha512-" + base64.b64encode(bytes(64)).decode()
        forged_sri = "sha512-" + base64.b64encode(bytes([1]) * 64).decode()
        tarball = "https://registry.npmjs.org/fixture/-/fixture-1.0.0.tgz"
        official = {"fixture": {"name": "fixture", "version": "1.0.0", "license": "MIT", "engines": None,
                               "peerDependencies": {}, "peerDependenciesMeta": {}, "dependencies": {}, "optionalDependencies": {},
                               "dist": {"tarball": tarball, "integrity": original_sri}}}
        forged_raw = {"name": "fixture", "version": "1.0.0", "license": "MIT", "dist": {"tarball": tarball, "integrity": forged_sri}}
        forged_summary = copy.deepcopy(official)
        forged_summary["fixture"]["dist"]["integrity"] = forged_sri
        forged_lock = {"version": "1.0.0", "resolved": tarball, "license": "MIT", "integrity": forged_sri}
        self.assertEqual(forged_raw["dist"]["integrity"], forged_summary["fixture"]["dist"]["integrity"])
        self.assertEqual(forged_raw["dist"]["integrity"], forged_lock["integrity"])
        with self.assertRaisesRegex(ValueError, "independently selected official metadata"):
            receive.independent_metadata_match(forged_summary, official)


class RealBridgeManifestOrderTests(unittest.TestCase):
    def test_real_current_node_bridge_preserves_nonlexical_manifest_bytes(self):
        # These deliberately nonlexical keys model the actual committed manifest.
        # The JSON receiver -> Node boundary, not a mocked serializer, is exercised.
        before = {
            "name": "synthetic-frontend", "private": True, "version": "1.0.0", "type": "module",
            "description": "Synthetic bridge — ordering control", "engines": {"node": ">=24.18.0 <25"},
            "scripts": {"z-last": "unchanged-z", "a-first": "unchanged-a"},
            "dependencies": {"z-kept": "1.0.0", "changed-dep": "1.0.0"},
            "devDependencies": {"z-tool": "4.0.0", "a-tool": "1.0.0"},
        }
        plan = {"schema": "frontend-dependency-plan/1", "changes": [
            {"section": "dependencies", "name": "changed-dep", "from": "1.0.0", "to": "2.0.0", "version": "2.0.0"},
        ]}
        sri = "sha512-" + base64.b64encode(bytes([3]) * 64).decode()
        def row(name, version):
            return {"version": version, "resolved": f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz",
                    "integrity": sri, "license": "MIT"}
        before_lock = {"name": before["name"], "version": before["version"], "lockfileVersion": 3, "requires": True,
                       "packages": {"": {"name": before["name"], "version": before["version"], "engines": before["engines"],
                                          "dependencies": before["dependencies"], "devDependencies": before["devDependencies"]}}}
        for section in ("dependencies", "devDependencies"):
            for name, version in before[section].items():
                before_lock["packages"]["node_modules/" + name] = row(name, version)
        wanted = copy.deepcopy(before)
        wanted["dependencies"]["changed-dep"] = "2.0.0"
        candidate_lock = copy.deepcopy(before_lock)
        candidate_lock["packages"][""]["dependencies"] = wanted["dependencies"]
        candidate_lock["packages"]["node_modules/changed-dep"] = row("changed-dep", "2.0.0")
        metadata = {"name": "changed-dep", "version": "2.0.0", "license": "MIT",
                    "dist": {"tarball": candidate_lock["packages"]["node_modules/changed-dep"]["resolved"], "integrity": sri}}
        payload = {"mode": "candidate", "plan": plan, "before_manifest": before, "before_lock": before_lock,
                   "candidate_manifest": wanted, "candidate_lock": candidate_lock, "metadata": [metadata]}
        expected = (json.dumps(wanted, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="receiver-real-bridge-order-") as directory:
            work = Path(directory)
            actual = receive.bridge(root, work, "original-order", payload)
            self.assertEqual(actual["manifest_text"].encode("utf-8"), expected,
                             "The real bridge must preserve original nonlexical root and nested manifest order")
            # Sorting just the original manifest recreates the lost information.
            # Policy equality still accepts the same values, but exact bytes must differ.
            sorted_control = copy.deepcopy(payload)
            sorted_control["before_manifest"] = json.loads(json.dumps(before, sort_keys=True))
            reordered = receive.bridge(root, work, "sorted-order-control", sorted_control)
            self.assertNotEqual(reordered["manifest_text"].encode("utf-8"), expected)


class DistTests(unittest.TestCase):
    def fixture(self):
        s = selected()
        s["profile"] = "frontend-dist"
        expect = {"commit": s["source_sha"], "tree": "2" * 40, "inputs": {"webapp/frontend/package.json": {"sha256": "c" * 64}}}
        source = receive.source_record(expect)
        data = b"<html>fixture</html>"
        record = {"schema": "frontend_build_handoff/1", "source": source, "members": {"index.html": {"bytes": len(data), "sha256": receive.digest(data)}},
                  "github_head": s["head_sha"], "run_id": "100", "run_attempt": "1", "node": "v24.19.0", "npm": s["npm_version"],
                  "status": "GENERATED_INPUT_FOR_REVIEW_ONLY", "release_authority": False, "final_source_rebuild_required": True}
        files = {"source-before.json": json.dumps(source).encode(), "handoff.json": json.dumps(record).encode(), "dist/index.html": data}
        return s, expect, record, files

    def test_exact_nonpromoting_dist_is_edit_data(self):
        s, expect, _, files = self.fixture()
        desired, supplied = receive.dist(files, expect, s, lambda path: [])
        self.assertEqual(set(desired), {"webapp/frontend/dist/index.html"})
        self.assertIsNone(supplied)

    def test_source_tools_members_promotion_and_privacy_refuse(self):
        for key, value in [("github_head", "3" * 40), ("node", "v25.0.0"), ("npm", "11.0.0"), ("run_attempt", "2"),
                           ("release_authority", True), ("final_source_rebuild_required", False), ("status", "APPROVED")]:
            s, expect, report, files = self.fixture()
            report[key] = value
            files["handoff.json"] = json.dumps(report).encode()
            with self.subTest(key=key), self.assertRaises(ValueError):
                receive.dist(files, expect, s, lambda path: [])
        s, expect, _, files = self.fixture()
        with self.assertRaises(ValueError):
            receive.dist(files | {"dist/extra.js": b"x"}, expect, s, lambda path: [])
        with self.assertRaises(ValueError):
            receive.dist(files, expect, s, lambda path: [re.compile("fixture")])
        changed = copy.deepcopy(expect)
        changed["inputs"]["webapp/frontend/package.json"]["sha256"] = "d" * 64
        with self.assertRaises(ValueError):
            receive.dist(files, changed, s, lambda path: [])


class BoundMarkerPolicyTests(unittest.TestCase):
    def sources(self):
        root = Path(__file__).resolve().parents[2]
        data = {path: (root / path).read_bytes() for _, path in receive.MARKER_CLOSURE}
        return root, data, {path: receive.digest(raw) for path, raw in data.items()}

    def with_content(self, relative, content):
        s, expected, report, files = DistTests("test_exact_nonpromoting_dist_is_edit_data").fixture()
        files["dist/" + relative] = content
        report["members"][relative] = {"bytes": len(content), "sha256": receive.digest(content)}
        files["handoff.json"] = json.dumps(report).encode()
        return s, expected, files

    def test_actual_canonical_policy_keeps_all_patterns_and_only_the_existing_bare_alias_exception(self):
        root, sources, expected = self.sources()
        original_path = list(sys.path)
        with receive.bound_marker_policy(root, sources, expected) as policy:
            prefix = policy.__package__
            self.assertEqual(sys.modules[prefix].__path__, ())
            self.assertEqual(policy.PackIntegrityError.__module__, prefix + ".registry_integrity")
            self.assertEqual(policy.verify_retained_eol_source_chain.__module__, prefix + ".eoldb")
            full = policy._client_marker_patterns()
            self.assertEqual(len(full), 12)
            ordinary = policy._marker_patterns_for("webapp/frontend/dist/index.html")
            asset = policy._marker_patterns_for("webapp/frontend/dist/assets/index-Ab12.js")
            lookalike = policy._marker_patterns_for("webapp/frontend/dist/assets/nested/index-Ab12.js")
            self.assertEqual(len(ordinary), 12)
            self.assertEqual(len(lookalike), 12)
            self.assertEqual(len(asset), 11)
            self.assertTrue(any(pattern is policy._BARE_INITIALS_MARKER for pattern in ordinary))
            self.assertFalse(any(pattern is policy._BARE_INITIALS_MARKER for pattern in asset))
            initials = "a" + "j"
            alias = ("export { value as " + initials + " };").encode()
            s, expectation, files = self.with_content("assets/index-Ab12.js", alias)
            desired, _ = receive.dist(files, expectation, s, policy._marker_patterns_for)
            self.assertIn("webapp/frontend/dist/assets/index-Ab12.js", desired)
            # Marker-bearing probes are assembled from existing policy-owner fragments and
            # never printed or used as assertion messages/artifact payloads by this test.
            for name, content in (("index.html", ("<!-- " + initials + " -->").encode()),
                                  ("assets/nested/index-Ab12.js", alias),
                                  ("assets/index-Ab12.js", ("/* " + "syn" + "tys" + "-core */").encode())):
                s, expectation, files = self.with_content(name, content)
                with self.assertRaisesRegex(ValueError, "canonical marker"):
                    receive.dist(files, expectation, s, policy._marker_patterns_for)
        self.assertEqual(sys.path, original_path)
        self.assertFalse(any(name == prefix or name.startswith(prefix + ".") for name in sys.modules))

    def test_preloaded_canonical_modules_cannot_replace_or_suppress_admitted_policy(self):
        root, sources, expected = self.sources()
        keys = ["cisco_toolkit" + ("." + suffix if suffix else "") for suffix, _ in receive.MARKER_CLOSURE]
        missing = object()
        prior = {key: sys.modules.get(key, missing) for key in keys}
        fake = {key: types.ModuleType(key) for key in keys}
        called = []
        def permissive(_):
            called.append("unselected cached module")
            return ()
        fake["cisco_toolkit"].__path__ = ()
        fake["cisco_toolkit.distribution_verify"].__file__ = str(root / "cisco_toolkit/distribution_verify.py")
        fake["cisco_toolkit.distribution_verify"]._marker_patterns_for = permissive
        fake["cisco_toolkit.distribution_verify"]._client_marker_patterns = lambda: ()
        try:
            sys.modules.update(fake)
            with receive.bound_marker_policy(root, sources, expected) as policy:
                self.assertIsNot(policy, fake["cisco_toolkit.distribution_verify"])
                self.assertEqual(len(policy._marker_patterns_for("webapp/frontend/dist/index.html")), 12)
                self.assertEqual(policy.PackIntegrityError.__module__, policy.__package__ + ".registry_integrity")
            self.assertEqual(called, [])
            for key in keys:
                self.assertIs(sys.modules[key], fake[key])
        finally:
            for key, value in prior.items():
                if value is missing:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value

    def test_matching_poisoned_pycs_for_initializer_sibling_and_policy_are_never_executed(self):
        _, sources, expected = self.sources()
        for _, poisoned in receive.MARKER_CLOSURE:
            with self.subTest(member=poisoned), tempfile.TemporaryDirectory(prefix="marker-policy-pyc-") as directory:
                root = Path(directory)
                for path, data in sources.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                path = root / poisoned
                prefix = b"raise RuntimeError('unselected cached fixture')\n#"
                poison = prefix + b"x" * (len(sources[poisoned]) - len(prefix) - 1) + b"\n"
                self.assertEqual(len(poison), len(sources[poisoned]))
                path.write_bytes(poison)
                before = path.stat()
                py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
                path.write_bytes(sources[poisoned])
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                # Prove this is an accepted timestamp/size cache, not a vacuous invalid pyc.
                spec = importlib.util.spec_from_file_location("synthetic_marker_cache_control", path)
                cached = importlib.util.module_from_spec(spec)
                with self.assertRaisesRegex(RuntimeError, "unselected cached fixture"):
                    spec.loader.exec_module(cached)
                with receive.bound_marker_policy(root, sources, expected) as policy:
                    self.assertEqual(len(policy._client_marker_patterns()), 12)
                    self.assertEqual(len(policy._marker_patterns_for("webapp/frontend/dist/assets/app.js")), 11)

    def test_changed_or_missing_bound_sibling_refuses_without_fallback(self):
        root, sources, expected = self.sources()
        before = {name for name in sys.modules if name.startswith("_atlas_bound_marker_")}
        for path in expected:
            changed = dict(sources)
            changed[path] += b"\nraise RuntimeError('changed closure must not execute')\n"
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "closure bytes"):
                with receive.bound_marker_policy(root, changed, expected):
                    self.fail("changed source was admitted")
            missing = dict(sources)
            del missing[path]
            with self.subTest(missing=path), self.assertRaisesRegex(ValueError, "closure census"):
                with receive.bound_marker_policy(root, missing, expected):
                    self.fail("missing source used a fallback")
        self.assertEqual({name for name in sys.modules if name.startswith("_atlas_bound_marker_")}, before)

    def test_new_relative_or_canonical_import_fails_and_private_namespace_is_cleaned(self):
        root, sources, _ = self.sources()
        original_path = list(sys.path)
        for extra in (b"\nfrom .unadmitted import unexpected\n", b"\nimport cisco_toolkit.registry_integrity\n"):
            changed = dict(sources)
            changed["cisco_toolkit/eoldb.py"] += extra
            expected = {path: receive.digest(data) for path, data in changed.items()}
            before = {name for name in sys.modules if name.startswith("_atlas_bound_marker_")}
            with self.assertRaisesRegex(ValueError, "import"):
                with receive.bound_marker_policy(root, changed, expected):
                    self.fail("unselected project import was admitted")
            self.assertEqual({name for name in sys.modules if name.startswith("_atlas_bound_marker_")}, before)
        self.assertEqual(sys.path, original_path)

    def test_private_namespace_collision_preserves_the_preexisting_entry(self):
        root, sources, expected = self.sources()
        suffix = "f" * 32
        name = "_atlas_bound_marker_" + suffix
        previous = types.ModuleType(name)
        self.assertNotIn(name, sys.modules)
        sys.modules[name] = previous
        try:
            with patch.object(receive.uuid, "uuid4", return_value=types.SimpleNamespace(hex=suffix)), self.assertRaisesRegex(ValueError, "not fresh"):
                with receive.bound_marker_policy(root, sources, expected):
                    self.fail("occupied private namespace was admitted")
            self.assertIs(sys.modules[name], previous)
        finally:
            sys.modules.pop(name, None)

    def test_missing_direct_exports_and_policy_functions_refuse_without_getter_fallback(self):
        root, sources, _ = self.sources()
        for path, export, message in (
            ("cisco_toolkit/registry_integrity.py", "source_freshness", "relative export is missing"),
            ("cisco_toolkit/eoldb.py", "verify_retained_eol_source_chain", "relative export is missing"),
            ("cisco_toolkit/distribution_verify.py", "_marker_patterns_for", "Canonical marker functions are missing"),
            ("cisco_toolkit/distribution_verify.py", "_client_marker_patterns", "Canonical marker functions are missing"),
        ):
            changed = dict(sources)
            # A deliberate admitted-source fixture: if the old attribute-based
            # admission invokes this fallback, the distinct sentinel fails the
            # expected missing-direct-export refusal rather than passing silently.
            changed[path] += (
                f"\ndel {export}\n"
                "def __getattr__(name):\n"
                "    raise RuntimeError('missing export getter executed')\n"
            ).encode()
            expected = {member: receive.digest(data) for member, data in changed.items()}
            before = {name for name in sys.modules if name.startswith("_atlas_bound_marker_")}
            with self.subTest(member=path, export=export), self.assertRaisesRegex(ValueError, message):
                with receive.bound_marker_policy(root, changed, expected):
                    self.fail("missing direct export was admitted")
            self.assertEqual({name for name in sys.modules if name.startswith("_atlas_bound_marker_")}, before)


if __name__ == "__main__":
    unittest.main()
