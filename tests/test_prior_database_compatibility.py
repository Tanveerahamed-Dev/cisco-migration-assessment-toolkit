from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from webapp.backend.storage import Store
from portable.database_preflight import DatabasePreflightError, migrate_and_compare


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "assesshub-v3.32.1.sql"
SOURCE_COMMIT = "47a1ff993f3bb9c9b2e4a138be6f073c8614498e"
SOURCE_TREE = "d4f9db52c0703ab02f25c3f4913d53baac8ddb60"
STORAGE_SHA256 = "f1d8f829c129db35763763b05e05c1220907f5ec851983cd3a4ba3e3208ca976"
FIXTURE_SHA256 = "2f47480d06ec6b87dfd42b88f61f6f7d4d2db7dccc7384ac0e255f3dd2b05382"


def _projected_rows(connection: sqlite3.Connection, table: str) -> list[tuple]:
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    names = ",".join(f'"{name}"' for name in columns)
    return sorted(connection.execute(f'SELECT {names} FROM "{table}"').fetchall())


def _write_fixture(path: Path) -> None:
    path.parent.mkdir()
    connection = sqlite3.connect(path)
    connection.executescript(FIXTURE.read_text(encoding="utf-8", errors="strict"))
    connection.close()


def test_current_store_migrates_exact_v3321_fixture_without_losing_prior_rows(tmp_path: Path) -> None:
    sql = FIXTURE.read_text(encoding="utf-8", errors="strict")
    assert f"-- source_commit={SOURCE_COMMIT}" in sql
    assert f"-- source_tree={SOURCE_TREE}" in sql
    assert f"-- storage_git_blob_sha256={STORAGE_SHA256}" in sql
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    database = tmp_path / "prior" / "assesshub.db"
    _write_fixture(database)
    connection = sqlite3.connect(database)
    prior_tables = ("campaigns", "snapshots", "executions", "gates")
    before = {table: _projected_rows(connection, table) for table in prior_tables}
    connection.close()

    store = Store(database, boot_hardening=True)
    assert store.get_campaign(1)["name"] == "Release 3.32.1 fixture"
    assert store.get_snapshot(1)["script_version"] == "3.32.1"
    assert store.get_execution(1)["state"]["label"] == "Prior run"
    store.close()

    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    for table in prior_tables:
        prior_columns = len(before[table][0]) if before[table] else len(
            connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        )
        current_columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
        names = ",".join(f'"{name}"' for name in current_columns[:prior_columns])
        assert sorted(connection.execute(f'SELECT {names} FROM "{table}"').fetchall()) == before[table]
    execution = connection.execute(
        "SELECT comparison_required, snapshot_id_high_watermark, lifecycle_state, "
        "started_at_epoch_us, ended_at_epoch_us FROM executions WHERE id=1"
    ).fetchone()
    assert execution == (0, 1, 1, 1785776400000000, 1785776460000000)
    connection.close()


def test_logical_preflight_censuses_every_prior_table_and_detects_row_loss(tmp_path: Path) -> None:
    database = tmp_path / "good" / "assesshub.db"
    _write_fixture(database)
    receipt = migrate_and_compare(database, Store)
    assert receipt["status"] == "pass"
    assert [row["table"] for row in receipt["prior_table_preservation"]] == [
        "campaigns",
        "executions",
        "gates",
        "snapshots",
    ]
    assert receipt["before"]["table_count"] == 4
    assert receipt["after"]["table_count"] >= 10

    damaged = tmp_path / "damaged" / "assesshub.db"
    _write_fixture(damaged)

    class DeletingStore:
        def __init__(self, path: Path, *, boot_hardening: bool) -> None:
            assert boot_hardening is True
            self.connection = sqlite3.connect(path)
            self.connection.execute("DELETE FROM campaigns WHERE id=1")
            self.connection.commit()

        def close(self) -> None:
            self.connection.close()

    with pytest.raises(
        DatabasePreflightError,
        match="foreign_key_check|changed prior-column row content",
    ):
        migrate_and_compare(damaged, DeletingStore)

    schema_damaged = tmp_path / "schema-damaged" / "assesshub.db"
    _write_fixture(schema_damaged)

    class SchemaDroppingStore:
        def __init__(self, path: Path, *, boot_hardening: bool) -> None:
            assert boot_hardening is True
            self.connection = sqlite3.connect(path)
            self.connection.execute("DROP INDEX ix_snapshots_campaign")
            self.connection.commit()

        def close(self) -> None:
            self.connection.close()

    with pytest.raises(DatabasePreflightError, match="removed or changed prior index"):
        migrate_and_compare(schema_damaged, SchemaDroppingStore)

    constrained = tmp_path / "constraint-damaged" / "assesshub.db"
    constrained.parent.mkdir()
    connection = sqlite3.connect(constrained)
    connection.executescript("CREATE TABLE x(a INTEGER CHECK(a>0)); INSERT INTO x VALUES(1);")
    connection.close()

    class ConstraintDroppingStore:
        def __init__(self, path: Path, *, boot_hardening: bool) -> None:
            assert boot_hardening is True
            self.connection = sqlite3.connect(path)
            self.connection.executescript(
                "ALTER TABLE x RENAME TO x_old;"
                "CREATE TABLE x(a INTEGER, b INTEGER);"
                "INSERT INTO x(a) SELECT a FROM x_old;"
                "DROP TABLE x_old;"
            )

        def close(self) -> None:
            self.connection.close()

    with pytest.raises(DatabasePreflightError, match="constraints while appending"):
        migrate_and_compare(constrained, ConstraintDroppingStore)
