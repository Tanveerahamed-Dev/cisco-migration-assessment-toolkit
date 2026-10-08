"""Pure data/IO refusal controls; execution is restricted to GitHub-hosted runners."""
from __future__ import annotations

import base64
from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.request
import zipfile
import zlib

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
    raise RuntimeError("jsonschema-rs observation tests require GitHub-hosted execution")

SOURCE = Path(__file__).resolve().parents[1] / ".github/scripts/observe_jsonschema_rs_wheel.py"
SPEC = importlib.util.spec_from_file_location("jsonschema_rs_observer_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


def files_fixture(license_present=True):
    # Synthetic wheel data, never imported; this sentinel would fail if executed.
    files = {
        "jsonschema_rs/__init__.py": b"raise RuntimeError('PACKAGE CODE MUST NOT EXECUTE')\n",
        "jsonschema_rs/jsonschema_rs.pyd": b"synthetic native bytes\x00\xff",
        observer.DIST_INFO + "METADATA": b"Metadata-Version: 2.4\nName: jsonschema_rs\nVersion: 0.58.5\nLicense: MIT\n\nFixture\n",
        observer.DIST_INFO + "WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp310-abi3-win_amd64\n\n",
        observer.DIST_INFO + "sboms/jsonschema-py.cyclonedx.json": b'{"bomFormat":"CycloneDX","specVersion":"1.5","components":[{"name":"synthetic-fixture"}]}\n',
    }
    if license_present:
        files[observer.DIST_INFO + "licenses/LICENSE"] = b"Synthetic license text; not upstream evidence.\n"
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, raw in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        writer.writerow([name, "sha256=" + digest, str(len(raw))])
    writer.writerow([observer.DIST_INFO + "RECORD", "", ""])
    files[observer.DIST_INFO + "RECORD"] = record.getvalue().encode()
    return files


class NonSeeking(io.BytesIO):
    def seek(self, *args):
        raise io.UnsupportedOperation("streamed fixture")


def wheel_fixture(files=None, method=zipfile.ZIP_DEFLATED, streamed=False, extra=()):
    output = NonSeeking() if streamed else io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=method, allowZip64=False) as archive:
        for name, raw, mode in [(name, raw, stat.S_IFREG | 0o644) for name, raw in (files if files is not None else files_fixture()).items()] + list(extra):
            info = zipfile.ZipInfo(name)
            info.compress_type = method
            info.external_attr = mode << 16
            archive.writestr(info, raw)
    return output.getvalue()


def metadata_fixture():
    return {"info": {"name": "jsonschema-rs", "version": "0.58.5"}, "urls": [{
        "filename": observer.FILENAME, "packagetype": "bdist_wheel", "yanked": False,
        "size": 6000000, "digests": {"sha256": observer.WHEEL_SHA256},
        "url": "https://files.pythonhosted.org/packages/aa/bb/cc/" + observer.FILENAME,
        "upload_time_iso_8601": "2026-10-02T21:51:00Z", "requires_python": ">=3.10",
    }]}


class SelectionTests(unittest.TestCase):
    def test_exact_public_target_selected_before_bytes(self):
        selected = observer.selected_distribution(metadata_fixture())
        self.assertEqual(selected["sha256"], observer.WHEEL_SHA256)
        self.assertEqual(selected["filename"], "jsonschema_rs-0.58.5-cp310-abi3-win_amd64.whl")

    def test_changed_target_identity_or_ambiguous_census_refused(self):
        for key, value in (("size", True), ("yanked", True), ("packagetype", "sdist"), ("digests", {"sha256": "0" * 64})):
            with self.subTest(key=key):
                metadata = metadata_fixture()
                metadata["urls"][0][key] = value
                with self.assertRaises(observer.Refused):
                    observer.selected_distribution(metadata)
        metadata = metadata_fixture()
        metadata["urls"].append(deepcopy(metadata["urls"][0]))
        with self.assertRaisesRegex(observer.Refused, "PYPI_TARGET_NOT_UNIQUE"):
            observer.selected_distribution(metadata)

    def test_foreign_credentialed_query_encoded_or_dot_paths_refused(self):
        for url in ("http://files.pythonhosted.org/packages/a/", "https://evil.example/packages/a/",
                    "https://user@files.pythonhosted.org/packages/a/", "https://files.pythonhosted.org/packages/../",
                    "https://files.pythonhosted.org/packages/%61/", "https://files.pythonhosted.org:443/packages/a/"):
            with self.subTest(url=url):
                metadata = metadata_fixture()
                metadata["urls"][0]["url"] = url + observer.FILENAME
                with self.assertRaises(observer.Refused):
                    observer.selected_distribution(metadata)
        with self.assertRaises(observer.Refused):
            observer.public_url(observer.METADATA_URL + "?token=synthetic", "pypi.org")

    def test_redirects_are_refused_and_request_has_no_authorization(self):
        with self.assertRaisesRegex(observer.Refused, "HTTP_REDIRECT_REFUSED"):
            observer.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example/")
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status, response.geturl.return_value = 200, observer.METADATA_URL
        response.headers, response.read.return_value = {"Content-Length": "2"}, b"{}"
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(urllib.request, "build_opener", return_value=opener):
            self.assertEqual(observer.fetch(observer.METADATA_URL, "pypi.org", 10), b"{}")
        request = opener.open.call_args.args[0]
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(request.get_header("Accept-encoding"), "identity")


class WheelDataTests(unittest.TestCase):
    def test_valid_stored_deflated_and_streamed_data_preserve_complete_texts(self):
        for method, streamed in ((0, False), (8, False), (8, True)):
            with self.subTest(method=method, streamed=streamed):
                original = files_fixture()
                actual, inventory = observer.wheel_members(wheel_fixture(original, method, streamed))
                self.assertEqual(actual, original)
                self.assertEqual(len(inventory), len(original))
                evidence, selected = observer.wheel_evidence(actual)
                self.assertEqual(evidence["sbom"]["component_count"], 1)
                self.assertEqual(evidence["wheel_license_status"], "PRESENT_REVIEW_REQUIRED")
                self.assertIn(observer.DIST_INFO + "licenses/LICENSE", selected)
                self.assertIn(observer.DIST_INFO + "RECORD", selected)
                self.assertEqual(set(evidence["record_verified_members"]), set(original) - {observer.DIST_INFO + "RECORD"})

    def test_no_license_text_is_explicit_absence_not_fallback(self):
        evidence, selected = observer.wheel_evidence(files_fixture(False))
        self.assertEqual(evidence["wheel_license_status"], "ABSENT_REVIEW_REQUIRED")
        self.assertEqual(evidence["wheel_license_members"], [])
        self.assertEqual(set(selected), set(observer.REQUIRED))

    def test_wrong_name_version_platform_or_missing_sbom_refused(self):
        for member, old, new in (("METADATA", b"jsonschema_rs", b"other"), ("METADATA", b"0.58.5", b"0.58.4"),
                                 ("WHEEL", b"win_amd64", b"manylinux_x86_64")):
            with self.subTest(member=member, new=new):
                files = files_fixture()
                files[observer.DIST_INFO + member] = files[observer.DIST_INFO + member].replace(old, new)
                with self.assertRaises(observer.Refused):
                    observer.wheel_evidence(files)
        files = files_fixture()
        del files[observer.REQUIRED[-1]]
        with self.assertRaisesRegex(observer.Refused, "WHEEL_METADATA_MEMBER_MISSING"):
            observer.wheel_evidence(files)

    def test_record_must_bind_even_unemitted_native_member_and_complete_census(self):
        files = files_fixture()
        files["jsonschema_rs/jsonschema_rs.pyd"] = b"tampered native data!\x00\xff"
        with self.assertRaises(observer.Refused):
            observer.wheel_evidence(files)
        files = files_fixture()
        files["jsonschema_rs/unrecorded.txt"] = b"not in RECORD"
        with self.assertRaisesRegex(observer.Refused, "WHEEL_RECORD_CENSUS"):
            observer.wheel_evidence(files)

    def test_record_self_digest_and_duplicate_rows_are_refused(self):
        files = files_fixture()
        files[observer.REQUIRED[2]] = files[observer.REQUIRED[2]].replace(b"RECORD,,", b"RECORD,sha256=forged,0")
        with self.assertRaises(observer.Refused):
            observer.wheel_evidence(files)
        files = files_fixture()
        files[observer.REQUIRED[2]] += files[observer.REQUIRED[2]].splitlines(keepends=True)[0]
        with self.assertRaisesRegex(observer.Refused, "WHEEL_RECORD_ROW"):
            observer.wheel_evidence(files)

    def test_path_escape_prefix_case_collisions_and_symlinks_refused(self):
        cases = [(("../outside", b"x", stat.S_IFREG | 0o644),),
                 (("jsonschema_rs/A/x", b"x", stat.S_IFREG | 0o644), ("jsonschema_rs/a/y", b"y", stat.S_IFREG | 0o644)),
                 (("jsonschema_rs/link", b"target", stat.S_IFLNK | 0o777),)]
        for extra in cases:
            with self.subTest(extra=extra):
                with self.assertRaises(observer.Refused):
                    observer.wheel_members(wheel_fixture(extra=extra))

    def test_stored_underreported_size_cannot_hide_suffix(self):
        # Actual local+central declared size/CRC agree on 'a', compressed span still 'ab'.
        raw = bytearray(wheel_fixture({"jsonschema_rs/data": b"ab"}, 0))
        central = raw.index(b"PK\x01\x02")
        struct.pack_into("<I", raw, 14, zlib.crc32(b"a"))
        struct.pack_into("<I", raw, 22, 1)
        struct.pack_into("<I", raw, central + 16, zlib.crc32(b"a"))
        struct.pack_into("<I", raw, central + 24, 1)
        with self.assertRaisesRegex(observer.Refused, "ZIP_STORED_SIZE"):
            observer.wheel_members(bytes(raw))

    def test_deflate_actual_stream_closure_not_declared_eof(self):
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        span = compressor.compress(b"ab") + compressor.flush()
        for candidate, size in ((span, 1), (span[:-1], 2), (span + span, 2), (span + b"tail", 2)):
            with self.subTest(size=size, candidate=candidate):
                with self.assertRaises(observer.Refused):
                    observer.expanded(candidate, 8, size, zlib.crc32(b"ab"[:size]))
        self.assertEqual(observer.expanded(span, 8, 2, zlib.crc32(b"ab")), b"ab")

    def test_empty_members_and_directories_are_data_only(self):
        files, inventory = observer.wheel_members(wheel_fixture({"jsonschema_rs/empty": b""}, extra=(("jsonschema_rs/dir/", b"", stat.S_IFDIR | 0o755),)))
        self.assertEqual(files, {"jsonschema_rs/empty": b""})
        self.assertEqual(inventory[-1]["kind"], "directory")

    def test_limits_crc_trailing_data_and_strict_json_are_refused(self):
        raw = wheel_fixture({"jsonschema_rs/data": b"abc"}, 0)
        with mock.patch.object(observer, "MAX_TOTAL", 2), self.assertRaises(observer.Refused):
            observer.wheel_members(raw)
        changed = bytearray(raw)
        changed[30 + len("jsonschema_rs/data")] ^= 1
        with self.assertRaises(observer.Refused):
            observer.wheel_members(bytes(changed))
        with self.assertRaises(observer.Refused):
            observer.wheel_members(raw + b"trailing")
        for body in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.subTest(body=body), self.assertRaises(observer.Refused):
                observer.json_data(body)


class SourceAndOutputTests(unittest.TestCase):
    def test_selected_git_bytes_refuse_hidden_modified_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            def git(*args):
                result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
                return result.stdout.decode().strip()
            git("init", "-q")
            git("config", "user.name", "Hosted fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "core.autocrlf", "false")
            hooks = root / "empty-hooks"
            hooks.mkdir()
            for name in observer.INPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic source\n")
            git("add", ".")
            git("-c", f"core.hooksPath={hooks.as_posix()}", "commit", "-qm", "synthetic observation fixture")
            commit = git("rev-parse", "HEAD")
            with mock.patch.dict(os.environ, {"EXPECTED_SOURCE_COMMIT": commit, "GITHUB_SHA": commit}):
                identity = observer.source_identity(root)
                self.assertEqual(set(identity["inputs"]), set(observer.INPUTS))
                git("update-index", "--assume-unchanged", observer.SELF)
                (root / observer.SELF).write_bytes(b"hidden changed source\n")
                with self.assertRaisesRegex(observer.Refused, "SOURCE_INPUT_DIFFERS_FROM_GIT"):
                    observer.source_identity(root)

    def test_output_is_exclusive_and_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "evidence.json"
            observer.write_new(path, b"{}")
            with self.assertRaises(FileExistsError):
                observer.write_new(path, b"replacement")
            self.assertEqual(path.read_bytes(), b"{}")
            with mock.patch.object(observer, "MAX_JSON", 1), self.assertRaises(observer.Refused):
                observer.write_new(path.with_name("too-big.json"), b"{}")

    def test_runtime_refuses_local_and_nonmanual_contexts_before_network(self):
        for changed in ({"GITHUB_ACTIONS": "false"}, {"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_JOB": "other"}):
            env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
                   "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_JOB": "frontend", **changed}
            with mock.patch.dict(os.environ, env), mock.patch.object(observer, "fetch") as fetch:
                with self.assertRaisesRegex(observer.Refused, "HOSTED_MANUAL_OBSERVER_ONLY"):
                    observer.main()
                fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
