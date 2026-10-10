"""Módulo A — Analisar minhas fotos."""

from __future__ import annotations

import streamlit as st

from database import images as images_repo
from services import preferences
from ui.components import fmt_num, metric_grid, page_header
from ui.image_views import (
    detail_view,
    filter_controls,
    gallery,
    no_images_state,
    selected_image,
    show_upload_errors,
    upload_section,
)
from ui.state import get_db, get_storage

db = get_db()
storage = get_storage()
KIND = "own"


def affinity_panel(row: dict) -> None:
    model, names = preferences.load_model(db)
    with st.container(border=True):
        st.markdown("**Afinidade com suas referências**")
        if not model.ready:
            st.caption(
                f"Avalie pelo menos {preferences.MIN_REFERENCES} referências em “Minhas referências” "
                f"para ver esta comparação (avaliadas: {model.evaluated})."
            )
            return
        aff = preferences.affinity(row, model, names)
        st.progress(aff.percent / 100, text=f"{aff.percent}% (50% = neutro)")
        if aff.positives:
            st.markdown("Pontos alinhados: " + "; ".join(p for p, _ in aff.positives) + ".")
        if aff.negatives:
            st.markdown("Pontos que você costuma avaliar pior: " + "; ".join(p for p, _ in aff.negatives) + ".")
        if aff.coverage < 0.5:
            st.caption("Poucas características desta foto aparecem nas suas referências avaliadas.")


page_header(
    "Analisar minhas fotos",
    "A pontuação técnica é uma estimativa para comparar suas fotos — não mede beleza, não prevê "
    "curtidas e não indica se uma foto vai viralizar.",
)
show_upload_errors(KIND)

selected = selected_image(KIND)
if selected:
    detail_view(db, storage, KIND, selected, extra=affinity_panel)
else:
    upload_section(
        db, storage, KIND,
        "As fotos são salvas sem metadados (EXIF/GPS) na pasta de dados privada desta aplicação.",
    )
    rows = images_repo.list_images(db, KIND)
    if not rows:
        no_images_state(KIND)
    else:
        scores = [r["technical_score"] or 0 for r in rows]
        metric_grid([
            ("Fotos", len(rows)),
            ("Pontuação média", fmt_num(sum(scores) / len(scores), 0)),
            ("Consideradas p/ feed", sum(1 for r in rows if r.get("in_feed_pool"))),
        ])
        filtered = filter_controls(db, rows, KIND)
        if not filtered:
            st.info("Nenhuma foto corresponde aos filtros.")
        gallery(db, storage, filtered, KIND)
