"""Raw-collection-dir secrets at rest (Plan A / Tier-1 #5).

The gap: --redact makes the DELIVERABLES share-safe but the raw collection dir (the
.txt captures, running-configs included) keeps every password / community / key in
CLEARTEXT on the consulting laptop, and nothing ever said so. This slice adds:
- redact_collection_dir(): opt-in IN-PLACE scrub of secret VALUES across the captures,
  reusing the same conservative _scrub_secrets deny-list (IPs / hostnames / MACs are
  KEPT so the dir stays analyzable and --compare-able; never auto-deleted);
- a loud [SENSITIVE] warning on every run naming the dir;
- --redact-collection CLI wiring (scrub runs AFTER analysis so the current run reads
  originals);
- devices.example.json + README making the password_env / $CISCO_PASS chain the
  documented default (the chain itself has existed since V3.23.1 — just unused)."""
import json
import os
import subprocess
import sys

import synthetic_fixtures as fx
from openpyxl import Workbook

from cisco_toolkit.html import _REDACT_PLACEHOLDER, redact_collection_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "COLLECT_PARSE_V3_23_0.py")

CONFIG = """hostname CORE-1
enable secret 5 $1$AAAA$FakeHashValue123
username admin privilege 15 secret 9 $9$FakeAdminHash
snmp-server community S3cr3tRW RW
tacacs-server host 10.9.9.9 key MyTacacsKey99
interface Vlan10
 ip address 10.1.2.3 255.255.255.0
"""


def _seed(tmp_path):
    dev = tmp_path / "CORE-1"
    dev.mkdir()
    (dev / "show_running-config.txt").write_text(CONFIG, encoding="utf-8")
    (dev / "show_version.txt").write_text(
        "Cisco IOS XE Software, Version 17.09.04a\nUptime is 1 week\nSerial: FXS1234\n",
        encoding="utf-8")
    (dev / "api_dump.json").write_text('{"password": "keepme-not-a-txt-capture"}',
                                       encoding="utf-8")
    return dev


def test_scrub_replaces_secret_values_keeps_topology_facts(tmp_path):
    dev = _seed(tmp_path)
    scanned, changed = redact_collection_dir(str(tmp_path))
    text = (dev / "show_running-config.txt").read_text(encoding="utf-8")
    for gone in ("$1$AAAA$FakeHashValue123", "$9$FakeAdminHash", "S3cr3tRW", "MyTacacsKey99"):
        assert gone not in text, f"secret value survived the scrub: {gone}"
    assert _REDACT_PLACEHOLDER in text
    # the analyzable facts SURVIVE — this dir must stay usable for --no-collect/--compare
    for kept in ("hostname CORE-1", "10.1.2.3", "interface Vlan10", "snmp-server community"):
        assert kept in text, f"non-secret context was destroyed: {kept}"
    assert scanned == 2 and changed == 1        # both .txt scanned; only the config changed


def test_scrub_is_idempotent(tmp_path):
    _seed(tmp_path)
    redact_collection_dir(str(tmp_path))
    scanned, changed = redact_collection_dir(str(tmp_path))
    assert scanned == 2 and changed == 0, "second pass must be a no-op"


def test_non_txt_captures_are_untouched(tmp_path):
    dev = _seed(tmp_path)
    redact_collection_dir(str(tmp_path))
    assert (dev / "api_dump.json").read_text(encoding="utf-8") == \
        '{"password": "keepme-not-a-txt-capture"}'


def test_cli_flag_scrubs_after_analysis_and_warns(tmp_path):
    """E2E: a --no-collect run with --redact-collection (a) prints the [SENSITIVE]
    warning naming the dir, (b) produces the normal deliverables from the ORIGINALS,
    (c) leaves the raw dir scrubbed afterwards. The synthetic fixture's own config
    carries real secret shapes (enable secret 9 / community public), so no injection
    is needed."""
    collection = fx.write_collection(str(tmp_path / "collection"))
    # A file the capture grammar CANNOT read, sitting in the folder the scrub is pointed at. The
    # console must say so: "scrubbed N of M" over an unstated denominator reads as "the folder is
    # clean" (R8/F4 — the Atlas exit disclosed this, the engine's primary entrypoint did not).
    os.makedirs(collection, exist_ok=True)
    with open(os.path.join(collection, "controller_dump.json"), "w", encoding="utf-8") as f:
        f.write('{"apicPassword": "keepme-not-a-capture"}')
    # ...and the same file under a name the producer and the verifier used to classify
    # DIFFERENTLY (R9/F1). `os.path.splitext` swallows every leading dot, `Path.suffix` swallows
    # one, so ``..json`` was a capture to the producer and a structured document to the verifier.
    # Measured pre-fix on this very path: the engine rewrote it in place until it stopped parsing
    # and then aborted the phase with "producer/verifier raw-capture file counts disagree".
    _two_dot = '{"cfg": "username admin password C1sco123"}'
    with open(os.path.join(collection, "..json"), "w", encoding="utf-8") as f:
        f.write(_two_dot)
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(str(template))
    out_xlsx = tmp_path / "out.xlsx"

    # precondition: cleartext secret shapes exist in the raw captures
    raw_before = ""
    for r, _d, files in os.walk(collection):
        for fn in files:
            if fn.endswith(".txt"):
                raw_before += open(os.path.join(r, fn), encoding="utf-8", errors="ignore").read()
    assert "community public" in raw_before and "$9$" in raw_before

    proc = subprocess.run(
        [sys.executable, SCRIPT, "--no-collect", "--collection-dir", collection,
         "--devices-file", str(devices), "--template", str(template),
         "--output", str(out_xlsx), "--no-html", "--workers", "1", "--redact-collection"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, f"pipeline failed:\n{proc.stdout}\n{proc.stderr}"
    console = proc.stdout + proc.stderr
    assert "[SENSITIVE]" in console, "the cleartext raw-dir warning must print on every run"
    assert "redact-collection" in console.lower()
    # R8/F4: the CLI now names what it did NOT cover, from BOTH accounts — the producer's own
    # skip list and the independent verifier's `uncovered`. Pre-fix the console carried only
    # "scrubbed 8 of 8 raw capture file(s)" while controller_dump.json was never looked at.
    assert "NOT COVERED" in console, f"the CLI printed no coverage disclosure:\n{console}"
    assert "controller_dump.json" in console, console
    # BOTH accounts, separately — the producer's skip list and the independent verifier's
    # `uncovered`. One standing in for the other would hide a producer/verifier divergence.
    assert "were not scrubbed" in console, console
    assert "NOT COVERED by the independent verifier" in console, console
    assert "NOT a statement that they are free of secrets" in console, console
    # and the file it declined to read is untouched — disclosure, not a silent rewrite
    with open(os.path.join(collection, "controller_dump.json"), encoding="utf-8") as f:
        assert f.read() == '{"apicPassword": "keepme-not-a-capture"}'
    # R9/F1 — the two-leading-dot name, at the CONSUMER: the engine's own console. It is named in
    # the disclosure (by BOTH accounts), the two counts reconcile, and its bytes are intact.
    assert "..json" in console, console
    assert "counts disagree" not in console, console
    with open(os.path.join(collection, "..json"), encoding="utf-8") as f:
        assert f.read() == _two_dot, "a structured document was rewritten in place"
    assert "Raw capture redaction verification FAILED" not in console, console

    # deliverables were produced (from the pre-scrub originals — scrub runs last)
    assert out_xlsx.is_file()
    snap = json.load(open(os.path.splitext(str(out_xlsx))[0] + ".snapshot.json",
                          encoding="utf-8"))
    assert "devices" in snap

    raw_after = ""
    for r, _d, files in os.walk(collection):
        for fn in files:
            if fn.endswith(".txt"):
                raw_after += open(os.path.join(r, fn), encoding="utf-8", errors="ignore").read()
    assert "$9$FAKEsecretHASHonly" not in raw_after, "enable-secret hash survived"
    assert "community public" not in raw_after, "SNMP community value survived"
    assert _REDACT_PLACEHOLDER in raw_after
    # and the dir still EXISTS (never auto-deleted — it is the --compare source)
    assert os.path.isdir(collection)


def test_sensitive_warning_prints_even_without_the_flag(tmp_path):
    """The warning is unconditional — knowing the exposure exists must not require
    having already opted into the fix."""
    collection = fx.write_collection(str(tmp_path / "collection"))
    devices = tmp_path / "devices.json"
    devices.write_text(json.dumps(fx.DEVICES), encoding="utf-8")
    template = tmp_path / "template.xlsx"
    wb = Workbook(); ws = wb.active; ws.title = "Interface Data"
    ws.append(["Hostname", "Port", "Status"]); wb.save(str(template))
    proc = subprocess.run(
        [sys.executable, SCRIPT, "--no-collect", "--collection-dir", collection,
         "--devices-file", str(devices), "--template", str(template),
         "--output", str(tmp_path / "o.xlsx"), "--no-html", "--workers", "1"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0
    assert "[SENSITIVE]" in (proc.stdout + proc.stderr)
    # no flag -> raw dir untouched
    raw = ""
    for r, _d, files in os.walk(collection):
        for fn in files:
            if fn.endswith(".txt"):
                raw += open(os.path.join(r, fn), encoding="utf-8", errors="ignore").read()
    assert "community public" in raw


def test_devices_example_documents_the_env_chain(monkeypatch):
    """devices.example.json ships at the repo root, holds NO literal passwords, uses
    password_env, and round-trips through the real loader (password resolves empty when
    the env is unset — the loader then warns instead of blocking, as designed)."""
    path = os.path.join(ROOT, "devices.example.json")
    assert os.path.isfile(path), "devices.example.json is missing from the repo root"
    raw = json.load(open(path, encoding="utf-8"))
    assert isinstance(raw, list) and raw
    assert all("password" not in e for e in raw), \
        "the EXAMPLE file must never carry a literal password field"
    assert any("password_env" in e for e in raw)

    sys.path.insert(0, ROOT)
    import COLLECT_PARSE_V3_23_0 as cp
    monkeypatch.delenv("CISCO_PASS", raising=False)
    for e in raw:
        monkeypatch.delenv(e.get("password_env", "") or "_NOPE_", raising=False)
    devices = cp.load_devices(path)
    assert devices and all(d["password"] == "" for d in devices)


def test_readme_documents_env_chain_and_redact_collection():
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for needle in ("CISCO_PASS", "password_env", "--redact-collection", "devices.example.json"):
        assert needle in readme, f"README must document {needle}"


# ── byte fidelity: this rewrites the engineer's ONLY copy of the raw captures ───
def test_scrub_preserves_every_byte_except_the_secret(tmp_path):
    """The docstring promises "values only ... nothing is ever deleted". Two bugs broke that on
    real captures: `errors="ignore"` DELETED bytes that are not valid UTF-8 (0x96 is the cp1252
    en-dash, routine in banners and interface descriptions), and text-mode write rewrote every
    LF to CRLF on Windows — so every line of every scrubbed capture changed."""
    dev = tmp_path / "core1"
    dev.mkdir()
    original = (b"! site \x96 Paris DC\n"
                b"snmp-server community s3cr3tvalue RO\n"
                b"interface Gi1/0/1\n")
    cap = dev / "show_run.txt"
    cap.write_bytes(original)

    scanned, changed = redact_collection_dir(str(tmp_path))
    after = cap.read_bytes()

    assert (scanned, changed) == (1, 1)
    assert b"s3cr3tvalue" not in after and b"<redacted>" in after
    # everything else is byte-identical: the non-UTF-8 byte and the LF endings both survive
    assert after == original.replace(b"s3cr3tvalue", b"<redacted>")


def test_scrub_is_atomic_and_leaves_no_partial(tmp_path, monkeypatch):
    """A yank or a full disk mid-rewrite left a TRUNCATED capture indistinguishable from a
    legitimate scrub — the run manifest is sealed a phase earlier, so nothing would catch it."""
    dev = tmp_path / "core1"
    dev.mkdir()
    original = b"snmp-server community s3cr3tvalue RO\n"
    cap = dev / "show_run.txt"
    cap.write_bytes(original)

    real_replace = os.replace

    def boom(src, dst):
        raise OSError("device or resource busy")

    monkeypatch.setattr(os, "replace", boom)
    redact_collection_dir(str(tmp_path))
    monkeypatch.setattr(os, "replace", real_replace)

    assert cap.read_bytes() == original, "the original capture must survive a failed rewrite"
    assert not list(dev.glob("*.redacting")), "a partial file was left beside the real capture"


def test_scrub_round_trips_arbitrary_binary_ish_content(tmp_path):
    """Captures come off real gear; assume nothing about their encoding."""
    dev = tmp_path / "core1"
    dev.mkdir()
    original = bytes(range(0x80, 0x100)) + b"\npassword 7 09604F0B\n" + bytes(range(0x80, 0xA0))
    cap = dev / "show_run.txt"
    cap.write_bytes(original)
    redact_collection_dir(str(tmp_path))
    after = cap.read_bytes()
    assert b"09604F0B" not in after
    # every high byte outside the scrubbed span is preserved exactly
    assert after.startswith(bytes(range(0x80, 0x100)))
    assert after.endswith(bytes(range(0x80, 0xA0)))


# ── R8/F6: two matchers for one rule (the producer and the independent verifier) ─
def _verifier_rule():
    """`redaction_verify.is_uncoverable_capture` — the OWNER of the raw-capture name rule (the
    ingest census delegates to it). Imported here, not in the producer, because the verifier's
    independence forbids the two importing each other."""
    sys.path.insert(0, os.path.join(ROOT, "webapp"))
    from backend.redaction_verify import is_uncoverable_capture
    return is_uncoverable_capture


def _excluded_suffixes():
    """The owner's exclusion set, read from the code — never restated here as a literal list."""
    from cisco_toolkit import html as _html
    return sorted(set(_html._REDACT_SKIP_CAPTURE_SUFFIXES) | {_html._REDACT_SCRUB_TEMP_SUFFIX})


def _capture_name_corpus():
    """Every name SHAPE that makes "the suffix of a filename" ambiguous, GENERATED from its axes —
    leading-dot runs x stem x tail — rather than hand-listed.

    A hand-list is how this bug survived two rounds: the previous corpus enumerated ~22 examples,
    every one of which the two matchers happened to agree on, so the parity assertion passed over
    a real divergence. The axes below are the ones the two primitives actually read differently
    (leading dots, a trailing dot, no extension at all, several dots, case, non-ASCII, spaces)."""
    leading_dots = ["", ".", "..", "..."]
    stems = ["", "show_run", "backup-config", "show_tech.support", "SHOW_VERSION",
             "cfg 2", "été-cfg"]
    tails = ["", ".", ".txt", ".cfg", ".log", ".out", ".conf", ".hidden",
             ".json", ".JSON", ".Json", ".xml", ".yml", ".yaml", ".html", ".htm",
             ".redacting", ".REDACTING", ".json.txt", ".txt.json", ".jsøn"]
    names = {dots + stem + tail for dots in leading_dots for stem in stems for tail in tails}
    return sorted(names - {"", ".", ".."})          # "." and ".." are not filenames


def test_the_producer_and_the_verifier_decide_capture_by_the_SAME_primitive():
    """One rule, two physically separate statements of it (the verifier may not import the producer
    and vice versa) — so they are pinned against each other over the whole structural class.

    Both previous restatements of the owner's ``Path(fn).suffix.casefold()`` were wrong in a way a
    hand-list of examples did not catch:

    * ``fn.lower().endswith((".json", ...))`` — disagreed on bare-name dotfiles: ``.json`` was
      SKIPPED by the producer (left unscrubbed) and treated as a CAPTURE by the verifier;
    * ``os.path.splitext(fn)[1].casefold()`` — shipped under a comment claiming it was identical to
      ``Path(...).suffix``. It is not: ``splitext`` skips EVERY leading dot of the basename, so
      ``..json`` had no extension to the producer (⇒ a capture: measured, `redact_collection_dir`
      rewrote it in place until it stopped parsing) and ``.json`` to the verifier (⇒ structured,
      never looked at), and the run then died on "producer/verifier raw-capture file counts
      disagree"."""
    from cisco_toolkit.html import _is_raw_capture

    is_uncoverable = _verifier_rule()
    corpus = _capture_name_corpus()
    disagree = [n for n in corpus if _is_raw_capture(n) != (is_uncoverable(n) == "")]
    assert disagree == [], (
        "producer and verifier disagree about what a capture is, over "
        f"{len(disagree)} of {len(corpus)} names: {ascii(disagree[:12])}")

    # NON-VACUITY: the corpus really does exercise both answers, so an always-True matcher
    # (or an always-False one) could not pass the assertion above.
    assert any(_is_raw_capture(n) for n in corpus) and any(not _is_raw_capture(n) for n in corpus)

    # ...and both divergent CLASSES are inside it, each derived from the owner's own suffix set:
    # a leading run of two or more dots (what `splitext` swallowed) ...
    leading_run = [dots + suffix.lstrip(".")
                   for dots in ("..", "...") for suffix in _excluded_suffixes()]
    assert set(leading_run) <= set(corpus), ascii(sorted(set(leading_run) - set(corpus)))
    for name in leading_run:
        assert not _is_raw_capture(name), ascii(name)
        assert is_uncoverable(name), ascii(name)
    # ... and the bare-name dotfile (what `endswith` swallowed), closed the SAFE way: a file
    # literally NAMED ".json" has no extension, so it is a capture and IS scrubbed.
    for suffix in _excluded_suffixes():
        assert _is_raw_capture(suffix) is True, ascii(suffix)
        assert is_uncoverable(suffix) == "", ascii(suffix)


def test_producer_and_verifier_agree_on_a_real_tree_including_the_count_reconciliation(tmp_path):
    """The parity above, exercised through the two real implementations over real files — and
    through the exact equality ``COLLECT_PARSE_V3_23_0.py:4267`` computes from them.

    Pre-fix, measured: a collection holding ``CORE-1/..json`` gave producer ``scanned=2`` against
    verifier ``files=1``, so the engine raised "producer/verifier raw-capture file counts disagree"
    and recorded a mandatory failure — after the producer had already rewritten that JSON in place
    until it no longer parsed (``Expecting ',' delimiter``), which is the exact damage the
    structured-document exclusion exists to prevent."""
    sys.path.insert(0, os.path.join(ROOT, "webapp"))
    from backend.redaction_verify import verify_collection_secret_scrub

    dev = tmp_path / "CORE-1"
    dev.mkdir()
    (dev / "show_run.txt").write_text("snmp-server community S3cr3t RO\n", encoding="utf-8")
    payload = json.dumps({"cfg": "username admin password C1sco123"})
    structured = [".." + s.lstrip(".") for s in _excluded_suffixes()]   # ..json, ..redacting, ...
    for name in structured:
        (dev / name).write_text(payload, encoding="utf-8")

    res = redact_collection_dir(str(tmp_path))
    scanned, _changed = res
    proof = verify_collection_secret_scrub(tmp_path)

    # the reconciliation the CLI performs, verbatim
    assert proof["files"] == scanned, (
        f"producer/verifier raw-capture file counts disagree ({scanned} vs {proof['files']})")
    # both accounts name the same excluded files -- neither side may be silent about them
    producer_excluded = {rel for rel, _why in res.uncovered}
    verifier_excluded = {row["file"] for row in proof["uncovered"]}
    assert producer_excluded == verifier_excluded == {f"CORE-1/{n}" for n in structured}
    # and the structured documents are BYTE-identical: disclosed, not rewritten
    for name in structured:
        assert (dev / name).read_text(encoding="utf-8") == payload, ascii(name)
        json.loads((dev / name).read_text(encoding="utf-8"))      # still parses

    # NON-VACUITY: the same tree without those names certifies with NOTHING uncovered on either
    # side, so the disclosure is not always-on and the equality is not trivially 0 == 0.
    for name in structured:
        (dev / name).unlink()
    res2 = redact_collection_dir(str(tmp_path))
    proof2 = verify_collection_secret_scrub(tmp_path)
    assert tuple(res2) == (1, 0) and res2.uncovered == ()
    assert proof2["files"] == 1 and proof2["uncovered"] == []


# ── R8/F7: default-INCLUDE is fail-safe, but it must be BOUNDED and say so ──────
def test_the_widened_scrub_is_bounded_and_discloses_every_file_it_declined(tmp_path):
    """`_is_raw_capture` defaults to INCLUDE, so this pass can now reach any text file under the
    collection root and rewrites it IN PLACE — the engineer's only copy. The bound is deliberate
    (name rule / binary content / size ceiling / the grammar must actually match) and every
    exclusion is returned, because "we did not look at this one" arriving as silence is the same
    false-health shape the scrub exists to remove."""
    from cisco_toolkit import html as _html

    dev = tmp_path / "CORE-1"
    dev.mkdir()
    (dev / "show_run.txt").write_text("snmp-server community S3cr3t RO\n", encoding="utf-8")
    (dev / "notes.md").write_text("no secrets here, just prose\n", encoding="utf-8")
    (dev / "api.json").write_text('{"password": "structured"}', encoding="utf-8")
    (dev / "blob.bin").write_bytes(b"\x00\x01\x02")
    (dev / "huge.log").write_text("x" * 4096, encoding="utf-8")

    monkey = _html._REDACT_MAX_CAPTURE_BYTES
    try:
        _html._REDACT_MAX_CAPTURE_BYTES = 1024        # the ceiling, exercised without a 128MB file
        res = _html.redact_collection_dir(str(tmp_path))
    finally:
        _html._REDACT_MAX_CAPTURE_BYTES = monkey

    scanned, changed = res                            # still a plain 2-tuple for every old caller
    assert (scanned, changed) == (2, 1)               # show_run.txt + notes.md read; only one rewritten
    assert res == (2, 1)

    reasons = dict(res.uncovered)
    assert set(reasons) == {"CORE-1/api.json", "CORE-1/blob.bin", "CORE-1/huge.log"}, reasons
    assert "not a raw capture by name" in reasons["CORE-1/api.json"]
    assert "binary content" in reasons["CORE-1/blob.bin"]
    assert "ceiling" in reasons["CORE-1/huge.log"]
    # bound 4: a file with no secret in it is read and left BYTE-identical, never rewritten
    assert (dev / "notes.md").read_text(encoding="utf-8") == "no secrets here, just prose\n"
    # the oversize file was not read, so it is not scrubbed AND not counted as scanned
    assert (dev / "huge.log").read_text(encoding="utf-8") == "x" * 4096

    # NON-VACUITY: a folder of ordinary captures produces an EMPTY uncovered list, so the
    # disclosure is not always-on.
    clean = tmp_path / "clean" / "CORE-2"
    clean.mkdir(parents=True)
    (clean / "show_version.txt").write_text("Version 17.09\n", encoding="utf-8")
    res2 = _html.redact_collection_dir(str(tmp_path / "clean"))
    assert tuple(res2) == (1, 0) and res2.uncovered == ()


# ── R9/F2: that bound, proved over a CORPUS instead of one example per rule ─────
#: Real container shapes, each carrying a NUL. The last one is the case the NAME cannot decide: a
#: genuine ``show run`` capture stored as UTF-16, where every ASCII character is followed by a NUL
#: byte — ``.txt`` says "capture" and only the bytes say "container".
_BINARY_SHAPES = {
    "core.dmp": b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 24,
    "capture.pcap": b"\xd4\xc3\xb2\xa1\x02\x00\x04\x00" + b"\x00" * 24,
    "logo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16,
    "bundle.zip": b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 16,
    "show_run_utf16.txt": "snmp-server community S3cr3t RO\n".encode("utf-16"),
}
_SECRET_LINE = "snmp-server community S3cr3t RO\n"


def test_the_bound_holds_over_a_corpus_of_structured_and_binary_files(tmp_path):
    """The widened rule REWRITES IN PLACE, so its two content-independent limits are proved over the
    whole class rather than one file each: EVERY structured suffix the owner names (in every case
    form, and under the two-leading-dot spelling), and every binary container shape.

    Each excluded file carries a line the grammar WOULD have rewritten, so "untouched" cannot pass
    for the trivial reason that there was nothing to change; each included file carries the same
    line and must come out scrubbed, which is the fail-safe direction the default-INCLUDE rule
    exists for (``.cfg`` / ``.log`` / ``.out`` / no extension at all were the measured leak). The
    independent verifier is then asked the same question about the same tree."""
    sys.path.insert(0, os.path.join(ROOT, "webapp"))
    from backend.redaction_verify import verify_collection_secret_scrub

    dev = tmp_path / "CORE-1"
    dev.mkdir()
    structured_payload = '{"cfg": "username admin password C1sco123"}'
    structured = []
    for i, suffix in enumerate(_excluded_suffixes()):
        bare = suffix.lstrip(".")
        # distinct STEMS for the case variants: this filesystem is case-insensitive, so
        # "dump.json"/"dump.JSON" would be one file and the upper-case arm would prove nothing.
        for name in (f"dump{i}{suffix}", f"upper{i}{suffix.upper()}",
                     f"mixed{i}.{bare.capitalize()}", f"..{bare}"):
            (dev / name).write_text(structured_payload, encoding="utf-8")
            structured.append(name)
    for name, blob in _BINARY_SHAPES.items():
        (dev / name).write_bytes(blob)
    # the fail-safe half: extensions nobody enumerated, and none at all
    captures = ["show_run.cfg", "show_tech-support.log", "running-config", "dump.out",
                "startup.conf", ".hidden", "..cfg", "show_version.txt"]
    for name in captures:
        (dev / name).write_text(_SECRET_LINE, encoding="utf-8")

    res = redact_collection_dir(str(tmp_path))
    scanned, changed = res

    excluded = {f"CORE-1/{n}" for n in structured} | {f"CORE-1/{n}" for n in _BINARY_SHAPES}
    assert {rel for rel, _why in res.uncovered} == excluded, ascii(sorted(res.uncovered))
    reasons = dict(res.uncovered)
    for name in structured:
        assert "not a raw capture by name" in reasons[f"CORE-1/{name}"], ascii(name)
        assert (dev / name).read_text(encoding="utf-8") == structured_payload, ascii(name)
    for name, blob in _BINARY_SHAPES.items():
        assert "binary content" in reasons[f"CORE-1/{name}"], name
        assert (dev / name).read_bytes() == blob, name

    # NON-VACUITY, the direction that matters: everything else WAS scrubbed, so the exclusions
    # above are a real bound and not an inert pass that touches nothing.
    assert (scanned, changed) == (len(captures), len(captures))
    for name in captures:
        text = (dev / name).read_text(encoding="utf-8")
        assert "S3cr3t" not in text and _REDACT_PLACEHOLDER in text, ascii(name)

    # ...and the independent verifier draws the same boundary over the same tree.
    proof = verify_collection_secret_scrub(tmp_path)
    assert proof["files"] == scanned
    assert {row["file"] for row in proof["uncovered"]} == excluded

    # The third limit is a NUMBER stated on both sides (the producer skips above it and DISCLOSES;
    # the verifier refuses to certify above it). They are only two accounts of one bound while the
    # number is the same, so it is pinned rather than left to a comment.
    import backend.redaction_verify as _rv
    from cisco_toolkit import html as _html
    assert _html._REDACT_MAX_CAPTURE_BYTES == _rv.MAX_ARTIFACT_BYTES
