"""Módulo D — Meu perfil: dados, bio, destaques, legendas, ideias e diagnóstico."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pandas as pd
import streamlit as st

from config import today
from database import images as images_repo
from database.settings import get_profile, save_profile
from models.vocab import BIO_LANGUAGES, INSTAGRAM_BIO_LIMIT
from services import content_planner, growth, metrics_log
from services import profile_suggestions as ps
from services.handles import normalize_url, normalize_username
from ui.components import copyable, done, page_header
from ui.state import get_db

db = get_db()
profile = get_profile(db)
categories = images_repo.list_categories(db)
category_weights = {c["name"]: c["weight"] for c in categories}

page_header(
    "Meu perfil",
    "Sugestões baseadas apenas no que você informar. Nada é alterado no Instagram: copie e "
    "aplique manualmente o que fizer sentido para você.",
)

tab_data, tab_bio, tab_high, tab_caps, tab_diag = st.tabs(
    ["Dados do perfil", "Bio", "Destaques", "Legendas e ideias", "Diagnóstico"]
)

ACCOUNT_CATEGORIES = ["Não sei", "Pessoal", "Criador de conteúdo", "Comercial"]

with tab_data:
    with st.form("profile_form"):
        a, b = st.columns(2)
        display_name = a.text_input("Nome de exibição", value=profile.get("display_name") or "", max_chars=64)
        username = b.text_input("Nome de usuário", value=profile.get("username") or "", placeholder="@usuario")
        bio = st.text_area("Bio atual", value=profile.get("bio") or "", max_chars=300,
                           help=f"O Instagram aceita até {INSTAGRAM_BIO_LIMIT} caracteres.")
        a, b = st.columns(2)
        acc = profile.get("account_category") or "Não sei"
        account_category = a.selectbox("Categoria de conta", ACCOUNT_CATEGORIES,
                                       index=ACCOUNT_CATEGORIES.index(acc) if acc in ACCOUNT_CATEGORIES else 0)
        bio_link = b.text_input("Link da bio", value=profile.get("bio_link") or "")
        a, b, c = st.columns(3)
        followers = a.number_input("Seguidores", min_value=0, value=profile.get("followers"), step=1)
        following = b.number_input("Seguindo", min_value=0, value=profile.get("following"), step=1)
        posts = c.number_input("Publicações", min_value=0, value=profile.get("posts"), step=1)
        register_metric = st.checkbox("Registrar estes números como métrica de hoje no Dashboard", value=False)
        st.markdown("**Sobre você** (usado para gerar sugestões; preencha só o que quiser)")
        a, b = st.columns(2)
        occupation = a.text_input("Ocupação ou estudo", value=profile.get("occupation") or "",
                                  placeholder="Ex.: Estudante de Engenharia", max_chars=60)
        location = b.text_input("Cidade / base", value=profile.get("location") or "", max_chars=40)
        activities = st.text_input("Esportes e atividades (separados por vírgula)",
                                   value=profile.get("activities") or "", placeholder="natação, futevôlei")
        interests = st.text_input("Interesses (separados por vírgula)", value=profile.get("interests") or "",
                                  placeholder="viagens, arquitetura, moda")
        highlights = st.text_area("Destaques existentes (um por linha)", value=profile.get("highlights") or "")
        goals = st.text_area("Objetivos pessoais", value=profile.get("goals") or "",
                             placeholder="Ex.: chegar a 1.000 seguidores reais, mostrar viagens e esportes")
        audience = st.text_area("Público que deseja alcançar", value=profile.get("audience") or "",
                                placeholder="Ex.: universitários, pessoas que curtem esporte e viagem")
        languages = st.multiselect("Idiomas da bio", list(BIO_LANGUAGES), format_func=BIO_LANGUAGES.get,
                                   default=profile.get("bio_languages") or ["pt"])
        if st.form_submit_button("Salvar perfil", type="primary", icon=":material/save:"):
            try:
                user = normalize_username(username) if username.strip() else None
                link = normalize_url(bio_link)
            except ValueError as exc:
                st.error(str(exc))
            else:
                save_profile(db, {
                    "display_name": display_name.strip() or None, "username": user, "bio": bio.strip() or None,
                    "account_category": account_category, "bio_link": link, "followers": followers,
                    "following": following, "posts": posts, "occupation": occupation.strip() or None,
                    "location": location.strip() or None, "activities": activities.strip() or None,
                    "interests": interests.strip() or None, "highlights": highlights.strip() or None,
                    "goals": goals.strip() or None, "audience": audience.strip() or None,
                    "bio_languages": languages or ["pt"],
                })
                if register_metric and followers is not None:
                    metrics_log.upsert_metric(db, {"date": today(), "followers": followers,
                                                   "following": following, "posts": posts})
                done("Perfil salvo.")

with tab_bio:
    current_bio = profile.get("bio") or ""
    st.markdown("#### Bio atual")
    if current_bio:
        st.text(current_bio)
        checks = ps.check_bio(current_bio, profile)
        st.caption(" · ".join(("✅ " if c.ok else "⚠️ ") + c.label for c in checks))
    else:
        st.caption("Nenhuma bio cadastrada em “Dados do perfil”.")

    bios = ps.generate_bios(profile)
    st.markdown("#### Alternativas")
    for style, style_label in ps.BIO_STYLES.items():
        st.markdown(f"**{style_label}**")
        for s in [b for b in bios if b.style == style]:
            if s.text:
                copyable(s.text, f"{BIO_LANGUAGES.get(s.language, s.language)} · {s.length} caracteres")
            for note in s.notes:
                st.caption(note)

    st.markdown("#### Comparação")
    candidates = [("Atual", current_bio)] + [
        (f"{ps.BIO_STYLES[b.style]} ({b.language.upper()})", b.text) for b in bios if b.text
    ]
    comparison = []
    for name, text in candidates:
        row = {"Bio": name, "Caracteres": len(text), "Checklist": f"{ps.bio_score(text, profile)}%"}
        for check in ps.check_bio(text, profile)[1:]:
            row[check.label] = "✅" if check.ok else "—"
        comparison.append(row)
    st.dataframe(pd.DataFrame(comparison), hide_index=True, width="stretch")
    st.caption("O checklist mede clareza e objetividade, não popularidade.")

with tab_high:
    own = images_repo.list_images(db, "own")
    tag_counts = Counter(t for r in own for t in r.get("tags") or [])
    suggestions = ps.suggest_highlights(profile, category_weights, dict(tag_counts))
    if not suggestions:
        st.info("Preencha atividades e interesses ou ajuste a importância das categorias para gerar sugestões.")
    else:
        st.markdown("#### Ordem sugerida")
        st.dataframe(
            pd.DataFrame([
                {"Ordem": i + 1, "Nome (PT)": h.name_pt, "Nome (EN)": h.name_en, "Por quê": h.reason}
                for i, h in enumerate(suggestions)
            ]),
            hide_index=True, width="stretch",
        )
        st.caption(
            "Nomes curtos (até 15 caracteres) aparecem inteiros. Capas com uma cor da sua paleta ou "
            "fotos simples deixam o perfil mais limpo. Os primeiros destaques são os mais vistos."
        )
    for note in ps.review_existing_highlights(profile.get("highlights")):
        st.markdown(f"- {note}")

with tab_caps:
    st.markdown("#### Legendas")
    a, b = st.columns(2)
    theme = a.selectbox("Tema", list(ps.CAPTION_THEMES), format_func=ps.CAPTION_THEMES.get)
    language = b.segmented_control("Idioma", ["pt", "en"], format_func=BIO_LANGUAGES.get, default="pt") or "pt"
    a, b = st.columns(2)
    place = a.text_input("Lugar (opcional)", placeholder="Ex.: Positano")
    acts = ps.split_list(profile.get("activities"))
    sport = b.text_input("Esporte (opcional)", value=acts[0] if acts else "")
    a, b, c = st.columns(3)
    with_cta = a.toggle("Chamada discreta")
    with_tags = b.toggle("Hashtags")
    if c.button("Gerar outras", icon=":material/refresh:"):
        st.session_state["caption_seed"] = st.session_state.get("caption_seed", 0) + 1
    for text in ps.generate_captions(theme, language, place, sport, with_cta, with_tags,
                                     seed=st.session_state.get("caption_seed", 0)):
        copyable(text)
    st.caption("Use poucas hashtags e só quando forem específicas do conteúdo.")

    st.markdown("#### Ideias de publicações e vídeos curtos")
    for cat, fmt, text in ps.content_ideas(category_weights):
        st.markdown(f"- **{fmt}** · {text} _({cat})_")

    st.markdown("#### Chamadas para ação discretas")
    lang_ctas = ps.CTAS[language]
    st.markdown("\n".join(f"- {c}" for group in lang_ctas.values() for c in group))

with tab_diag:
    df = growth.metrics_dataframe(metrics_log.list_metrics(db))
    rate = growth.average_daily_gain(df, window_days=30) if len(df) >= 2 else None
    recent = content_planner.published_since(db, today() - timedelta(days=14))
    has_plan = bool(content_planner.list_items(db))
    icons = {"acao": "🔴", "dica": "🟡", "ok": "🟢"}
    for level, text in ps.diagnose(profile, rate, recent if has_plan else None):
        st.markdown(f"{icons[level]} {text}")
    st.caption("🔴 ação recomendada · 🟡 dica · 🟢 tudo certo. Cada item explica o motivo.")
