"""Valores padrão das configurações ajustáveis pelo usuário.

Os pesos são documentados no README (seção "Critérios e pesos").
"""

from __future__ import annotations

from models.vocab import DEFAULT_INTEREST_CATEGORIES, DEFAULT_PHOTO_TAGS

# Pontuação técnica 0–100: peso relativo de cada critério (normalizados para somar 1).
DEFAULT_SCORE_WEIGHTS = {
    "exposure": 20,
    "contrast": 15,
    "sharpness": 25,
    "clipping": 10,
    "color": 10,
    "resolution": 10,
    "composition": 10,
}

# Organizador do feed: equilíbrio entre os quatro objetivos.
DEFAULT_FEED_WEIGHTS = {
    "quality": 35,
    "diversity": 25,
    "coherence": 20,
    "preference": 20,
}

# Aprendizado de preferências: importância de cada grupo de característica.
DEFAULT_PREFERENCE_GROUP_WEIGHTS = {
    "category": 1.0,
    "context": 1.0,
    "lighting": 1.0,
    "framing": 0.8,
    "clothing": 0.6,
    "tag": 0.6,
    "tone": 0.5,
    "temperature": 0.5,
    "saturation": 0.4,
}

DEFAULT_CONTENT_FREQUENCY = {
    "reels": 2,
    "carrossel": 1,
    "foto": 0,
    "stories": 3,
    "weekdays": ["Ter", "Qui", "Sáb"],
}

DEFAULT_SETTINGS = {
    "target_followers": 1000,
    "max_upload_mb": None,  # None = usar IGT_MAX_UPLOAD_MB
    "score_weights": DEFAULT_SCORE_WEIGHTS,
    "feed_weights": DEFAULT_FEED_WEIGHTS,
    "preference_group_weights": DEFAULT_PREFERENCE_GROUP_WEIGHTS,
    "interest_categories": DEFAULT_INTEREST_CATEGORIES,
    "photo_tags": DEFAULT_PHOTO_TAGS,
    "content_frequency": DEFAULT_CONTENT_FREQUENCY,
}
