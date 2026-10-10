"""Fixtures compartilhadas: banco temporário, armazenamento e imagens sintéticas."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from database import Database
from services.image_storage import ImageStorage


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def storage(tmp_path):
    return ImageStorage(tmp_path / "images")


def scene(size=(1080, 1350), seed=0, warm=False, blur=0.0, brightness=1.0) -> Image.Image:
    """Imagem sintética com céu, mar, areia e um "assunto" com textura."""
    w, h = size
    rng = np.random.default_rng(seed)
    arr = np.zeros((h, w, 3), np.float32)
    y = np.linspace(0, 1, h)[:, None]
    sky = np.array([235, 170, 120] if warm else [120, 170, 230], np.float32)
    arr[:] = (sky * (1 - 0.3 * y))[:, None, :]
    arr[int(h * 0.45) : int(h * 0.7)] = [30, 110, 170]
    arr[int(h * 0.7) :] = [220, 200, 160]
    arr += rng.normal(0, 4, arr.shape)
    img = Image.fromarray(np.clip(arr * brightness, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)
    x0 = int(w * 0.6) + seed * 7 % 50
    draw.ellipse([x0, int(h * 0.37), x0 + w // 10, int(h * 0.46)], fill=(200, 150, 120))
    draw.rectangle([x0 - 10, int(h * 0.46), x0 + w // 10 + 10, int(h * 0.74)], fill=(240, 240, 235))
    for i in range(0, w, 7 + seed % 5):
        draw.line([(i, int(h * 0.72)), (i + 3, h)], fill=(200, 180, 140), width=1)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return img


def encode(img: Image.Image, fmt: str = "JPEG", **kwargs) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes():
    return encode(scene(size=(800, 1000)))


@pytest.fixture
def app_data_dir(tmp_path, monkeypatch):
    """Diretório de dados isolado para testes da interface (AppTest)."""
    data_dir = tmp_path / "appdata"
    monkeypatch.setenv("IGT_DATA_DIR", str(data_dir))
    monkeypatch.delenv("IGT_APP_PASSWORD", raising=False)
    return data_dir


def matrix_icc_profile(primaries, gamma: float = 2.2, description: str = "Teste P3") -> bytes:
    """Perfil ICC v2 mínimo (matriz + curva gama) para testar conversão de cor.

    `primaries` = colorantes R, G e B em XYZ (D50).
    """
    import struct

    def s15(v):
        return struct.pack(">i", int(round(v * 65536)))

    def xyz(x, y, z):
        return b"XYZ " + b"\0" * 4 + s15(x) + s15(y) + s15(z)

    ascii_desc = description.encode("ascii") + b"\0"
    desc = (b"desc" + b"\0" * 4 + struct.pack(">I", len(ascii_desc)) + ascii_desc
            + b"\0" * 8 + b"\0" * 3 + b"\0" * 67)
    curve = b"curv" + b"\0" * 4 + struct.pack(">I", 1) + struct.pack(">H", int(gamma * 256)) + b"\0\0"
    tags = [(b"desc", desc), (b"wtpt", xyz(0.9642, 1.0, 0.8249)),
            (b"rXYZ", xyz(*primaries[0])), (b"gXYZ", xyz(*primaries[1])), (b"bXYZ", xyz(*primaries[2])),
            (b"rTRC", curve), (b"gTRC", curve), (b"bTRC", curve),
            (b"cprt", b"text" + b"\0" * 4 + b"teste\0")]
    offset = 128 + 4 + 12 * len(tags)
    table, blob = b"", b""
    for sig, data in tags:
        while (offset + len(blob)) % 4:
            blob += b"\0"
        table += sig + struct.pack(">II", offset + len(blob), len(data))
        blob += data
    body = struct.pack(">I", len(tags)) + table + blob
    header = (struct.pack(">I", 128 + len(body)) + b"\0" * 4 + struct.pack(">I", 0x02100000)
              + b"mntrRGB XYZ " + b"\0" * 12 + b"acsp" + b"\0" * 24 + struct.pack(">I", 0)
              + s15(0.9642) + s15(1.0) + s15(0.8249) + b"\0" * 48)
    return header + body


DISPLAY_P3_D50 = [(0.5151, 0.2412, -0.0011), (0.2919, 0.6922, 0.0419), (0.1572, 0.0666, 0.7841)]


def malformed_exif_orientation(orientation: int = 6) -> bytes:
    """Bloco EXIF com orientação válida e XResolution gravado como texto (tipo errado).

    O Pillow lê a orientação, mas falha ao regravar esse EXIF (caso real de
    algumas câmeras e aplicativos).
    """
    import struct

    entries = [
        struct.pack("<HHI", 0x0112, 3, 1) + struct.pack("<HH", orientation, 0),  # SHORT
        struct.pack("<HHI", 0x011A, 2, 3) + b"72\0\0",  # XResolution como ASCII
    ]
    ifd = struct.pack("<H", len(entries)) + b"".join(entries) + struct.pack("<I", 0)
    return b"Exif\0\0" + b"II*\0" + struct.pack("<I", 8) + ifd
