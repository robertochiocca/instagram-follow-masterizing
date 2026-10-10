"""Sugestões para o perfil: bios, destaques, legendas, ideias de conteúdo e diagnóstico.

Regras de geração:
- Usa SOMENTE fatos informados pelo usuário (ocupação, cidade, atividades,
  interesses). Nada de "influencer", números de seguidores ou conquistas não
  confirmadas.
- Textos curtos, sem clichês; o limite de 150 caracteres da bio é respeitado.
- Geração por modelos (templates) — determinística e sem serviços externos.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from models.vocab import HIGHLIGHT_NAME_LIMIT, INSTAGRAM_BIO_LIMIT

# Tradução de termos comuns para as versões em inglês (termos desconhecidos ficam como estão).
PT_EN = {
    "natação": "swimming", "natacao": "swimming", "futevôlei": "footvolley", "futevolei": "footvolley",
    "futebol": "football", "vôlei": "volleyball", "volei": "volleyball", "corrida": "running",
    "academia": "gym", "musculação": "training", "musculacao": "training", "treino": "training",
    "surfe": "surf", "surf": "surf", "tênis": "tennis", "tenis": "tennis", "ciclismo": "cycling",
    "praia": "beach", "viagens": "travel", "viagem": "travel", "moda": "style", "estilo": "style",
    "arquitetura": "architecture", "fotografia": "photography", "música": "music", "musica": "music",
    "cidades": "cities", "mar": "sea", "gastronomia": "food", "cinema": "film", "leitura": "books",
    "design": "design", "arte": "art", "remo": "rowing", "vela": "sailing", "padel": "padel",
    "beach tennis": "beach tennis", "basquete": "basketball", "golfe": "golf", "yoga": "yoga",
}

SPORT_EMOJI = {
    "natação": "🏊", "natacao": "🏊", "swimming": "🏊", "futevôlei": "⚽", "futevolei": "⚽",
    "futebol": "⚽", "vôlei": "🏐", "volei": "🏐", "corrida": "🏃", "running": "🏃", "academia": "🏋️",
    "musculação": "🏋️", "treino": "🏋️", "surfe": "🏄", "surf": "🏄", "tênis": "🎾", "tenis": "🎾",
    "beach tennis": "🎾", "padel": "🎾", "ciclismo": "🚴", "praia": "🌊", "remo": "🚣", "vela": "⛵",
    "basquete": "🏀", "golfe": "⛳", "yoga": "🧘",
}

TRAVEL_WORDS = {"viagens", "viagem", "travel", "arquitetura", "cidades", "mundo", "europa", "mediterrâneo"}

GENERIC_PHRASES = [
    "good vibes", "only good vibes", "living my best life", "vivendo a vida", "vivendo intensamente",
    "just me", "sorria", "seja feliz", "carpe diem", "não sou perfeito", "nao sou perfeito",
    "influencer", "digital influencer", "blogueiro", "sigam", "follow me", "sigo de volta",
    "f4f", "follow for follow",
]

BIO_STYLES = {
    "curta": "Curta e natural",
    "minimalista": "Minimalista",
    "esportes": "Esportes e lifestyle",
    "viagens": "Viagens e estilo internacional",
}


def split_list(text: str | None) -> list[str]:
    items = re.split(r"[,;\n/·|]+", text or "")
    out = []
    for item in items:
        clean = item.strip(" .-—")
        if clean and clean.lower() not in [o.lower() for o in out]:
            out.append(clean)
    return out


def translate(term: str, lang: str) -> str:
    if lang != "en":
        return term
    return PT_EN.get(term.strip().lower(), term)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


@dataclass
class BioSuggestion:
    style: str
    language: str
    text: str
    notes: list[str] = field(default_factory=list)

    @property
    def length(self) -> int:
        return len(self.text)


def _fit(lines: list[str]) -> str:
    """Junta linhas e remove as últimas até caber em 150 caracteres."""
    lines = [l for l in lines if l]
    while lines and len("\n".join(lines)) > INSTAGRAM_BIO_LIMIT:
        lines.pop()
    return "\n".join(lines)


def generate_bios(profile: dict, languages: list[str] | None = None) -> list[BioSuggestion]:
    langs = languages or profile.get("bio_languages") or ["pt"]
    occupation = (profile.get("occupation") or "").strip()
    location = (profile.get("location") or "").strip()
    activities = split_list(profile.get("activities"))
    interests = split_list(profile.get("interests"))
    has_link = bool((profile.get("bio_link") or "").strip())
    out: list[BioSuggestion] = []
    missing = []
    if not occupation:
        missing.append("ocupação/estudo")
    if not location:
        missing.append("cidade")
    if not activities and not interests:
        missing.append("atividades ou interesses")
    base_note = (
        [f"Preencha {', '.join(missing)} em “Dados do perfil” para sugestões mais pessoais."]
        if missing else []
    )

    for lang in langs:
        acts = [translate(a, lang) for a in activities]
        ints = [translate(i, lang) for i in interests]
        en = lang == "en"
        note = ["Revise a tradução de termos pessoais."] if en and (occupation or acts or ints) else []
        pin = f"📍 {location}" if location else ""

        # 1. Curta e natural
        middle = " · ".join(x.lower() for x in (acts + ints)[:3])
        lines = [occupation, _cap(middle), pin]
        out.append(BioSuggestion("curta", lang, _fit(lines), base_note + note))

        # 2. Minimalista: uma ou duas linhas, sem emoji
        first = " — ".join(p for p in (location, occupation) if p)
        second = " / ".join(a.lower() for a in (acts + ints)[:3])
        out.append(BioSuggestion("minimalista", lang, _fit([first, second]), base_note + note))

        # 3. Esportes e lifestyle
        if activities:
            sport_line = " · ".join(
                f"{SPORT_EMOJI.get(a.lower(), '')} {_cap(translate(a, lang))}".strip() for a in activities[:3]
            )
            lifestyle = ints[:2]
            extra = (" & ".join(lifestyle) if en else " e ".join(lifestyle)).lower()
            lines = [sport_line, _cap(extra) if extra else "", " · ".join(p for p in (occupation, location) if p)]
            out.append(BioSuggestion("esportes", lang, _fit(lines), base_note + note))
        else:
            out.append(BioSuggestion(
                "esportes", lang, "",
                ["Informe seus esportes/atividades em “Dados do perfil” para gerar esta versão."],
            ))

        # 4. Viagens e estilo internacional
        travel_terms = [i for i in interests if i.lower() in TRAVEL_WORDS]
        languages_line = " · ".join(code.upper() for code in langs) if len(langs) > 1 else ""
        trips = " · ".join(translate(t, lang).lower() for t in (travel_terms or interests)[:3])
        lines = [
            f"{location} ✈️" if location else "✈️",
            _cap(trips) if trips else "",
            occupation,
            languages_line,
        ]
        notes = base_note + note
        if not travel_terms:
            notes = notes + ["Acrescente “viagens”, “arquitetura” ou “cidades” aos interesses, se fizer sentido para você."]
        out.append(BioSuggestion("viagens", lang, _fit(lines), notes))

    if has_link:
        for s in out:
            if s.text and len(s.text) + 2 <= INSTAGRAM_BIO_LIMIT:
                s.text += "\n↓"
    return out


@dataclass
class BioCheck:
    label: str
    ok: bool


def check_bio(text: str, profile: dict) -> list[BioCheck]:
    """Checklist objetivo usado para comparar a bio atual com as alternativas."""
    text = text or ""
    lower = text.lower()
    facts = split_list(profile.get("activities")) + split_list(profile.get("interests"))
    emojis = len(re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", text))
    hashtags = len(re.findall(r"#\w+", text))
    return [
        BioCheck(f"Até {INSTAGRAM_BIO_LIMIT} caracteres ({len(text)})", 0 < len(text) <= INSTAGRAM_BIO_LIMIT),
        BioCheck("Diz quem você é (ocupação ou cidade)", any(
            p and p.lower() in lower for p in (profile.get("occupation"), profile.get("location"))
        )),
        BioCheck("Cita interesses/atividades que você informou", any(
            f.lower() in lower or translate(f, "en").lower() in lower for f in facts
        )),
        BioCheck("No máximo 4 emojis", emojis <= 4),
        BioCheck("No máximo 1 hashtag", hashtags <= 1),
        BioCheck("Sem frases genéricas ou pedidos de follow", not any(p in lower for p in GENERIC_PHRASES)),
        BioCheck("No máximo 4 linhas", text.count("\n") <= 3),
    ]


def bio_score(text: str, profile: dict) -> int:
    checks = check_bio(text, profile)
    return round(sum(c.ok for c in checks) / len(checks) * 100) if text else 0


# --- Destaques -----------------------------------------------------------------------

HIGHLIGHT_CATALOG = [
    # (chave, nome PT, nome EN, palavras relacionadas)
    ("viagens", "Viagens", "Trips", {"viagens", "viagem", "travel", "mundo"}),
    ("praia", "Verão", "Summer", {"praia", "mar", "mediterrâneo", "verão"}),
    ("esportes", "Esportes", "Sports", {"esporte", "esportes", "fitness", "natação", "futevôlei",
                                         "futebol", "vôlei", "surfe", "tênis", "corrida"}),
    ("treino", "Treino", "Training", {"academia", "treino", "musculação", "fitness"}),
    ("cidades", "Cidades", "Cities", {"cidades", "arquitetura", "cidade"}),
    ("estilo", "Looks", "Style", {"moda", "estilo", "old money", "minimalista", "casual"}),
    ("amigos", "Amigos", "Friends", {"social", "amigos", "universitária", "festa"}),
    ("uni", "Uni", "Campus", {"universidade", "faculdade", "universitária", "campus"}),
]

CATEGORY_TO_HIGHLIGHT = {
    "Mediterrâneo e verão europeu": ["praia", "viagens"],
    "Minimalista e old money": ["estilo"],
    "Moda masculina casual": ["estilo"],
    "Fitness e esportes": ["esportes", "treino"],
    "Viagens e arquitetura": ["viagens", "cidades"],
    "Vida universitária e social": ["amigos", "uni"],
    "Espontâneo e retrato natural": ["amigos"],
    "Luxo discreto": ["estilo"],
}


@dataclass
class HighlightSuggestion:
    name_pt: str
    name_en: str
    reason: str
    score: float


def suggest_highlights(
    profile: dict,
    category_weights: dict[str, float],
    photo_tag_counts: dict[str, int] | None = None,
    limit: int = 6,
) -> list[HighlightSuggestion]:
    """Destaques ordenados por relevância: categorias valorizadas, atividades e fotos existentes."""
    words = {w.lower() for w in split_list(profile.get("activities")) + split_list(profile.get("interests"))}
    words |= {w.lower() for w in split_list(profile.get("goals"))}
    tags = {k.lower(): v for k, v in (photo_tag_counts or {}).items()}
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for category, weight in category_weights.items():
        for key in CATEGORY_TO_HIGHLIGHT.get(category, []):
            scores[key] = scores.get(key, 0) + weight
            reasons.setdefault(key, []).append(f"categoria “{category}”")
    for key, _, _, related in HIGHLIGHT_CATALOG:
        hits = sorted(words & related)
        if hits:
            scores[key] = scores.get(key, 0) + 1.5
            reasons.setdefault(key, []).append("você citou " + ", ".join(hits))
        photo_hits = sum(v for t, v in tags.items() if t in related)
        if photo_hits:
            scores[key] = scores.get(key, 0) + min(1.5, photo_hits * 0.15)
            reasons.setdefault(key, []).append(f"{photo_hits} foto(s) com tags relacionadas")
    # Atividades específicas podem virar destaque próprio (ex.: “Futevôlei”).
    specific = []
    for act in split_list(profile.get("activities"))[:2]:
        if len(act) <= HIGHLIGHT_NAME_LIMIT:
            specific.append(HighlightSuggestion(_cap(act), _cap(translate(act, "en")),
                                                "atividade que você pratica", 2.0))
    catalog = {k: (pt, en) for k, pt, en, _ in HIGHLIGHT_CATALOG}
    general = [
        HighlightSuggestion(catalog[k][0], catalog[k][1], "; ".join(dict.fromkeys(reasons.get(k, []))), s)
        for k, s in scores.items()
        if s > 0
    ]
    merged = sorted(specific + general, key=lambda h: -h.score)
    out, seen = [], set()
    for h in merged:
        if h.name_pt.lower() in seen:
            continue
        # Evita “Esportes” genérico quando já há destaque de um esporte específico.
        if h.name_pt == "Esportes" and specific:
            continue
        seen.add(h.name_pt.lower())
        out.append(h)
    return out[:limit]


def review_existing_highlights(text: str | None) -> list[str]:
    names = split_list(text)
    notes = []
    for n in names:
        if len(n) > HIGHLIGHT_NAME_LIMIT:
            notes.append(f"“{n}” tem {len(n)} caracteres; nomes longos são cortados na tela do perfil.")
    if len(names) > 8:
        notes.append("Mais de 8 destaques dificulta a navegação; considere agrupar temas parecidos.")
    if names and len(names) < 3:
        notes.append("Com menos de 3 destaques o perfil mostra pouco de você; 4–6 costuma ser um bom número.")
    return notes


# --- Legendas ----------------------------------------------------------------------------

CAPTION_THEMES = {
    "praia": "Praia / mar",
    "viagem": "Viagem",
    "cidade": "Cidade / arquitetura",
    "esporte": "Esporte / treino",
    "social": "Amigos / social",
    "retrato": "Retrato / estilo",
    "universidade": "Universidade",
}

CAPTIONS = {
    "praia": {
        "pt": ["Sal no cabelo, sem pressa.", "Mar calmo, cabeça leve.", "Dia de mar.",
               "O melhor horário é quando o sol começa a baixar.", "Pé na areia e mais nada.",
               "{lugar}, água clara e tempo sobrando."],
        "en": ["Salt water, slow days.", "Sea first, plans later.", "Golden hour by the water.",
               "Another day by the sea.", "{lugar}, no rush."],
    },
    "viagem": {
        "pt": ["Anotando lugares para voltar.", "Andar sem mapa é a melhor parte.",
               "Pouca mala, muito caminho.", "{lugar}, visto devagar.", "Lembranças de {lugar}."],
        "en": ["Collecting places to come back to.", "{lugar}, slowly.", "Wandering without a plan.",
               "Notes from {lugar}.", "Light luggage, long walks."],
    },
    "cidade": {
        "pt": ["Esquinas que valem a pausa.", "A cidade fica melhor a pé.", "Arquitetura e café, nessa ordem.",
               "{lugar} entre prédios e luz."],
        "en": ["Corners worth stopping for.", "Cities are better on foot.", "Architecture, then coffee.",
               "{lugar} in good light."],
    },
    "esporte": {
        "pt": ["Treino feito, cabeça no lugar.", "Areia, bola e amigos.", "Constância > intensidade.",
               "Mais uma sessão de {esporte}.", "Dia de quadra."],
        "en": ["Training done, mind clear.", "Sand, ball, good company.", "Consistency over intensity.",
               "Another {esporte} session.", "Court days."],
    },
    "social": {
        "pt": ["Os de sempre.", "Boa companhia resolve.", "Noites que viram história.",
               "Encontro marcado, sem hora pra acabar."],
        "en": ["The usual suspects.", "Good company, long night.", "Nights worth remembering."],
    },
    "retrato": {
        "pt": ["Simples funciona.", "Linho e dia longo.", "Menos é mais, quase sempre.",
               "Luz natural, nada além."],
        "en": ["Keep it simple.", "Linen and long days.", "Less, but better.", "Natural light, nothing else."],
    },
    "universidade": {
        "pt": ["Entre aulas e planos.", "Semestre em andamento.", "Campus, café e prazos."],
        "en": ["Between classes and plans.", "Semester mode.", "Campus, coffee, deadlines."],
    },
}

CTAS = {
    "pt": {
        "viagem": ["Qual lugar eu deveria conhecer em seguida?", "Me conta seu lugar favorito pra isso.",
                   "Salva pra próxima viagem."],
        "esporte": ["Quem também joga?", "Qual treino vocês não pulam?", "Bora marcar um jogo?"],
        "geral": ["Qual foto vocês preferem?", "Dicas nos comentários são bem-vindas."],
    },
    "en": {
        "viagem": ["Where should I go next?", "Tell me your favorite spot.", "Save it for your next trip."],
        "esporte": ["Who else plays?", "Which workout do you never skip?"],
        "geral": ["Which one is your favorite?", "Tips in the comments are welcome."],
    },
}
CTA_GROUP = {"praia": "viagem", "viagem": "viagem", "cidade": "viagem", "esporte": "esporte"}

HASHTAGS = {
    "praia": ["#summer", "#mediterranean", "#seaside"],
    "viagem": ["#travel", "#europe", "#travelgram"],
    "cidade": ["#architecture", "#citywalk", "#streetphotography"],
    "esporte": ["#futevolei", "#swimming", "#training"],
    "social": ["#friends", "#weekend"],
    "retrato": ["#mensstyle", "#minimalstyle", "#oldmoney"],
    "universidade": ["#campuslife", "#university"],
}


def generate_captions(
    theme: str,
    language: str = "pt",
    place: str = "",
    sport: str = "",
    with_cta: bool = False,
    with_hashtags: bool = False,
    count: int = 4,
    seed: int = 0,
) -> list[str]:
    bank = CAPTIONS.get(theme, CAPTIONS["retrato"])[language if language in ("pt", "en") else "pt"]
    place = place.strip()
    sport = translate(sport.strip(), language) if sport else ""
    usable = [
        c for c in bank
        if ("{lugar}" not in c or place) and ("{esporte}" not in c or sport)
    ]
    rng = random.Random(f"{theme}-{language}-{seed}")
    picks = rng.sample(usable, k=min(count, len(usable)))
    out = []
    for i, text in enumerate(picks):
        text = text.replace("{lugar}", place).replace("{esporte}", sport.lower())
        if with_cta:
            ctas = CTAS[language if language in CTAS else "pt"][CTA_GROUP.get(theme, "geral")]
            text += "\n\n" + ctas[(seed + i) % len(ctas)]
        if with_hashtags:
            text += "\n\n" + " ".join(HASHTAGS.get(theme, [])[:3])
        out.append(text)
    return out


# --- Ideias de conteúdo ---------------------------------------------------------------------

IDEAS = [
    ("Fitness e esportes", "Reels", "Treino em 3 cortes (aquecimento, série principal, pós-treino), 10–15 s, celular fixo."),
    ("Fitness e esportes", "Reels", "Melhor jogada de futevôlei em câmera lenta, câmera fixa na lateral da quadra."),
    ("Fitness e esportes", "Carrossel", "“Semana de treino”: uma foto por dia, mesma paleta de cores."),
    ("Mediterrâneo e verão europeu", "Carrossel", "Trio clássico: plano aberto do mar + retrato meio corpo + detalhe (óculos, toalha)."),
    ("Mediterrâneo e verão europeu", "Reels", "7 s da água em câmera lenta com legenda curta, sem texto na tela."),
    ("Viagens e arquitetura", "Reels", "“Um dia em <cidade>” com 6–8 clipes de 1 s cada, na ordem do dia."),
    ("Viagens e arquitetura", "Carrossel", "Detalhes arquitetônicos com cores parecidas (portas, janelas, escadas)."),
    ("Viagens e arquitetura", "Foto", "Antes e depois do pôr do sol no mesmo ponto."),
    ("Minimalista e old money", "Carrossel", "Look em 3 fotos: corpo inteiro, meio corpo e detalhe do tecido."),
    ("Moda masculina casual", "Reels", "Como monto um look casual com 4 peças, cortes de 2 s."),
    ("Vida universitária e social", "Carrossel", "Fotodump do mês: 6–10 fotos espontâneas com amigos."),
    ("Vida universitária e social", "Stories", "Bastidores do campus com enquete simples."),
    ("Espontâneo e retrato natural", "Foto", "Peça a um amigo para fotografar em sequência enquanto você caminha; escolha o quadro mais natural."),
    ("Luxo discreto", "Foto", "Detalhes: relógio, café, textura do linho — sem exibir marcas em excesso."),
    (None, "Stories", "Caixinha de perguntas sobre seus esportes ou viagens; responda 3 por dia."),
    (None, "Reels", "Transição simples: entrar no mar / mergulho em um corte."),
    (None, "Carrossel", "“Minha semana em 7 fotos”, com uma frase curta na legenda."),
]


def content_ideas(category_weights: dict[str, float], limit: int = 8) -> list[tuple[str, str, str]]:
    """Ideias (categoria, formato, descrição) priorizando as categorias mais valorizadas."""
    def score(item):
        cat = item[0]
        return category_weights.get(cat, 0.5) if cat else 0.6
    ranked = sorted(IDEAS, key=lambda it: -score(it))
    return [(cat or "Geral", fmt, text) for cat, fmt, text in ranked if score((cat, fmt, text)) > 0][:limit]


# --- Diagnóstico ---------------------------------------------------------------------------------


def diagnose(profile: dict, avg_daily_gain: float | None = None, published_last_14_days: int | None = None) -> list[tuple[str, str]]:
    """Lista de (nível, recomendação explicada). Níveis: 'acao', 'dica', 'ok'."""
    out: list[tuple[str, str]] = []
    bio = (profile.get("bio") or "").strip()
    followers = profile.get("followers")
    following = profile.get("following")
    posts = profile.get("posts")
    if not bio:
        out.append(("acao", "Escreva uma bio: quem você é, 2–3 interesses reais e onde está. Veja as sugestões abaixo."))
    elif len(bio) > INSTAGRAM_BIO_LIMIT:
        out.append(("acao", f"A bio tem {len(bio)} caracteres; o Instagram aceita até {INSTAGRAM_BIO_LIMIT}."))
    if posts is not None and posts < 9:
        out.append(("acao", f"Você tem {posts} publicações. Com 9 ou mais a grade forma 3 linhas e o perfil "
                            "transmite mais consistência para quem visita."))
    if followers and following and following > 2 * followers:
        out.append(("dica", f"Você segue {following} perfis e tem {followers} seguidores. Seguir muitas contas "
                            "sem afinidade pode parecer follow-for-follow; priorize perfis do seu nicho."))
    if not split_list(profile.get("highlights")):
        out.append(("dica", "Crie de 3 a 6 destaques com temas claros (ex.: viagens, esportes, amigos)."))
    if not (profile.get("goals") or "").strip() or not (profile.get("audience") or "").strip():
        out.append(("dica", "Defina objetivo e público desejado: as sugestões ficam mais precisas."))
    if published_last_14_days is not None and published_last_14_days < 2:
        out.append(("dica", "Poucas publicações nos últimos 14 dias. Um ritmo sustentável é 2–3 por semana, "
                            "com Stories nos outros dias."))
    if avg_daily_gain is not None and avg_daily_gain <= 0:
        out.append(("dica", "Seguidores estáveis ou em queda no último mês: teste Reels curtos, responda "
                            "comentários e interaja de verdade com perfis do seu nicho."))
    if (profile.get("account_category") or "").lower().startswith("pessoal"):
        out.append(("dica", "Contas profissionais (Criador de conteúdo) liberam Insights de alcance e visitas "
                            "gratuitamente, e é possível voltar para conta pessoal depois."))
    if not out:
        out.append(("ok", "Perfil bem estruturado. Mantenha a regularidade e acompanhe os resultados no Dashboard."))
    return out
