"""Armazenamento privado das imagens em disco.

- Nomes de arquivo gerados pela aplicação (UUID), nunca o nome enviado.
- Cópia sanitizada: a imagem é recodificada sem metadados EXIF (inclusive GPS).
- Escrita atômica (arquivo .tmp + rename) e limpeza de temporários órfãos.
- Estrutura: <base>/<kind>/full/<uuid>.<ext> e <base>/<kind>/thumbs/<uuid>.jpg
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

from PIL import Image

from models.vocab import FORMAT_EXTENSION, IMAGE_KINDS
from services.image_validation import ValidatedImage

THUMB_SIZE = 512
_FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")


class ImageStorage:
    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir).resolve()

    def _dir(self, kind: str, sub: str) -> Path:
        if kind not in IMAGE_KINDS:
            raise ValueError("Tipo de imagem inválido.")
        path = self.base_dir / kind / sub
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe(self, kind: str, sub: str, filename: str) -> Path:
        if not filename or not _FILENAME_RE.match(filename):
            raise ValueError("Nome de arquivo inválido.")
        path = (self._dir(kind, sub) / filename).resolve()
        if self.base_dir not in path.parents:
            raise ValueError("Caminho fora da pasta de dados.")
        return path

    def path(self, kind: str, filename: str) -> Path:
        return self._safe(kind, "full", filename)

    def thumb_path(self, kind: str, filename: str) -> Path:
        return self._safe(kind, "thumbs", filename)

    @staticmethod
    def _atomic_save(img: Image.Image, dest: Path, fmt: str, **options) -> None:
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            with open(tmp, "wb") as fh:
                img.save(fh, format=fmt, **options)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)

    def save(self, validated: ValidatedImage, kind: str) -> tuple[str, str]:
        """Grava a imagem sanitizada e a miniatura; devolve (arquivo, miniatura)."""
        stem = uuid.uuid4().hex
        ext = FORMAT_EXTENSION[validated.format]
        filename = f"{stem}.{ext}"
        thumb_name = f"{stem}.jpg"
        options = {
            "JPEG": {"quality": 92, "optimize": True},
            "PNG": {"optimize": True},
            "WEBP": {"quality": 90},
        }[validated.format]
        full_path = self.path(kind, filename)
        self._atomic_save(validated.image, full_path, validated.format, **options)
        try:
            thumb = validated.image.copy()
            thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
            self._atomic_save(
                thumb, self.thumb_path(kind, thumb_name), "JPEG", quality=82, optimize=True
            )
        except Exception:
            full_path.unlink(missing_ok=True)
            raise
        return filename, thumb_name

    def delete(self, kind: str, filename: str | None, thumb_filename: str | None) -> None:
        for sub, name in (("full", filename), ("thumbs", thumb_filename)):
            if name and _FILENAME_RE.match(name):
                self._safe(kind, sub, name).unlink(missing_ok=True)

    def delete_all(self, kind: str) -> int:
        """Remove todos os arquivos de um tipo; devolve quantos arquivos foram apagados."""
        if kind not in IMAGE_KINDS:
            raise ValueError("Tipo de imagem inválido.")
        root = self.base_dir / kind
        removed = sum(1 for p in root.rglob("*") if p.is_file()) if root.exists() else 0
        shutil.rmtree(root, ignore_errors=True)
        return removed

    def cleanup_temp(self) -> int:
        """Apaga arquivos .tmp esquecidos por gravações interrompidas."""
        if not self.base_dir.exists():
            return 0
        removed = 0
        for tmp in self.base_dir.rglob("*.tmp"):
            tmp.unlink(missing_ok=True)
            removed += 1
        return removed

    def usage(self) -> tuple[int, int]:
        """(quantidade de arquivos, bytes ocupados)."""
        if not self.base_dir.exists():
            return 0, 0
        files = [p for p in self.base_dir.rglob("*") if p.is_file()]
        return len(files), sum(p.stat().st_size for p in files)
