"""Módulo H — Planejador de conteúdo."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from config import today
from database import images as images_repo
from database.settings import get_setting, set_setting
from models.vocab import CONTENT_OBJECTIVES, CONTENT_STATUS, CONTENT_TYPES, WEEKDAYS
from services import content_planner as cp
from services.csv_io import to_csv_bytes
from ui.components import confirm_button, done, empty_state, fmt_date, fmt_num, page_header
from ui.state import get_db

db = get_db()
day = today()

page_header(
    "Planejador de conteúdo",
    "Planeje com uma frequência que você consiga manter. Regularidade vale mais que volume — e "
    "nada é publicado automaticamente.",
)

STATUS_COLORS = {"ideia": "gray", "planejado": "blue", "publicado": "green"}
TYPE_ICONS = {"reels": "🎬", "carrossel": "🖼️", "foto": "📷", "stories": "⏱️"}


def item_form(key: str, item: dict | None = None) -> dict | None:
    item = item or {}
    with st.form(key, clear_on_submit=not item):
        a, b, c = st.columns(3)
        planned = a.date_input("Data planejada", value=date.fromisoformat(item["planned_date"])
                               if item.get("planned_date") else day, format="DD/MM/YYYY")
        ctype = b.selectbox("Tipo", list(CONTENT_TYPES), format_func=CONTENT_TYPES.get,
                            index=list(CONTENT_TYPES).index(item.get("content_type", "reels")))
        status = c.selectbox("Status", list(CONTENT_STATUS), format_func=CONTENT_STATUS.get,
                             index=list(CONTENT_STATUS).index(item.get("status", "ideia")))
        a, b = st.columns(2)
        theme = a.text_input("Tema", value=item.get("theme") or "", max_chars=120)
        objectives = list(dict.fromkeys([*CONTENT_OBJECTIVES, *([item["objective"]] if item.get("objective") else [])]))
        objective = b.selectbox("Objetivo", objectives,
                                index=objectives.index(item["objective"]) if item.get("objective") in objectives else 0)
        caption = st.text_area("Legenda provisória", value=item.get("caption") or "", max_chars=2200)
        result = {}
        if item:
            st.markdown("**Resultados após a publicação** (copie do Insights da publicação)")
            a, b, c, d = st.columns(4)
            published = a.date_input("Data de publicação", value=date.fromisoformat(item["published_date"])
                                     if item.get("published_date") else None, format="DD/MM/YYYY")
            reach = b.number_input("Contas alcançadas", min_value=0, value=item.get("reach"), step=1)
            views = c.number_input("Visualizações", min_value=0, value=item.get("views"), step=1)
            follows = d.number_input("Seguidores ganhos", value=item.get("follows_gained"), step=1)
            a, b, c, d = st.columns(4)
            likes = a.number_input("Curtidas", min_value=0, value=item.get("likes"), step=1)
            comments = b.number_input("Comentários", min_value=0, value=item.get("comments"), step=1)
            saves = c.number_input("Salvamentos", min_value=0, value=item.get("saves"), step=1)
            shares = d.number_input("Compartilhamentos", min_value=0, value=item.get("shares"), step=1)
            notes = st.text_area("Notas sobre o resultado", value=item.get("result_notes") or "", max_chars=1000)
            learnings = st.text_area("Aprendizados", value=item.get("learnings") or "", max_chars=1000)
            result = {"published_date": published, "reach": reach, "views": views, "follows_gained": follows,
                      "likes": likes, "comments": comments, "saves": saves, "shares": shares,
                      "result_notes": notes, "learnings": learnings}
        if st.form_submit_button("Salvar", type="primary", icon=":material/save:"):
            return {"planned_date": planned, "content_type": ctype, "status": status, "theme": theme,
                    "objective": objective, "caption": caption, **result}
    return None


tab_cal, tab_routine, tab_results = st.tabs(["Calendário", "Rotina sugerida", "Resultados"])

with tab_cal:
    with st.expander("Adicionar conteúdo", icon=":material/add:"):
        data = item_form("new_item")
        if data:
            try:
                cp.add_item(db, data)
            except ValueError as exc:
                st.error(str(exc))
            else:
                done("Conteúdo adicionado.")

    everything = cp.list_items(db)
    if not everything:
        empty_state(
            "Calendário vazio",
            "Adicione ideias manualmente ou gere uma rotina na aba “Rotina sugerida”.",
            icon="🗓️",
        )
    else:
        a, b, c = st.columns(3)
        period = a.selectbox("Período", ["Próximas 4 semanas", "Últimas 4 semanas", "Tudo"])
        sel_status = b.multiselect("Status", list(CONTENT_STATUS), format_func=CONTENT_STATUS.get)
        sel_types = c.multiselect("Tipo", list(CONTENT_TYPES), format_func=CONTENT_TYPES.get)
        start = end = None
        if period == "Próximas 4 semanas":
            start, end = day - timedelta(days=day.weekday()), day + timedelta(weeks=4)
        elif period == "Últimas 4 semanas":
            start, end = day - timedelta(weeks=4), day
        items = cp.list_items(db, sel_status, sel_types, start, end)
        if not items:
            st.info("Nenhum conteúdo neste filtro.")
        current_week = None
        for it in items:
            planned = date.fromisoformat(it["planned_date"])
            week = planned - timedelta(days=planned.weekday())
            if week != current_week:
                current_week = week
                st.markdown(f"##### Semana de {fmt_date(week)}")
            with st.container(border=True):
                top_a, top_b = st.columns([3, 1], vertical_alignment="center")
                top_a.markdown(
                    f"{TYPE_ICONS[it['content_type']]} **{WEEKDAYS[planned.weekday()]} {fmt_date(planned)}** · "
                    f"{CONTENT_TYPES[it['content_type']]} · {it.get('theme') or 'sem tema'}"
                )
                with top_b:
                    st.badge(CONTENT_STATUS[it["status"]], color=STATUS_COLORS[it["status"]])
                if it.get("objective"):
                    st.caption(f"Objetivo: {it['objective']}")
                if it.get("caption"):
                    st.caption(it["caption"][:160] + ("…" if len(it["caption"]) > 160 else ""))
                if it["status"] == "publicado":
                    eng = cp.engagement(it)
                    if eng is not None:
                        st.caption(f"Engajamento: {fmt_num(eng, 1, '%')} · alcance {it.get('reach')}")
                c1, c2 = st.columns(2)
                if it["status"] != "publicado" and c1.button("Marcar como publicado", key=f"pub_{it['id']}",
                                                             icon=":material/check_circle:", width="stretch"):
                    cp.update_item(db, it["id"], {"status": "publicado"})
                    done("Marcado como publicado. Registre os resultados depois em “Editar”.")
                with st.expander("Editar / resultados / excluir"):
                    data = item_form(f"edit_item_{it['id']}", it)
                    if data:
                        try:
                            cp.update_item(db, it["id"], data)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            done("Conteúdo atualizado.")
                    if confirm_button("Excluir conteúdo", f"del_item_{it['id']}", "Excluir este conteúdo do calendário?"):
                        cp.delete_item(db, it["id"])
                        done("Conteúdo excluído.")
        st.download_button("Exportar calendário (CSV)", to_csv_bytes(cp.to_dataframe(everything)),
                           "calendario.csv", "text/csv", icon=":material/download:")

with tab_routine:
    freq = get_setting(db, "content_frequency")
    st.caption(
        "Sugestão inicial sustentável: 2 Reels + 1 carrossel por semana, com Stories nos outros dias. "
        "Ajuste ao seu tempo disponível."
    )
    with st.form("frequency"):
        a, b, c, d = st.columns(4)
        reels = a.number_input("Reels/semana", 0, 14, int(freq.get("reels", 2)))
        carrossel = b.number_input("Carrosséis/semana", 0, 14, int(freq.get("carrossel", 1)))
        foto = c.number_input("Fotos/semana", 0, 14, int(freq.get("foto", 0)))
        stories = d.number_input("Stories/semana", 0, 28, int(freq.get("stories", 3)))
        weekdays = st.pills("Dias disponíveis para publicar", WEEKDAYS, selection_mode="multi",
                            default=freq.get("weekdays") or ["Ter", "Qui", "Sáb"])
        if st.form_submit_button("Salvar frequência", type="primary"):
            set_setting(db, "content_frequency", {"reels": reels, "carrossel": carrossel, "foto": foto,
                                                  "stories": stories, "weekdays": weekdays})
            done("Frequência salva.")
    for warning in cp.frequency_warnings(freq):
        st.warning(warning)

    categories = sorted(images_repo.list_categories(db), key=lambda c: -c["weight"])
    theme_options = [c["name"] for c in categories if c["weight"] > 0]
    a, b = st.columns(2)
    weeks = a.number_input("Semanas a planejar", 1, 8, 4)
    start = b.date_input("Começar em", value=day, min_value=day, format="DD/MM/YYYY")
    themes = st.multiselect("Temas em rodízio", theme_options, default=theme_options[:4],
                            accept_new_options=True)
    if st.button("Gerar prévia da rotina", icon=":material/auto_awesome:"):
        st.session_state["schedule_preview"] = cp.generate_schedule(start, int(weeks), freq, themes)
    preview = st.session_state.get("schedule_preview")
    if preview:
        st.dataframe(
            pd.DataFrame([
                {"Data": fmt_date(p["planned_date"]), "Dia": WEEKDAYS[p["planned_date"].weekday()],
                 "Tipo": CONTENT_TYPES[p["content_type"]], "Tema": p["theme"], "Objetivo": p["objective"]}
                for p in preview
            ]),
            hide_index=True, width="stretch",
        )
        a, b = st.columns(2)
        if a.button(f"Adicionar {len(preview)} itens ao calendário", type="primary", width="stretch"):
            cp.add_items(db, preview)
            st.session_state.pop("schedule_preview", None)
            done("Rotina adicionada ao calendário.")
        if b.button("Descartar prévia", width="stretch"):
            st.session_state.pop("schedule_preview", None)
            st.rerun()

with tab_results:
    items = cp.list_items(db)
    table = cp.results_table(items)
    if table.empty:
        st.info("Marque conteúdos como publicados e registre alcance e interações para comparar resultados.")
    else:
        avg = table["engajamento_pct"].mean()
        a, b, c = st.columns(3)
        a.metric("Publicações com resultado", int(table["engajamento_pct"].notna().sum()))
        b.metric("Engajamento médio", fmt_num(avg, 1, "%") if pd.notna(avg) else "—",
                 help="(curtidas + comentários + salvamentos + compartilhamentos) ÷ alcance × 100")
        c.metric("Seguidores ganhos (soma)", int(pd.to_numeric(table["novos_seguidores"]).fillna(0).sum()))
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={
                "engajamento_pct": st.column_config.NumberColumn("Engaj. %", format="%.2f"),
                "vs_media_pp": st.column_config.NumberColumn("vs. média (p.p.)", format="%+.2f"),
            },
        )
        a, b = st.columns(2)
        with a:
            st.markdown("**Por tipo**")
            st.dataframe(cp.best_groups(items, "tipo"), hide_index=True, width="stretch")
        with b:
            st.markdown("**Por tema**")
            st.dataframe(cp.best_groups(items, "tema"), hide_index=True, width="stretch")
        learned = [i for i in items if i.get("learnings")]
        if learned:
            st.markdown("**Aprendizados registrados**")
            for it in learned[-10:]:
                st.markdown(f"- {fmt_date(it.get('published_date') or it['planned_date'])} · {it['learnings']}")
        st.caption("Compare tendências ao longo de várias publicações; um único resultado pode ser acaso.")
