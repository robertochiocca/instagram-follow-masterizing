"""Versões salvas do feed (sequência de fotos e posições fixadas)."""

from __future__ import annotations

from typing import Any

from database import crud
from database.connection import Database


def _write_items(conn, version_id: int, items: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM feed_items WHERE version_id = ?", (version_id,))
    conn.executemany(
        "INSERT INTO feed_items (version_id, position, image_id, pinned) VALUES (?, ?, ?, ?)",
        [
            (version_id, pos, int(item["image_id"]), int(bool(item.get("pinned"))))
            for pos, item in enumerate(items)
        ],
    )


def save_version(
    db: Database,
    name: str,
    items: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    notes: str = "",
) -> int:
    """`items` = lista ordenada de {"image_id": int, "pinned": bool}."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Dê um nome para a versão do feed.")
    if not items:
        raise ValueError("A sequência está vazia.")
    with db.connect() as conn:
        version_id = crud.insert(
            conn, "feed_versions", {"name": name[:80], "notes": notes, "params": params or {}}
        )
        _write_items(conn, version_id, items)
    return version_id


def update_version(
    db: Database,
    version_id: int,
    items: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
    name: str | None = None,
) -> None:
    data: dict[str, Any] = {"params": params or {}}
    if name:
        data["name"] = name.strip()[:80]
    with db.connect() as conn:
        crud.update(conn, "feed_versions", version_id, data)
        _write_items(conn, version_id, items)


def list_versions(db: Database) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT v.*, COUNT(i.image_id) AS item_count
            FROM feed_versions v LEFT JOIN feed_items i ON i.version_id = v.id
            GROUP BY v.id ORDER BY v.updated_at DESC, v.id DESC
            """
        ).fetchall()
    return [crud.decode_row("feed_versions", r) for r in rows]


def get_version(db: Database, version_id: int) -> dict[str, Any] | None:
    with db.connect() as conn:
        version = crud.get(conn, "feed_versions", version_id)
        if not version:
            return None
        version["items"] = [
            {"image_id": r["image_id"], "pinned": bool(r["pinned"])}
            for r in conn.execute(
                "SELECT image_id, pinned FROM feed_items WHERE version_id = ? ORDER BY position",
                (version_id,),
            )
        ]
    return version


def delete_version(db: Database, version_id: int) -> bool:
    with db.connect() as conn:
        return crud.delete(conn, "feed_versions", version_id)
