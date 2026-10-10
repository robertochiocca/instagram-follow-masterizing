"""Importação, reanálise e exclusão de imagens (fotos próprias e referências)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from database import images as images_repo
from database.connection import Database
from models.analysis import ImageMetrics
from services import image_analysis
from services.image_storage import ImageStorage
from services.image_validation import (
    ImageValidationError,
    safe_display_name,
    validate_image_bytes,
)

log = logging.getLogger(__name__)


@dataclass
class UploadOutcome:
    display_name: str
    ok: bool
    message: str
    image_id: int | None = None


def import_image(
    db: Database,
    storage: ImageStorage,
    data: bytes,
    filename: str,
    kind: str,
    max_bytes: int,
    score_weights: dict | None = None,
) -> UploadOutcome:
    """Valida, sanitiza, analisa e registra uma imagem. Nunca lança erro de validação."""
    try:
        validated = validate_image_bytes(data, filename, max_bytes)
    except ImageValidationError as exc:
        return UploadOutcome(display_name=safe_display_name(filename), ok=False, message=str(exc))

    existing = images_repo.find_by_hash(db, kind, validated.sha256)
    if existing:
        return UploadOutcome(
            validated.display_name, False, "Esta imagem já foi enviada antes.", existing["id"]
        )

    metrics, score, notes = image_analysis.analyze(validated.image, score_weights)
    filename_saved, thumb_saved = storage.save(validated, kind)
    record = {
        "kind": kind,
        "filename": filename_saved,
        "thumb_filename": thumb_saved,
        "original_name": validated.display_name,
        "format": validated.format,
        "width": validated.width,
        "height": validated.height,
        "file_size": validated.size_bytes,
        "sha256": validated.sha256,
        "metrics": metrics.to_dict(),
        "technical_score": score.total,
        "score_breakdown": score.to_dict(),
        "observations": notes,
        "dhash": metrics.dhash,
    }
    try:
        image_id = images_repo.add_image(db, record)
    except Exception:
        storage.delete(kind, filename_saved, thumb_saved)  # não deixar arquivos órfãos
        log.exception("Falha ao registrar imagem no banco (kind=%s)", kind)
        return UploadOutcome(validated.display_name, False, "Erro ao salvar a imagem. Tente novamente.")
    log.info("Imagem importada id=%s kind=%s", image_id, kind)
    return UploadOutcome(validated.display_name, True, "Imagem analisada e salva.", image_id)


def metrics_of(row: dict) -> ImageMetrics | None:
    data = row.get("metrics") or {}
    if not data:
        return None
    try:
        return ImageMetrics.from_dict(data)
    except TypeError:
        return None


def rescore_all(db: Database, weights: dict | None) -> int:
    """Recalcula a pontuação técnica de todas as imagens com novos pesos."""
    updated = 0
    for kind in ("own", "reference"):
        for row in images_repo.list_images(db, kind):
            metrics = metrics_of(row)
            if metrics is None:
                continue
            score = image_analysis.score_metrics(metrics, weights)
            images_repo.update_image(
                db, row["id"], {"technical_score": score.total, "score_breakdown": score.to_dict()}
            )
            updated += 1
    return updated


def delete_image(db: Database, storage: ImageStorage, image_id: int) -> bool:
    row = images_repo.delete_image_row(db, image_id)
    if not row:
        return False
    storage.delete(row["kind"], row["filename"], row["thumb_filename"])
    log.info("Imagem apagada id=%s", image_id)
    return True


def delete_all_images(db: Database, storage: ImageStorage, kind: str) -> int:
    rows = images_repo.delete_rows_by_kind(db, kind)
    storage.delete_all(kind)
    log.info("Todas as imagens apagadas kind=%s total=%s", kind, len(rows))
    return len(rows)
