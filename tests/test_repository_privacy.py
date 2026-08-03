from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _privacy_module():
    path = ROOT / ".github" / "scripts" / "verify_repository_privacy.py"
    spec = importlib.util.spec_from_file_location("_repository_privacy", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "privacy@example.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Privacy Test"], cwd=tmp_path, check=True)
    denylist = (
        tmp_path / ".github" / "privacy" / "known_client_hostname_sha256.txt"
    )
    denylist.parent.mkdir(parents=True, exist_ok=True)
    denylist.write_text("0" * 64 + "\n", encoding="utf-8")
    data_dir = tmp_path / "cisco_toolkit" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    pack_payloads = {
        "oui_registry.tsv.gz": b"\x1f\x8b\x00oui-test",
        "port_registry.tsv.gz": b"\x1f\x8b\x00port-test",
    }
    packs = {}
    for name, payload in pack_payloads.items():
        (data_dir / name).write_bytes(payload)
        packs[name] = {
            "compressed_bytes": len(payload),
            "compressed_sha256": hashlib.sha256(payload).hexdigest(),
        }
    (data_dir / "registry_manifest.json").write_text(
        json.dumps({"packs": packs}),
        encoding="utf-8",
    )
    iana_header = [
        "Service Name",
        "Port Number",
        "Transport Protocol",
        "Description",
        "Assignee",
        "Contact",
        "Registration Date",
        "Modification Date",
        "Reference",
        "Service Code",
        "Unauthorized Use Reported",
        "Assignment Notes",
    ]
    ieee_header = [
        "Registry",
        "Assignment",
        "Organization Name",
        "Organization Address",
    ]
    official_inputs = {
        "iana-service-names-port-numbers": {
            "path": (
                "reference-data/official-sources/iana/"
                "service-names-port-numbers.csv"
            ),
            "url": (
                "https://www.iana.org/assignments/"
                "service-names-port-numbers/"
                "service-names-port-numbers.csv"
            ),
            "header": iana_header,
            "row": ["https", "443", "tcp"] + [""] * 9,
        },
        "ieee-ma-l": {
            "path": "reference-data/official-sources/ieee/oui.csv",
            "url": "https://standards-oui.ieee.org/oui/oui.csv",
            "header": ieee_header,
            "row": ["MA-L", "001122", "Al " + "Jazeera", "Example"],
        },
        "ieee-ma-m": {
            "path": "reference-data/official-sources/ieee/mam.csv",
            "url": "https://standards-oui.ieee.org/oui28/mam.csv",
            "header": ieee_header,
            "row": ["MA-M", "0011223", "Example M", "Example"],
        },
        "ieee-ma-s": {
            "path": "reference-data/official-sources/ieee/oui36.csv",
            "url": "https://standards-oui.ieee.org/oui36/oui36.csv",
            "header": ieee_header,
            "row": ["MA-S", "001122334", "Example S", "Example"],
        },
    }
    source_records = {}
    source_paths = []
    for source_id, contract in official_inputs.items():
        relative = contract["path"]
        source_path = tmp_path / relative
        source_path.parent.mkdir(parents=True, exist_ok=True)
        text = (
            ",".join(contract["header"])
            + "\n"
            + ",".join(contract["row"])
            + "\n"
        )
        payload = text.encode("utf-8")
        source_path.write_bytes(payload)
        source_records[source_id] = {
            "bytes": len(payload),
            "encoding": "utf-8",
            "expected_header": contract["header"],
            "expected_rows": 1,
            "media_type": "text/csv",
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "url": contract["url"],
        }
        source_paths.append(relative)
    eol_source_id = "cisco-eol-bulletin-semantic-fixture"
    retained_manifest = json.loads(
        (
            ROOT
            / "reference-data"
            / "official-sources"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    eol_record = retained_manifest["sources"][eol_source_id]
    eol_relative = eol_record["path"]
    eol_payload = (ROOT / eol_relative).read_bytes()
    eol_path = tmp_path / eol_relative
    eol_path.parent.mkdir(parents=True, exist_ok=True)
    eol_path.write_bytes(eol_payload)
    source_records[eol_source_id] = eol_record
    source_paths.append(eol_relative)
    source_manifest = (
        tmp_path / "reference-data" / "official-sources" / "manifest.json"
    )
    source_manifest.write_text(
        json.dumps({"schema_version": 1, "sources": source_records}),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "add",
            "--",
            ".github/privacy/known_client_hostname_sha256.txt",
            "cisco_toolkit/data/oui_registry.tsv.gz",
            "cisco_toolkit/data/port_registry.tsv.gz",
            "cisco_toolkit/data/registry_manifest.json",
            "reference-data/official-sources/manifest.json",
            *source_paths,
        ],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _track(root: Path, relative: str, text: str = "synthetic\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "--", relative], cwd=root, check=True)


def test_guard_rejects_engagement_paths_and_client_markers(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    _track(root, "private-inputs/client.json")
    _track(root, "docs/assessment/fleet.md")
    _track(root, "src/module.py", "# " + "Al " + "Jazeera" + " fleet\n")
    violations = module.inspect_tracked_tree(root)
    assert any("private-inputs/client.json" in item for item in violations)
    assert any("docs/assessment/fleet.md" in item for item in violations)
    assert any("src/module.py" in item and "client marker" in item for item in violations)


def test_guard_allows_reviewed_synthetic_snapshots_and_examples(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    _track(root, "tests/golden/snapshot.json", "{}\n")
    _track(root, "webapp/sample_data/sample_fleet.snapshot.json", "{}\n")
    _track(root, "requirements.sample.json", "{}\n")
    _track(root, "src/module.py", "# Meridian uses 192.0.2.10\n")
    assert module.inspect_tracked_tree(root) == []


def test_guard_rejects_other_snapshots_and_office_artifacts(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    _track(root, "output/client.snapshot.json", "{}\n")
    _track(root, "output/report.xlsx", "not really a workbook\n")
    violations = module.inspect_tracked_tree(root)
    assert any("client.snapshot.json" in item for item in violations)
    assert any("report.xlsx" in item for item in violations)


def test_guard_rejects_hashed_private_hostname_without_storing_it(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    private_hostname = "private-switch-01"
    digest = hashlib.sha256(private_hostname.encode("utf-8")).hexdigest()
    denylist = (
        root / ".github" / "privacy" / "known_client_hostname_sha256.txt"
    )
    denylist.write_text(digest + "\n", encoding="utf-8")
    _track(root, "src/module.py", f'HOST = "{private_hostname}"\n')

    violations = module.inspect_tracked_tree(root)

    assert private_hostname not in denylist.read_text(encoding="utf-8")
    assert any(
        "src/module.py" in item and "private hostname" in item
        for item in violations
    )


def test_guard_checks_commit_visible_untracked_files(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    path = root / "src" / "untracked.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + "Al " + "Jazeera" + " fleet\n", encoding="utf-8")

    violations = module.inspect_tracked_tree(root)

    assert any("src/untracked.py" in item for item in violations)


def test_guard_scans_staged_blob_when_worktree_copy_is_clean(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    path = root / "src" / "module.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + "Al " + "Jazeera" + " fleet\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "src/module.py"], cwd=root, check=True)
    path.write_text("# public synthetic fixture\n", encoding="utf-8")

    violations = module.inspect_tracked_tree(root)

    assert any(
        "src/module.py" in item and "indexed text" in item
        for item in violations
    )
    assert module.inspect_tracked_tree(root, include_index=False) == []


def test_guard_scans_index_blob_when_worktree_copy_is_deleted(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    path = root / "src" / "module.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + "Al " + "Jazeera" + " fleet\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "src/module.py"], cwd=root, check=True)
    path.unlink()

    violations = module.inspect_tracked_tree(root)

    assert any(
        "src/module.py" in item and "indexed text" in item
        for item in violations
    )


def test_guard_rejects_unapproved_binary_and_manifest_tampering(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    binary = root / "assets" / "evidence.png"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00private")
    subprocess.run(
        ["git", "add", "--", "assets/evidence.png"],
        cwd=root,
        check=True,
    )
    no_nul = root / "assets" / "opaque.bin"
    no_nul.write_bytes(b"\xff\xfe\xfdprivate-binary")
    subprocess.run(["git", "add", "--", "assets/opaque.bin"], cwd=root, check=True)

    violations = module.inspect_tracked_tree(root)

    assert any(
        "assets/evidence.png" in item and "not allowlisted" in item
        for item in violations
    )
    assert any(
        "assets/opaque.bin" in item and "not allowlisted" in item
        for item in violations
    )

    binary.unlink()
    pack = root / "cisco_toolkit" / "data" / "oui_registry.tsv.gz"
    pack.write_bytes(pack.read_bytes() + b"\x00tampered")
    violations = module.inspect_tracked_tree(root)
    assert any(
        "oui_registry.tsv.gz" in item and "manifest integrity" in item
        for item in violations
    )


def test_guard_allows_only_the_exact_manifest_bound_social_asset(tmp_path):
    module = _privacy_module()
    relative = "master-reference/public/og.png"
    payload = (ROOT / relative).read_bytes()

    module._validate_project_binary_asset(relative, payload)
    with pytest.raises(ValueError, match="exact manifest integrity"):
        module._validate_project_binary_asset(relative, payload[:-1])

    root = _repo(tmp_path)
    impostor = root / relative
    impostor.parent.mkdir(parents=True, exist_ok=True)
    impostor.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + (1730).to_bytes(4, "big")
        + (909).to_bytes(4, "big")
    )
    violations = module.inspect_tracked_tree(root, include_index=False)
    assert any(
        relative in item and "exact manifest integrity" in item
        for item in violations
    )


def test_guard_requires_exact_manifest_bound_official_public_sources(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    source = root / "reference-data" / "official-sources" / "ieee" / "oui.csv"

    assert module.inspect_tracked_tree(root) == []

    source.write_bytes(source.read_bytes() + b"MA-L,FFFFFF,Tampered,Example\n")
    violations = module.inspect_tracked_tree(root)
    assert any(
        "official source fails manifest integrity" in item
        for item in violations
    )


def test_guard_requires_exact_semantic_eol_fixture(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    source = (
        root
        / "reference-data"
        / "official-sources"
        / "cisco"
        / "eol-bulletins.json"
    )

    assert module.inspect_tracked_tree(root) == []

    source.write_bytes(source.read_bytes() + b"\n")
    violations = module.inspect_tracked_tree(root)
    assert any(
        "official source fails manifest integrity" in item
        for item in violations
    )


def test_guard_bounds_individual_and_aggregate_candidate_bytes(tmp_path, monkeypatch):
    module = _privacy_module()
    root = _repo(tmp_path)
    _track(root, "src/large.txt", "x" * 32)

    monkeypatch.setattr(module, "_MAX_TEXT_BYTES", 16)
    violations = module.inspect_tracked_tree(root)
    assert any(
        "src/large.txt" in item and "exceeds privacy-scan limit" in item
        for item in violations
    )

    monkeypatch.setattr(module, "_MAX_TEXT_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(module, "_MAX_CANDIDATE_BYTES", 1)
    violations = module.inspect_tracked_tree(root)
    assert any("aggregate privacy-scan limit" in item for item in violations)

    monkeypatch.setattr(module, "_MAX_CANDIDATE_BYTES", 512 * 1024 * 1024)
    monkeypatch.setattr(module, "_MAX_CANDIDATE_FILES", 1)
    violations = module.inspect_tracked_tree(root)
    assert any("file privacy-scan limit" in item for item in violations)


def test_bounded_reader_rejects_reparse_and_identity_changes(
    tmp_path, monkeypatch
):
    module = _privacy_module()
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("stable\n", encoding="utf-8")
    real_lstat = Path.lstat

    def copied(info, **changes):
        values = {
            "st_dev": info.st_dev,
            "st_ino": info.st_ino,
            "st_mode": info.st_mode,
            "st_size": info.st_size,
            "st_mtime_ns": info.st_mtime_ns,
            "st_file_attributes": getattr(info, "st_file_attributes", 0),
        }
        values.update(changes)
        return SimpleNamespace(**values)

    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "lstat",
            lambda path: (
                copied(
                    real_lstat(path),
                    st_file_attributes=module._REPARSE_POINT,
                )
                if path == candidate
                else real_lstat(path)
            ),
        )
        with pytest.raises(ValueError, match="regular non-link"):
            module._read_bounded(candidate, 1024)

    calls = 0

    def changed_after_read(path):
        nonlocal calls
        info = real_lstat(path)
        if path != candidate:
            return info
        calls += 1
        return copied(info, st_ino=info.st_ino + (calls > 1))

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", changed_after_read)
        with pytest.raises(ValueError, match="identity changed during"):
            module._read_bounded(candidate, 1024)


def test_guard_rejects_nonregular_git_entries(tmp_path):
    module = _privacy_module()
    root = _repo(tmp_path)
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=root,
        input=b"outside-target",
        capture_output=True,
        check=True,
    ).stdout.decode("ascii").strip()
    subprocess.run(
        [
            "git",
            "update-index",
            "--add",
            "--cacheinfo",
            f"120000,{blob},external-link",
        ],
        cwd=root,
        check=True,
    )

    violations = module.inspect_tracked_tree(root)

    assert any(
        "external-link" in item and "non-regular Git entry" in item
        for item in violations
    )


def test_repository_hostname_denylist_is_one_way_and_complete():
    denylist = (
        ROOT / ".github" / "privacy" / "known_client_hostname_sha256.txt"
    )
    values = [
        line.strip()
        for line in denylist.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(values) == 256  # 253 canonical names plus three observed variants.
    assert len(set(values)) == len(values)
    assert all(
        len(value) == 64 and set(value) <= set("0123456789abcdef")
        for value in values
    )


def test_the_two_client_marker_implementations_cannot_diverge():
    """There are TWO copies of this rule and only one got fixed.

    `.github/scripts/verify_repository_privacy.py` guards the repository;
    `cisco_toolkit/distribution_verify.py` guards the wheel and sdist that get UPLOADED. Both build
    their own `_client_marker_patterns()`. The `\b`-treats-underscore-as-a-word-character P0 was
    fixed in the repository gate and left in the release-facing copy, so the scanner standing
    between a client identifier and PyPI was the weaker of the pair -- measured: 7 spellings the
    repository gate flagged and the archive scanner missed.

    Pinned as a PARITY property rather than by re-asserting each pattern, because the defect is the
    divergence itself: any future fix applied to one copy and not the other fails here.
    """
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "_vrp_parity", root / ".github" / "scripts" / "verify_repository_privacy.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    from cisco_toolkit import distribution_verify

    gate_patterns = gate._client_marker_patterns()
    dist_patterns = distribution_verify._client_marker_patterns()
    assert len(gate_patterns) == len(dist_patterns), (
        f"the two marker sets have drifted in SIZE: repository gate has {len(gate_patterns)}, "
        f"distribution verifier has {len(dist_patterns)}")

    # Structural spellings, assembled from fragments so this file does not itself carry a marker.
    brand, short, initials = "al" + "jazeera", "a" + "jmn", "a" + "j"
    bid, side, user = "al" + "waj", "syn" + "tys", "jaj" + "ch"
    probes = [
        brand + "_dc_design", short + "_core01", initials + "_switch01",
        initials + "_vlan_plan", bid + "_bid", user + "_home", "_" + user,
        side + "_dc_design",
        "the " + brand + " report",                    # control: must flag on both
        "ordinary networking prose about ospf timers",  # control: must flag on neither
    ]
    for probe in probes:
        folded = probe.casefold()
        in_gate = any(p.search(folded) for p in gate_patterns)
        in_dist = any(p.search(folded) for p in dist_patterns)
        assert in_gate == in_dist, (
            f"marker divergence: repository gate={'FLAG' if in_gate else 'miss'} but "
            f"distribution verifier={'FLAG' if in_dist else 'miss'} for an underscore-glued "
            "identifier spelling")

    # Non-vacuity: the probe set must actually exercise the boundary, or parity is trivially true.
    assert any(p.search((brand + "_dc_design").casefold()) for p in gate_patterns), \
        "the probe set no longer reaches the underscore boundary this test exists to pin"
    assert not any(p.search("ordinary networking prose about ospf timers") for p in dist_patterns), \
        "the archive scanner now flags ordinary prose -- it became a blanket match"


def test_minified_bundle_carveout_silences_only_the_bare_initials_and_only_in_bundles():
    """Minified bundles emit alphabetical two-char export aliases, so a large enough public
    library bundle is structurally GUARANTEED to contain the bare initials as a generated
    identifier (first observed: three 0.185, 2026-08-03 -- `ah as X, ai as Y, <initials> as Z`).
    Both marker implementations therefore exclude EXACTLY that one pattern for built bundle
    assets, and nothing else, nowhere else. Pinned in both directions on both copies, because a
    carve-out is precisely where a real leak would hide if it grew wider than measured."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "_vrp_carveout", root / ".github" / "scripts" / "verify_repository_privacy.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    from cisco_toolkit import distribution_verify

    initials, side = "a" + "j", "syn" + "tys"
    bundle_alias_run = "ah as gn,ai as Mo," + initials + " as Po,ak as Kh"
    real_leak = "hostname " + side + "-core-01 collected"
    repo_bundle = "webapp/frontend/dist/assets/index-Ab12Cd34.js"
    sdist_bundle = "pkg-9.9.9/webapp/frontend/dist/assets/index-Ab12Cd34.js"
    prose_path = "docs/notes.md"

    gate_full = gate._client_marker_patterns()
    for label, patterns in (
        ("repository gate", gate._marker_patterns_for(repo_bundle, gate_full)),
        ("archive scanner", distribution_verify._marker_patterns_for(sdist_bundle)),
    ):
        # The alias run no longer flags in a bundle...
        assert not any(p.search(bundle_alias_run) for p in patterns), label
        # ...but a REAL marker in the same bundle still does (the carve-out is one pattern wide).
        assert any(p.search(real_leak) for p in patterns), (
            f"{label}: the bundle carve-out silenced more than the bare-initials pattern")
        # Exactly one pattern was removed.
        assert len(patterns) == len(gate_full) - 1, label

    # Outside bundle paths the bare pattern still fires, in both copies (non-vacuity).
    assert any(p.search(bundle_alias_run)
               for p in gate._marker_patterns_for(prose_path, gate_full)), \
        "the bare-initials pattern stopped firing on ordinary paths -- the carve-out leaked"
    assert any(p.search(bundle_alias_run)
               for p in distribution_verify._marker_patterns_for(prose_path)), \
        "the archive scanner's bare-initials pattern stopped firing on ordinary members"
    # And the path class is exact: a lookalike path outside dist/assets gets the full set.
    assert len(gate._marker_patterns_for("webapp/frontend/src/evil.js", gate_full)) == \
        len(gate_full)
