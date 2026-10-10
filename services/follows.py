"""Acompanhamento MANUAL de follow-back.

Este módulo apenas organiza anotações do usuário. Ele não segue, não deixa de
seguir, não curte e não envia mensagens — nenhuma ação é feita no Instagram.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from config import today
from database import crud
from database.connection import Database
from models.vocab import FOLLOW_STATUS
from services.handles import normalize_url, normalize_username

# Acima disso, a interface mostra um lembrete sobre comportamento que pode
# parecer automatizado. Não é um limite oficial do Instagram.
WEEKLY_FOLLOW_REMINDER = 50


def _iso(value) -> str | None:
    if value is None or value == "":
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def _clean(data: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "username" in data or not partial:
        out["username"] = normalize_username(data.get("username", ""))
    if "url" in data:
        out["url"] = normalize_url(data.get("url"))
    if "followed_at" in data or not partial:
        out["followed_at"] = _iso(data.get("followed_at")) or today().isoformat()
    if "category" in data:
        out["category"] = (data.get("category") or "").strip()[:60] or None
    if "status" in data:
        if data["status"] not in FOLLOW_STATUS:
            raise ValueError("Status inválido.")
        out["status"] = data["status"]
    if "last_reviewed_at" in data:
        out["last_reviewed_at"] = _iso(data.get("last_reviewed_at"))
    if "notes" in data:
        out["notes"] = (data.get("notes") or "").strip()[:1000] or None
    if "archived" in data:
        out["archived"] = int(bool(data["archived"]))
    return out


def add_follow(db: Database, data: dict[str, Any]) -> int:
    with db.connect() as conn:
        return crud.insert(conn, "follow_tracking", _clean(data))


def update_follow(db: Database, follow_id: int, data: dict[str, Any]) -> None:
    with db.connect() as conn:
        crud.update(conn, "follow_tracking", follow_id, _clean(data, partial=True))


def mark_reviewed(db: Database, follow_id: int, status: str | None = None) -> None:
    data: dict[str, Any] = {"last_reviewed_at": today()}
    if status:
        data["status"] = status
    update_follow(db, follow_id, data)


def set_archived(db: Database, follow_id: int, archived: bool = True) -> None:
    update_follow(db, follow_id, {"archived": archived})


def delete_follow(db: Database, follow_id: int) -> bool:
    with db.connect() as conn:
        return crud.delete(conn, "follow_tracking", follow_id)


def get_follow(db: Database, follow_id: int) -> dict | None:
    with db.connect() as conn:
        return crud.get(conn, "follow_tracking", follow_id)


def list_follows(
    db: Database,
    statuses: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    include_archived: bool = False,
    search: str = "",
    category: str | None = None,
) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = crud.select(conn, "follow_tracking", order_by="followed_at", descending=True)
    if not include_archived:
        rows = [r for r in rows if not r["archived"]]
    if statuses:
        rows = [r for r in rows if r["status"] in statuses]
    if start:
        rows = [r for r in rows if r["followed_at"] >= start.isoformat()]
    if end:
        rows = [r for r in rows if r["followed_at"] <= end.isoformat()]
    if category:
        rows = [r for r in rows if r.get("category") == category]
    term = (search or "").strip().lower().lstrip("@")
    if term:
        rows = [r for r in rows if term in r["username"] or term in (r.get("notes") or "").lower()]
    return rows


def summary(rows: list[dict[str, Any]], reference_day: date | None = None, stale_days: int = 7) -> dict:
    """Contagens por status, taxa de follow-back e pendentes antigos.

    Taxa de follow-back = seguiram de volta / (seguiram + não seguiram) — os
    pendentes ficam de fora porque ainda não têm resposta.
    """
    day = reference_day or today()
    counts = {code: 0 for code in FOLLOW_STATUS}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    decided = counts["seguiu_de_volta"] + counts["nao_seguiu_de_volta"]
    limit = (day - timedelta(days=stale_days)).isoformat()
    stale = [
        r for r in rows
        if r["status"] == "pendente" and (r.get("last_reviewed_at") or r["followed_at"]) <= limit
    ]
    week_start = (day - timedelta(days=7)).isoformat()
    return {
        "counts": counts,
        "total": len(rows),
        "followback_rate": counts["seguiu_de_volta"] / decided * 100 if decided else None,
        "stale_pending": stale,
        "followed_last_7_days": sum(1 for r in rows if r["followed_at"] > week_start),
    }


def to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "usuario": r["username"],
                "url": r.get("url") or "",
                "data_seguiu": r["followed_at"],
                "categoria": r.get("category") or "",
                "status": FOLLOW_STATUS.get(r["status"], r["status"]),
                "ultima_revisao": r.get("last_reviewed_at") or "",
                "arquivado": "sim" if r.get("archived") else "não",
                "observacoes": r.get("notes") or "",
            }
            for r in rows
        ],
        columns=["usuario", "url", "data_seguiu", "categoria", "status", "ultima_revisao",
                 "arquivado", "observacoes"],
    )
