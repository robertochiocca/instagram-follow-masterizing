"""Componentes reutilizáveis da interface."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

import streamlit as st

from config import PROJECT_ROOT

T = TypeVar("T")

_FLASH_KEY = "_flash_messages"
_CONFIRM_KEY = "_pending_confirmation"


def inject_css() -> None:
    css = Path(PROJECT_ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def page_header(title: str, intro: str | None = None) -> None:
    st.title(title)
    if intro:
        st.caption(intro)


# --- Mensagens que sobrevivem a um st.rerun() ------------------------------------


def flash(message: str, kind: str = "success") -> None:
    st.session_state.setdefault(_FLASH_KEY, []).append((kind, message))


def show_flash() -> None:
    icons = {"success": "✅", "info": "ℹ️", "warning": "⚠️", "error": "❌"}
    for kind, message in st.session_state.pop(_FLASH_KEY, []):
        st.toast(message, icon=icons.get(kind, "ℹ️"))


EXPORT_KEYS = ("export_zip", "db_backup", "feed_zip")


def forget_exports() -> None:
    """Descarta exportações preparadas: depois de uma alteração elas estariam desatualizadas
    (e poderiam conter fotos ou registros já apagados)."""
    for key in EXPORT_KEYS:
        st.session_state.pop(key, None)


def done(message: str, kind: str = "success") -> None:
    """Registra a mensagem, descarta exportações antigas e recarrega a página."""
    flash(message, kind)
    forget_exports()
    st.rerun()


def form_key(base: str) -> str:
    """Chave de formulário que só muda após um envio bem-sucedido.

    Assim os campos são limpos quando o registro é salvo, mas o que foi digitado
    continua na tela se a validação falhar (o que clear_on_submit não permite).
    """
    return f"{base}__{st.session_state.get(f'_form_nonce_{base}', 0)}"


def reset_form(base: str) -> None:
    nonce = f"_form_nonce_{base}"
    st.session_state[nonce] = st.session_state.get(nonce, 0) + 1


# --- Estados vazios e confirmações ------------------------------------------------


def empty_state(title: str, text: str, icon: str = "📭") -> None:
    with st.container(border=True):
        st.markdown(f"### {icon} {title}")
        st.write(text)


def confirm_button(
    label: str,
    key: str,
    prompt: str,
    confirm_label: str = "Sim, excluir",
    icon: str = ":material/delete:",
    button_type: str = "secondary",
) -> bool:
    """Botão em duas etapas. Devolve True apenas na execução em que o usuário confirma."""
    if st.session_state.get(_CONFIRM_KEY) != key:
        if st.button(label, key=f"{key}__ask", icon=icon, type=button_type):
            st.session_state[_CONFIRM_KEY] = key
            st.rerun()
        return False
    st.warning(prompt, icon="⚠️")
    yes, no = st.columns(2)
    if yes.button(confirm_label, key=f"{key}__yes", type="primary", width="stretch"):
        st.session_state.pop(_CONFIRM_KEY, None)
        return True
    if no.button("Cancelar", key=f"{key}__no", width="stretch"):
        st.session_state.pop(_CONFIRM_KEY, None)
        st.rerun()
    return False


def typed_confirmation(label: str, key: str, word: str = "APAGAR") -> bool:
    """Confirmação forte para operações irreversíveis (o usuário digita uma palavra)."""
    typed = st.text_input(f"Para confirmar, digite {word}", key=f"{key}__typed")
    return st.button(label, key=f"{key}__go", type="primary", disabled=typed.strip() != word)


# --- Utilidades ----------------------------------------------------------------


def paginate(items: Sequence[T], key: str, per_page: int = 12) -> Sequence[T]:
    total_pages = max(1, math.ceil(len(items) / per_page))
    if total_pages == 1:
        return items
    page = st.number_input(
        f"Página (1–{total_pages})", min_value=1, max_value=total_pages, value=1, key=key
    )
    start = (int(page) - 1) * per_page
    st.caption(f"Mostrando {start + 1}–{min(start + per_page, len(items))} de {len(items)}")
    return items[start : start + per_page]


def copyable(text: str, label: str | None = None) -> None:
    """Texto com botão de copiar (ícone no canto do bloco)."""
    if label:
        st.markdown(f"**{label}**")
    st.code(text, language=None, wrap_lines=True)


def data_badge(estimate: bool = False) -> None:
    if estimate:
        st.badge("Estimativa", icon=":material/insights:", color="orange")
    else:
        st.badge("Dado informado por você", icon=":material/edit_note:", color="blue")


def fmt_int(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{int(value):,}".replace(",", ".")


def fmt_num(value, decimals: int = 1, suffix: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    text = f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text + suffix


def fmt_date(value) -> str:
    if not value:
        return "—"
    text = str(value)[:10]
    try:
        y, m, d = text.split("-")
        return f"{d}/{m}/{y}"
    except ValueError:
        return text


def fmt_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return str(size)


def metric_grid(items: Sequence[tuple], width: int = 170) -> None:
    """Métricas em cartões de largura fixa que quebram linha conforme a tela.

    Cada item é (rótulo, valor) ou (rótulo, valor, ajuda).
    """
    with st.container(horizontal=True, gap="small"):
        for item in items:
            label, value, *rest = item
            st.metric(label, value, help=rest[0] if rest else None, width=width, border=True)


def actions_row():
    """Linha de botões que quebra para a linha seguinte em telas estreitas."""
    return st.container(horizontal=True, gap="small")
