"""Configurações chave/valor (JSON) e a linha única do perfil."""

from __future__ import annotations

import copy
import json
from typing import Any

from config import now_iso
from database import crud
from database.connection import Database
from models.defaults import DEFAULT_SETTINGS


def get_setting(db: Database, key: str, default: Any = None) -> Any:
    if default is None and key in DEFAULT_SETTINGS:
        default = copy.deepcopy(DEFAULT_SETTINGS[key])
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        value = json.loads(row["value"])
    except json.JSONDecodeError:
        return default
    # Para dicionários, completa chaves novas com os padrões (compatibilidade).
    if isinstance(default, dict) and isinstance(value, dict):
        return {**default, **value}
    return value


def set_setting(db: Database, key: str, value: Any) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def reset_setting(db: Database, key: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def get_profile(db: Database) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO profile (id, updated_at) VALUES (1, ?)", (now_iso(),))
            row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    return crud.decode_row("profile", row)


def save_profile(db: Database, data: dict[str, Any]) -> None:
    data = {**data, "updated_at": now_iso()}
    with db.connect() as conn:
        crud.update(conn, "profile", 1, data)
