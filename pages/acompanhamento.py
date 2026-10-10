"""Módulo F — Acompanhamento manual de follow-back."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from config import today
from database.settings import get_setting
from models.vocab import FOLLOW_STATUS
from services import follows
from services.csv_io import to_csv_bytes
from services.handles import profile_url
from ui.components import (
    actions_row,
    confirm_button,
    done,
    empty_state,
    fmt_date,
    fmt_num,
    metric_grid,
    page_header,
    paginate,
)
from ui.state import get_db

db = get_db()
day = today()
categories = get_setting(db, "interest_categories")

page_header(
    "Acompanhamento",
    "Organizador manual: você segue as pessoas no app do Instagram e registra aqui. Esta página "
    "não segue, não deixa de seguir, não curte e não envia mensagens.",
)

STATUS_COLORS = {"pendente": "orange", "seguiu_de_volta": "green", "nao_seguiu_de_volta": "red",
                 "encerrado": "gray"}

with st.expander("Registrar perfil que segui", icon=":material/person_add:",
                 expanded=not follows.list_follows(db, include_archived=True)):
    with st.form("add_follow", clear_on_submit=True):
        a, b = st.columns(2)
        username = a.text_input("Nome de usuário ou URL *", placeholder="@usuario")
        url = b.text_input("URL informada (opcional)")
        a, b, c = st.columns(3)
        followed_at = a.date_input("Data em que segui", value=day, max_value=day, format="DD/MM/YYYY")
        category = b.selectbox("Categoria", categories)
        status = c.selectbox("Status", list(FOLLOW_STATUS), format_func=FOLLOW_STATUS.get)
        notes = st.text_input("Observações", max_chars=1000)
        if st.form_submit_button("Salvar", type="primary", icon=":material/save:"):
            try:
                follows.add_follow(db, {"username": username, "url": url, "followed_at": followed_at,
                                        "category": category, "status": status, "notes": notes})
            except ValueError as exc:
                st.error(str(exc))
            else:
                done("Registro salvo.")

everything = follows.list_follows(db, include_archived=True)
if not everything:
    empty_state(
        "Nenhum registro ainda",
        "Quando seguir alguém manualmente, registre aqui para lembrar de revisar depois se a pessoa "
        "seguiu de volta. Você também pode usar o botão “Registrar que segui” em Perfis de interesse.",
        icon="🤝",
    )
    st.stop()

active = [r for r in everything if not r["archived"]]
stats = follows.summary(active, day)
metric_grid([
    ("Registros ativos", stats["total"]),
    ("Pendentes", stats["counts"]["pendente"]),
    ("Seguiram de volta", stats["counts"]["seguiu_de_volta"]),
    ("Taxa de follow-back",
     fmt_num(stats["followback_rate"], 0, "%") if stats["followback_rate"] is not None else "—",
     "Seguiram de volta ÷ (seguiram + não seguiram). Pendentes não entram na conta."),
])
if stats["stale_pending"]:
    st.info(f"{len(stats['stale_pending'])} registro(s) pendente(s) há mais de 7 dias sem revisão.")
if stats["followed_last_7_days"] > follows.WEEKLY_FOLLOW_REMINDER:
    st.warning(
        f"Você registrou {stats['followed_last_7_days']} follows nos últimos 7 dias. Seguir muitas "
        "contas em pouco tempo pode parecer comportamento automatizado para o Instagram; prefira "
        "interações genuínas com perfis do seu nicho."
    )

with st.expander("Filtros", icon=":material/filter_list:"):
    a, b = st.columns(2)
    sel_status = a.multiselect("Status", list(FOLLOW_STATUS), format_func=FOLLOW_STATUS.get)
    period = b.selectbox("Período (data em que seguiu)",
                         ["Tudo", "Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias", "Personalizado"])
    start = end = None
    if period in ("Últimos 7 dias", "Últimos 30 dias", "Últimos 90 dias"):
        start = day - timedelta(days=int(period.split()[1]))
    elif period == "Personalizado":
        a, b = st.columns(2)
        start = a.date_input("De", value=day - timedelta(days=30), format="DD/MM/YYYY")
        end = b.date_input("Até", value=day, format="DD/MM/YYYY")
    a, b, c = st.columns(3)
    search = a.text_input("Pesquisar", placeholder="usuário ou observação")
    category = b.selectbox("Categoria", [None, *categories], format_func=lambda c: c or "Todas")
    include_archived = c.toggle("Incluir arquivados")

rows = follows.list_follows(db, sel_status, start, end, include_archived, search, category)
st.caption(f"{len(rows)} registro(s)")

for r in paginate(rows, "follow_page", per_page=15):
    with st.container(border=True):
        top_a, top_b = st.columns([3, 1], vertical_alignment="center", wrap=False)
        days_ago = (day - date.fromisoformat(r["followed_at"])).days
        top_a.markdown(
            f"**@{r['username']}** · seguiu em {fmt_date(r['followed_at'])} "
            f"({days_ago} dia{'s' if days_ago != 1 else ''})" + (" · _arquivado_" if r["archived"] else "")
        )
        with top_b:
            st.badge(FOLLOW_STATUS[r["status"]], color=STATUS_COLORS[r["status"]])
        meta = [r.get("category") or "sem categoria",
                f"última revisão: {fmt_date(r['last_reviewed_at'])}" if r.get("last_reviewed_at") else "nunca revisado"]
        st.caption(" · ".join(meta))
        if r.get("notes"):
            st.caption(f"📝 {r['notes']}")

        with actions_row():
            st.link_button("Abrir perfil", profile_url(r["username"], r.get("url")),
                           icon=":material/open_in_new:")
            if st.button("Marcar como revisado", key=f"rev_{r['id']}", icon=":material/task_alt:"):
                follows.mark_reviewed(db, r["id"])
                done("Revisão registrada.")
            if r["archived"]:
                if st.button("Desarquivar", key=f"unarch_{r['id']}", icon=":material/unarchive:"):
                    follows.set_archived(db, r["id"], False)
                    done("Registro desarquivado.")
            elif st.button("Arquivar", key=f"arch_{r['id']}", icon=":material/archive:"):
                follows.set_archived(db, r["id"], True)
                done("Registro arquivado.")

        new_status = st.segmented_control(
            "Atualizar status", list(FOLLOW_STATUS), format_func=FOLLOW_STATUS.get,
            default=r["status"], key=f"status_{r['id']}_{r['status']}", width="stretch",
        )
        if new_status and new_status != r["status"]:
            follows.mark_reviewed(db, r["id"], new_status)
            done(f"@{r['username']}: {FOLLOW_STATUS[new_status]}.")

        with st.expander("Editar observações ou excluir"):
            with st.form(f"notes_{r['id']}"):
                notes = st.text_area("Observações", value=r.get("notes") or "", max_chars=1000)
                if st.form_submit_button("Salvar observações"):
                    follows.update_follow(db, r["id"], {"notes": notes})
                    done("Observações salvas.")
            if confirm_button("Apagar registro", f"del_follow_{r['id']}",
                              f"Apagar o registro de @{r['username']} permanentemente?"):
                follows.delete_follow(db, r["id"])
                done("Registro apagado.")

st.download_button("Exportar registros filtrados (CSV)", to_csv_bytes(follows.to_dataframe(rows)),
                   "acompanhamento.csv", "text/csv", icon=":material/download:")
