"""Vocabulários controlados usados no banco, nos serviços e na interface.

Os códigos (chaves) são gravados no banco; os rótulos (valores) aparecem na
interface. Manter os códigos estáveis evita migrações quando um texto muda.
"""

from __future__ import annotations

# --- Imagens -----------------------------------------------------------------

IMAGE_KINDS = ("own", "reference")

ALLOWED_EXTENSIONS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}
ALLOWED_FORMATS = frozenset(ALLOWED_EXTENSIONS.values())
FORMAT_EXTENSION = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}

DEFAULT_PHOTO_TAGS = [
    "praia",
    "retrato",
    "viagem",
    "esporte",
    "academia",
    "social",
    "cidade",
    "arquitetura",
    "moda",
    "natureza",
]

FRAMING = {
    "close": "Close / rosto",
    "meio_corpo": "Meio corpo",
    "corpo_inteiro": "Corpo inteiro",
    "plano_aberto": "Plano aberto / cenário",
    "detalhe": "Detalhe / objeto",
    "grupo": "Grupo",
}

LIGHTING = {
    "natural_dia": "Luz natural de dia",
    "golden_hour": "Golden hour (luz quente)",
    "sombra": "Sombra / nublado",
    "contraluz": "Contraluz",
    "noite": "Noite / luz artificial",
    "interna": "Interna / estúdio",
}

CONTEXT = {
    "praia": "Praia / mar",
    "cidade": "Cidade / rua",
    "arquitetura": "Arquitetura",
    "natureza": "Natureza",
    "esporte": "Esporte / academia",
    "social": "Evento social",
    "universidade": "Universidade",
    "interior": "Casa / interior",
    "restaurante": "Restaurante / bar",
    "viagem": "Viagem / ponto turístico",
}

CLOTHING = {
    "nao_aplica": "Não se aplica",
    "casual": "Casual bem cuidado",
    "minimalista": "Minimalista / old money",
    "esportivo": "Esportivo",
    "praia": "Moda praia",
    "social": "Social / alfaiataria",
    "streetwear": "Streetwear",
}

REACTIONS = {
    "gosto": "Gosto",
    "neutro": "Neutro",
    "nao_gosto": "Não gosto",
}
REACTION_SIGNAL = {"gosto": 1.0, "neutro": 0.0, "nao_gosto": -1.0}

DEFAULT_CATEGORIES = [
    ("Mediterrâneo e verão europeu", "Praia, mar azul, luz de verão, cidades costeiras."),
    ("Minimalista e old money", "Paleta neutra, peças clássicas, poucos elementos na cena."),
    ("Moda masculina casual", "Roupas bem cuidadas do dia a dia, caimento e combinação."),
    ("Fitness e esportes", "Natação, futevôlei, treino e esportes ao ar livre."),
    ("Viagens e arquitetura", "Cidades, construções, pontos de viagem e perspectiva urbana."),
    ("Vida universitária e social", "Amigos, eventos, campus e momentos sociais."),
    ("Espontâneo e retrato natural", "Fotos sem pose rígida, expressões naturais."),
    ("Luxo discreto", "Elegância sem ostentação: detalhes, lugares e texturas."),
]

# --- Perfis de interesse ------------------------------------------------------

INTEREST_STATUS = {
    "novo": "Novo",
    "revisar": "Revisar",
    "interessante": "Interessante",
    "arquivado": "Arquivado",
}

PRIORITY = {"baixa": "Baixa", "media": "Média", "alta": "Alta"}
PRIORITY_ORDER = {"alta": 0, "media": 1, "baixa": 2}

DEFAULT_INTEREST_CATEGORIES = [
    "Moda e lifestyle",
    "Esporte e fitness",
    "Universidade",
    "Viagens",
    "Fotografia",
    "Outros",
]

DISCOVERY_SOURCES = [
    "Explorar",
    "Reels",
    "Indicação de amigo",
    "Marcação em foto",
    "Hashtag ou local",
    "Comentários",
    "Fora do Instagram",
    "Outra",
]

# --- Acompanhamento de follow-back ---------------------------------------------

FOLLOW_STATUS = {
    "pendente": "Pendente",
    "seguiu_de_volta": "Seguiu de volta",
    "nao_seguiu_de_volta": "Não seguiu de volta",
    "encerrado": "Encerrado",
}

# --- Planejador de conteúdo -----------------------------------------------------

CONTENT_TYPES = {
    "reels": "Reels (vídeo curto)",
    "carrossel": "Carrossel",
    "foto": "Foto única",
    "stories": "Stories",
}

CONTENT_STATUS = {
    "ideia": "Ideia",
    "planejado": "Planejado",
    "publicado": "Publicado",
}

CONTENT_OBJECTIVES = [
    "Alcance (novas pessoas)",
    "Conexão com quem já segue",
    "Mostrar estilo pessoal",
    "Mostrar rotina esportiva",
    "Mostrar viagens",
    "Gerar conversas",
]

WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# --- Perfil ---------------------------------------------------------------------

BIO_LANGUAGES = {"pt": "Português", "en": "Inglês"}
INSTAGRAM_BIO_LIMIT = 150
HIGHLIGHT_NAME_LIMIT = 15


def label(mapping: dict[str, str], code: str | None, default: str = "—") -> str:
    """Rótulo legível de um código; devolve `default` se vazio ou desconhecido."""
    if not code:
        return default
    return mapping.get(code, code)
