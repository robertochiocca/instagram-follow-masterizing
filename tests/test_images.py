"""Validação, armazenamento, análise e biblioteca de imagens."""

import io
import os

import pytest
from PIL import Image

from conftest import encode, scene
from database import images as images_repo
from services import image_analysis, photo_library
from services.image_validation import ImageValidationError, safe_display_name, validate_image_bytes

MB = 1024 * 1024


# --- Validação ------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt,ext", [("JPEG", "foto.jpg"), ("JPEG", "foto.JPEG"), ("PNG", "a.png"), ("WEBP", "a.webp")])
def test_valid_formats_are_accepted(fmt, ext):
    data = encode(scene(size=(400, 500)), fmt)
    v = validate_image_bytes(data, ext, 5 * MB)
    assert v.format == fmt and (v.width, v.height) == (400, 500)
    assert v.image.mode == "RGB" and len(v.sha256) == 64


@pytest.mark.parametrize("name", ["foto.gif", "foto.txt", "foto", "foto.jpg.exe", "foto.svg"])
def test_disallowed_extensions(name, jpeg_bytes):
    with pytest.raises(ImageValidationError, match="Formato não permitido"):
        validate_image_bytes(jpeg_bytes, name, 5 * MB)


def test_empty_and_oversized_files(jpeg_bytes):
    with pytest.raises(ImageValidationError, match="vazio"):
        validate_image_bytes(b"", "a.jpg", 5 * MB)
    with pytest.raises(ImageValidationError, match="limite"):
        validate_image_bytes(jpeg_bytes, "a.jpg", len(jpeg_bytes) - 1)


def test_corrupted_and_truncated_files(jpeg_bytes):
    with pytest.raises(ImageValidationError, match="corrompido"):
        validate_image_bytes(os.urandom(5000), "a.jpg", 5 * MB)
    with pytest.raises(ImageValidationError, match="corrompido"):
        validate_image_bytes(jpeg_bytes[: len(jpeg_bytes) // 2], "a.jpg", 5 * MB)
    with pytest.raises(ImageValidationError):
        validate_image_bytes(b"GIF89a" + b"\x00" * 100, "a.png", 5 * MB)


def test_extension_must_match_content():
    png = encode(scene(size=(300, 300)), "PNG")
    with pytest.raises(ImageValidationError, match="não corresponde"):
        validate_image_bytes(png, "disfarcado.jpg", 5 * MB)
    gif = encode(scene(size=(300, 300)).convert("P"), "GIF")
    with pytest.raises(ImageValidationError):
        validate_image_bytes(gif, "anim.png", 5 * MB)


def test_tiny_images_rejected():
    with pytest.raises(ImageValidationError, match="pequena"):
        validate_image_bytes(encode(Image.new("RGB", (40, 40), "red")), "a.jpg", 5 * MB)


def test_decompression_bomb_rejected(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 5_000)
    data = encode(Image.new("RGB", (100, 100), "blue"), "PNG")  # 10.000 px = 2× o limite
    with pytest.raises(ImageValidationError, match="dimensões"):
        validate_image_bytes(data, "a.png", 5 * MB)
    data = encode(Image.new("RGB", (80, 80), "blue"), "PNG")  # 6.400 px: só aviso -> tratado como erro
    with pytest.raises(ImageValidationError, match="dimensões"):
        validate_image_bytes(data, "a.png", 5 * MB)


def test_exif_orientation_and_transparency():
    img = scene(size=(400, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # girar 90°
    data = encode(img, "JPEG", exif=exif.tobytes())
    v = validate_image_bytes(data, "a.jpg", 5 * MB)
    assert (v.width, v.height) == (200, 400)

    rgba = Image.new("RGBA", (100, 100), (255, 0, 0, 0))
    v = validate_image_bytes(encode(rgba, "PNG"), "t.png", 5 * MB)
    assert v.image.mode == "RGB" and v.image.getpixel((5, 5)) == (255, 255, 255)


def test_safe_display_name():
    assert safe_display_name("../../etc/passwd") == "passwd"
    assert safe_display_name("C:\\fotos\\praia.jpg") == "praia.jpg"
    assert safe_display_name("") == "imagem"
    assert len(safe_display_name("a" * 500 + ".jpg")) == 120


# --- Armazenamento ----------------------------------------------------------------------------


def test_storage_saves_sanitized_copy_without_gps(storage):
    img = scene(size=(600, 800))
    exif = Image.Exif()
    exif[0x8825] = {2: (23.0, 33.0, 1.0)}  # GPSInfo
    exif[0x010F] = "CameraMaker"
    data = encode(img, "JPEG", exif=exif.tobytes())
    assert Image.open(io.BytesIO(data)).getexif()  # o original tem EXIF
    v = validate_image_bytes(data, "gps.jpg", 5 * MB)
    name, thumb = storage.save(v, "own")
    assert name.endswith(".jpg") and len(name) == 36
    with Image.open(storage.path("own", name)) as saved:
        assert not saved.getexif()
        assert saved.size == (600, 800)
    with Image.open(storage.thumb_path("own", thumb)) as t:
        assert max(t.size) <= 512


def test_storage_rejects_path_traversal(storage):
    for bad in ["../x.jpg", "abc.jpg", "/etc/passwd", "0" * 32 + ".exe", ""]:
        with pytest.raises(ValueError):
            storage.path("own", bad)
    with pytest.raises(ValueError):
        storage.path("../other", "0" * 32 + ".jpg")


def test_storage_delete_cleanup_and_usage(storage):
    v = validate_image_bytes(encode(scene(size=(300, 300))), "a.jpg", 5 * MB)
    name, thumb = storage.save(v, "reference")
    assert storage.usage()[0] == 2
    stray = storage.base_dir / "reference" / "full" / "x.jpg.tmp"
    stray.write_bytes(b"temp")
    assert storage.cleanup_temp() == 1 and not stray.exists()
    storage.delete("reference", name, thumb)
    assert storage.usage() == (0, 0)
    storage.save(v, "own")
    assert storage.delete_all("own") == 2
    assert storage.usage()[0] == 0


# --- Análise -----------------------------------------------------------------------------------


def test_sharp_image_scores_higher_than_blurred():
    sharp = scene()
    blurred = scene(blur=4)
    m_sharp = image_analysis.compute_metrics(sharp)
    m_blur = image_analysis.compute_metrics(blurred)
    assert m_sharp.sharpness > 10 * m_blur.sharpness
    assert image_analysis.score_metrics(m_sharp).total > image_analysis.score_metrics(m_blur).total
    assert any("desfoque" in o for o in image_analysis.observations(m_blur))


def test_exposure_and_clipping_penalties():
    good = image_analysis.score_metrics(image_analysis.compute_metrics(scene()))
    dark_m = image_analysis.compute_metrics(scene(brightness=0.15))
    bright_m = image_analysis.compute_metrics(scene(brightness=2.5))
    comp = lambda s, k: next(c.score for c in s.components if c.key == k)  # noqa: E731
    dark, bright = image_analysis.score_metrics(dark_m), image_analysis.score_metrics(bright_m)
    assert comp(dark, "exposure") < comp(good, "exposure")
    assert comp(bright, "clipping") < 0.5
    assert image_analysis.lighting_guess(dark_m) == "noite"
    assert any("escura" in o for o in image_analysis.observations(dark_m))


def test_score_range_and_weights():
    m = image_analysis.compute_metrics(scene(size=(540, 675)))
    s = image_analysis.score_metrics(m)
    assert 0 <= s.total <= 100
    assert abs(sum(c.weight for c in s.components) - 1) < 1e-9
    only_res = image_analysis.score_metrics(m, {"resolution": 1, **{k: 0 for k in image_analysis.SCORE_LABELS if k != "resolution"}})
    assert only_res.total == pytest.approx(50.0, abs=0.1)  # 540 / 1080
    zero = image_analysis.normalize_weights({k: 0 for k in image_analysis.SCORE_LABELS})
    assert zero == image_analysis.normalize_weights(None)  # tudo zero volta ao padrão
    assert s.to_dict()["components"][0]["points"] >= 0


def test_flat_image_has_neutral_composition():
    m = image_analysis.compute_metrics(Image.new("RGB", (500, 500), (128, 128, 128)))
    assert m.composition == 0.5 and m.sharpness == 0
    assert image_analysis.score_metrics(m).total < 60


def test_dhash_and_palette():
    a = scene(seed=1)
    b = scene(seed=1).resize((540, 675))
    c = Image.effect_noise((512, 512), 80).convert("RGB")
    ha, hb, hc = (image_analysis.dhash(x) for x in (a, b, c))
    assert len(ha) == 16
    assert image_analysis.hamming(ha, hb) <= 4
    assert image_analysis.hamming(ha, hc) > 12
    assert image_analysis.hamming("", ha) == 64
    palette = image_analysis.extract_palette(a)
    assert 1 <= len(palette) <= 5
    assert all(p.hex.startswith("#") and len(p.hex) == 7 for p in palette)
    assert sum(p.share for p in palette) <= 1.0001


def test_aspect_ratio_info():
    assert image_analysis.aspect_ratio_info(1080, 1350)["name"] == "4:5"
    assert image_analysis.aspect_ratio_info(1080, 1350)["fits_feed"]
    story = image_analysis.aspect_ratio_info(1080, 1920)
    assert story["name"] == "9:16" and not story["fits_feed"]
    assert image_analysis.aspect_ratio_info(1000, 1000)["name"] == "1:1"
    assert not image_analysis.aspect_ratio_info(3000, 1000)["fits_feed"]


def test_metrics_roundtrip():
    from models.analysis import ImageMetrics

    m = image_analysis.compute_metrics(scene(size=(300, 400)))
    again = ImageMetrics.from_dict(m.to_dict())
    assert again == m


# --- Biblioteca (importação e exclusão) ---------------------------------------------------------


def test_import_creates_record_and_files(db, storage, jpeg_bytes):
    out = photo_library.import_image(db, storage, jpeg_bytes, "praia.jpg", "own", 5 * MB)
    assert out.ok and out.image_id
    row = images_repo.get_image(db, out.image_id)
    assert row["original_name"] == "praia.jpg"
    assert 0 <= row["technical_score"] <= 100
    assert row["metrics"]["width"] == 800 and row["observations"]
    assert storage.path("own", row["filename"]).exists()
    assert storage.thumb_path("own", row["thumb_filename"]).exists()


def test_import_rejects_duplicates_and_invalid(db, storage, jpeg_bytes):
    assert photo_library.import_image(db, storage, jpeg_bytes, "a.jpg", "own", 5 * MB).ok
    dup = photo_library.import_image(db, storage, jpeg_bytes, "b.jpg", "own", 5 * MB)
    assert not dup.ok and "já foi enviada" in dup.message
    # a mesma imagem pode existir como referência
    assert photo_library.import_image(db, storage, jpeg_bytes, "b.jpg", "reference", 5 * MB).ok
    bad = photo_library.import_image(db, storage, b"not an image", "x.jpg", "own", 5 * MB)
    assert not bad.ok
    too_big = photo_library.import_image(db, storage, encode(scene(seed=3)), "y.jpg", "own", 100)
    assert not too_big.ok and "limite" in too_big.message
    assert storage.usage()[0] == 4  # 2 imagens válidas × (arquivo + miniatura)


def test_import_cleans_files_when_database_fails(db, storage, jpeg_bytes, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(photo_library.images_repo, "add_image", boom)
    out = photo_library.import_image(db, storage, jpeg_bytes, "a.jpg", "own", 5 * MB)
    assert not out.ok
    assert storage.usage() == (0, 0)


def test_delete_image_and_delete_all(db, storage):
    ids = [
        photo_library.import_image(db, storage, encode(scene(seed=i)), f"{i}.jpg", "own", 5 * MB).image_id
        for i in range(3)
    ]
    ref = photo_library.import_image(db, storage, encode(scene(seed=9)), "r.jpg", "reference", 5 * MB)
    assert photo_library.delete_image(db, storage, ids[0])
    assert images_repo.get_image(db, ids[0]) is None
    assert not photo_library.delete_image(db, storage, ids[0])
    assert photo_library.delete_all_images(db, storage, "own") == 2
    assert images_repo.count_images(db, "own") == 0
    assert images_repo.count_images(db, "reference") == 1
    assert storage.path("reference", images_repo.get_image(db, ref.image_id)["filename"]).exists()


def test_rescore_all_uses_new_weights(db, storage):
    out = photo_library.import_image(db, storage, encode(scene(size=(540, 675))), "a.jpg", "own", 5 * MB)
    weights = {k: 0 for k in image_analysis.SCORE_LABELS} | {"resolution": 1}
    assert photo_library.rescore_all(db, weights) == 1
    assert images_repo.get_image(db, out.image_id)["technical_score"] == pytest.approx(50.0, abs=0.1)
