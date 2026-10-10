"""Upload, galeria e tela de detalhes compartilhados por "Minhas fotos" e "Minhas referências"."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from database import images as images_repo
from database.connection import Database
from database.settings import get_setting
from models.vocab import CLOTHING, CONTEXT, FRAMING, LIGHTING, REACTIONS, label
from services import image_analysis, photo_library
from services.image_storage import ImageStorage
from ui.components import confirm_button, done, empty_state, flash, fmt_bytes, fmt_date, paginate
from ui.state import max_upload_mb

KIND_TEXT = {
    "own": {"noun": "foto", "plural": "fotos"},
    "reference": {"noun": "referência", "plural": "referências"},
}


def _sel_key(kind: str) -> str:
    return f"selected_image_{kind}"


def open_image(kind: str, image_id: int) -> None:
    st.session_state[_sel_key(kind)] = image_id


def selected_image(kind: str) -> int | None:
    return st.session_state.get(_sel_key(kind))


def close_image(kind: str) -> None:
    st.session_state.pop(_sel_key(kind), None)


def swatches(colors: list[str]) -> None:
    safe = [c for c in colors if isinstance(c, str) and len(c) == 7 and c.startswith("#")]
    if not safe:
        return
    cells = "".join(
        f'<div class="igt-swatch" style="background:{html.escape(c)}" title="{html.escape(c)}"></div>'
        for c in safe
    )
    st.markdown(f'<div class="igt-swatches">{cells}</div>', unsafe_allow_html=True)


# --- Upload --------------------------------------------------------------------------


def upload_section(db: Database, storage: ImageStorage, kind: str, help_text: str) -> None:
    limit = max_upload_mb()
    nonce_key = f"upload_nonce_{kind}"
    nonce = st.session_state.get(nonce_key, 0)
    files = st.file_uploader(
        f"Envie {KIND_TEXT[kind]['plural']} (JPG, JPEG, PNG ou WEBP, até {limit} MB cada)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key=f"uploader_{kind}_{nonce}",
        max_upload_size=limit,
        help=help_text,
    )
    if not files:
        return
    if st.button(f"Analisar e salvar {len(files)} arquivo(s)", type="primary", icon=":material/upload:"):
        weights = get_setting(db, "score_weights")
        ok, failed = 0, []
        progress = st.progress(0.0, text="Analisando…")
        for i, f in enumerate(files, start=1):
            outcome = photo_library.import_image(
                db, storage, f.getvalue(), f.name, kind, limit * 1024 * 1024, weights
            )
            if outcome.ok:
                ok += 1
            else:
                failed.append(f"{outcome.display_name}: {outcome.message}")
            progress.progress(i / len(files), text=f"Analisando {i}/{len(files)}…")
        st.session_state[nonce_key] = nonce + 1  # limpa o seletor de arquivos
        if ok:
            flash(f"{ok} {KIND_TEXT[kind]['noun'] if ok == 1 else KIND_TEXT[kind]['plural']} salva(s).")
        if failed:
            st.session_state[f"upload_errors_{kind}"] = failed
        st.rerun()


def show_upload_errors(kind: str) -> None:
    errors = st.session_state.pop(f"upload_errors_{kind}", None)
    if errors:
        st.error("Alguns arquivos não foram salvos:\n\n" + "\n".join(f"- {e}" for e in errors))


# --- Galeria -----------------------------------------------------------------------------


CARD_WIDTH = 168  # cabem 2 cartões por linha num celular de 390 px


def _card_caption(row: dict, kind: str) -> tuple[str, str]:
    parts = [f"**{row['technical_score']:.0f}**/100" if row.get("technical_score") is not None else ""]
    if row.get("user_rating"):
        parts.append(f"{row['user_rating']}★")
    if kind == "own" and row.get("in_feed_pool"):
        parts.append("▦")
    if kind == "reference" and row.get("reaction"):
        parts.append(REACTIONS[row["reaction"]])
    tags = " ".join(f"#{t}" for t in (row.get("tags") or [])[:2])
    return " · ".join(p for p in parts if p), tags


def gallery(db: Database, storage: ImageStorage, rows: list[dict], kind: str) -> None:
    page_rows = paginate(rows, key=f"page_{kind}", per_page=12)
    with st.container(horizontal=True, gap="small"):
        for row in page_rows:
            with st.container(border=True, width=CARD_WIDTH):
                try:
                    st.image(str(storage.thumb_path(kind, row["thumb_filename"])), width="stretch")
                except Exception:
                    st.caption("Miniatura indisponível.")
                line, tags = _card_caption(row, kind)
                st.markdown(line)
                if tags:
                    st.caption(tags)
                with st.container(horizontal=True, gap="small"):
                    if st.button("Abrir", key=f"open_{kind}_{row['id']}", width="stretch"):
                        open_image(kind, row["id"])
                        st.rerun()
                    if kind == "own":
                        fav = bool(row.get("favorite"))
                        if st.button("♥" if fav else "♡", key=f"fav_{row['id']}",
                                     help="Remover dos favoritos" if fav else "Favoritar",
                                     type="primary" if fav else "secondary"):
                            images_repo.update_image(db, row["id"], {"favorite": not fav})
                            st.rerun()
                if kind == "reference":
                    _quick_reaction(db, row)


def _quick_reaction(db: Database, row: dict) -> None:
    current = row.get("reaction")
    choice = st.segmented_control(
        "Reação",
        list(REACTIONS),
        format_func=lambda c: {"gosto": "👍", "neutro": "😐", "nao_gosto": "👎"}[c],
        default=current,
        key=f"react_{row['id']}_{current}",
        label_visibility="collapsed",
        width="stretch",
    )
    if choice != current:  # inclui desmarcar (None) a reação atual
        images_repo.update_image(db, row["id"], {"reaction": choice})
        st.rerun()


def filter_controls(db: Database, rows: list[dict], kind: str) -> list[dict]:
    categories = {c["id"]: c["name"] for c in images_repo.list_categories(db)}
    all_tags = sorted({t for r in rows for t in r.get("tags") or []})
    with st.expander("Filtrar e ordenar", icon=":material/filter_list:"):
        a, b = st.columns(2)
        order = a.selectbox(
            "Ordenar por",
            ["recent", "score", "rating", "oldest"],
            format_func={"recent": "Mais recentes", "score": "Maior pontuação técnica",
                         "rating": "Maior nota sua", "oldest": "Mais antigas"}.get,
            key=f"order_{kind}",
        )
        tag = b.selectbox("Tag", [None, *all_tags], format_func=lambda t: t or "Todas", key=f"tag_{kind}")
        a, b = st.columns(2)
        cat = a.selectbox("Categoria", [None, *categories], format_func=lambda c: categories.get(c, "Todas"),
                          key=f"cat_{kind}")
        if kind == "own":
            only_fav = b.toggle("Só favoritas", key=f"fav_only_{kind}")
            reaction = None
        else:
            only_fav = False
            reaction = b.selectbox("Reação", [None, *REACTIONS],
                                   format_func=lambda r: REACTIONS.get(r, "Todas"), key=f"reaction_{kind}")
    if order == "score":
        rows = sorted(rows, key=lambda r: -(r.get("technical_score") or 0))
    elif order == "rating":
        rows = sorted(rows, key=lambda r: (-(r.get("user_rating") or 0), -(r.get("technical_score") or 0)))
    elif order == "oldest":
        rows = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    if tag:
        rows = [r for r in rows if tag in (r.get("tags") or [])]
    if cat:
        rows = [r for r in rows if cat in r.get("category_ids", [])]
    if only_fav:
        rows = [r for r in rows if r.get("favorite")]
    if reaction:
        rows = [r for r in rows if r.get("reaction") == reaction]
    return rows


# --- Detalhes ------------------------------------------------------------------------------


def _select(label_text: str, mapping: dict[str, str], current: str | None, key: str, help_text=None):
    options = [None, *mapping]
    index = options.index(current) if current in options else 0
    return st.selectbox(label_text, options, index=index, key=key, help=help_text,
                        format_func=lambda c: "—" if c is None else mapping[c])


def technical_panel(row: dict) -> None:
    metrics = photo_library.metrics_of(row)
    info = image_analysis.aspect_ratio_info(row["width"], row["height"])
    st.markdown(
        f"**{row['width']} × {row['height']} px** · proporção {info['name']} · "
        f"{fmt_bytes(row['file_size'])} · {row['format']}"
    )
    st.caption(f"{info['note']} Enviada em {fmt_date(row['created_at'])}.")
    st.metric(
        "Pontuação técnica (estimativa)",
        f"{row.get('technical_score') or 0:.0f}/100",
        help="Compara aspectos técnicos entre as suas fotos. Não mede beleza nem prevê curtidas.",
    )
    breakdown = (row.get("score_breakdown") or {}).get("components") or []
    if breakdown:
        table = pd.DataFrame(
            [
                {"Critério": c["label"], "Nota": round(c["score"] * 100), "Peso": f"{c['weight']:.0%}",
                 "Pontos": c["points"], "Detalhe": c["explanation"]}
                for c in breakdown
            ]
        )
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={"Nota": st.column_config.ProgressColumn("Nota", min_value=0, max_value=100,
                                                                   format="%d")},
        )
    if metrics:
        st.markdown("**Paleta predominante**")
        swatches([p.hex for p in metrics.palette])
        st.caption(
            f"Brilho {metrics.brightness:.0%} · contraste {metrics.contrast:.2f} · saturação "
            f"{metrics.saturation:.0%} · {image_analysis.temperature_class(metrics)}"
        )
    notes = row.get("observations") or []
    if notes:
        st.markdown("**Observações**")
        st.markdown("\n".join(f"- {n}" for n in notes))


def detail_view(db: Database, storage: ImageStorage, kind: str, image_id: int, extra=None) -> None:
    row = images_repo.get_image(db, image_id)
    if not row or row["kind"] != kind:
        close_image(kind)
        st.rerun()
    if st.button("Voltar para a galeria", icon=":material/arrow_back:"):
        close_image(kind)
        st.rerun()

    left, right = st.columns([3, 2])
    with left:
        st.image(str(storage.path(kind, row["filename"])), width="stretch")
        st.caption(row.get("original_name") or "")
    with right:
        technical_panel(row)

    if extra:
        extra(row)

    categories = images_repo.list_categories(db)
    cat_names = {c["id"]: c["name"] for c in categories}
    tag_options = sorted(set(get_setting(db, "photo_tags")) | set(row.get("tags") or []))
    metrics = photo_library.metrics_of(row)
    guess = image_analysis.lighting_guess(metrics) if metrics else None

    st.subheader("Sua avaliação" if kind == "own" else "Classificação da referência")
    with st.form(f"edit_{kind}_{image_id}"):
        rating = st.select_slider(
            "Sua nota", options=[0, 1, 2, 3, 4, 5], value=int(row.get("user_rating") or 0),
            format_func=lambda v: "sem nota" if v == 0 else "★" * v,
        )
        reaction = None
        if kind == "reference":
            reaction = st.segmented_control(
                "Reação", list(REACTIONS), format_func=REACTIONS.get, default=row.get("reaction"),
            )
        a, b = st.columns(2)
        with a:
            chosen_categories = st.multiselect(
                "Categorias estéticas", list(cat_names), default=row.get("category_ids") or [],
                format_func=cat_names.get,
            )
            tags = st.multiselect(
                "Tags", tag_options, default=row.get("tags") or [], accept_new_options=True,
                help="Escolha ou digite novas tags (ex.: praia, retrato, viagem).",
            )
            framing = _select("Enquadramento", FRAMING, row.get("framing"), f"fr_{image_id}")
        with b:
            lighting = _select(
                "Iluminação", LIGHTING, row.get("lighting") or guess, f"li_{image_id}",
                help_text=(f"Sugestão automática: {label(LIGHTING, guess)} — confirme ou altere."
                           if guess and not row.get("lighting") else None),
            )
            context = _select("Cenário / contexto", CONTEXT, row.get("context"), f"cx_{image_id}")
            clothing = _select("Estilo de roupa", CLOTHING, row.get("clothing_style"), f"cl_{image_id}")
        comment = st.text_area(
            "Comentários" if kind == "own" else "O que agradou ou desagradou",
            value=row.get("comment") or "", max_chars=1000,
        )
        favorite = in_pool = None
        if kind == "own":
            a, b = st.columns(2)
            favorite = a.toggle("Favorita", value=bool(row.get("favorite")))
            in_pool = b.toggle("Considerar para o feed", value=bool(row.get("in_feed_pool")))
        if st.form_submit_button("Salvar", type="primary", icon=":material/save:"):
            data = {
                "user_rating": rating or None,
                "framing": framing,
                "lighting": lighting,
                "context": context,
                "clothing_style": clothing,
                "tags": [str(t).strip().lower()[:40] for t in tags if str(t).strip()],
                "comment": comment.strip() or None,
            }
            if kind == "reference":
                data["reaction"] = reaction
            else:
                data["favorite"] = favorite
                data["in_feed_pool"] = in_pool
            images_repo.update_image(db, image_id, data, category_ids=chosen_categories)
            done("Alterações salvas.")

    st.divider()
    if confirm_button(
        f"Excluir esta {KIND_TEXT[kind]['noun']}",
        f"del_img_{image_id}",
        f"A {KIND_TEXT[kind]['noun']} e todos os dados dela serão apagados de forma permanente.",
    ):
        photo_library.delete_image(db, storage, image_id)
        close_image(kind)
        done(f"{KIND_TEXT[kind]['noun'].capitalize()} excluída.")


def no_images_state(kind: str) -> None:
    if kind == "own":
        empty_state(
            "Nenhuma foto enviada",
            "Envie suas fotos acima. Cada uma recebe análise de brilho, contraste, nitidez, "
            "composição e uma pontuação técnica explicada. As imagens ficam privadas na pasta de "
            "dados e podem ser apagadas a qualquer momento.",
            icon="🖼️",
        )
    else:
        empty_state(
            "Nenhuma referência enviada",
            "Envie imagens que você admira (inclusive capturas de tela). Avalie cada uma com "
            "Gosto/Neutro/Não gosto e uma nota; depois de 5 avaliações a aplicação mostra o que você "
            "costuma preferir.",
            icon="🎨",
        )
