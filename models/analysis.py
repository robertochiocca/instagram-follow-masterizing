"""Estruturas de dados da análise de imagens (sem dependência de interface)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class PaletteColor:
    hex: str
    share: float  # fração da imagem (0–1)


@dataclass
class ImageMetrics:
    """Medidas objetivas calculadas a partir dos pixels.

    Todas as grandezas são aproximações; nenhuma delas mede beleza ou
    popularidade.
    """

    width: int
    height: int
    aspect_ratio: float  # largura / altura
    brightness: float  # luminância média, 0–1
    contrast: float  # desvio-padrão da luminância, 0–0,5
    sharpness: float  # variância do Laplaciano (escala reduzida)
    saturation: float  # saturação média HSV, 0–1
    colorfulness: float  # métrica de Hasler & Süsstrunk
    warmth: float  # (R − B) médio normalizado, −1 a 1
    clipped_highlights: float  # fração de pixels quase brancos
    clipped_shadows: float  # fração de pixels quase pretos
    composition: float  # 0–1, proximidade do "centro de detalhe" às linhas dos terços
    detail_x: float  # centro de massa do detalhe, 0–1 (esquerda→direita)
    detail_y: float  # 0–1 (topo→base)
    mean_color: str  # hex
    palette: list[PaletteColor] = field(default_factory=list)
    dhash: str = ""  # hash perceptual de 64 bits em hexadecimal

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageMetrics":
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["palette"] = [
            p if isinstance(p, PaletteColor) else PaletteColor(**p) for p in data.get("palette", [])
        ]
        return cls(**values)


@dataclass
class ScoreComponent:
    key: str
    label: str
    weight: float  # peso normalizado (soma 1)
    score: float  # 0–1
    explanation: str

    @property
    def points(self) -> float:
        return round(self.weight * self.score * 100, 1)


@dataclass
class TechnicalScore:
    total: float  # 0–100
    components: list[ScoreComponent]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "components": [asdict(c) | {"points": c.points} for c in self.components],
        }
