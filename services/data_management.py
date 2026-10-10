"""Exportação completa, backup e exclusão dos dados do usuário."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

import pandas as pd

from config import now_iso
from database import crud
from database.connection import Database
from database.schema import seed_defaults
from services.csv_io import to_csv_bytes
from services.image_storage import ImageStorage

log = logging.getLogger(__name__)

EXPORT_TABLES = [
    "profile",
    "images",
    "categories",
    "image_categories",
    "feed_versions",
    "feed_items",
    "interest_profiles",
    "follow_tracking",
    "metrics",
    "content_plan",
    "settings",
]
# Ordem de exclusão respeitando chaves estrangeiras.
_DELETE_ORDER = [
    "feed_items",
    "feed_versions",
    "image_categories",
    "images",
    "categories",
    "interest_profiles",
    "follow_tracking",
    "metrics",
    "content_plan",
    "settings",
    "profile",
]


def _table_rows(conn, table: str) -> list[dict[str, Any]]:
    return [crud.decode_row(table, r) for r in conn.execute(f"SELECT * FROM {table}")]


def export_all_zip(db: Database, storage: ImageStorage, include_images: bool = True) -> bytes:
    """ZIP com JSON completo, um CSV por tabela e (opcionalmente) as imagens."""
    buf = io.BytesIO()
    with db.connect() as conn:
        tables = {t: _table_rows(conn, t) for t in EXPORT_TABLES}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "dados.json",
            json.dumps({"exportado_em": now_iso(), "tabelas": tables}, ensure_ascii=False, indent=2),
        )
        for table, rows in tables.items():
            df = pd.DataFrame(rows)
            for col in df.columns:
                df[col] = df[col].map(
                    lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                )
            zf.writestr(f"csv/{table}.csv", to_csv_bytes(df))
        if include_images:
            for row in tables["images"]:
                path = storage.path(row["kind"], row["filename"])
                if path.exists():
                    folder = "minhas_fotos" if row["kind"] == "own" else "referencias"
                    zf.write(path, f"imagens/{folder}/{row['id']}_{row['filename']}")
        zf.writestr(
            "LEIA-ME.txt",
            "Exportação completa do Instagram Growth Tool.\n"
            "- dados.json: todas as tabelas em JSON.\n"
            "- csv/: uma planilha por tabela (UTF-8).\n"
            "- imagens/: cópias sanitizadas (sem EXIF) das suas fotos e referências, se incluídas.\n"
            "Guarde este arquivo em local seguro: ele contém seus dados pessoais.\n",
        )
    return buf.getvalue()


def delete_all_data(db: Database, storage: ImageStorage) -> None:
    """Apaga TODOS os registros e imagens; recria apenas os padrões iniciais."""
    with db.connect() as conn:
        for table in _DELETE_ORDER:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")
        seed_defaults(conn)
    for kind in ("own", "reference"):
        storage.delete_all(kind)
    with db.connect() as conn:
        conn.execute("VACUUM")  # remove restos dos dados apagados do arquivo
    log.info("Todos os dados foram apagados pelo usuário.")


def summary_counts(db: Database) -> dict[str, int]:
    with db.connect() as conn:
        counts = {t: crud.count(conn, t) for t in EXPORT_TABLES if t not in {"profile", "settings"}}
        counts["own_images"] = conn.execute(
            "SELECT COUNT(*) FROM images WHERE kind = 'own'"
        ).fetchone()[0]
        counts["reference_images"] = conn.execute(
            "SELECT COUNT(*) FROM images WHERE kind = 'reference'"
        ).fetchone()[0]
    return counts
