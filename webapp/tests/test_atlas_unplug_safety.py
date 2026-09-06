"""Atlas P3 slice 1 — SQLite unplug-safety at boot (docs/atlas-p3-plan-2026-07-21.md).

The stick gets yanked, the laptop dies mid-write, the DB is client evidence. The production entry
(serve.main) must prove the store is sound before serving, keep a rotating restorable copy, and
turn the two field failure modes (corrupt DB, write-locked stick) into friendly refusals instead
of tracebacks. Everything is opt-in via ``boot_hardening`` so dev servers and tests keep today's
behavior; only serve.main turns it on.

Doctrine anchors: fail-loud (corruption refuses to serve), never-destructive (the corrupt file is
left byte-identical — restore is a documented human action), coverage-honest (a failed backup
WARNS every boot rather than silently degrading).
"""

import os
import shutil
import sqlite3
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

import backend.serve as serve  # noqa: E402
import backend.storage as storage_module  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.storage import Store, StoreCorruptError  # noqa: E402


_orig_connect = sqlite3.connect  # kept before any monkeypatching, for tests that need a real one


def _backups(db: Path) -> list:
    """Only backups the product created — a test helper using the loose glob would count an
    engineer's parked copies and hide the very rotation bug these tests pin."""
    import re as _re

    return sorted(p for p in (db.parent / "backups").glob("assesshub-*.db")
                  if _re.match(r"^assesshub-\d{8}T\d{6}Z\.db$", p.name))


def _boot(db: Path, hardened: bool = True) -> None:
    """One app-boot lifecycle against the store, connection closed (Windows tmp cleanup)."""
    s = Store(db, boot_hardening=hardened)
    s.close()


def _seed_row(db: Path) -> None:
    """A boot that also WRITES (so the file's mtime moves past any existing backup's)."""
    s = Store(db)
    s.create_campaign("evidence")
    s.close()


# ── backup-at-boot ──────────────────────────────────────────────────────────────
def test_default_boot_is_unhardened_no_backup_machinery(tmp_path):
    db = tmp_path / "data" / "hub.db"
    _boot(db, hardened=False)
    _seed_row(db)
    _boot(db, hardened=False)
    assert not (db.parent / "backups").exists()


def test_first_boot_backs_nothing_up(tmp_path):
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    assert _backups(db) == []  # a brand-new empty store is not evidence worth copying


def test_repeated_empty_boots_neither_back_up_nor_claim_backup_evidence(tmp_path, capsys):
    """A campaign-free store is a normal state, not evidence that an existing backup is richer."""
    db = tmp_path / "data" / "hub.db"
    for _ in range(3):
        _boot(db)
    assert _backups(db) == []
    assert "TRUNCATED" not in capsys.readouterr().err


def test_legacy_empty_backup_does_not_trigger_a_false_campaign_warning(tmp_path, capsys):
    """Older builds created empty owned backups; their existence proves no campaign content."""
    db = tmp_path / "شبكة #%25" / "data" / "hub.db"
    _boot(db)
    backups = db.parent / "backups"
    backups.mkdir()
    legacy = backups / "assesshub-20200101T000000Z.db"
    shutil.copy2(db, legacy)
    legacy_bytes = legacy.read_bytes()
    capsys.readouterr()

    _boot(db)

    assert _backups(db) == [legacy]
    assert legacy.read_bytes() == legacy_bytes
    assert capsys.readouterr().err == ""


def test_unreadable_owned_backup_is_preserved_without_claiming_it_has_campaigns(tmp_path, capsys):
    """Unreadable is unknown, not proof of campaigns and not permission to rotate the file."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    backups = db.parent / "backups"
    backups.mkdir()
    unreadable = backups / "assesshub-20200101T000000Z.db"
    payload = b"not a sqlite database"
    unreadable.write_bytes(payload)
    capsys.readouterr()

    _boot(db)

    err = capsys.readouterr().err
    assert "could not be verified" in err
    assert "while backups in" not in err
    assert unreadable.read_bytes() == payload
    assert _backups(db) == [unreadable]


def test_backup_campaign_scan_prefers_proven_campaign_evidence_over_unknown(tmp_path, capsys):
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    backups = db.parent / "backups"
    backups.mkdir()
    unknown = backups / "assesshub-20200101T000000Z.db"
    unknown.write_bytes(b"not sqlite")
    seeded = tmp_path / "seeded.db"
    _seed_row(seeded)
    proven = backups / "assesshub-20200102T000000Z.db"
    shutil.copy2(seeded, proven)
    expected = {path: path.read_bytes() for path in (unknown, proven)}
    capsys.readouterr()

    _boot(db)

    err = capsys.readouterr().err
    assert "at least one Atlas-owned backup" in err
    assert "could not be verified" not in err
    assert {path: path.read_bytes() for path in (unknown, proven)} == expected
    assert _backups(db) == [unknown, proven]


def test_schema_valid_backup_without_campaigns_table_is_unknown(tmp_path, capsys):
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    backups = db.parent / "backups"
    backups.mkdir()
    legacy = backups / "assesshub-20200101T000000Z.db"
    conn = sqlite3.connect(str(legacy))
    try:
        conn.execute("CREATE TABLE legacy_evidence (value TEXT)")
        conn.execute("INSERT INTO legacy_evidence VALUES ('preserve me')")
        conn.commit()
    finally:
        conn.close()
    expected = legacy.read_bytes()
    capsys.readouterr()

    _boot(db)

    assert "could not be verified" in capsys.readouterr().err
    assert legacy.read_bytes() == expected
    assert _backups(db) == [legacy]


def test_wal_header_backup_is_inspected_without_creating_sqlite_sidecars(tmp_path, capsys):
    """Even mode=ro can create -wal/-shm; immutable inspection must leave no new files."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    backups = db.parent / "backups"
    backups.mkdir()
    wal_backup = backups / "assesshub-20200101T000000Z.db"
    conn = sqlite3.connect(str(wal_backup))
    try:
        assert conn.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        conn.execute("CREATE TABLE campaigns (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO campaigns (name) VALUES ('retained evidence')")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    companions = [Path(f"{wal_backup}-wal"), Path(f"{wal_backup}-shm")]
    for companion in companions:
        companion.unlink(missing_ok=True)
    expected = wal_backup.read_bytes()
    capsys.readouterr()

    _boot(db)

    assert "at least one Atlas-owned backup" in capsys.readouterr().err
    assert wal_backup.read_bytes() == expected
    assert not any(companion.exists() for companion in companions)


def test_existing_wal_companions_force_unknown_without_touching_any_bytes(tmp_path, capsys):
    """Immutable SQLite ignores live WAL state, so companions must prevent positive classification."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    backups = db.parent / "backups"
    backups.mkdir()
    seeded = tmp_path / "seeded.db"
    _seed_row(seeded)
    candidate = backups / "assesshub-20200101T000000Z.db"
    shutil.copy2(seeded, candidate)
    companions = [Path(f"{candidate}-wal"), Path(f"{candidate}-shm")]
    companions[0].write_bytes(b"live wal state")
    companions[1].write_bytes(b"live shm state")
    expected = {path: path.read_bytes() for path in (candidate, *companions)}
    capsys.readouterr()

    _boot(db)

    err = capsys.readouterr().err
    assert "could not be verified" in err
    assert "at least one Atlas-owned backup" not in err
    assert {path: path.read_bytes() for path in (candidate, *companions)} == expected


def test_failed_backup_quick_check_cannot_be_misclassified_as_campaign_evidence(
        tmp_path, monkeypatch):
    candidate = tmp_path / "assesshub-20200101T000000Z.db"
    candidate.write_bytes(b"resolved path placeholder")

    class FakeConnection:
        def __init__(self):
            self.statement = ""
            self.closed = False

        def execute(self, statement):
            self.statement = statement
            return self

        def fetchall(self):
            assert self.statement == "PRAGMA quick_check"
            return [("database disk image is malformed",)]

        def fetchone(self):
            assert self.statement == "SELECT COUNT(*) FROM campaigns"
            return (1,)

        def close(self):
            self.closed = True

    fake = FakeConnection()
    monkeypatch.setattr(storage_module.sqlite3, "connect", lambda *_a, **_kw: fake)

    assert storage_module._backup_campaign_evidence([candidate]) == "unknown"
    assert fake.closed is True


def test_second_boot_takes_a_restorable_backup(tmp_path):
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)
    _boot(db)
    baks = _backups(db)
    assert len(baks) == 1
    # restorable = the client's row is really in the copy
    conn = sqlite3.connect(str(baks[0]))
    try:
        assert conn.execute("SELECT name FROM campaigns").fetchone()[0] == "evidence"
    finally:
        conn.close()


def test_unchanged_store_is_not_rebacked_up(tmp_path):
    """A boot loop on an idle stick must not churn flash with identical copies."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)
    _boot(db)
    _boot(db)
    _boot(db)
    assert len(_backups(db)) == 1


def test_rotation_keeps_newest_three(tmp_path):
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)
    bak_dir = db.parent / "backups"
    bak_dir.mkdir(exist_ok=True)
    for stamp in ("20200101T000000Z", "20200102T000000Z", "20200103T000000Z"):
        old = bak_dir / f"assesshub-{stamp}.db"
        old.write_bytes(b"old backup")
        os.utime(old, (1, 1))  # older than the db → a fresh backup is due
    _boot(db)
    kept = _backups(db)
    assert len(kept) == 3
    assert kept[0].name == "assesshub-20200102T000000Z.db"  # the single oldest was dropped
    assert kept[-1].read_bytes() != b"old backup"  # newest is the real copy just taken


# ── corruption: fail loud, never destructive ────────────────────────────────────
def test_garbage_file_refuses_to_serve_and_stays_untouched(tmp_path):
    db = tmp_path / "data" / "hub.db"
    db.parent.mkdir(parents=True)
    payload = b"this was never a sqlite database " * 64
    db.write_bytes(payload)
    with pytest.raises(StoreCorruptError) as e:
        Store(db, boot_hardening=True)
    msg = str(e.value)
    assert "hub.db" in msg and "backups" in msg  # names the file and where restores live
    assert db.read_bytes() == payload  # NEVER deleted/renamed/"repaired" — it is client evidence


def test_bitflipped_real_database_refuses_to_serve(tmp_path):
    """Not just torn headers: a once-valid store with damaged pages must also refuse."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    s = Store(db)
    for i in range(200):
        s.create_campaign(f"c{i}")
    s.close()
    raw = bytearray(db.read_bytes())
    # SQLite packs cells from each page's TAIL (the middle is free space quick_check ignores) —
    # stomp the tail of every page past the header page so the rows' pages are really damaged,
    # while the intact 100-byte header keeps connect() succeeding.
    ps = int.from_bytes(raw[16:18], "big")
    ps = 65536 if ps == 1 else ps
    for pg in range(2, len(raw) // ps + 1):
        raw[pg * ps - 512:pg * ps] = b"\xff" * 512
    db.write_bytes(bytes(raw))
    with pytest.raises(StoreCorruptError):
        Store(db, boot_hardening=True)


def test_create_app_threads_boot_hardening_to_store(tmp_path):
    db = tmp_path / "data" / "hub.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"garbage")
    with pytest.raises(StoreCorruptError):
        create_app(db_path=str(db), boot_hardening=True)
    # and the default stays unhardened: same corrupt file, plain sqlite error (old behavior)
    with pytest.raises(sqlite3.DatabaseError):
        create_app(db_path=str(db))


# ── serve.main: the field-facing refusals ───────────────────────────────────────
def _dist(tmp_path) -> Path:
    d = tmp_path / "dist"
    d.mkdir(exist_ok=True)
    (d / "index.html").write_text("<html>", encoding="utf-8")
    return d


def test_serve_main_corrupt_db_exits_1_with_friendly_message(tmp_path, capsys):
    db = tmp_path / "data" / "hub.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"garbage")
    rc = serve.main(["--db", str(db), "--dist", str(_dist(tmp_path)), "--no-browser"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "refusing to start" in err and "backups" in err
    assert "Traceback" not in err


def test_serve_main_unwritable_data_dir_exits_1_with_friendly_message(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory must go", encoding="utf-8")
    db = blocker / "data" / "hub.db"  # mkdir(parents) under a FILE → OSError on any OS
    rc = serve.main(["--db", str(db), "--dist", str(_dist(tmp_path)), "--no-browser"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not writable" in err and "write-locked" in err
    assert "Traceback" not in err


def test_serve_main_turns_boot_hardening_on(monkeypatch, tmp_path):
    """The production entry is the one caller that MUST harden — pin the wiring, not just the
    machinery, so a refactor cannot quietly ship an unhardened Atlas.exe."""
    import backend.app as app_module

    rec = {}

    def fake_create_app(**kw):
        rec.update(kw)
        return object()

    monkeypatch.setattr(app_module, "create_app", fake_create_app)
    monkeypatch.setitem(sys.modules, "uvicorn",
                        types.SimpleNamespace(run=lambda app, **kw: None))
    rc = serve.main(["--db", str(tmp_path / "data" / "hub.db"),
                     "--dist", str(_dist(tmp_path)), "--no-browser"])
    assert rc == 0
    assert rec["boot_hardening"] is True


# ── durability pragmas + selftest surface ───────────────────────────────────────
def test_hardened_store_pins_rollback_journal_not_wal(tmp_path):
    """WAL on removable exFAT media loses committed transactions when the -wal file is orphaned
    by a yank; rollback journaling recovers on next open. Pin DELETE + FULL."""
    db = tmp_path / "data" / "hub.db"
    s = Store(db, boot_hardening=True)
    try:
        assert s._conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert s._conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    finally:
        s.close()


# ── hazards found by independent review (all reproduced before being fixed) ─────
def test_locked_store_is_not_reported_as_corruption(tmp_path, monkeypatch, capsys):
    """sqlite3.OperationalError ('database is locked' — a second Atlas instance) SUBCLASSES
    DatabaseError. Treating it as corruption told the engineer to overwrite a HEALTHY store
    holding the newest evidence with an older backup: the worst advice this program can give."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)

    # A REAL lock, exactly like a second Atlas instance: sqlite3.Connection attributes cannot be
    # monkeypatched, and a fake would not prove the except-clause ordering that caused the bug.
    holder = sqlite3.connect(str(db), isolation_level=None, timeout=0.1)
    holder.execute("BEGIN EXCLUSIVE")
    monkeypatch.setattr(sqlite3, "connect",
                        lambda *a, **kw: _orig_connect(*a, **{**kw, "timeout": 0.1}))
    try:
        # It may well fail to open (the lock is real) — what must NEVER happen is being told the
        # store is CORRUPT and to restore a backup over healthy evidence. serve.main turns this
        # into a friendly refusal (see test_unopenable_store_refuses_without_a_traceback).
        with pytest.raises(sqlite3.OperationalError) as e:
            Store(db, boot_hardening=True)
        assert not isinstance(e.value, StoreCorruptError)
    finally:
        holder.rollback()
        holder.close()
    err = capsys.readouterr().err
    assert "already running" in err and "WITHOUT unplug protection" in err
    assert "corrupt" not in err.lower()
    # and the evidence is still there, untouched
    conn = _orig_connect(str(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 1
    finally:
        conn.close()


def test_truncated_store_is_not_backed_up_over_real_evidence(tmp_path, capsys):
    """A 0-byte file is a VALID EMPTY SQLite db — quick_check returns 'ok'. Backing it up pushed
    the real backups out of the keep window, destroying the evidence this feature protects."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)
    _boot(db)                                   # one real backup exists
    good = _backups(db)
    assert len(good) == 1
    db.write_bytes(b"")                          # the yank: truncated to zero bytes
    for _ in range(4):                           # four ordinary restarts
        s = Store(db, boot_hardening=True)
        s.close()
    kept = _backups(db)
    assert kept == good, "the truncated store rotated real evidence off the disk"
    err = capsys.readouterr().err
    assert "TRUNCATED" in err
    assert "at least one Atlas-owned backup" in err
    conn = sqlite3.connect(str(kept[0]))
    try:
        assert conn.execute("SELECT name FROM campaigns").fetchone()[0] == "evidence"
    finally:
        conn.close()


def test_rotation_never_touches_the_engineers_own_parked_copies(tmp_path):
    """`assesshub-*.db` also matches a human's labelled copies, and those sort AFTER the digit
    stamps — the loose glob deleted the fresh backup the instant it was written (silently
    disabling backups forever) and could delete the engineer's file too."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)
    parked = db.parent / "backups"
    parked.mkdir(exist_ok=True)
    names = ["assesshub-pre-cutover.db", "assesshub-post-wave1.db", "assesshub-signoff.db",
             "assesshub-2026-07-01-DO-NOT-DELETE.db"]
    for n in names:
        (parked / n).write_bytes(b"the engineer's own copy")
    _boot(db)
    for n in names:
        assert (parked / n).read_bytes() == b"the engineer's own copy", f"rotation ate {n}"
    assert len(_backups(db)) == 1, "our own fresh backup was rotated away immediately"


def test_failed_backup_leaves_no_stub_in_the_keep_set(tmp_path, monkeypatch, capsys):
    """A backup killed mid-write must never be mistaken for a good one: the destination file is
    created before any page is copied, and an empty stub passes quick_check."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)

    # A REAL SQLITE_FULL, injected only into the backup destination by capping its page count —
    # so the partial file is genuinely created-then-abandoned, exactly like a stick filling up.
    def capped_connect(target, *a, **kw):
        conn = _orig_connect(target, *a, **kw)
        if str(target).endswith(".partial"):
            conn.execute("PRAGMA max_page_count = 1")
        return conn

    monkeypatch.setattr(sqlite3, "connect", capped_connect)
    _boot(db)
    monkeypatch.undo()
    assert _backups(db) == [], "a partial backup was left where a restore could pick it"
    assert not list((db.parent / "backups").glob("*.partial"))
    assert "boot backup failed" in capsys.readouterr().err


def test_clock_skew_suppression_is_announced_not_silent(tmp_path, capsys):
    """FAT32 stores LOCAL time: a stick written at another offset reads 'in the future' and would
    suppress every future backup in silence."""
    db = tmp_path / "data" / "hub.db"
    _boot(db)
    _seed_row(db)
    _boot(db)
    capsys.readouterr()
    bak = _backups(db)[0]
    future = db.stat().st_mtime + 4 * 3600
    os.utime(bak, (future, future))
    _seed_row(db)
    _boot(db)
    assert "clock skew" in capsys.readouterr().err


def test_unopenable_store_refuses_without_a_traceback(tmp_path, monkeypatch, capsys):
    """sqlite3.connect happens BEFORE hardening, so its errors bypassed the StoreCorruptError
    handler and reached the engineer as a raw traceback."""
    import backend.app as app_module

    def boom(**kw):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(app_module, "create_app", boom)
    rc = serve.main(["--db", str(tmp_path / "data" / "hub.db"),
                     "--dist", str(_dist(tmp_path)), "--no-browser"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "cannot open the store" in err and "Traceback" not in err


def test_refusal_line_is_ascii_so_the_field_guide_can_quote_it(tmp_path, capsys):
    """README-FIELD is ASCII-only (enforced by tests/test_readme_field.py) and a cp437 field
    console renders an em-dash as '?' — so this line must not contain one."""
    db = tmp_path / "data" / "hub.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"garbage")
    serve.main(["--db", str(db), "--dist", str(_dist(tmp_path)), "--no-browser"])
    line = next(l for l in capsys.readouterr().err.splitlines() if "refusing to start" in l)
    # The brand title legitimately carries an em-dash; what the guide QUOTES must be ASCII.
    quoted = line[line.index("refusing to start"):]
    assert quoted.isascii(), quoted
    assert quoted.startswith("refusing to start - integrity check failed")


def test_the_documented_restore_procedure_actually_works(tmp_path):
    """Execute README-FIELD's CORRUPTION steps verbatim — the procedure an engineer follows at 2am
    with client evidence on the line, and the one that was never exercised end-to-end.

    Also pins the guide's loss promise ("EXPECT TO LOSE work done since Atlas last started"):
    backups are taken at BOOT, so a restore costs exactly the current session and nothing more.
    Understating that would be worse than saying nothing."""
    db = tmp_path / "data" / "assesshub.db"

    def atlas_session(labels):           # one real Atlas run: hardened boot, work, close
        s = Store(db, boot_hardening=True)
        for label in labels:
            s.create_campaign(label)
        s.close()
        # Force the store's mtime PAST the backup this session just took, rather than sleeping and
        # hoping. `_boot_hardening` skips the backup when `newest >= db_mtime` (storage.py:174), and
        # `shutil.copy2` PRESERVES the source mtime, so the backup's mtime equals the db's mtime as of
        # that boot. If this session's writes then land in the same filesystem tick as its own boot,
        # the two stay equal and the NEXT boot SKIPS its backup -- leaving the newest backup a whole
        # session stale, which is exactly the `names` assertion below. Sleeping BETWEEN sessions could
        # not fix that: it advances the wall clock, but the comparison needs the db's mtime to move
        # after its own backup was copied. Deterministic idiom, already used by the rotation test
        # above (os.utime), and it drops ~2.2s of sleeping from the suite.
        bumped = db.stat().st_mtime + 2       # +2s: unambiguous, far under the 60s clock-skew warning
        os.utime(db, (bumped, bumped))

    atlas_session(["day1-a", "day1-b"])
    atlas_session(["day2-a"])
    atlas_session(["day3-a", "day3-b"])

    db.write_bytes(b"\x00" * 4096 + b"torn")          # the yank
    with pytest.raises(StoreCorruptError):            # step 1: Atlas refuses, file untouched
        Store(db, boot_hardening=True)

    corrupt = db.parent / "assesshub.db.corrupt"
    db.rename(corrupt)                                # step 2: RENAME, never copy over
    shutil.copy2(_backups(db)[-1], db)                # step 3: newest backup into place

    s = Store(db, boot_hardening=True)                # step 4: start and check the campaign list
    names = sorted(r["name"] for r in s.list_campaigns())
    s.close()

    assert names == ["day1-a", "day1-b", "day2-a"], names
    assert corrupt.is_file() and corrupt.stat().st_size > 0   # salvage material preserved
    assert _backups(db), "the restore must not consume the remaining backups"


def test_selftest_gains_backup_dir_check(tmp_path, capsys):
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    rc = serve.run_selftest(dist_dir=_dist(tmp_path), db_path=str(tmp_path / "data" / "hub.db"))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "backup-dir" in out
