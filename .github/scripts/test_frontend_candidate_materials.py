"""Pure hosted controls for candidate materials; no npm or JavaScript package execution."""
import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import subprocess
import tempfile
import unittest
from unittest.mock import patch

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
    raise RuntimeError("Candidate-material tests run only on GitHub-hosted runners")

spec = importlib.util.spec_from_file_location("candidate_materials", Path(__file__).with_name("frontend_candidate_materials.py"))
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)
ROOT = Path(__file__).resolve().parents[2]
SRI = "sha512-" + base64.b64encode(bytes(64)).decode()


class CarrierOwnerTests(unittest.TestCase):
    def test_owner_map_is_read_as_data_without_executing_pipeline(self):
        source = ("raise RuntimeError('pipeline must not execute')\n"
                  + "_VITE_BUNDLED_BRACES_REVIEWED = {" + repr(subject.VERSION) + ": " + repr(SRI) + "}\n").encode()
        self.assertEqual(subject.reviewed_carriers(source), {subject.VERSION: SRI})

    def test_missing_duplicate_or_computed_carrier_facts_refuse(self):
        for source in ["_VITE_BUNDLED_BRACES_REVIEWED = {}",
                       "_VITE_BUNDLED_BRACES_REVIEWED = dict()",
                       f"_VITE_BUNDLED_BRACES_REVIEWED = {{{subject.VERSION!r}: {SRI!r}, {subject.VERSION!r}: {SRI!r}}}",
                       f"_VITE_BUNDLED_BRACES_REVIEWED = {{{subject.VERSION!r}: 'sha512-short'}}",
                       f"_VITE_BUNDLED_BRACES_REVIEWED = {{{subject.VERSION!r}: {SRI!r}}}\n_VITE_BUNDLED_BRACES_REVIEWED: dict = {{}}",
                       f"_VITE_BUNDLED_BRACES_REVIEWED = {{{subject.VERSION!r}: {SRI!r}}}\n_VITE_BUNDLED_BRACES_REVIEWED = {{}}"]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                subject.reviewed_carriers(source.encode())

    def test_current_literal_and_owned_read_only_get_shape_passes(self):
        source = (f"_VITE_BUNDLED_BRACES_REVIEWED = {{{subject.VERSION!r}: {SRI!r}}}\n"
                  "def _vite_bundled_braces_carriers(components):\n"
                  "    version = components[0]\n"
                  "    return _VITE_BUNDLED_BRACES_REVIEWED.get(version)\n")
        self.assertEqual(subject.reviewed_carriers(source.encode()), {subject.VERSION: SRI})

    def test_mutation_attribute_subscript_delete_and_alias_escapes_refuse(self):
        declaration = f"_VITE_BUNDLED_BRACES_REVIEWED = {{{subject.VERSION!r}: {SRI!r}}}\n"
        for use in ["_VITE_BUNDLED_BRACES_REVIEWED['8.2.4'] = 'changed'",
                    "del _VITE_BUNDLED_BRACES_REVIEWED['8.2.4']",
                    "_VITE_BUNDLED_BRACES_REVIEWED.get = lambda v: 'changed'",
                    "_VITE_BUNDLED_BRACES_REVIEWED.update({'8.2.4': 'changed'})",
                    "_VITE_BUNDLED_BRACES_REVIEWED.clear()",
                    "alias = _VITE_BUNDLED_BRACES_REVIEWED\nalias['8.2.4'] = 'changed'",
                    "getter = _VITE_BUNDLED_BRACES_REVIEWED.get",
                    "escaped = [_VITE_BUNDLED_BRACES_REVIEWED]",
                    "value = _VITE_BUNDLED_BRACES_REVIEWED.get('8.2.4')",
                    "escaped = globals()['_VITE_BUNDLED_BRACES_REVIEWED']"]:
            with self.subTest(use=use), self.assertRaises(ValueError):
                subject.reviewed_carriers((declaration + use + "\n").encode())


class BoundOwnerExecutionTests(unittest.TestCase):
    def test_matching_poisoned_pyc_cannot_replace_admitted_source_bytes(self):
        admitted = b"VALUE = 'admitted'\n"
        poison = b"VALUE = 'poisoned'\n"
        self.assertEqual(len(admitted), len(poison))
        with tempfile.TemporaryDirectory(prefix="candidate-owner-pyc-") as directory:
            path = Path(directory) / "owner.py"
            path.write_bytes(poison)
            before = path.stat()
            py_compile.compile(str(path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            path.write_bytes(admitted)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            # Genuine matched-cache control: the old loading mechanism chooses poisoned bytecode.
            cached_spec = importlib.util.spec_from_file_location("synthetic_cached_owner", path)
            cached = importlib.util.module_from_spec(cached_spec)
            cached_spec.loader.exec_module(cached)
            self.assertEqual(cached.VALUE, "poisoned")
            actual = subject.load_inventory_owner(admitted, path)
            self.assertEqual(actual.VALUE, "admitted")
            self.assertEqual(path.read_bytes(), admitted)

    def test_loader_requires_bounded_bytes_not_a_mutable_or_path_selected_program(self):
        for value in ("VALUE=1", bytearray(b"VALUE=1"), Path("/tmp/owner.py")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                subject.load_inventory_owner(value, Path("/tmp/owner.py"))
        with patch.object(subject, "MAX_FILE", 2), self.assertRaises(ValueError):
            subject.load_inventory_owner(b"VALUE=1", Path("/tmp/owner.py"))


class InstalledIdentityTests(unittest.TestCase):
    def fixture(self):
        manifest = {"devDependencies": {"vite": subject.VERSION}}
        row = {"version": subject.VERSION, "resolved": f"https://registry.npmjs.org/vite/-/vite-{subject.VERSION}.tgz",
               "integrity": SRI, "license": "MIT"}
        lock = {"lockfileVersion": 3, "packages": {"": {"devDependencies": {"vite": subject.VERSION}}, "node_modules/vite": row}}
        installed = {"name": "vite", "version": subject.VERSION, "license": "MIT"}
        observed = {name: {"bytes": 10, "sha256": sha} for name, sha in subject.REVIEWED_MEMBERS.items()}
        return manifest, lock, installed, observed, {subject.VERSION: SRI}

    def test_correct_map_lock_identity_and_selected_full_file_digests_join(self):
        subject.validate_vite(*self.fixture())
        self.assertEqual(set(subject.REVIEWED_MEMBERS), {"dist/node/chunks/node.js", "LICENSE.md"})

    def test_version_sri_distribution_identity_and_each_byte_witness_refuse_drift(self):
        mutations = [lambda m, lock, p, rows, carriers: m["devDependencies"].update(vite="^8.2.4"),
                     lambda m, lock, p, rows, carriers: lock["packages"][""]["devDependencies"].update(vite="8.2.2"),
                     lambda m, lock, p, rows, carriers: lock["packages"]["node_modules/vite"].update(version="8.2.5"),
                     lambda m, lock, p, rows, carriers: lock["packages"]["node_modules/vite"].update(integrity="sha512-wrong"),
                     lambda m, lock, p, rows, carriers: lock["packages"]["node_modules/vite"].update(resolved="https://example.invalid/vite.tgz"),
                     lambda m, lock, p, rows, carriers: lock["packages"]["node_modules/vite"].update(link=True),
                     lambda m, lock, p, rows, carriers: p.update(version="8.2.2"),
                     lambda m, lock, p, rows, carriers: p.update(name="not-vite"),
                     lambda m, lock, p, rows, carriers: p.update(license="unreviewed"),
                     lambda m, lock, p, rows, carriers: carriers.clear(),
                     lambda m, lock, p, rows, carriers: rows["dist/node/chunks/node.js"].update(sha256="0" * 64),
                     lambda m, lock, p, rows, carriers: rows["LICENSE.md"].update(sha256="0" * 64),
                     lambda m, lock, p, rows, carriers: rows.update({"unrequested.js": {"sha256": "0" * 64}})]
        for mutate in mutations:
            values = self.fixture()
            mutate(*values)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                subject.validate_vite(*values)


class BoundedDataTests(unittest.TestCase):
    def test_ordinary_bytes_are_read_without_executing_javascript(self):
        with tempfile.TemporaryDirectory(prefix="candidate-material-bytes-") as directory:
            path = Path(directory) / "node.js"
            raw = b"throw new Error('data-only fixture must not execute');\n"
            path.write_bytes(raw)
            self.assertEqual(subject.ordinary(path), raw)

    def test_links_nonregular_shared_and_oversized_files_refuse(self):
        with tempfile.TemporaryDirectory(prefix="candidate-material-refusals-") as directory:
            root = Path(directory)
            source = root / "ordinary"
            source.write_bytes(b"fixture")
            link = root / "link"
            link.symlink_to(source)
            with self.assertRaises(ValueError):
                subject.ordinary(link)
            with self.assertRaises(ValueError):
                subject.ordinary(root)
            with patch.object(subject, "MAX_FILE", 2), self.assertRaises(ValueError):
                subject.ordinary(source)
            hardlink = root / "hardlink"
            os.link(source, hardlink)
            with self.assertRaises(ValueError):
                subject.ordinary(source)

    def test_json_duplicate_and_nonfinite_values_refuse(self):
        for raw in (b'{"version":"one","version":"two"}', b'{"value":NaN}', b'{"value":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                subject.strict_json(raw)


class CanonicalInventoryTests(unittest.TestCase):
    def owner(self):
        path = ROOT / "portable/release_contract.py"
        return subject.load_inventory_owner(subject.ordinary(path), path)

    def test_full_inventory_and_digest_are_delegated_to_existing_owner(self):
        owner = self.owner()
        lock = {"lockfileVersion": 3, "packages": {
            "": {"name": "synthetic"},
            "node_modules/z-runtime": {"version": "2.0.0", "license": "MIT", "integrity": SRI},
            "node_modules/a-runtime": {"version": "1.0.0", "license": "MIT", "integrity": SRI},
            "node_modules/a-runtime/node_modules/z-runtime": {"version": "1.0.0", "license": "MIT", "integrity": SRI},
            "node_modules/test-only": {"version": "1.0.0", "dev": True, "license": "MIT", "integrity": SRI},
        }}
        original = copy.deepcopy(lock)
        with tempfile.TemporaryDirectory(prefix="candidate-material-inventory-") as directory:
            root = Path(directory)
            path = root / "webapp/frontend/package-lock.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(lock), encoding="utf-8")
            admitted = path.read_bytes()
            with patch.object(owner, "_bundled_frontend_packages", wraps=owner._bundled_frontend_packages) as rows_call, \
                    patch.object(owner, "digest_object", wraps=owner.digest_object) as digest_call:
                result = subject.observe_inventory(owner, admitted, root)
                rows_call.assert_called_once()
                private_root = rows_call.call_args.args[0]
                self.assertNotEqual(private_root, root)
                self.assertTrue(private_root.is_relative_to(root))
                self.assertEqual((private_root / subject.LOCK).read_bytes(), admitted)
                digest_call.assert_called_once_with(result["rows"])
            self.assertEqual(result["count"], 3)
            self.assertEqual([row["install_path"] for row in result["rows"]],
                             ["node_modules/a-runtime", "node_modules/a-runtime/node_modules/z-runtime", "node_modules/z-runtime"])
            self.assertEqual(result["digest"], owner.digest_object(result["rows"]))
            self.assertFalse(result["matches_current_reviewed_pin"])
            self.assertIn("remain blocking", result["pin_disposition"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_changed_worktree_lock_after_admission_cannot_change_inventory_snapshot(self):
        owner = self.owner()
        original = {"packages": {"node_modules/kept": {"version": "1.0.0", "license": "MIT", "integrity": SRI}}}
        changed = {"packages": {"node_modules/replaced": {"version": "9.0.0", "license": "MIT", "integrity": SRI}}}
        with tempfile.TemporaryDirectory(prefix="candidate-bound-lock-") as directory:
            root = Path(directory)
            live = root / "checkout" / subject.LOCK
            live.parent.mkdir(parents=True)
            live.write_text(json.dumps(original), encoding="utf-8")
            admitted = subject.ordinary(live)
            live.write_text(json.dumps(changed), encoding="utf-8")
            observation = subject.observe_inventory(owner, admitted, root)
            self.assertEqual([row["name"] for row in observation["rows"]], ["kept"])
            self.assertEqual(observation["admitted_lock_copy"]["sha256"], subject.sha(admitted))
            self.assertEqual(json.loads(live.read_text(encoding="utf-8")), changed)

    def test_private_copy_changed_during_owner_read_is_refused(self):
        owner = self.owner()
        admitted = b'{"packages":{"node_modules/kept":{"version":"1.0.0"}}}'
        project = owner._bundled_frontend_packages
        def tamper(root):
            rows = project(root)
            path = root / subject.LOCK
            path.chmod(0o600)
            path.write_bytes(b'{"packages":{}}')
            return rows
        with tempfile.TemporaryDirectory(prefix="candidate-copy-drift-") as directory, \
                patch.object(owner, "_bundled_frontend_packages", side_effect=tamper), self.assertRaisesRegex(ValueError, "copy changed"):
            subject.observe_inventory(owner, admitted, Path(directory))


class RealGitSourceBindingTests(unittest.TestCase):
    def git(self, root, *arguments):
        return subprocess.check_output(["git", "-C", str(root), "-c", "core.hooksPath=/dev/null", *arguments], text=True).strip()

    def test_real_clean_source_wrong_sha_and_live_drift_controls(self):
        with tempfile.TemporaryDirectory(prefix="candidate-source-binding-") as directory:
            root = Path(directory)
            self.git(root, "init", "--quiet")
            self.git(root, "config", "core.autocrlf", "false")
            for name in subject.INPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic tracked input\n", encoding="utf-8")
            self.git(root, "add", "--all")
            self.git(root, "-c", "user.name=Source Fixture", "-c", "user.email=source-fixture@example.invalid", "commit", "-qm", "fixture")
            head = self.git(root, "rev-parse", "HEAD")
            record, inputs = subject.source_identity(root, head)
            self.assertEqual(record["commit"], head)
            self.assertEqual(set(inputs), set(subject.INPUTS))
            with self.assertRaisesRegex(ValueError, "exact source"):
                subject.source_identity(root, "0" * 40)
            (root / subject.LOCK).write_text("changed after admission\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not clean"):
                subject.source_identity(root, head)
            self.assertEqual(inputs[subject.LOCK], b"synthetic tracked input\n")


if __name__ == "__main__":
    unittest.main()
