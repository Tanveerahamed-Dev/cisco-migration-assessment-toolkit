"""Pure hostile-input controls; execute only on GitHub-hosted runners."""
import base64
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
    raise RuntimeError("These observer tests run only on GitHub-hosted runners")

spec = importlib.util.spec_from_file_location("observer", Path(__file__).with_name("observe_vite_distribution.py"))
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def sri(raw):
    return "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()


BASE = [
    ("package/package.json", json.dumps({"name": "vite", "version": "8.2.4"}).encode(), tarfile.REGTYPE),
    ("package/dist/node/chunks/example.js", b"// synthetic fixture: braces.expand", tarfile.REGTYPE),
]


def archive(entries, suffix=b""):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data, kind in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.mode = 0o644
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = "../../escape"
            tar.addfile(member, io.BytesIO(data) if member.size else None)
    return gzip.compress(output.getvalue() + suffix)


def physical_header(raw, *, name=None, kind=None):
    data = bytearray(gzip.decompress(raw))
    if name is not None:
        data[:100] = name.ljust(100, b"\0")
    if kind is not None:
        data[156:157] = kind
    data[148:156] = b" " * 8
    data[148:156] = (f"{sum(data[:512]):06o}\0 ").encode()
    return gzip.compress(data)


class ObserverTests(unittest.TestCase):
    def test_positive_complete_bytes_and_census(self):
        raw = archive(BASE)
        files, rows = observer.inspect_tar(raw, sri(raw))
        self.assertEqual(files, {name: data for name, data, _ in BASE})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["sha256"], hashlib.sha256(BASE[1][1]).hexdigest())

    def test_positive_optional_directory_entry(self):
        raw = archive([("package/", b"", tarfile.DIRTYPE), *BASE])
        files, rows = observer.inspect_tar(raw, sri(raw))
        self.assertEqual(len(files), 2)
        self.assertEqual(len(rows), 3)

    def test_wrong_sri(self):
        raw = archive(BASE)
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            observer.inspect_tar(raw, sri(raw + b"changed"))

    def test_unsafe_paths(self):
        for name in ("/package/x", "C:/package/x", "package/../x", "package/./x", "other/x", "package/a\\b", "package/a\nb", "package//x"):
            with self.subTest(name=name):
                raw = archive([*BASE, (name, b"x", tarfile.REGTYPE)])
                with self.assertRaisesRegex(ValueError, "Unsafe TAR"):
                    observer.inspect_tar(raw, sri(raw))

    def test_duplicate_alias_and_implied_parent_alias(self):
        variants = [
            [("package/package.json", b"x", tarfile.REGTYPE)],
            [("package/PACKAGE.json", b"x", tarfile.REGTYPE)],
            [("package/A/x", b"x", tarfile.REGTYPE), ("package/a/y", b"y", tarfile.REGTYPE)],
        ]
        for extra in variants:
            with self.subTest(extra=extra):
                raw = archive([*BASE, *extra])
                with self.assertRaisesRegex(ValueError, "[Aa]lias"):
                    observer.inspect_tar(raw, sri(raw))

    def test_links_and_special_entries(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE):
            with self.subTest(kind=kind):
                raw = archive([*BASE, ("package/bad", b"", kind)])
                with self.assertRaisesRegex(ValueError, "Linked or special"):
                    observer.inspect_tar(raw, sri(raw))

    def test_physical_sparse_and_contiguous_types(self):
        for kind in (tarfile.GNUTYPE_SPARSE, tarfile.CONTTYPE, tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME):
            with self.subTest(kind=kind):
                # Deliberately no sparse map/extent payload: type refusal precedes parser normalization.
                raw = physical_header(archive(BASE), kind=kind)
                with self.assertRaisesRegex(ValueError, "Linked or special"):
                    observer.inspect_tar(raw, sri(raw))

    def test_physical_directory_alias_before_parser_normalization(self):
        raw = physical_header(archive([("package/", b"", tarfile.DIRTYPE), *BASE]), name=b"package//")
        with self.assertRaisesRegex(ValueError, "Noncanonical TAR directory"):
            observer.inspect_tar(raw, sri(raw))

    def test_windows_path_aliases(self):
        for name in ("package/CON.txt", "package/Lpt1", "package/a./x", "package/a /x"):
            with self.subTest(name=name):
                raw = archive([*BASE, (name, b"x", tarfile.REGTYPE)])
                with self.assertRaisesRegex(ValueError, "Windows TAR path alias"):
                    observer.inspect_tar(raw, sri(raw))

    def test_file_directory_collisions_both_orders(self):
        for extra in ([('package/a', b'x', tarfile.REGTYPE), ('package/a/x', b'x', tarfile.REGTYPE)],
                      [('package/a/x', b'x', tarfile.REGTYPE), ('package/a', b'x', tarfile.REGTYPE)]):
            raw = archive([*BASE, *extra])
            with self.assertRaisesRegex(ValueError, "(parent|descendants)"):
                observer.inspect_tar(raw, sri(raw))

    def test_missing_and_wrong_package_identity(self):
        raw = archive(BASE[1:])
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            observer.inspect_tar(raw, sri(raw))
        raw = archive([(BASE[0][0], b'{"name":"vite","version":"8.3.2"}', tarfile.REGTYPE), BASE[1]])
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            observer.inspect_tar(raw, sri(raw))

    def test_trailing_nonzero_data(self):
        raw = archive(BASE, b"unexpected")
        with self.assertRaisesRegex(ValueError, "Trailing or concatenated"):
            observer.inspect_tar(raw, sri(raw))

    def test_metadata_exact_selected_identity(self):
        expected = sri(b"selected bytes")
        value = {"name": "vite", "version": "8.2.4", "dist": {"tarball": observer.TARBALL, "integrity": expected}}
        self.assertEqual(observer.selected_metadata(json.dumps(value).encode(), expected), value)
        for key, replacement in (("tarball", "https://example.com/vite.tgz"), ("integrity", sri(b"other"))):
            changed = json.loads(json.dumps(value))
            changed["dist"][key] = replacement
            with self.assertRaisesRegex(ValueError, "selected lock identity"):
                observer.selected_metadata(json.dumps(changed).encode(), expected)

    def test_duplicate_json_and_nonfinite(self):
        for raw in (b'{"name":"vite","name":"other"}', b'{"a":1,"\\u0061":2}',
                    b'{"name":"vite","n":NaN}', b'{"n":1e999}', b'{"n":-1e999}'):
            with self.assertRaises(ValueError):
                observer.strict_json(raw)
        self.assertEqual(observer.strict_json(b'{"finite":1e2,"fraction":-1.25}'),
                         {"finite": 100.0, "fraction": -1.25})

    def test_integrity_format_and_archive_cap(self):
        with self.assertRaisesRegex(ValueError, "Noncanonical"):
            observer.checked_integrity("sha1-anything")
        original = observer.MAX_ARCHIVE
        try:
            observer.MAX_ARCHIVE = 1
            raw = archive(BASE)
            with self.assertRaisesRegex(ValueError, "Oversized archive"):
                observer.inspect_tar(raw, sri(raw))
        finally:
            observer.MAX_ARCHIVE = original

    def test_independent_expansion_member_and_entry_caps(self):
        raw = archive(BASE)
        cases = (("MAX_EXPANDED", 1, "TAR expansion"),
                 ("MAX_MEMBER", 1, "Oversized or nonempty"),
                 ("MAX_MEMBERS", 1, "Too many TAR entries"))
        for name, value, error in cases:
            with self.subTest(cap=name):
                original = getattr(observer, name)
                try:
                    setattr(observer, name, value)
                    with self.assertRaisesRegex(ValueError, error):
                        observer.inspect_tar(raw, sri(raw))
                finally:
                    setattr(observer, name, original)

    def test_truncated_archive_cannot_become_complete(self):
        raw = archive(BASE)[:-6]
        with self.assertRaises((EOFError, ValueError, OSError)):
            observer.inspect_tar(raw, sri(raw))

    def test_output_must_be_fresh_and_outside_checkout(self):
        with tempfile.TemporaryDirectory() as parent:
            base = Path(parent).resolve()
            root = base / "checkout"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            good = observer.output_path(str(outside), root)
            self.assertEqual(good, outside / "vite-distribution-observation")
            self.assertFalse(good.exists())
            inside = root / "temp"
            inside.mkdir()
            with self.assertRaisesRegex(ValueError, "outside checkout"):
                observer.output_path(str(inside), root)
            good.mkdir()
            with self.assertRaisesRegex(ValueError, "fresh"):
                observer.output_path(str(outside), root)
            linked = base / "alias"
            linked.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "ordinary absolute"):
                observer.output_path(str(linked), root)

    def test_redirect_refusal_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "redirect refused"):
            observer.NoRedirect().redirect_request(None, None, 302, None, None, "https://other.invalid/vite.tgz")

    def test_actual_git_source_identity_and_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            empty = root / "empty-template"
            empty.mkdir()
            def git(*arguments):
                return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *arguments])
            git("init", "--quiet", "--template=" + str(empty))
            script = root / ".github/scripts/observe_vite_distribution.py"
            script.parent.mkdir(parents=True)
            script.write_bytes(b"# explicit synthetic source fixture\n")
            git("add", "--", ".github/scripts/observe_vite_distribution.py")
            git("-c", "user.name=Observer fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "fixture")
            head = git("rev-parse", "HEAD").decode().strip()
            expected = observer.source_identity(root, head, script)
            self.assertEqual(expected[:2], (head, script.read_bytes()))
            with self.assertRaisesRegex(ValueError, "source mismatch"):
                observer.source_identity(root, "0" * 40, script)
            script.write_bytes(b"# changed fixture\n")
            with self.assertRaisesRegex(ValueError, "must be clean"):
                observer.source_identity(root, head, script)
            # An index stat shortcut must not turn different script bytes into an admitted source.
            git("update-index", "--assume-unchanged", ".github/scripts/observe_vite_distribution.py")
            with self.assertRaisesRegex(ValueError, "selected Git blob"):
                observer.source_identity(root, head, script)


if __name__ == "__main__":
    unittest.main()
