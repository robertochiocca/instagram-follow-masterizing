"""Módulo C — Minhas referências e aprendizado de preferências estéticas."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from database import images as images_repo
from services import preferences
from ui.components import page_header
from ui.image_views import (
    detail_view,
    filter_controls,
    gallery,
    no_images_state,
    selected_image,
    show_upload_errors,
    swatches,
    upload_section,
)
from ui.state import get_db, get_storage

db = get_db()
storage = get_storage()
KIND = "reference"

page_header(
    "Minhas referências",
    "Imagens que inspiram você. Usamos apenas características gerais (luz, cores, cenário, "
    "enquadramento, estilo) — sem reconhecimento facial, sem identificar pessoas e sem vincular "
    "imagens a contas.",
)
show_upload_errors(KIND)

selected = selected_image(KIND)
if selected:
    detail_view(db, storage, KIND, selected)
    st.stop()

tab_gallery, tab_learn = st.tabs(["Galeria", "O que aprendi"])

with tab_gallery:
    upload_section(
        db, storage, KIND,
        "Capturas de tela são aceitas. As referências ficam privadas e podem ser apagadas a qualquer momento.",
    )
    rows = images_repo.list_images(db, KIND)
    if not rows:
        no_images_state(KIND)
    else:
        pending = sum(1 for r in rows if not r.get("reaction") and not r.get("user_rating"))
        if pending:
            st.caption(f"{pending} referência(s) ainda sem avaliação — use 👍 😐 👎 nos cartões.")
        filtered = filter_controls(db, rows, KIND)
        if not filtered:
            st.info("Nenhuma referência corresponde aos filtros.")
        gallery(db, storage, filtered, KIND)

with tab_learn:
    model, names = preferences.load_model(db)
    st.progress(
        min(1.0, model.evaluated / preferences.MIN_REFERENCES),
        text=f"{model.evaluated} referência(s) avaliada(s) — mínimo {preferences.MIN_REFERENCES} para recomendações",
    )
    with st.expander("Como o aprendizado funciona"):
        st.markdown(
            "- Cada avaliação vira um sinal de −1 a +1: nota 1–5 → (nota − 3) ÷ 2; "
            "Gosto/Neutro/Não gosto → +1/0/−1 (média dos dois, se houver).\n"
            "- Para cada característica (categoria, cenário, luz, enquadramento, roupa, tags, brilho, "
            "temperatura e saturação) calculamos: **soma dos sinais ÷ (avaliações + 2)**. O “+2” "
            "evita conclusões com poucos exemplos.\n"
            "- Os pesos por grupo e a importância de cada categoria são ajustáveis em Configurações.\n"
            "- É estatística simples e transparente, não um modelo de IA."
        )
    if not model.ready:
        st.info(
            "Avalie mais referências (inclusive as que você não gosta) para liberar as recomendações."
        )
    else:
        st.subheader("Suas preferências")
        for line in preferences.insights(model):
            st.markdown(f"- {line}")
        if model.preferred_palette:
            st.markdown("**Cores frequentes nas referências de que você gosta**")
            swatches(model.preferred_palette)

        own = images_repo.list_images(db, "own")
        st.subheader("Comparação com as suas fotos")
        if not own:
            st.caption("Envie fotos em “Minhas fotos” para comparar.")
        else:
            for line in preferences.compare_with_own_photos(own, model, names):
                st.markdown(f"- {line}")
            ranked = sorted(
                ((preferences.affinity(r, model, names), r) for r in own),
                key=lambda item: -item[0].score,
            )[:6]
            st.markdown("**Suas fotos mais alinhadas às suas referências**")
            cols = st.columns(3)
            for i, (aff, row) in enumerate(ranked):
                with cols[i % 3].container(border=True):
                    st.image(str(storage.thumb_path("own", row["thumb_filename"])), width="stretch")
                    st.markdown(f"Afinidade **{aff.percent}%**")
                    if aff.positives:
                        st.caption("; ".join(p for p, _ in aff.positives))

        with st.expander("Tabela de características aprendidas"):
            table = pd.DataFrame(
                [
                    {
                        "Grupo": preferences.GROUP_LABELS.get(s.group, s.group),
                        "Característica": s.phrase,
                        "Avaliações": s.count,
                        "Média bruta": round(s.mean, 2),
                        "Preferência suavizada": round(s.preference, 2),
                    }
                    for s in sorted(model.stats.values(), key=lambda s: -s.preference)
                ]
            )
            st.dataframe(table, hide_index=True, width="stretch")
