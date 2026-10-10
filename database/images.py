"""Repositório de imagens (fotos próprias e referências) e categorias estéticas."""

from __future__ import annotations

import sqlite3
from typing import Any

from config import now_iso
from database import crud
from database.connection import Database

_ORDERINGS = {
    "recent": "created_at DESC, id DESC",
    "score": "technical_score DESC, id DESC",
    "rating": "COALESCE(user_rating, 0) DESC, technical_score DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
}


def _attach_categories(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    marks = ",".join("?" for _ in ids)
    links: dict[int, list[int]] = {i: [] for i in ids}
    for link in conn.execute(
        f"SELECT image_id, category_id FROM image_categories WHERE image_id IN ({marks})", ids
    ):
        links[link["image_id"]].append(link["category_id"])
    for r in rows:
        r["category_ids"] = sorted(links[r["id"]])
    return rows


def _set_categories(conn: sqlite3.Connection, image_id: int, category_ids) -> None:
    conn.execute("DELETE FROM image_categories WHERE image_id = ?", (image_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO image_categories (image_id, category_id) VALUES (?, ?)",
        [(image_id, int(c)) for c in set(category_ids or [])],
    )


def add_image(db: Database, record: dict[str, Any], category_ids=None) -> int:
    with db.connect() as conn:
        image_id = crud.insert(conn, "images", record)
        if category_ids:
            _set_categories(conn, image_id, category_ids)
    return image_id


def get_image(db: Database, image_id: int) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = crud.get(conn, "images", image_id)
        return _attach_categories(conn, [row])[0] if row else None


def find_by_hash(db: Database, kind: str, sha256: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM images WHERE kind = ? AND sha256 = ?", (kind, sha256)
        ).fetchone()
    return crud.decode_row("images", row)


def list_images(
    db: Database,
    kind: str,
    *,
    favorites_only: bool = False,
    in_pool_only: bool = False,
    order: str = "recent",
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM images WHERE kind = ?"
    params: list[Any] = [kind]
    if favorites_only:
        sql += " AND favorite = 1"
    if in_pool_only:
        sql += " AND in_feed_pool = 1"
    sql += " ORDER BY " + _ORDERINGS.get(order, _ORDERINGS["recent"])
    with db.connect() as conn:
        rows = [crud.decode_row("images", r) for r in conn.execute(sql, params)]
        return _attach_categories(conn, rows)


def get_images_by_ids(db: Database, ids) -> dict[int, dict[str, Any]]:
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    with db.connect() as conn:
        rows = [
            crud.decode_row("images", r)
            for r in conn.execute(f"SELECT * FROM images WHERE id IN ({marks})", ids)
        ]
        rows = _attach_categories(conn, rows)
    return {r["id"]: r for r in rows}


def update_image(db: Database, image_id: int, data: dict[str, Any], category_ids=None) -> bool:
    with db.connect() as conn:
        changed = crud.update(conn, "images", image_id, data) if data else False
        if category_ids is not None:
            _set_categories(conn, image_id, category_ids)
            if not data:
                crud.update(conn, "images", image_id, {})
                changed = True
    return changed


def set_feed_pool(db: Database, image_ids, in_pool: bool) -> None:
    with db.connect() as conn:
        conn.executemany(
            "UPDATE images SET in_feed_pool = ?, updated_at = ? WHERE id = ? AND kind = 'own'",
            [(int(in_pool), now_iso(), int(i)) for i in image_ids],
        )


def delete_image_row(db: Database, image_id: int) -> dict[str, Any] | None:
    """Apaga o registro (e vínculos em cascata). Devolve a linha para limpeza dos arquivos."""
    with db.connect() as conn:
        row = crud.get(conn, "images", image_id)
        if row:
            crud.delete(conn, "images", image_id)
    return row


def delete_rows_by_kind(db: Database, kind: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = crud.select(conn, "images", {"kind": kind})
        conn.execute("DELETE FROM images WHERE kind = ?", (kind,))
    return rows


def count_images(db: Database, kind: str) -> int:
    with db.connect() as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM images WHERE kind = ?", (kind,)).fetchone()[0]
        )


# --- Categorias ------------------------------------------------------------------


def list_categories(db: Database) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(ic.image_id) AS usage
            FROM categories c LEFT JOIN image_categories ic ON ic.category_id = c.id
            GROUP BY c.id ORDER BY c.id
            """
        ).fetchall()
    return [dict(r) for r in rows]


def add_category(db: Database, name: str, description: str = "", weight: float = 1.0) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Informe um nome para a categoria.")
    if len(name) > 60:
        raise ValueError("O nome da categoria deve ter no máximo 60 caracteres.")
    with db.connect() as conn:
        try:
            return crud.insert(
                conn,
                "categories",
                {
                    "name": name,
                    "description": (description or "").strip(),
                    "weight": float(weight),
                    "created_at": now_iso(),
                },
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Já existe uma categoria com esse nome.") from exc


def update_category(db: Database, category_id: int, **fields: Any) -> None:
    data = {k: v for k, v in fields.items() if k in {"name", "description", "weight"}}
    if "name" in data:
        data["name"] = (data["name"] or "").strip()
        if not data["name"]:
            raise ValueError("O nome da categoria não pode ficar vazio.")
    if "weight" in data:
        data["weight"] = max(0.0, min(3.0, float(data["weight"])))
    with db.connect() as conn:
        try:
            crud.update(conn, "categories", category_id, data)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Já existe uma categoria com esse nome.") from exc


def delete_category(db: Database, category_id: int) -> bool:
    with db.connect() as conn:
        return crud.delete(conn, "categories", category_id)
