"""Logical SQLite census for Atlas update-copy migration preflight.

The updater supplies a disposable same-volume copy. This module snapshots every pre-existing
user table, opens/migrates the copy through the current Store owner, then proves every old column
and row survived exactly. New tables, columns, indexes, triggers, and derived authority rows may be
added by the migration; the receipt enumerates both complete before/after states.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import sqlite3
import struct
from pathlib import Path
from typing import Any, Callable


class DatabasePreflightError(RuntimeError):
    """The caller-supplied database copy could not be migrated without lost prior rows."""


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bytes):
        return {"type": "blob", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise DatabasePreflightError("SQLite census encountered invalid Unicode text") from exc
        return {"type": "text", "value": value}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DatabasePreflightError("SQLite census encountered a non-finite real value")
        return {"type": "real-ieee754", "value": struct.pack(">d", value).hex()}
    raise DatabasePreflightError(f"SQLite census encountered unsupported value {type(value).__name__}")


def _rows(connection: sqlite3.Connection, table: str, columns: list[str]) -> dict[str, Any]:
    projection = ",".join(_quote(column) for column in columns)
    order = ",".join(_quote(column) for column in columns)
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(
        f"SELECT {projection} FROM {_quote(table)} ORDER BY {order}"
    ):
        encoded = _canonical([_value(value) for value in row])
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return {"row_count": count, "projected_row_digest": digest.hexdigest()}


def _open_readonly(path: Path) -> sqlite3.Connection:
    uri = path.resolve(strict=True).as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def census(path: str | Path) -> dict[str, Any]:
    database = Path(path)
    connection = _open_readonly(database)
    try:
        quick = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
        if quick != ["ok"]:
            raise DatabasePreflightError("SQLite quick_check did not return exactly ok")
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise DatabasePreflightError("SQLite integrity_check did not return exactly ok")
        foreign_key_errors = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        if foreign_key_errors:
            raise DatabasePreflightError("SQLite foreign_key_check reported violations")
        table_names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables = []
        for table in table_names:
            table_sql_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            table_sql = str(table_sql_row[0]) if table_sql_row and table_sql_row[0] else ""
            columns = [
                {
                    "cid": int(row[0]),
                    "name": str(row[1]),
                    "declared_type": str(row[2]),
                    "not_null": bool(row[3]),
                    "default": row[4],
                    "primary_key_ordinal": int(row[5]),
                }
                for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
            ]
            if not columns:
                raise DatabasePreflightError(f"SQLite table has no visible columns: {table}")
            foreign_keys = [
                {
                    "id": int(row[0]),
                    "sequence": int(row[1]),
                    "referenced_table": str(row[2]),
                    "from_column": str(row[3]),
                    "to_column": None if row[4] is None else str(row[4]),
                    "on_update": str(row[5]),
                    "on_delete": str(row[6]),
                    "match": str(row[7]),
                }
                for row in connection.execute(f"PRAGMA foreign_key_list({_quote(table)})")
            ]
            foreign_keys.sort(key=lambda item: (item["id"], item["sequence"]))
            indexes = []
            for index_row in connection.execute(f"PRAGMA index_list({_quote(table)})"):
                index_name = str(index_row[1])
                columns_detail = [
                    {
                        "sequence": int(detail[0]),
                        "column_id": int(detail[1]),
                        "column_name": None if detail[2] is None else str(detail[2]),
                        "descending": bool(detail[3]),
                        "collation": None if detail[4] is None else str(detail[4]),
                        "key_column": bool(detail[5]),
                    }
                    for detail in connection.execute(f"PRAGMA index_xinfo({_quote(index_name)})")
                ]
                indexes.append({
                    "name": index_name,
                    "unique": bool(index_row[2]),
                    "origin": str(index_row[3]),
                    "partial": bool(index_row[4]),
                    "columns": columns_detail,
                })
            indexes.sort(key=lambda item: item["name"])
            projection = _rows(connection, table, [item["name"] for item in columns])
            tables.append({
                "name": table,
                "table_sql": table_sql,
                "columns": columns,
                "foreign_keys": foreign_keys,
                "indexes": indexes,
                **projection,
            })
        schema_objects = [
            {
                "type": str(row[0]),
                "name": str(row[1]),
                "table": str(row[2]),
                "sql": str(row[3]),
            }
            for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE type IN ('index','trigger','view') AND name NOT LIKE 'sqlite_%' "
                "AND sql IS NOT NULL ORDER BY type, name"
            )
        ]
        sequence = None
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
        ).fetchone():
            sequence = _rows(connection, "sqlite_sequence", ["name", "seq"])
        return {
            "quick_check": "ok",
            "integrity_check": "ok",
            "foreign_key_check": "ok",
            "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
            "table_count": len(tables),
            "tables": tables,
            "table_set_digest": _digest(tables),
            "schema_object_count": len(schema_objects),
            "schema_objects": schema_objects,
            "schema_object_set_digest": _digest(schema_objects),
            "sqlite_sequence": sequence,
        }
    finally:
        connection.close()


def verify_migrated_copy(
    path: str | Path,
    before: dict[str, Any],
    after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Independently verify a candidate-migrated copy against a pre-execution census."""
    database = Path(path).resolve(strict=True)
    after = census(database) if after is None else after
    after_by_name = {item["name"]: item for item in after["tables"]}
    connection = _open_readonly(database)
    preservation = []
    try:
        if after["user_version"] != before["user_version"]:
            raise DatabasePreflightError("migration changed the unsupported SQLite user_version")
        if before.get("sqlite_sequence") is not None and (
            after.get("sqlite_sequence") != before["sqlite_sequence"]
        ):
            raise DatabasePreflightError("migration changed prior AUTOINCREMENT high-water marks")
        after_schema = {
            (item["type"], item["name"]): item for item in after["schema_objects"]
        }
        for prior_object in before["schema_objects"]:
            if after_schema.get((prior_object["type"], prior_object["name"])) != prior_object:
                raise DatabasePreflightError(
                    f"migration removed or changed prior {prior_object['type']} {prior_object['name']}"
                )
        for prior in before["tables"]:
            current = after_by_name.get(prior["name"])
            if current is None:
                raise DatabasePreflightError(f"migration removed prior table {prior['name']}")
            prior_columns = [item["name"] for item in prior["columns"]]
            current_columns = [item["name"] for item in current["columns"]]
            if (
                current_columns[: len(prior_columns)] != prior_columns
                or current["columns"][: len(prior_columns)] != prior["columns"]
                or current["foreign_keys"] != prior["foreign_keys"]
            ):
                raise DatabasePreflightError(
                    f"migration removed, reordered, or renamed prior columns in {prior['name']}"
                )
            current_indexes = {item["name"]: item for item in current["indexes"]}
            if any(current_indexes.get(item["name"]) != item for item in prior["indexes"]):
                raise DatabasePreflightError(
                    f"migration removed or changed prior index semantics in {prior['name']}"
                )
            if (
                len(current["columns"]) == len(prior["columns"])
                and current["table_sql"] != prior["table_sql"]
            ):
                raise DatabasePreflightError(
                    f"migration changed prior table constraints in {prior['name']}"
                )
            if len(current["columns"]) > len(prior["columns"]):
                prior_sql = prior["table_sql"].rstrip()
                if (
                    not prior_sql.endswith(")")
                    or not current["table_sql"].startswith(prior_sql[:-1].rstrip())
                ):
                    raise DatabasePreflightError(
                        f"migration changed prior table constraints while appending columns in "
                        f"{prior['name']}"
                    )
            projected = _rows(connection, prior["name"], prior_columns)
            if (
                projected["row_count"] != prior["row_count"]
                or projected["projected_row_digest"] != prior["projected_row_digest"]
            ):
                raise DatabasePreflightError(
                    f"migration changed prior-column row content in {prior['name']}"
                )
            preservation.append({
                "table": prior["name"],
                "prior_column_count": len(prior_columns),
                **projected,
                "status": "preserved",
            })
    finally:
        connection.close()
    return {
        "schema": "atlas.database-logical-migration/1",
        "status": "pass",
        "before": before,
        "after": after,
        "prior_table_preservation": preservation,
        "prior_table_preservation_digest": _digest(preservation),
    }


def migrate_and_compare(
    path: str | Path,
    store_factory: Callable[..., Any],
) -> dict[str, Any]:
    database = Path(path).resolve(strict=True)
    before = census(database)
    store = None
    try:
        store = store_factory(database, boot_hardening=True)
    finally:
        if store is not None:
            store.close()
    return verify_migrated_copy(database, before)
