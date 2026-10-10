"""Validação de uploads de imagem: extensão, tamanho e conteúdo real.

Mensagens de erro são genéricas e não incluem conteúdo do arquivo.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import PurePath

from PIL import Image, ImageOps, UnidentifiedImageError

from config import MAX_IMAGE_PIXELS
from models.vocab import ALLOWED_EXTENSIONS, ALLOWED_FORMATS

MIN_SIDE_PX = 64

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageValidationError(ValueError):
    """Erro com mensagem pronta para exibir ao usuário."""


@dataclass
class ValidatedImage:
    image: Image.Image  # RGB, orientação EXIF já aplicada
    format: str  # JPEG, PNG ou WEBP
    width: int
    height: int
    size_bytes: int
    sha256: str
    display_name: str  # nome original reduzido, apenas para exibição


def safe_display_name(filename: str) -> str:
    """Nome curto e sem diretórios, usado só para exibição na interface."""
    name = PurePath((filename or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable())
    return name[:120] or "imagem"


def to_rgb(img: Image.Image) -> Image.Image:
    """Converte qualquer modo para RGB, compondo transparência sobre branco."""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def validate_image_bytes(data: bytes, filename: str, max_bytes: int) -> ValidatedImage:
    ext = PurePath((filename or "").lower()).suffix
    if ext not in ALLOWED_EXTENSIONS:
        raise ImageValidationError("Formato não permitido. Envie arquivos JPG, JPEG, PNG ou WEBP.")
    size = len(data or b"")
    if size == 0:
        raise ImageValidationError("O arquivo está vazio.")
    if size > max_bytes:
        raise ImageValidationError(
            f"Arquivo maior que o limite de {max_bytes / (1024 * 1024):.0f} MB."
        )

    corrupted = ImageValidationError("Arquivo corrompido ou que não é uma imagem válida.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            real_format = probe.format
            probe.verify()  # checa a estrutura; o objeto fica inutilizável depois
            img = Image.open(io.BytesIO(data))
            img.load()  # decodifica todos os pixels; detecta arquivos truncados
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageValidationError("Imagem com dimensões grandes demais para processar.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as exc:
        raise corrupted from exc

    if real_format not in ALLOWED_FORMATS:
        raise ImageValidationError("O conteúdo não é JPG, PNG ou WEBP.")
    if real_format != ALLOWED_EXTENSIONS[ext]:
        raise ImageValidationError("A extensão do arquivo não corresponde ao conteúdo da imagem.")

    try:
        img = ImageOps.exif_transpose(img)
    except Exception:  # EXIF malformado não deve impedir o uso da imagem
        pass
    rgb = to_rgb(img)
    width, height = rgb.size
    if min(width, height) < MIN_SIDE_PX:
        raise ImageValidationError(f"Imagem pequena demais (mínimo de {MIN_SIDE_PX} px por lado).")

    return ValidatedImage(
        image=rgb,
        format=real_format,
        width=width,
        height=height,
        size_bytes=size,
        sha256=hashlib.sha256(data).hexdigest(),
        display_name=safe_display_name(filename),
    )
