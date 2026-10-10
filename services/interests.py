"""Perfis de interesse adicionados manualmente pelo usuário (sem scraping)."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

import pandas as pd

from config import today
from database import crud
from database.connection import Database
from models.vocab import INTEREST_STATUS, PRIORITY, PRIORITY_ORDER
from services.handles import normalize_url, normalize_username, parse_tags

TEXT_LIMITS = {"reason": 300, "notes": 1000, "category": 60, "source": 60}


def _clean(data: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "username" in data or not partial:
        out["username"] = normalize_username(data.get("username", ""))
    if "url" in data:
        out["url"] = normalize_url(data.get("url"))
    for key, limit in TEXT_LIMITS.items():
        if key in data:
            out[key] = (data.get(key) or "").strip()[:limit] or None
    if "priority" in data:
        if data["priority"] not in PRIORITY:
            raise ValueError("Prioridade inválida.")
        out["priority"] = data["priority"]
    if "status" in data:
        if data["status"] not in INTEREST_STATUS:
            raise ValueError("Status inválido.")
        out["status"] = data["status"]
    if "tags" in data:
        out["tags"] = parse_tags(data.get("tags"))
    if "added_at" in data or not partial:
        added = data.get("added_at") or today()
        out["added_at"] = added.isoformat() if isinstance(added, date) else str(added)
    return out


def add_interest(db: Database, data: dict[str, Any]) -> int:
    record = _clean(data)
    with db.connect() as conn:
        try:
            return crud.insert(conn, "interest_profiles", record)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"@{record['username']} já está na sua lista.") from exc


def update_interest(db: Database, interest_id: int, data: dict[str, Any]) -> None:
    record = _clean(data, partial=True)
    with db.connect() as conn:
        try:
            crud.update(conn, "interest_profiles", interest_id, record)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Já existe outro registro com esse nome de usuário.") from exc


def set_status(db: Database, interest_id: int, status: str) -> None:
    update_interest(db, interest_id, {"status": status})


def delete_interest(db: Database, interest_id: int) -> bool:
    with db.connect() as conn:
        return crud.delete(conn, "interest_profiles", interest_id)


def get_interest(db: Database, interest_id: int) -> dict | None:
    with db.connect() as conn:
        return crud.get(conn, "interest_profiles", interest_id)


SORTS = {
    "recentes": "Mais recentes",
    "prioridade": "Prioridade",
    "usuario": "Nome de usuário (A–Z)",
    "status": "Status",
}


def list_interests(
    db: Database,
    search: str = "",
    categories: list[str] | None = None,
    statuses: list[str] | None = None,
    priorities: list[str] | None = None,
    tag: str | None = None,
    sort: str = "recentes",
) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = crud.select(conn, "interest_profiles")
    term = (search or "").strip().lower().lstrip("@")
    if term:
        rows = [
            r for r in rows
            if term in " ".join(
                str(r.get(k) or "") for k in ("username", "reason", "notes", "category", "source")
            ).lower()
            or any(term in t for t in r.get("tags") or [])
        ]
    if categories:
        rows = [r for r in rows if r.get("category") in categories]
    if statuses:
        rows = [r for r in rows if r.get("status") in statuses]
    if priorities:
        rows = [r for r in rows if r.get("priority") in priorities]
    if tag:
        rows = [r for r in rows if tag in (r.get("tags") or [])]
    if sort == "prioridade":
        rows.sort(key=lambda r: (PRIORITY_ORDER.get(r["priority"], 9), r["username"]))
    elif sort == "usuario":
        rows.sort(key=lambda r: r["username"])
    elif sort == "status":
        order = list(INTEREST_STATUS)
        rows.sort(key=lambda r: (order.index(r["status"]), r["username"]))
    else:
        rows.sort(key=lambda r: (r.get("added_at") or "", r["id"]), reverse=True)
    return rows


def all_tags(db: Database) -> list[str]:
    with db.connect() as conn:
        rows = crud.select(conn, "interest_profiles")
    return sorted({t for r in rows for t in r.get("tags") or []})


def to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "usuario": r["username"],
                "url": r.get("url") or "",
                "categoria": r.get("category") or "",
                "motivo": r.get("reason") or "",
                "data_inclusao": r.get("added_at") or "",
                "origem": r.get("source") or "",
                "prioridade": PRIORITY.get(r.get("priority"), ""),
                "status": INTEREST_STATUS.get(r.get("status"), ""),
                "tags": ", ".join(r.get("tags") or []),
                "observacoes": r.get("notes") or "",
            }
            for r in rows
        ],
        columns=["usuario", "url", "categoria", "motivo", "data_inclusao", "origem",
                 "prioridade", "status", "tags", "observacoes"],
    )
