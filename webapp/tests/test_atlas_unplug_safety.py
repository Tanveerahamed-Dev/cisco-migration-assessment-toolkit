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
import sqlite3
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `backend` importable

import backend.serve as serve  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.storage import Store, StoreCorruptError  # noqa: E402


def _backups(db: Path) -> list:
    return sorted((db.parent / "backups").glob("assesshub-*.db"))


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


def test_selftest_gains_backup_dir_check(tmp_path, capsys):
    pytest.importorskip("docx")
    pytest.importorskip("pptx")
    rc = serve.run_selftest(dist_dir=_dist(tmp_path), db_path=str(tmp_path / "data" / "hub.db"))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "backup-dir" in out
