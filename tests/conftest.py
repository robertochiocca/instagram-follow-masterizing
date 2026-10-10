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
