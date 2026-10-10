"""Organizador do feed: sugere, avalia e exporta sequências de fotos.

A grade do perfil tem 3 colunas; a posição 1 é a do canto superior esquerdo,
ou seja, a publicação MAIS RECENTE. A ordem de publicação é a inversa da
ordem da grade.

Algoritmo (guloso e explicável): para cada posição livre, escolhe a foto que
maximiza

    utilidade = Wq·qualidade + Wp·preferência + Wc·coerência − Wd·semelhança_vizinhos

- qualidade: pontuação técnica (0–1), com bônus de nota manual e favorita;
- preferência: afinidade com as referências (0,5 = neutro se não houver dados);
- coerência: proximidade da cor média da foto à cor média do conjunto (Lab);
- semelhança: máximo de semelhança com as vizinhas já posicionadas (esquerda,
  direita, acima, abaixo), combinando hash perceptual, tags/cenário,
  iluminação e cor.
Posições fixadas pelo usuário nunca são alteradas.
"""

from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass, field

import pandas as pd
from PIL import Image, ImageDraw, ImageOps

from models.defaults import DEFAULT_FEED_WEIGHTS
from models.vocab import CONTEXT, FRAMING, LIGHTING
from services import image_analysis
from services.image_storage import ImageStorage
from services.photo_library import metrics_of
from services.preferences import feature_phrase

GRID_COLUMNS = 3
NEAR_DUPLICATE_BITS = 10
ADJACENT_SIMILARITY_ALERT = 0.6


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def hex_to_lab(hex_color: str) -> tuple[float, float, float]:
    """Converte sRGB (hex) para CIELAB (D65)."""
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


@dataclass
class FeedPhoto:
    id: int
    name: str
    quality: float
    preference: float
    labels: frozenset[str]
    tags: tuple[str, ...]
    lighting: str | None
    framing: str | None
    context: str | None
    dhash: str
    brightness: float
    warmth: float
    lab: tuple[float, float, float]
    technical_score: float
    tone: str = ""
    temperature: str = ""

    @classmethod
    def from_row(cls, row: dict, preference: float | None = None) -> "FeedPhoto":
        metrics = metrics_of(row)
        quality = (row.get("technical_score") or 0) / 100
        if row.get("user_rating"):
            quality = 0.7 * quality + 0.3 * (int(row["user_rating"]) - 1) / 4
        if row.get("favorite"):
            quality = min(1.0, quality + 0.05)
        labels = {f"tag:{t}" for t in row.get("tags") or []}
        for col in ("context", "framing"):
            if row.get(col):
                labels.add(f"{col}:{row[col]}")
        return cls(
            id=int(row["id"]),
            name=row.get("original_name") or f"Foto {row['id']}",
            quality=_clamp(quality),
            preference=0.5 if preference is None else _clamp(preference),
            labels=frozenset(labels),
            tags=tuple(row.get("tags") or []),
            lighting=row.get("lighting"),
            framing=row.get("framing"),
            context=row.get("context"),
            dhash=row.get("dhash") or "",
            brightness=metrics.brightness if metrics else 0.5,
            warmth=metrics.warmth if metrics else 0.0,
            lab=hex_to_lab(metrics.mean_color) if metrics else (50.0, 0.0, 0.0),
            technical_score=float(row.get("technical_score") or 0),
            tone=image_analysis.tone_class(metrics) if metrics else "",
            temperature=image_analysis.temperature_class(metrics) if metrics else "",
        )


def similarity(a: FeedPhoto, b: FeedPhoto) -> float:
    """Semelhança visual aproximada entre 0 (diferentes) e 1 (quase iguais)."""
    hash_sim = _clamp(1 - image_analysis.hamming(a.dhash, b.dhash) / 32)
    union = a.labels | b.labels
    content_sim = len(a.labels & b.labels) / len(union) if union else 0.0
    light_sim = 1 - _clamp((abs(a.brightness - b.brightness) + abs(a.warmth - b.warmth)) / 0.35)
    if a.lighting and a.lighting == b.lighting:
        light_sim = max(light_sim, 0.8)
    color_sim = 1 - _clamp(math.dist(a.lab, b.lab) / 50)
    return 0.35 * hash_sim + 0.30 * content_sim + 0.15 * light_sim + 0.20 * color_sim


def neighbors(position: int, total: int) -> list[int]:
    out = []
    col = position % GRID_COLUMNS
    if col > 0:
        out.append(position - 1)
    if col < GRID_COLUMNS - 1 and position + 1 < total:
        out.append(position + 1)
    if position - GRID_COLUMNS >= 0:
        out.append(position - GRID_COLUMNS)
    if position + GRID_COLUMNS < total:
        out.append(position + GRID_COLUMNS)
    return out


def normalize_feed_weights(weights: dict | None) -> dict[str, float]:
    base = {k: max(0.0, float((weights or {}).get(k, v))) for k, v in DEFAULT_FEED_WEIGHTS.items()}
    total = sum(base.values())
    if total <= 0:
        return normalize_feed_weights(DEFAULT_FEED_WEIGHTS)
    return {k: v / total for k, v in base.items()}


def color_centroid(photos: list[FeedPhoto]) -> tuple[float, float, float]:
    if not photos:
        return (50.0, 0.0, 0.0)
    weights = [0.2 + p.quality for p in photos]
    total = sum(weights)
    return tuple(sum(p.lab[i] * w for p, w in zip(photos, weights)) / total for i in range(3))


def coherence(photo: FeedPhoto, centroid) -> float:
    return 1 - _clamp(math.dist(photo.lab, centroid) / 60)


@dataclass
class FeedPlan:
    sequence: list[int]  # ids na ordem da grade (posição 0 = mais recente)
    reasons: dict[int, list[str]] = field(default_factory=dict)  # posição → motivos


def plan_feed(
    photos: list[FeedPhoto],
    slots: int,
    pins: dict[int, int] | None = None,
    weights: dict | None = None,
) -> FeedPlan:
    """Monta a sequência sugerida respeitando `pins` (posição → id da foto)."""
    w = normalize_feed_weights(weights)
    by_id = {p.id: p for p in photos}
    pins = {pos: pid for pos, pid in (pins or {}).items() if pid in by_id and 0 <= pos}
    slots = max(1, min(slots, len(photos)))
    pins = {pos: pid for pos, pid in pins.items() if pos < slots}
    placed: list[int | None] = [None] * slots
    for pos, pid in pins.items():
        placed[pos] = pid
    available = [p for p in photos if p.id not in set(pins.values())]
    centroid = color_centroid(photos)
    reasons: dict[int, list[str]] = {pos: ["Posição fixada por você."] for pos in pins}

    for pos in range(slots):
        if placed[pos] is not None or not available:
            continue
        neigh = [by_id[placed[n]] for n in neighbors(pos, slots) if placed[n] is not None]

        def utility(p: FeedPhoto) -> tuple[float, float]:
            sim = max((similarity(p, n) for n in neigh), default=0.0)
            value = (
                w["quality"] * p.quality
                + w["preference"] * p.preference
                + w["coherence"] * coherence(p, centroid)
                - w["diversity"] * sim
            )
            return value, -p.id  # desempate estável

        best = max(available, key=utility)
        available.remove(best)
        placed[pos] = best.id
        reasons[pos] = _explain(best, neigh, centroid)

    sequence = [pid for pid in placed if pid is not None]
    return FeedPlan(sequence=sequence, reasons=reasons)


def _explain(p: FeedPhoto, neigh: list[FeedPhoto], centroid) -> list[str]:
    out = []
    if p.quality >= 0.75:
        out.append(f"Boa qualidade técnica ({p.technical_score:.0f}/100).")
    if p.preference >= 0.65:
        out.append("Alinhada às características que você prefere nas referências.")
    if coherence(p, centroid) >= 0.75:
        out.append("Cores coerentes com o restante do feed.")
    if neigh:
        max_sim = max(similarity(p, n) for n in neigh)
        if max_sim < 0.4:
            out.append("Contrasta bem com as fotos vizinhas.")
    return out or ["Melhor equilíbrio disponível entre os critérios."]


@dataclass
class FeedEvaluation:
    quality: float
    preference: float
    coherence: float
    diversity: float
    overall: float
    adjacent_alerts: list[str]


def evaluate_sequence(photos: list[FeedPhoto], weights: dict | None = None) -> FeedEvaluation:
    """Indicadores 0–100 de uma sequência (para comparar versões)."""
    if not photos:
        return FeedEvaluation(0, 0, 0, 0, 0, [])
    w = normalize_feed_weights(weights)
    n = len(photos)
    centroid = color_centroid(photos)
    max_sims = []
    alerts = []
    for pos, p in enumerate(photos):
        sims = [(similarity(p, photos[j]), j) for j in neighbors(pos, n)]
        max_sims.append(max((s for s, _ in sims), default=0.0))
        for s, j in sims:
            if j > pos and s >= ADJACENT_SIMILARITY_ALERT:
                alerts.append(f"Posições {pos + 1} e {j + 1} estão muito parecidas (semelhança {s:.0%}).")
    quality = sum(p.quality for p in photos) / n
    preference = sum(p.preference for p in photos) / n
    coh = sum(coherence(p, centroid) for p in photos) / n
    diversity = 1 - sum(max_sims) / n
    overall = (
        w["quality"] * quality
        + w["preference"] * preference
        + w["coherence"] * coh
        + w["diversity"] * diversity
    )
    pct = lambda v: round(v * 100, 1)  # noqa: E731
    return FeedEvaluation(pct(quality), pct(preference), pct(coh), pct(diversity), pct(overall), alerts)


def repetition_warnings(photos: list[FeedPhoto]) -> list[str]:
    """Detecta repetição visual aproximada e excesso de um mesmo tipo de foto."""
    out = []
    n = len(photos)
    # Agrupa fotos quase iguais (união de pares) para gerar um aviso por grupo.
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if image_analysis.hamming(photos[i].dhash, photos[j].dhash) <= NEAR_DUPLICATE_BITS:
                parent[root(j)] = root(i)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(root(i), []).append(i + 1)
    for members in groups.values():
        if len(members) > 1:
            listed = ", ".join(map(str, members[:-1])) + f" e {members[-1]}"
            out.append(f"As fotos nas posições {listed} parecem quase iguais; considere manter só uma.")
    if n >= 4:
        tag_counts: dict[str, int] = {}
        for p in photos:
            for t in set(p.tags):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        for tag, count in sorted(tag_counts.items(), key=lambda kv: -kv[1]):
            if count / n > 0.5:
                out.append(f"{count} de {n} fotos têm a tag “{tag}”. Alterne com outros temas.")
        looks: dict[str, int] = {}
        for p in photos:
            if p.lighting:
                key = LIGHTING.get(p.lighting, p.lighting).lower()
            else:
                key = f"{feature_phrase('tone', p.tone)} e {feature_phrase('temperature', p.temperature)}"
            looks[key] = looks.get(key, 0) + 1
        key, count = max(looks.items(), key=lambda kv: kv[1])
        if count / n > 0.6:
            out.append(f"{count} de {n} fotos têm iluminação semelhante ({key}). Varie luz e horário.")
        framings: dict[str, int] = {}
        for p in photos:
            if p.framing:
                framings[p.framing] = framings.get(p.framing, 0) + 1
        for fr, count in framings.items():
            if count / n > 0.6:
                out.append(
                    f"{count} de {n} fotos usam enquadramento “{FRAMING.get(fr, fr)}”. "
                    "Misture planos abertos, meio corpo e detalhes."
                )
    return out


THEME_GROUPS = {
    "Retratos": {"tag:retrato", "framing:close", "framing:meio_corpo"},
    "Viagens": {"tag:viagem", "context:viagem", "tag:cidade", "tag:arquitetura", "context:cidade",
                "context:arquitetura"},
    "Esporte": {"tag:esporte", "tag:academia", "context:esporte"},
    "Social": {"tag:social", "context:social", "framing:grupo", "context:universidade",
               "context:restaurante"},
    "Praia": {"tag:praia", "context:praia"},
}


def alternation_suggestions(photos: list[FeedPhoto]) -> list[str]:
    """Sugestões para alternar retratos, viagens, esporte e fotos sociais."""
    if not photos:
        return []
    out = []
    groups_per_photo = [{g for g, labels in THEME_GROUPS.items() if p.labels & labels} for p in photos]
    present = set().union(*groups_per_photo)
    missing = [g for g in ("Retratos", "Viagens", "Esporte", "Social") if g not in present]
    if missing and len(photos) >= 6:
        out.append("Temas ausentes nesta sequência: " + ", ".join(missing) + ".")
    for start in range(0, len(photos), GRID_COLUMNS):
        row = groups_per_photo[start : start + GRID_COLUMNS]
        if len(row) == GRID_COLUMNS:
            common = set.intersection(*row)
            if common:
                out.append(
                    f"A linha {start // GRID_COLUMNS + 1} tem só fotos de {', '.join(sorted(common)).lower()}; "
                    "intercale com outro tema."
                )
    untagged = sum(1 for g in groups_per_photo if not g)
    if untagged:
        out.append(
            f"{untagged} foto(s) sem tags ou cenário definidos: marque-as em “Minhas fotos” para "
            "melhorar as sugestões de alternância."
        )
    return out


# --- Exportação ----------------------------------------------------------------


def sequence_dataframe(rows: list[dict], pinned_positions: set[int] | None = None) -> pd.DataFrame:
    pinned_positions = pinned_positions or set()
    n = len(rows)
    data = []
    for pos, row in enumerate(rows):
        data.append(
            {
                "posicao_grade": pos + 1,
                "ordem_publicacao": n - pos,
                "id_foto": row["id"],
                "nome": row.get("original_name") or "",
                "tags": ", ".join(row.get("tags") or []),
                "cenario": CONTEXT.get(row.get("context") or "", ""),
                "pontuacao_tecnica": row.get("technical_score"),
                "fixada": "sim" if pos in pinned_positions else "não",
            }
        )
    return pd.DataFrame(data)


def grid_preview_png(
    storage: ImageStorage,
    rows: list[dict],
    cell: int = 300,
    gap: int = 4,
    pinned_positions: set[int] | None = None,
) -> bytes:
    """Prévia da grade (miniaturas recortadas em 3:4, como na grade do perfil).

    Cada célula mostra o número da posição; posições fixadas ganham um
    marcador amarelo no canto superior direito.
    """
    pinned_positions = pinned_positions or set()
    cols = GRID_COLUMNS
    n_rows = max(1, math.ceil(len(rows) / cols))
    cell_h = int(cell * 4 / 3)
    canvas = Image.new("RGB", (cols * cell + (cols - 1) * gap, n_rows * cell_h + (n_rows - 1) * gap), "white")
    draw = ImageDraw.Draw(canvas)
    for pos, row in enumerate(rows):
        x = (pos % cols) * (cell + gap)
        y = (pos // cols) * (cell_h + gap)
        try:
            with Image.open(storage.thumb_path(row["kind"], row["thumb_filename"])) as im:
                tile = ImageOps.fit(im.convert("RGB"), (cell, cell_h), Image.Resampling.LANCZOS)
            canvas.paste(tile, (x, y))
        except (OSError, ValueError):
            draw.rectangle([x, y, x + cell, y + cell_h], fill=(230, 230, 230))
        size = max(18, cell // 9)
        draw.rectangle([x + 6, y + 6, x + 6 + size * 2, y + 6 + size], fill=(0, 0, 0))
        draw.text((x + 10, y + 8), str(pos + 1), fill=(255, 255, 255), font_size=size - 4)
        if pos in pinned_positions:
            draw.ellipse([x + cell - 6 - size, y + 6, x + cell - 6, y + 6 + size],
                         fill=(250, 178, 25), outline=(0, 0, 0), width=2)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def export_zip(storage: ImageStorage, rows: list[dict], pinned_positions: set[int] | None = None) -> bytes:
    """ZIP com as fotos renomeadas na ORDEM DE PUBLICAÇÃO, CSV e prévia da grade."""
    buf = io.BytesIO()
    n = len(rows)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for pos, row in enumerate(rows):
            publish_order = n - pos
            ext = row["filename"].rsplit(".", 1)[-1]
            path = storage.path(row["kind"], row["filename"])
            if path.exists():
                zf.write(path, f"publicar_{publish_order:02d}_grade_{pos + 1:02d}.{ext}")
        zf.writestr(
            "sequencia.csv",
            sequence_dataframe(rows, pinned_positions).to_csv(index=False).encode("utf-8-sig"),
        )
        zf.writestr("previa_grade.png", grid_preview_png(storage, rows))
        zf.writestr(
            "LEIA-ME.txt",
            "Publique os arquivos na ordem do prefixo publicar_01, publicar_02...\n"
            "A última publicada aparece no canto superior esquerdo da grade (posição 1).\n"
            "Nada foi publicado automaticamente.\n",
        )
    return buf.getvalue()
