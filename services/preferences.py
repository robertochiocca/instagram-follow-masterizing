"""Aprendizado de preferências estéticas a partir de avaliações explícitas.

Método (propositalmente simples e explicável — não é um modelo de IA):

1. Cada referência avaliada gera um sinal entre −1 e +1:
   nota 1–5 → (nota − 3) / 2; reação Gosto/Neutro/Não gosto → +1/0/−1;
   havendo os dois, usa-se a média.
2. Cada referência tem características: categorias, cenário, iluminação,
   enquadramento, roupa, tags e classes de tom/temperatura/saturação
   calculadas dos pixels.
3. Para cada característica: preferência = soma dos sinais / (n + k), com
   k = 2 (suavização que puxa para zero quando há poucos exemplos).
4. A afinidade de uma foto é a média ponderada das preferências das suas
   características (pesos por grupo e por categoria ajustáveis).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from models.defaults import DEFAULT_PREFERENCE_GROUP_WEIGHTS
from models.vocab import CLOTHING, CONTEXT, FRAMING, LIGHTING, REACTION_SIGNAL
from services import image_analysis
from services.photo_library import metrics_of

MIN_REFERENCES = 5
PRIOR_STRENGTH = 2.0
MIN_FEATURE_COUNT = 2
INSIGHT_THRESHOLD = 0.2

GROUP_LABELS = {
    "category": "Categoria estética",
    "context": "Cenário",
    "lighting": "Iluminação",
    "framing": "Enquadramento",
    "clothing": "Estilo de roupa",
    "tag": "Tag",
    "tone": "Brilho",
    "temperature": "Temperatura de cor",
    "saturation": "Saturação",
}

_TONE = {"escura": "imagens escuras", "equilibrada": "brilho equilibrado", "clara": "imagens claras"}
_TEMP = {"quente": "tons quentes", "fria": "tons frios", "neutra": "cores neutras"}
_SAT = {"suave": "cores suaves", "moderada": "saturação moderada", "vibrante": "cores vibrantes"}


def feature_phrase(group: str, value: str) -> str:
    """Descrição em linguagem natural de uma característica."""
    if group == "category":
        return f"estética “{value}”"
    if group == "context":
        return f"cenário de {CONTEXT.get(value, value).lower()}"
    if group == "lighting":
        return LIGHTING.get(value, value).lower()
    if group == "framing":
        return f"enquadramento {FRAMING.get(value, value).lower()}"
    if group == "clothing":
        return f"roupa {CLOTHING.get(value, value).lower()}"
    if group == "tag":
        return f"tag “{value}”"
    if group == "tone":
        return _TONE.get(value, value)
    if group == "temperature":
        return _TEMP.get(value, value)
    if group == "saturation":
        return _SAT.get(value, value)
    return value


def image_signal(row: dict) -> float | None:
    values = []
    rating = row.get("user_rating")
    if rating:
        values.append((int(rating) - 3) / 2)
    reaction = row.get("reaction")
    if reaction in REACTION_SIGNAL:
        values.append(REACTION_SIGNAL[reaction])
    return sum(values) / len(values) if values else None


def image_features(row: dict, category_names: dict[int, str]) -> list[tuple[str, str]]:
    feats: list[tuple[str, str]] = []
    for cid in row.get("category_ids") or []:
        if cid in category_names:
            feats.append(("category", category_names[cid]))
    for group, column in (
        ("context", "context"),
        ("lighting", "lighting"),
        ("framing", "framing"),
        ("clothing", "clothing_style"),
    ):
        value = row.get(column)
        if value and value != "nao_aplica":
            feats.append((group, value))
    for tag in row.get("tags") or []:
        feats.append(("tag", str(tag)))
    metrics = metrics_of(row)
    if metrics:
        feats.append(("tone", image_analysis.tone_class(metrics)))
        feats.append(("temperature", image_analysis.temperature_class(metrics)))
        feats.append(("saturation", image_analysis.saturation_class(metrics)))
    return list(dict.fromkeys(feats))


@dataclass
class FeatureStat:
    group: str
    value: str
    count: int
    signal_sum: float

    @property
    def mean(self) -> float:
        return self.signal_sum / self.count if self.count else 0.0

    @property
    def preference(self) -> float:
        """Média suavizada (−1 a 1)."""
        return self.signal_sum / (self.count + PRIOR_STRENGTH)

    @property
    def confidence(self) -> float:
        return self.count / (self.count + PRIOR_STRENGTH)

    @property
    def phrase(self) -> str:
        return feature_phrase(self.group, self.value)


@dataclass
class PreferenceModel:
    stats: dict[tuple[str, str], FeatureStat]
    evaluated: int
    group_weights: dict[str, float]
    category_weights: dict[str, float]
    preferred_palette: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.evaluated >= MIN_REFERENCES

    def weight(self, group: str, value: str) -> float:
        w = float(self.group_weights.get(group, 1.0))
        if group == "category":
            w *= float(self.category_weights.get(value, 1.0))
        return max(0.0, w)

    def ranked(self, positive: bool = True, min_count: int = MIN_FEATURE_COUNT) -> list[FeatureStat]:
        items = [s for s in self.stats.values() if s.count >= min_count]
        items = [s for s in items if (s.preference > 0) == positive and s.preference != 0]
        return sorted(
            items,
            key=lambda s: s.preference * self.weight(s.group, s.value),
            reverse=positive,
        )


def learn_preferences(
    references: list[dict],
    category_names: dict[int, str],
    group_weights: dict[str, float] | None = None,
    category_weights: dict[str, float] | None = None,
) -> PreferenceModel:
    stats: dict[tuple[str, str], FeatureStat] = {}
    evaluated = 0
    palette_votes: dict[str, float] = defaultdict(float)
    for row in references:
        signal = image_signal(row)
        if signal is None:
            continue
        evaluated += 1
        for group, value in image_features(row, category_names):
            stat = stats.setdefault((group, value), FeatureStat(group, value, 0, 0.0))
            stat.count += 1
            stat.signal_sum += signal
        if signal > 0:
            metrics = metrics_of(row)
            for color in metrics.palette if metrics else []:
                palette_votes[_coarse_hex(color.hex)] += color.share * signal
    preferred = [h for h, _ in sorted(palette_votes.items(), key=lambda kv: kv[1], reverse=True)[:6]]
    return PreferenceModel(
        stats=stats,
        evaluated=evaluated,
        group_weights={**DEFAULT_PREFERENCE_GROUP_WEIGHTS, **(group_weights or {})},
        category_weights=category_weights or {},
        preferred_palette=preferred,
    )


def _coarse_hex(hex_color: str) -> str:
    """Agrupa cores parecidas arredondando cada canal em passos de 32."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    q = lambda v: min(255, (v // 32) * 32 + 16)  # noqa: E731
    return f"#{q(r):02x}{q(g):02x}{q(b):02x}"


@dataclass
class Affinity:
    score: float  # −1 a 1
    coverage: float  # fração das características da foto conhecidas pelo modelo
    positives: list[tuple[str, float]]
    negatives: list[tuple[str, float]]

    @property
    def percent(self) -> int:
        return round((self.score + 1) / 2 * 100)


def affinity(row: dict, model: PreferenceModel, category_names: dict[int, str]) -> Affinity:
    feats = image_features(row, category_names)
    contributions: list[tuple[str, float]] = []
    total_weight = 0.0
    weighted = 0.0
    for group, value in feats:
        stat = model.stats.get((group, value))
        if not stat:
            continue
        w = model.weight(group, value)
        if w <= 0:
            continue
        total_weight += w
        weighted += w * stat.preference
        contributions.append((stat.phrase, stat.preference))
    known = len(contributions)
    score = weighted / total_weight if total_weight else 0.0
    positives = sorted([c for c in contributions if c[1] > 0.05], key=lambda c: -c[1])[:3]
    negatives = sorted([c for c in contributions if c[1] < -0.05], key=lambda c: c[1])[:3]
    return Affinity(
        score=max(-1.0, min(1.0, score)),
        coverage=known / len(feats) if feats else 0.0,
        positives=positives,
        negatives=negatives,
    )


def _join(phrases: list[str]) -> str:
    if len(phrases) <= 1:
        return "".join(phrases)
    return ", ".join(phrases[:-1]) + " e " + phrases[-1]


def insights(model: PreferenceModel, limit: int = 4) -> list[str]:
    """Frases explicáveis sobre o que o usuário costuma avaliar melhor ou pior."""
    if not model.ready:
        return []
    out = []
    liked = [s for s in model.ranked(True) if s.preference >= INSIGHT_THRESHOLD][:limit]
    disliked = [s for s in model.ranked(False) if s.preference <= -INSIGHT_THRESHOLD][:limit]
    if liked:
        out.append(
            "Você costuma avaliar melhor fotografias com "
            + _join([s.phrase for s in liked])
            + f" (com base em {model.evaluated} referências avaliadas)."
        )
    if disliked:
        out.append("Você tende a avaliar pior imagens com " + _join([s.phrase for s in disliked]) + ".")
    if not out:
        out.append(
            "Ainda não há um padrão claro: suas avaliações estão equilibradas entre as características. "
            "Avaliar mais referências, inclusive as que você não gosta, ajuda a revelar preferências."
        )
    return out


def compare_with_own_photos(
    own_photos: list[dict], model: PreferenceModel, category_names: dict[int, str]
) -> list[str]:
    """Recomendações comparando suas fotos com o que você prefere nas referências."""
    if not model.ready or not own_photos:
        return []
    total = len(own_photos)
    own_feats = [set(image_features(p, category_names)) for p in own_photos]

    def share(key: tuple[str, str]) -> float:
        return sum(1 for feats in own_feats if key in feats) / total

    recs = []
    for stat in [s for s in model.ranked(True) if s.preference >= INSIGHT_THRESHOLD][:4]:
        s = share((stat.group, stat.value))
        if s < 0.3:
            recs.append(
                f"Suas referências preferidas costumam ter {stat.phrase}, mas só {s:.0%} das suas "
                f"fotos têm essa característica. Vale produzir mais fotos assim."
            )
    for stat in [s for s in model.ranked(False) if s.preference <= -INSIGHT_THRESHOLD][:3]:
        s = share((stat.group, stat.value))
        if s >= 0.4:
            recs.append(
                f"{s:.0%} das suas fotos têm {stat.phrase}, algo que você costuma avaliar pior nas "
                "referências. Considere priorizar outras opções no feed."
            )
    if not recs:
        recs.append("Suas fotos já estão alinhadas às características que você mais valoriza nas referências.")
    return recs


def load_model(db) -> tuple[PreferenceModel, dict[int, str]]:
    """Monta o modelo a partir do banco: referências, categorias e pesos salvos."""
    from database import images as images_repo
    from database.settings import get_setting

    categories = images_repo.list_categories(db)
    names = {c["id"]: c["name"] for c in categories}
    model = learn_preferences(
        images_repo.list_images(db, "reference"),
        names,
        group_weights=get_setting(db, "preference_group_weights"),
        category_weights={c["name"]: c["weight"] for c in categories},
    )
    return model, names
