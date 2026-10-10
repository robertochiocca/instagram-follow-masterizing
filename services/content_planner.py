"""Planejador de conteúdo: calendário, rotina sustentável e análise de resultados."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from config import today
from database import crud
from database.connection import Database
from models.vocab import CONTENT_STATUS, CONTENT_TYPES, WEEKDAYS

RESULT_FIELDS = ("reach", "views", "likes", "comments", "saves", "shares", "follows_gained")

DEFAULT_OBJECTIVE = {
    "reels": "Alcance (novas pessoas)",
    "carrossel": "Conexão com quem já segue",
    "foto": "Mostrar estilo pessoal",
    "stories": "Gerar conversas",
}


def _iso(value) -> str | None:
    if value in (None, ""):
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def _clean(data: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "planned_date" in data or not partial:
        if not data.get("planned_date"):
            raise ValueError("Informe a data planejada.")
        out["planned_date"] = _iso(data["planned_date"])
    if "content_type" in data or not partial:
        if data.get("content_type") not in CONTENT_TYPES:
            raise ValueError("Tipo de conteúdo inválido.")
        out["content_type"] = data["content_type"]
    if "status" in data:
        if data["status"] not in CONTENT_STATUS:
            raise ValueError("Status inválido.")
        out["status"] = data["status"]
    for key, limit in (("theme", 120), ("objective", 120), ("caption", 2200), ("result_notes", 1000),
                       ("learnings", 1000)):
        if key in data:
            out[key] = (data.get(key) or "").strip()[:limit] or None
    if "published_date" in data:
        out["published_date"] = _iso(data.get("published_date"))
    for key in RESULT_FIELDS:
        if key in data:
            value = data.get(key)
            if value in (None, ""):
                out[key] = None
            else:
                value = int(value)
                if value < 0 and key != "follows_gained":
                    raise ValueError("Métricas não podem ser negativas.")
                out[key] = value
    return out


def add_item(db: Database, data: dict[str, Any]) -> int:
    with db.connect() as conn:
        return crud.insert(conn, "content_plan", _clean(data))


def add_items(db: Database, items: list[dict[str, Any]]) -> int:
    with db.connect() as conn:
        for item in items:
            crud.insert(conn, "content_plan", _clean(item))
    return len(items)


def update_item(db: Database, item_id: int, data: dict[str, Any]) -> None:
    record = _clean(data, partial=True)
    if record.get("status") == "publicado" and not record.get("published_date"):
        current = get_item(db, item_id)
        if current and not current.get("published_date"):
            # Publicado antes da data planejada: registra hoje, nunca uma data futura.
            record["published_date"] = min(current["planned_date"], today().isoformat())
    with db.connect() as conn:
        crud.update(conn, "content_plan", item_id, record)


def delete_item(db: Database, item_id: int) -> bool:
    with db.connect() as conn:
        return crud.delete(conn, "content_plan", item_id)


def get_item(db: Database, item_id: int) -> dict | None:
    with db.connect() as conn:
        return crud.get(conn, "content_plan", item_id)


def list_items(
    db: Database,
    statuses: list[str] | None = None,
    types: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = crud.select(conn, "content_plan", order_by="planned_date")
    if statuses:
        rows = [r for r in rows if r["status"] in statuses]
    if types:
        rows = [r for r in rows if r["content_type"] in types]
    if start:
        rows = [r for r in rows if r["planned_date"] >= start.isoformat()]
    if end:
        rows = [r for r in rows if r["planned_date"] <= end.isoformat()]
    return rows


def published_since(db: Database, since: date) -> int:
    with db.connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM content_plan WHERE status = 'publicado' "
                "AND content_type != 'stories' AND COALESCE(published_date, planned_date) >= ?",
                (since.isoformat(),),
            ).fetchone()[0]
        )


# --- Rotina sugerida ------------------------------------------------------------------------


def frequency_warnings(freq: dict[str, Any]) -> list[str]:
    feed = int(freq.get("reels", 0)) + int(freq.get("carrossel", 0)) + int(freq.get("foto", 0))
    out = []
    if feed == 0:
        out.append("Sem publicações no feed: o perfil fica parado para quem visita.")
    if feed > 7:
        out.append("Mais de uma publicação por dia é difícil de sustentar; qualidade e regularidade "
                   "pesam mais que volume.")
    elif int(freq.get("reels", 0)) > 4:
        out.append("Mais de 4 Reels por semana exige muito tempo de gravação e edição; teste se é sustentável.")
    if int(freq.get("stories", 0)) > 14:
        out.append("Stories demais podem cansar; algumas por dia já mantêm o perfil ativo.")
    if not freq.get("weekdays"):
        out.append("Escolha ao menos um dia da semana disponível.")
    return out


def generate_schedule(
    start: date,
    weeks: int,
    frequency: dict[str, Any],
    themes: list[str],
) -> list[dict[str, Any]]:
    """Distribui publicações nos dias escolhidos e Stories nos demais dias.

    Os temas giram em sequência para alternar assuntos.
    """
    weekdays = [WEEKDAYS.index(d) for d in frequency.get("weekdays") or [] if d in WEEKDAYS] or [1, 3, 5]
    weekdays.sort()
    themes = themes or ["Livre"]
    feed_types = (
        ["reels"] * int(frequency.get("reels", 0))
        + ["carrossel"] * int(frequency.get("carrossel", 0))
        + ["foto"] * int(frequency.get("foto", 0))
    )
    # Intercala tipos (ex.: reels, carrossel, reels) em vez de agrupar.
    ordered: list[str] = []
    pools = {t: feed_types.count(t) for t in ("reels", "carrossel", "foto")}
    while sum(pools.values()):
        for t in ("reels", "carrossel", "foto"):
            if pools[t]:
                ordered.append(t)
                pools[t] -= 1
    stories = int(frequency.get("stories", 0))
    items: list[dict[str, Any]] = []
    theme_index = 0
    week_start = start - timedelta(days=start.weekday())
    for w in range(max(1, weeks)):
        base = week_start + timedelta(weeks=w)
        post_days = [base + timedelta(days=d) for d in weekdays]
        for i, ctype in enumerate(ordered):
            day = post_days[i % len(post_days)]
            if day < start:
                continue
            items.append({
                "planned_date": day,
                "content_type": ctype,
                "theme": themes[theme_index % len(themes)],
                "objective": DEFAULT_OBJECTIVE[ctype],
                "status": "planejado",
            })
            theme_index += 1
        other_days = [base + timedelta(days=d) for d in range(7) if d not in weekdays] or post_days
        for i in range(stories):
            day = other_days[i % len(other_days)]
            if day < start:
                continue
            items.append({
                "planned_date": day,
                "content_type": "stories",
                "theme": themes[(theme_index + i) % len(themes)],
                "objective": DEFAULT_OBJECTIVE["stories"],
                "status": "ideia",
            })
    items.sort(key=lambda it: (it["planned_date"], it["content_type"] == "stories"))
    return items


# --- Resultados --------------------------------------------------------------------------------


def interactions(item: dict[str, Any]) -> int | None:
    values = [item.get(k) for k in ("likes", "comments", "saves", "shares")]
    if all(v is None for v in values):
        return None
    return sum(int(v or 0) for v in values)


def engagement(item: dict[str, Any]) -> float | None:
    """(curtidas + comentários + salvamentos + compartilhamentos) ÷ alcance × 100."""
    total = interactions(item)
    reach = item.get("reach")
    if total is None or not reach:
        return None
    return total / reach * 100


def results_table(items: list[dict[str, Any]]) -> pd.DataFrame:
    published = [i for i in items if i["status"] == "publicado"]
    rows = []
    for it in published:
        rows.append({
            "data": it.get("published_date") or it["planned_date"],
            "tipo": CONTENT_TYPES[it["content_type"]],
            "tema": it.get("theme") or "",
            "alcance": it.get("reach"),
            "visualizacoes": it.get("views"),
            "interacoes": interactions(it),
            "engajamento_pct": engagement(it),
            "novos_seguidores": it.get("follows_gained"),
            "aprendizados": it.get("learnings") or "",
        })
    df = pd.DataFrame(rows, columns=["data", "tipo", "tema", "alcance", "visualizacoes", "interacoes",
                                     "engajamento_pct", "novos_seguidores", "aprendizados"])
    if not df.empty:
        df["engajamento_pct"] = pd.to_numeric(df["engajamento_pct"]).round(2)
        avg = df["engajamento_pct"].mean()
        df["vs_media_pp"] = (df["engajamento_pct"] - avg).round(2)
    return df


def best_groups(items: list[dict[str, Any]], key: str) -> pd.DataFrame:
    """Média de engajamento e alcance por tipo ou tema (somente publicados com dados)."""
    df = results_table(items)
    if df.empty:
        return pd.DataFrame(columns=[key, "publicacoes", "engajamento_medio_pct", "alcance_medio"])
    grouped = (
        df.groupby(key)
        .agg(publicacoes=("data", "count"), engajamento_medio_pct=("engajamento_pct", "mean"),
             alcance_medio=("alcance", "mean"))
        .reset_index()
        .sort_values("engajamento_medio_pct", ascending=False)
    )
    grouped["engajamento_medio_pct"] = grouped["engajamento_medio_pct"].round(2)
    grouped["alcance_medio"] = grouped["alcance_medio"].round(0)
    return grouped


def to_dataframe(items: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "data_planejada": it["planned_date"],
                "tipo": CONTENT_TYPES.get(it["content_type"], it["content_type"]),
                "tema": it.get("theme") or "",
                "objetivo": it.get("objective") or "",
                "legenda": it.get("caption") or "",
                "status": CONTENT_STATUS.get(it["status"], it["status"]),
                "data_publicacao": it.get("published_date") or "",
                **{k: it.get(k) for k in RESULT_FIELDS},
                "notas_resultado": it.get("result_notes") or "",
                "aprendizados": it.get("learnings") or "",
            }
            for it in items
        ]
    )
