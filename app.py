"""Instagram Growth Tool — Personal Edition.

Execute com:  streamlit run app.py
"""

from __future__ import annotations

import logging

import streamlit as st

from config import load_config
from ui.auth import logout_button, require_password
from ui.components import inject_css, show_flash
from ui.state import get_db

st.set_page_config(
    page_title="Instagram Growth Tool",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="auto",
)

cfg = load_config()
logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

inject_css()
require_password(cfg)
get_db()  # cria/migra o banco na primeira execução

pages = {
    "Início": [
        st.Page("pages/dashboard.py", title="Dashboard", icon=":material/monitoring:", default=True),
    ],
    "Fotos": [
        st.Page("pages/minhas_fotos.py", title="Minhas fotos", icon=":material/photo_library:"),
        st.Page("pages/organizador_feed.py", title="Organizador do feed", icon=":material/grid_view:"),
        st.Page("pages/minhas_referencias.py", title="Minhas referências", icon=":material/style:"),
    ],
    "Perfil e rede": [
        st.Page("pages/meu_perfil.py", title="Meu perfil", icon=":material/person:"),
        st.Page("pages/perfis_interesse.py", title="Perfis de interesse", icon=":material/bookmarks:"),
        st.Page("pages/acompanhamento.py", title="Acompanhamento", icon=":material/how_to_reg:"),
    ],
    "Planejamento": [
        st.Page(
            "pages/planejador_conteudo.py",
            title="Planejador de conteúdo",
            icon=":material/calendar_month:",
        ),
    ],
    "Sistema": [
        st.Page("pages/configuracoes.py", title="Configurações", icon=":material/settings:"),
    ],
}

navigation = st.navigation(pages)
logout_button(cfg)
st.sidebar.caption("Uso pessoal · nenhuma ação é feita no Instagram automaticamente.")
show_flash()
navigation.run()
