"""Módulo E — Perfis de interesse (lista manual, sem scraping)."""

from __future__ import annotations

import streamlit as st

from config import today
from database.settings import get_setting
from models.vocab import DISCOVERY_SOURCES, INTEREST_STATUS, PRIORITY
from services import follows, interests
from services.csv_io import to_csv_bytes
from services.handles import profile_url
from ui.components import (
    actions_row,
    confirm_button,
    done,
    empty_state,
    fmt_date,
    form_key,
    page_header,
    paginate,
    reset_form,
)
from ui.state import get_db

db = get_db()
categories = get_setting(db, "interest_categories")

page_header(
    "Perfis de interesse",
    "Lista pessoal preenchida por você. A aplicação não acessa o Instagram, não coleta dados de "
    "perfis e não deduz idade, identidade ou outros atributos a partir de fotos.",
)

STATUS_COLORS = {"novo": "blue", "revisar": "orange", "interessante": "green", "arquivado": "gray"}
PRIORITY_ICONS = {"alta": "🔺", "media": "▪️", "baixa": "🔻"}


def interest_form(key: str, record: dict | None = None) -> dict | None:
    record = record or {}
    with st.form(key):
        a, b = st.columns(2)
        username = a.text_input("Nome de usuário ou URL do perfil *", value=record.get("username", ""),
                                placeholder="@usuario")
        url = b.text_input("URL informada (opcional)", value=record.get("url") or "")
        a, b, c = st.columns(3)
        cat_options = list(dict.fromkeys([*categories, *( [record["category"]] if record.get("category") else [])]))
        category = a.selectbox("Categoria", cat_options,
                               index=cat_options.index(record["category"]) if record.get("category") in cat_options else 0)
        source_options = list(dict.fromkeys([*DISCOVERY_SOURCES, *([record["source"]] if record.get("source") else [])]))
        source = b.selectbox("Origem da descoberta", source_options,
                             index=source_options.index(record["source"]) if record.get("source") in source_options else 0)
        added_at = c.date_input("Data de inclusão", value=record.get("added_at") or today(), format="DD/MM/YYYY")
        a, b = st.columns(2)
        priority = a.segmented_control("Prioridade", list(PRIORITY), format_func=PRIORITY.get,
                                       default=record.get("priority", "media"))
        status = b.segmented_control("Status", list(INTEREST_STATUS), format_func=INTEREST_STATUS.get,
                                     default=record.get("status", "novo"))
        reason = st.text_input("Motivo de interesse", value=record.get("reason") or "", max_chars=300)
        tags = st.text_input("Tags (separadas por vírgula)", value=", ".join(record.get("tags") or []))
        notes = st.text_area("Observações", value=record.get("notes") or "", max_chars=1000)
        if st.form_submit_button("Salvar", type="primary", icon=":material/save:"):
            return {"username": username, "url": url, "category": category, "source": source,
                    "added_at": added_at, "priority": priority or "media", "status": status or "novo",
                    "reason": reason, "tags": tags, "notes": notes}
    return None


all_rows = interests.list_interests(db)
with st.expander("Adicionar perfil", expanded=not all_rows, icon=":material/person_add:"):
    data = interest_form(form_key("add_interest"))
    if data:
        try:
            interests.add_interest(db, data)
        except ValueError as exc:
            st.error(str(exc))
        else:
            reset_form("add_interest")
            done("Perfil adicionado.")

if not all_rows:
    empty_state(
        "Sua lista está vazia",
        "Adicione perfis que você quer acompanhar como inspiração (moda, esporte, viagens, "
        "fotografia…). Informe o @ ou cole a URL do perfil.",
        icon="🔖",
    )
    st.stop()

with st.expander("Pesquisar, filtrar e ordenar", icon=":material/filter_list:"):
    search = st.text_input("Pesquisar", placeholder="usuário, motivo, observações ou tag")
    a, b = st.columns(2)
    sel_categories = a.multiselect("Categorias", sorted({r.get("category") for r in all_rows if r.get("category")}))
    sel_status = b.multiselect("Status", list(INTEREST_STATUS), format_func=INTEREST_STATUS.get,
                               default=["novo", "revisar", "interessante"])
    a, b, c = st.columns(3)
    sel_priority = a.multiselect("Prioridade", list(PRIORITY), format_func=PRIORITY.get)
    tag_choice = b.selectbox("Tag", [None, *interests.all_tags(db)], format_func=lambda t: t or "Todas")
    sort = c.selectbox("Ordenar por", list(interests.SORTS), format_func=interests.SORTS.get)

rows = interests.list_interests(db, search, sel_categories, sel_status, sel_priority, tag_choice, sort)
a, b = st.columns([3, 2], vertical_alignment="bottom")
a.caption(f"{len(rows)} de {len(all_rows)} perfis")
view = b.segmented_control("Visualização", ["Cartões", "Tabela"], default="Cartões", key="interest_view")

if view == "Tabela":
    st.dataframe(interests.to_dataframe(rows), hide_index=True, width="stretch",
                 column_config={"url": st.column_config.LinkColumn("url")})
else:
    for r in paginate(rows, "interest_page", per_page=15):
        with st.container(border=True):
            top_a, top_b = st.columns([3, 1], vertical_alignment="center", wrap=False)
            top_a.markdown(f"**@{r['username']}** {PRIORITY_ICONS.get(r['priority'], '')} "
                           f"· {r.get('category') or 'sem categoria'}")
            with top_b:
                st.badge(INTEREST_STATUS[r["status"]], color=STATUS_COLORS[r["status"]])
            if r.get("reason"):
                st.write(r["reason"])
            meta = [f"Incluído em {fmt_date(r['added_at'])}"]
            if r.get("source"):
                meta.append(f"origem: {r['source']}")
            if r.get("tags"):
                meta.append(" ".join(f"#{t}" for t in r["tags"]))
            st.caption(" · ".join(meta))
            if r.get("notes"):
                st.caption(f"📝 {r['notes']}")
            editing = st.session_state.get("edit_interest") == r["id"]
            with actions_row():
                st.link_button("Abrir perfil", profile_url(r["username"], r.get("url")),
                               icon=":material/open_in_new:")
                if st.button("Fechar edição" if editing else "Editar", key=f"edit_{r['id']}",
                             icon=":material/edit:"):
                    st.session_state["edit_interest"] = None if editing else r["id"]
                    st.rerun()
                if r["status"] != "arquivado":
                    if st.button("Arquivar", key=f"arch_{r['id']}", icon=":material/archive:"):
                        interests.set_status(db, r["id"], "arquivado")
                        done(f"@{r['username']} arquivado.")
                elif st.button("Reativar", key=f"unarch_{r['id']}", icon=":material/unarchive:"):
                    interests.set_status(db, r["id"], "revisar")
                    done(f"@{r['username']} reativado.")
                if st.button("Registrar que segui", key=f"follow_{r['id']}", icon=":material/how_to_reg:",
                             help="Cria um registro manual na página Acompanhamento."):
                    follows.add_follow(db, {"username": r["username"], "url": r.get("url"),
                                            "category": r.get("category"), "status": "pendente"})
                    done(f"@{r['username']} adicionado ao Acompanhamento.")
            if editing:
                data = interest_form(f"edit_form_{r['id']}", r)
                if data:
                    try:
                        interests.update_interest(db, r["id"], data)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["edit_interest"] = None
                        done("Perfil atualizado.")
                if confirm_button("Excluir perfil", f"del_interest_{r['id']}",
                                  f"Excluir @{r['username']} da lista permanentemente?"):
                    interests.delete_interest(db, r["id"])
                    st.session_state["edit_interest"] = None
                    done("Perfil excluído.")

st.download_button(
    "Exportar lista filtrada (CSV)", to_csv_bytes(interests.to_dataframe(rows)),
    "perfis_de_interesse.csv", "text/csv", icon=":material/download:",
)
