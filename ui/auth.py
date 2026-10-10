"""Senha opcional de acesso (IGT_APP_PASSWORD).

Útil quando a porta é exposta na rede ou publicamente. A senha nunca é
armazenada pela aplicação; apenas comparada em tempo constante.
"""

from __future__ import annotations

import hmac
import time

import streamlit as st

from config import AppConfig

_AUTH_KEY = "_igt_authenticated"


def require_password(cfg: AppConfig) -> None:
    if not cfg.app_password or st.session_state.get(_AUTH_KEY):
        return
    st.title("Instagram Growth Tool")
    st.caption("Acesso protegido por senha.")
    with st.form("login"):
        password = st.text_input("Senha de acesso", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if submitted:
        if hmac.compare_digest(password.encode("utf-8"), cfg.app_password.encode("utf-8")):
            st.session_state[_AUTH_KEY] = True
            st.rerun()
        time.sleep(1.0)  # desacelera tentativas repetidas
        st.error("Senha incorreta.")
    st.stop()


def logout_button(cfg: AppConfig) -> None:
    if cfg.app_password and st.session_state.get(_AUTH_KEY):
        if st.sidebar.button("Sair", icon=":material/logout:"):
            st.session_state.pop(_AUTH_KEY, None)
            st.rerun()
