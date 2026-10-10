"""Validação de uploads de imagem: extensão, tamanho e conteúdo real.

Mensagens de erro são genéricas e não incluem conteúdo do arquivo.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import PurePath

import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from config import MAX_IMAGE_PIXELS
from models.vocab import ALLOWED_EXTENSIONS, ALLOWED_FORMATS

MIN_SIDE_PX = 64
# Apenas estes decodificadores do Pillow são usados: um arquivo de outro tipo (por
# exemplo PostScript, que acionaria o Ghostscript) nunca chega a ser decodificado.
DECODERS = ("JPEG", "PNG", "WEBP")
# Fotos de câmeras e celulares com imagem extra embutida (prévia, mapa de
# profundidade) são JPEG com segmento MPF; o Pillow as chama de "MPO".
FORMAT_ALIASES = {"MPO": "JPEG"}
_HIGH_BIT_MODES = {"I;16", "I;16B", "I;16L", "I;16N", "I", "F"}
_ORIENTATION_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
_SRGB = ImageCms.createProfile("sRGB")

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


def _high_bit_to_rgba(img: Image.Image) -> Image.Image:
    """Reduz imagens de 16/32 bits para 8 bits (escala, sem estourar) preservando a cor-chave."""
    raw = np.asarray(img)
    values = raw.astype(np.float64)
    if img.mode.startswith("I;16") or values.max(initial=0) > 255:
        values = values / 257.0
    gray = Image.fromarray(np.clip(np.rint(values), 0, 255).astype(np.uint8), "L")
    rgba = gray.convert("RGBA")
    key = img.info.get("transparency")
    if isinstance(key, int):
        rgba.putalpha(Image.fromarray(np.where(raw == key, 0, 255).astype(np.uint8), "L"))
    return rgba


def to_rgb(img: Image.Image) -> Image.Image:
    """Converte qualquer modo para RGB de 8 bits, compondo transparência sobre branco."""
    if img.mode in _HIGH_BIT_MODES:
        img = _high_bit_to_rgba(img)
    if img.mode == "RGB" and "transparency" not in img.info:
        return img
    if img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in img.info:
        rgba = img.convert("RGBA")  # também aplica a cor-chave (tRNS) de PNGs L, RGB e P
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def apply_orientation(img: Image.Image) -> Image.Image:
    """Aplica a orientação EXIF; se o EXIF estiver malformado, gira só os pixels."""
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        pass
    try:
        method = _ORIENTATION_TRANSPOSE.get(img.getexif().get(0x0112))
    except Exception:
        return img
    return img.transpose(method) if method is not None else img


def to_srgb(img: Image.Image) -> Image.Image:
    """Converte para sRGB quando há perfil de cor embutido (ex.: Display P3 do iPhone).

    As cópias são salvas sem perfil; navegadores e o Instagram assumem sRGB.
    """
    icc = img.info.get("icc_profile")
    if not icc or img.mode not in ("RGB", "RGBA", "CMYK", "L"):
        return img
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        out_mode = "RGBA" if img.mode == "RGBA" else "RGB"
        return ImageCms.profileToProfile(img, source, _SRGB, outputMode=out_mode)
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        return img  # perfil inválido: mantém os pixels como estão


def _strip_metadata(img: Image.Image) -> Image.Image:
    """Cópia sem nenhum metadado herdado (EXIF, XMP, comentários, perfil de cor)."""
    clean = img.copy()
    clean.info = {}
    return clean


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
            probe = Image.open(io.BytesIO(data), formats=DECODERS)
            real_format = FORMAT_ALIASES.get(probe.format, probe.format)
            # Tipo e extensão são conferidos antes de decodificar os pixels.
            if real_format not in ALLOWED_FORMATS:
                raise ImageValidationError("O conteúdo não é JPG, PNG ou WEBP.")
            if real_format != ALLOWED_EXTENSIONS[ext]:
                raise ImageValidationError("A extensão do arquivo não corresponde ao conteúdo da imagem.")
            probe.verify()  # checa a estrutura; o objeto fica inutilizável depois
            img = Image.open(io.BytesIO(data), formats=DECODERS)
            img.load()  # decodifica todos os pixels (1º quadro); detecta arquivos truncados
    except ImageValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageValidationError("Imagem com dimensões grandes demais para processar.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as exc:
        raise corrupted from exc

    try:
        rgb = _strip_metadata(to_rgb(to_srgb(apply_orientation(img))))
    except (OSError, ValueError) as exc:
        raise corrupted from exc
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
