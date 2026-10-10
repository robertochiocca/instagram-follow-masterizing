"""Análise técnica de fotografias com Pillow + NumPy (sem IA, sem serviços externos).

A pontuação de 0 a 100 é uma ESTIMATIVA TÉCNICA para comparar fotos entre si.
Ela não mede beleza, não prevê curtidas e não indica se uma foto vai viralizar.
Critérios e pesos padrão estão em `models/defaults.py` e documentados no README.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from models.analysis import ImageMetrics, PaletteColor, ScoreComponent, TechnicalScore
from models.defaults import DEFAULT_SCORE_WEIGHTS

ANALYSIS_MAX_SIDE = 1024
TARGET_SHORT_SIDE = 1080  # largura de referência das publicações no Instagram

# Faixas usadas na pontuação (todas documentadas no README).
EXPOSURE_IDEAL = (0.30, 0.70)
EXPOSURE_ZERO = (0.05, 0.95)
CONTRAST_IDEAL = (0.16, 0.30)
SHARPNESS_RANGE = (40.0, 800.0)  # variância do Laplaciano: 40 → 0 pontos, 800 → nota máxima
CLIP_OK, CLIP_BAD = 0.01, 0.15
SATURATION_IDEAL = (0.18, 0.55)

SCORE_LABELS = {
    "exposure": "Exposição (brilho)",
    "contrast": "Contraste",
    "sharpness": "Nitidez aproximada",
    "clipping": "Áreas estouradas / sem detalhe",
    "color": "Equilíbrio de cor",
    "resolution": "Resolução",
    "composition": "Composição (aproximação)",
}

NAMED_RATIOS = [
    ("1:1", 1.0),
    ("4:5", 0.8),
    ("3:4", 0.75),
    ("2:3", 2 / 3),
    ("9:16", 9 / 16),
    ("16:9", 16 / 9),
    ("3:2", 1.5),
    ("4:3", 4 / 3),
    ("1,91:1", 1.91),
]
FEED_MIN_RATIO, FEED_MAX_RATIO = 0.8, 1.91


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x != x:  # NaN nunca vira nota máxima
        return lo
    return max(lo, min(hi, x))


def _downscale(img: Image.Image, max_side: int = ANALYSIS_MAX_SIDE) -> Image.Image:
    small = img.convert("RGB") if img.mode != "RGB" else img.copy()
    small.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return small


def _laplacian(gray: np.ndarray) -> np.ndarray:
    """Laplaciano 4-vizinhos sem dependências extras (bordas descartadas)."""
    return (
        gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4.0 * gray[1:-1, 1:-1]
    )


def _tile_sharpness(lap: np.ndarray, grid: int = 4) -> float:
    """Média dos 25% blocos mais nítidos.

    Usar os blocos mais nítidos evita punir retratos com fundo desfocado
    (bokeh), em que só o assunto principal precisa estar em foco.
    """
    h, w = lap.shape
    values = []
    for i in range(grid):
        for j in range(grid):
            tile = lap[i * h // grid : (i + 1) * h // grid, j * w // grid : (j + 1) * w // grid]
            if tile.size:
                values.append(float(tile.var()))
    if not values:  # imagem extremamente estreita: não há área para medir
        return 0.0
    values.sort(reverse=True)
    top = values[: max(1, len(values) // 4)]
    return float(np.mean(top))


def dhash(img: Image.Image, size: int = 8) -> str:
    """Hash perceptual por diferença (64 bits) para achar fotos quase iguais."""
    gray = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = np.asarray(gray, dtype=np.int16)
    bits = (px[:, 1:] > px[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def extract_palette(img: Image.Image, colors: int = 5) -> list[PaletteColor]:
    small = _downscale(img, 160)
    quant = small.quantize(colors=colors + 1, method=Image.Quantize.MEDIANCUT)
    palette = quant.getpalette() or []
    counts = sorted(quant.getcolors() or [], reverse=True)
    total = sum(c for c, _ in counts) or 1
    out = []
    for count, index in counts[:colors]:
        r, g, b = palette[index * 3 : index * 3 + 3]
        out.append(PaletteColor(hex=f"#{r:02x}{g:02x}{b:02x}", share=round(count / total, 3)))
    return out


def compute_metrics(img: Image.Image) -> ImageMetrics:
    width, height = img.size
    small = _downscale(img)
    rgb = np.asarray(small, dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    hsv = np.asarray(small.convert("HSV"), dtype=np.float32)
    saturation = float(hsv[..., 1].mean() / 255.0)

    rg = r - g
    yb = 0.5 * (r + g) - b
    colorfulness = float(
        math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )

    lap = _laplacian(lum)
    sharpness = _tile_sharpness(lap)

    # "Centro de detalhe": centro de massa da energia de bordas.
    energy = np.abs(lap)
    total = float(energy.sum())
    has_detail = energy.size > 0 and total / energy.size >= 0.5
    if has_detail:
        ys, xs = np.indices(energy.shape)
        detail_x = float((xs * energy).sum() / total / max(1, energy.shape[1] - 1))
        detail_y = float((ys * energy).sum() / total / max(1, energy.shape[0] - 1))
    else:
        detail_x = detail_y = 0.5

    mean_rgb = rgb.reshape(-1, 3).mean(axis=0)
    return ImageMetrics(
        width=width,
        height=height,
        aspect_ratio=round(width / height, 4),
        brightness=round(float(lum.mean() / 255.0), 4),
        contrast=round(float(lum.std() / 255.0), 4),
        sharpness=round(sharpness, 2),
        saturation=round(saturation, 4),
        colorfulness=round(colorfulness, 2),
        warmth=round(float((r.mean() - b.mean()) / 255.0), 4),
        clipped_highlights=round(float((lum >= 250).mean()), 4),
        clipped_shadows=round(float((lum <= 5).mean()), 4),
        # Sem detalhe mensurável, a composição fica neutra (0,5).
        composition=round(composition_score(detail_x, detail_y), 4) if has_detail else 0.5,
        detail_x=round(detail_x, 4),
        detail_y=round(detail_y, 4),
        mean_color="#{:02x}{:02x}{:02x}".format(*(int(round(v)) for v in mean_rgb)),
        palette=extract_palette(small),
        dhash=dhash(small),
    )


def composition_score(x: float, y: float) -> float:
    """Proximidade do centro de detalhe a um ponto dos terços ou ao centro.

    Composições centralizadas (comuns em retratos) recebem até 0,85; pontos
    dos terços recebem até 1,0; detalhe colado na borda é penalizado.
    """
    thirds = [(tx, ty) for tx in (1 / 3, 2 / 3) for ty in (1 / 3, 2 / 3)]
    d_thirds = min(math.dist((x, y), p) for p in thirds)
    d_center = math.dist((x, y), (0.5, 0.5))
    score = max(_clamp(1 - d_thirds / 0.25), 0.85 * _clamp(1 - d_center / 0.25))
    edge = min(x, y, 1 - x, 1 - y)
    if edge < 0.12:
        score *= 0.6
    return _clamp(score)


def _band_score(value: float, ideal: tuple[float, float], zero: tuple[float, float]) -> float:
    lo, hi = ideal
    zlo, zhi = zero
    if lo <= value <= hi:
        return 1.0
    if value < lo:
        return _clamp((value - zlo) / (lo - zlo))
    return _clamp((zhi - value) / (zhi - hi))


def normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    base = {k: float(v) for k, v in (weights or DEFAULT_SCORE_WEIGHTS).items() if k in SCORE_LABELS}
    for key in SCORE_LABELS:
        base.setdefault(key, 0.0)
    total = sum(max(0.0, v) for v in base.values())
    if total <= 0:
        return normalize_weights(DEFAULT_SCORE_WEIGHTS)
    return {k: max(0.0, v) / total for k, v in base.items()}


def score_metrics(m: ImageMetrics, weights: dict[str, float] | None = None) -> TechnicalScore:
    w = normalize_weights(weights)
    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731

    exposure = _band_score(m.brightness, EXPOSURE_IDEAL, EXPOSURE_ZERO)

    c = m.contrast
    lo, hi = CONTRAST_IDEAL
    if c < lo:
        contrast = _clamp((c - 0.04) / (lo - 0.04))
    elif c <= hi:
        contrast = 1.0
    else:
        contrast = max(0.5, 1 - (c - hi) / 0.24)

    s_lo, s_hi = SHARPNESS_RANGE
    sharpness = m.sharpness if math.isfinite(m.sharpness) else 0.0
    sharp = _clamp(
        (math.log10(max(sharpness, 1e-6)) - math.log10(s_lo)) / (math.log10(s_hi) - math.log10(s_lo))
    )

    clipped = m.clipped_highlights + m.clipped_shadows
    clipping = _clamp(1 - (clipped - CLIP_OK) / (CLIP_BAD - CLIP_OK)) if clipped > CLIP_OK else 1.0

    sat = m.saturation
    sat_lo, sat_hi = SATURATION_IDEAL
    if sat < sat_lo:
        color = 0.6 + 0.4 * sat / sat_lo  # pouca cor pode ser intencional (minimalismo, P&B)
    elif sat <= sat_hi:
        color = 1.0
    else:
        color = max(0.3, 1 - (sat - sat_hi) / 0.3 * 0.7)

    short_side = min(m.width, m.height)
    resolution = _clamp(short_side / TARGET_SHORT_SIDE)

    components = [
        ScoreComponent(
            "exposure", SCORE_LABELS["exposure"], w["exposure"], exposure,
            f"Brilho médio {pct(m.brightness)}; faixa ideal {pct(EXPOSURE_IDEAL[0])}–{pct(EXPOSURE_IDEAL[1])}.",
        ),
        ScoreComponent(
            "contrast", SCORE_LABELS["contrast"], w["contrast"], contrast,
            f"Desvio da luminância {m.contrast:.2f}; faixa ideal {lo:.2f}–{hi:.2f}.",
        ),
        ScoreComponent(
            "sharpness", SCORE_LABELS["sharpness"], w["sharpness"], sharp,
            f"Variância do Laplaciano nas áreas mais nítidas: {m.sharpness:.0f} "
            f"(≤{s_lo:.0f} = sem nitidez, ≥{s_hi:.0f} = nota máxima).",
        ),
        ScoreComponent(
            "clipping", SCORE_LABELS["clipping"], w["clipping"], clipping,
            f"{pct(m.clipped_highlights)} estourado (branco) e {pct(m.clipped_shadows)} em preto puro.",
        ),
        ScoreComponent(
            "color", SCORE_LABELS["color"], w["color"], color,
            f"Saturação média {pct(sat)}; faixa equilibrada {pct(sat_lo)}–{pct(sat_hi)}.",
        ),
        ScoreComponent(
            "resolution", SCORE_LABELS["resolution"], w["resolution"], resolution,
            f"Lado menor com {short_side} px; referência {TARGET_SHORT_SIDE} px.",
        ),
        ScoreComponent(
            "composition", SCORE_LABELS["composition"], w["composition"], m.composition,
            "Posição do centro de detalhe em relação aos terços e ao centro.",
        ),
    ]
    total = round(sum(comp.weight * comp.score for comp in components) * 100, 1)
    return TechnicalScore(total=total, components=components)


def aspect_ratio_info(width: int, height: int) -> dict[str, object]:
    ratio = width / height
    name, ref = min(NAMED_RATIOS, key=lambda item: abs(item[1] - ratio))
    if abs(ref - ratio) / ref > 0.03:
        name = f"{ratio:.2f}:1"
    fits = FEED_MIN_RATIO * 0.98 <= ratio <= FEED_MAX_RATIO * 1.02
    if ratio < FEED_MIN_RATIO * 0.98:
        note = (
            "Mais vertical que 4:5: ótima para Reels e Stories; no feed tende a ser "
            "cortada para 4:5 ou 3:4."
        )
    elif ratio > FEED_MAX_RATIO * 1.02:
        note = "Mais horizontal que 1,91:1: será cortada no feed."
    elif ratio < 0.95:
        note = "Vertical: ocupa mais espaço na tela do feed."
    elif ratio <= 1.05:
        note = "Quadrada: segura para o feed e para a grade."
    else:
        note = "Horizontal: aparece menor no feed; a grade do perfil mostra um recorte central."
    return {"name": name, "ratio": round(ratio, 3), "fits_feed": fits, "note": note}


def lighting_guess(m: ImageMetrics) -> str | None:
    """Palpite de iluminação a partir de brilho e cor (o usuário deve confirmar)."""
    if m.brightness < 0.22:
        return "noite"
    if m.clipped_highlights > 0.06 and m.clipped_shadows > 0.04:
        return "contraluz"
    if m.warmth > 0.12 and 0.25 <= m.brightness <= 0.75:
        return "golden_hour"
    if m.contrast < 0.13 and m.saturation < 0.25:
        return "sombra"
    if m.brightness >= 0.4:
        return "natural_dia"
    return None


def tone_class(m: ImageMetrics) -> str:
    return "escura" if m.brightness < 0.35 else ("clara" if m.brightness > 0.62 else "equilibrada")


def temperature_class(m: ImageMetrics) -> str:
    return "quente" if m.warmth > 0.08 else ("fria" if m.warmth < -0.04 else "neutra")


def saturation_class(m: ImageMetrics) -> str:
    return "suave" if m.saturation < 0.18 else ("vibrante" if m.saturation > 0.45 else "moderada")


def observations(m: ImageMetrics) -> list[str]:
    """Observações objetivas sobre iluminação, enquadramento e técnica."""
    notes: list[str] = []
    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731

    if m.brightness < 0.15:
        notes.append("Foto muito escura: experimente fotografar com mais luz ou aumentar a exposição.")
    elif m.brightness < 0.30:
        notes.append("Foto um pouco escura: um leve aumento de exposição pode revelar detalhes.")
    elif m.brightness > 0.80:
        notes.append("Foto muito clara: verifique se rosto e roupas não perderam detalhes.")

    if m.clipped_highlights > 0.03:
        notes.append(
            f"{pct(m.clipped_highlights)} da imagem está estourada (branco puro); "
            "reduzir realces ou exposição pode recuperar o céu e a pele."
        )
    if m.clipped_shadows > 0.05:
        notes.append(f"{pct(m.clipped_shadows)} da imagem está em preto puro; sombras sem detalhe.")

    if m.contrast < 0.12:
        notes.append("Contraste baixo: aparência lavada. Um pequeno aumento de contraste pode ajudar.")
    elif m.contrast > 0.32:
        notes.append("Contraste alto: confira se sombras do rosto não ficaram duras demais.")

    if m.sharpness < 90:
        notes.append(
            "Possível desfoque ou tremido: confira o foco no rosto ou no assunto principal "
            "ampliando a foto."
        )

    short_side = min(m.width, m.height)
    if short_side < TARGET_SHORT_SIDE:
        notes.append(
            f"Lado menor com {short_side} px (abaixo de {TARGET_SHORT_SIDE} px): pode perder "
            "nitidez depois da compressão do Instagram."
        )

    if min(m.detail_x, m.detail_y, 1 - m.detail_x, 1 - m.detail_y) < 0.12:
        notes.append(
            "A área com mais detalhes está perto da borda: verifique se o assunto não foi cortado."
        )
    elif math.dist((m.detail_x, m.detail_y), (0.5, 0.5)) < 0.08:
        notes.append(
            "Assunto aparentemente centralizado: funciona bem em retratos; em paisagens, "
            "experimente posicioná-lo sobre uma linha dos terços."
        )

    if m.saturation > 0.6:
        notes.append("Cores muito saturadas: um tratamento mais natural combina com estética limpa.")
    elif m.saturation < 0.05:
        notes.append("Imagem monocromática ou quase sem cor.")

    if m.warmth > 0.15:
        notes.append("Tons quentes, típicos de fim de tarde ou praia.")
    elif m.warmth < -0.08:
        notes.append("Tons frios/azulados; confira o balanço de branco se a pele parecer acinzentada.")

    info = aspect_ratio_info(m.width, m.height)
    notes.append(f"Proporção {info['name']} — {info['note']}")
    return notes


def analyze(img: Image.Image, weights: dict[str, float] | None = None):
    """Atalho: (métricas, pontuação, observações)."""
    metrics = compute_metrics(img)
    return metrics, score_metrics(metrics, weights), observations(metrics)
