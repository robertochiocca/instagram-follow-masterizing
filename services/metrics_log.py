"""Registro manual de métricas do perfil (dados reais informados pelo usuário)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from database import crud
from database.connection import Database
from services.growth import METRIC_COLUMNS

OPTIONAL_COLUMNS = [c for c in METRIC_COLUMNS if c != "followers"]

EXPORT_NAMES = {
    "date": "data",
    "followers": "seguidores",
    "following": "seguindo",
    "posts": "publicacoes",
    "reach": "alcance",
    "views": "visualizacoes",
    "profile_visits": "visitas_perfil",
    "interactions": "interacoes",
    "source": "origem",
    "notes": "observacoes",
}


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    day = data.get("date")
    if not day:
        raise ValueError("Informe a data.")
    out: dict[str, Any] = {"date": day.isoformat() if isinstance(day, date) else str(day)}
    followers = data.get("followers")
    if followers is not None and int(followers) < 0:
        raise ValueError("A quantidade de seguidores não pode ser negativa.")
    out["followers"] = None if followers is None else int(followers)
    for col in OPTIONAL_COLUMNS:
        value = data.get(col)
        if value is None or value == "":
            out[col] = None
        else:
            if int(value) < 0:
                raise ValueError("Os valores não podem ser negativos.")
            out[col] = int(value)
    out["notes"] = (data.get("notes") or "").strip()[:500] or None
    return out


def upsert_metric(db: Database, data: dict[str, Any]) -> tuple[int, bool]:
    """Grava o registro do dia; se já existir um para a data, atualiza. Devolve (id, criado?).

    Na atualização, campos vazios (None) mantêm o valor já registrado: salvar só
    os seguidores não apaga alcance, visualizações ou observações do mesmo dia, e
    completar o alcance de um dia passado não altera os seguidores daquele dia.
    Para uma data nova, os seguidores são obrigatórios.
    """
    record = _clean(data)
    record["source"] = "manual"
    with db.connect() as conn:
        existing = conn.execute("SELECT id FROM metrics WHERE date = ?", (record["date"],)).fetchone()
        if existing:
            changes = {k: v for k, v in record.items() if v is not None}
            crud.update(conn, "metrics", existing["id"], changes)
            return existing["id"], False
        if record["followers"] is None:
            raise ValueError("Informe a quantidade de seguidores para registrar uma nova data.")
        return crud.insert(conn, "metrics", record), True


def list_metrics(db: Database) -> list[dict[str, Any]]:
    with db.connect() as conn:
        return crud.select(conn, "metrics", order_by="date")


def delete_metric(db: Database, metric_id: int) -> bool:
    with db.connect() as conn:
        return crud.delete(conn, "metrics", metric_id)


def export_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    cols = list(EXPORT_NAMES)
    df = pd.DataFrame(rows or [], columns=["id", *cols])[cols]
    for col in METRIC_COLUMNS:  # contagens continuam inteiras mesmo com valores vazios
        df[col] = df[col].astype("Int64")
    return df.rename(columns=EXPORT_NAMES)
