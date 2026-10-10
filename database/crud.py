"""Operações CRUD genéricas com proteção contra injeção de SQL.

Nomes de tabela vêm de uma lista fixa e nomes de coluna são conferidos contra
o schema real (`PRAGMA table_info`); valores são sempre parametrizados.
Colunas JSON são codificadas e decodificadas automaticamente.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from config import now_iso

TABLES = frozenset(
    {
        "images",
        "categories",
        "image_categories",
        "feed_versions",
        "feed_items",
        "profile",
        "interest_profiles",
        "follow_tracking",
        "metrics",
        "content_plan",
        "settings",
    }
)

JSON_COLUMNS: dict[str, frozenset[str]] = {
    "images": frozenset({"metrics", "score_breakdown", "observations", "tags"}),
    "feed_versions": frozenset({"params"}),
    "profile": frozenset({"bio_languages"}),
    "interest_profiles": frozenset({"tags"}),
}

# Tabelas com colunas created_at/updated_at preenchidas automaticamente.
_TIMESTAMPED = frozenset(
    {"images", "feed_versions", "interest_profiles", "follow_tracking", "metrics", "content_plan"}
)


def _check_table(table: str) -> None:
    if table not in TABLES:
        raise ValueError(f"Tabela desconhecida: {table}")


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    _check_table(table)
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _check_columns(conn: sqlite3.Connection, table: str, names) -> None:
    allowed = set(table_columns(conn, table))
    unknown = [n for n in names if n not in allowed]
    if unknown:
        raise ValueError(f"Colunas inválidas para {table}: {', '.join(unknown)}")


def encode_row(table: str, data: dict[str, Any]) -> dict[str, Any]:
    json_cols = JSON_COLUMNS.get(table, frozenset())
    out = {}
    for key, value in data.items():
        if key in json_cols and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            value = int(value)
        out[key] = value
    return out


def decode_row(table: str, row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in JSON_COLUMNS.get(table, frozenset()):
        if key in data and isinstance(data[key], str):
            try:
                data[key] = json.loads(data[key])
            except json.JSONDecodeError:
                data[key] = None
    return data


def insert(conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> int:
    _check_table(table)
    data = dict(data)
    if table in _TIMESTAMPED:
        ts = now_iso()
        data.setdefault("created_at", ts)
        data.setdefault("updated_at", ts)
    _check_columns(conn, table, data)
    data = encode_row(table, data)
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, table: str, row_id: int, data: dict[str, Any]) -> bool:
    _check_table(table)
    data = {k: v for k, v in data.items() if k not in {"id", "created_at"}}
    if not data:
        return False
    if table in _TIMESTAMPED:
        data["updated_at"] = now_iso()
    _check_columns(conn, table, data)
    data = encode_row(table, data)
    assignments = ", ".join(f"{k} = ?" for k in data)
    cur = conn.execute(
        f"UPDATE {table} SET {assignments} WHERE id = ?", (*data.values(), int(row_id))
    )
    return cur.rowcount > 0


def delete(conn: sqlite3.Connection, table: str, row_id: int) -> bool:
    _check_table(table)
    cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (int(row_id),))
    return cur.rowcount > 0


def get(conn: sqlite3.Connection, table: str, row_id: int) -> dict[str, Any] | None:
    _check_table(table)
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (int(row_id),)).fetchone()
    return decode_row(table, row)


def select(
    conn: sqlite3.Connection,
    table: str,
    where: dict[str, Any] | None = None,
    order_by: str | None = None,
    descending: bool = False,
) -> list[dict[str, Any]]:
    """SELECT simples com igualdade nas colunas de `where`."""
    _check_table(table)
    where = where or {}
    names = list(where)
    if order_by:
        names.append(order_by)
    _check_columns(conn, table, names)
    sql = f"SELECT * FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
    if order_by:
        sql += f" ORDER BY {order_by} {'DESC' if descending else 'ASC'}, id"
    rows = conn.execute(sql, tuple(encode_row(table, where).values())).fetchall()
    return [decode_row(table, r) for r in rows]


def count(conn: sqlite3.Connection, table: str) -> int:
    _check_table(table)
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
