"""Módulo B — Organizador do feed."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

from database import feeds as feeds_repo
from database import images as images_repo
from database.settings import get_setting, set_setting
from models.defaults import DEFAULT_FEED_WEIGHTS
from services import feed_planner as fp
from services import preferences
from services.csv_io import to_csv_bytes
from ui.components import confirm_button, done, empty_state, flash, fmt_date, metric_grid, page_header
from ui.state import get_db, get_storage

db = get_db()
storage = get_storage()
DRAFT = "feed_draft"
SLOTS = "feed_slots"
ZIP = "feed_zip"

page_header(
    "Organizador do feed",
    "Monte e compare sequências para a grade do perfil. A posição 1 (canto superior esquerdo) é a "
    "publicação mais recente. Nada é publicado, excluído ou alterado no Instagram.",
)


@st.cache_data(max_entries=600, show_spinner=False)
def grid_tile(path: str, mtime: float) -> bytes:
    """Miniatura recortada em 3:4, como aparece na grade do perfil."""
    with Image.open(path) as im:
        tile = ImageOps.fit(im.convert("RGB"), (300, 400), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    tile.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def tile_bytes(row: dict) -> bytes | None:
    try:
        path = storage.thumb_path("own", row["thumb_filename"])
        return grid_tile(str(path), path.stat().st_mtime)
    except (OSError, ValueError):
        return None


own = images_repo.list_images(db, "own")
if not own:
    empty_state("Nenhuma foto disponível",
                "Envie fotos em “Minhas fotos” e marque as que deseja considerar para o feed.", icon="▦")
    st.stop()
by_id = {r["id"]: r for r in own}
model, cat_names = preferences.load_model(db)


def preference_of(row: dict) -> float | None:
    """Afinidade 0–1 com as referências (None = neutro enquanto não há dados suficientes)."""
    return preferences.affinity(row, model, cat_names).percent / 100 if model.ready else None


def load_version(version_id: int) -> None:
    full = feeds_repo.get_version(db, version_id)
    if not full:
        flash("Essa versão não existe mais.", "warning")
        return
    ids = [i["image_id"] for i in full["items"]]
    images_repo.set_feed_pool(db, ids, True)
    st.session_state[DRAFT] = {
        "sequence": ids,
        "pinned": [i["image_id"] for i in full["items"] if i["pinned"]],
        "reasons": {}, "version_id": version_id,
    }
    st.session_state[SLOTS] = max(2, len(ids))
    flash(f"“{full['name']}” carregada.")


def render_versions(draft: dict | None, weights: dict) -> None:
    st.subheader("4. Versões salvas")
    versions = feeds_repo.list_versions(db)
    if not versions:
        st.caption("Nenhuma versão salva ainda.")
        return
    for v in versions:
        with st.container(border=True):
            a, b, c = st.columns([3, 1, 1], vertical_alignment="center")
            a.markdown(f"**{v['name']}** · {v['item_count']} fotos · atualizada em {fmt_date(v['updated_at'])}")
            b.button("Carregar", key=f"load_{v['id']}", width="stretch", on_click=load_version, args=(v["id"],))
            with c:
                if confirm_button("Excluir", f"del_version_{v['id']}", f"Excluir a versão “{v['name']}”?"):
                    feeds_repo.delete_version(db, v["id"])
                    if draft and draft.get("version_id") == v["id"]:
                        draft["version_id"] = None  # o rascunho continua, mas sem vínculo
                    done("Versão excluída.")

    st.markdown("**Comparar sequências**")
    choices = st.multiselect("Escolha até 3 versões", [v["id"] for v in versions], max_selections=3,
                             format_func=lambda vid: next(v["name"] for v in versions if v["id"] == vid))
    compare = []
    if draft:
        compare.append(("Rascunho atual", draft["sequence"]))
    for vid in choices:
        full = feeds_repo.get_version(db, vid)
        if full:
            compare.append((full["name"], [i["image_id"] for i in full["items"]]))
    if len(compare) < 2:
        st.caption("Selecione versões (e/ou tenha um rascunho) para comparar lado a lado.")
        return
    all_rows = images_repo.get_images_by_ids(db, {pid for _, s in compare for pid in s})
    table = []
    for name, seq_ids in compare:
        fps = [fp.FeedPhoto.from_row(all_rows[pid], preference_of(all_rows[pid]))
               for pid in seq_ids if pid in all_rows]
        e = fp.evaluate_sequence(fps, weights)
        table.append({"Sequência": name, "Fotos": len(fps), "Equilíbrio": e.overall, "Qualidade": e.quality,
                      "Diversidade": e.diversity, "Coerência": e.coherence, "Preferência": e.preference,
                      "Alertas": len(e.adjacent_alerts) + len(fp.repetition_warnings(fps))})
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    cols = st.columns(len(compare))
    for col, (name, seq_ids) in zip(cols, compare):
        with col:
            st.caption(name)
            st.image(fp.grid_preview_png(storage, [all_rows[p] for p in seq_ids if p in all_rows], cell=120),
                     width="stretch")


# --- 1. Seleção das fotos consideradas ------------------------------------------------------------


def toggle_pool(image_id: int, key: str) -> None:
    images_repo.set_feed_pool(db, [image_id], st.session_state[key])


weights = get_setting(db, "feed_weights")
pool = [r for r in own if r.get("in_feed_pool")]
with st.expander(f"1. Fotos consideradas ({len(pool)} de {len(own)})", expanded=len(pool) < 3,
                 icon=":material/checklist:"):
    a, b, c = st.columns(3)
    if a.button("Selecionar favoritas", width="stretch"):
        images_repo.set_feed_pool(db, [r["id"] for r in own if r.get("favorite")], True)
        st.rerun()
    if b.button("Top 12 por pontuação", width="stretch"):
        top = sorted(own, key=lambda r: -(r.get("technical_score") or 0))[:12]
        images_repo.set_feed_pool(db, [r["id"] for r in top], True)
        st.rerun()
    if c.button("Limpar seleção", width="stretch"):
        images_repo.set_feed_pool(db, [r["id"] for r in own], False)
        st.session_state.pop(DRAFT, None)
        st.rerun()
    with st.container(horizontal=True, gap="small"):
        for r in own:
            with st.container(width=110):
                data = tile_bytes(r)
                if data:
                    st.image(data, width="stretch")
                # A chave inclui o valor salvo: se um botão em massa mudar o banco, a caixa
                # é recriada com o valor novo em vez de manter o estado antigo.
                in_pool = bool(r.get("in_feed_pool"))
                key = f"pool_{r['id']}_{int(in_pool)}"
                st.checkbox(f"{r['technical_score']:.0f}", value=in_pool, key=key,
                            on_change=toggle_pool, args=(r["id"], key))

if len(pool) < 2:
    st.info("Selecione pelo menos 2 fotos para montar uma sequência.")
    render_versions(None, weights)
    st.stop()

# --- 2. Parâmetros ----------------------------------------------------------------------------------

photos = {r["id"]: fp.FeedPhoto.from_row(r, preference_of(r)) for r in pool}

with st.expander("2. Critérios do algoritmo", icon=":material/tune:"):
    st.caption(
        "Utilidade = qualidade técnica + preferência + coerência de cores − semelhança com vizinhas. "
        "Os pesos abaixo definem o equilíbrio (normalizados para somar 100%)."
    )
    with st.form("feed_weights"):
        labels = {"quality": "Qualidade técnica (inclui sua nota e favoritas)",
                  "diversity": "Diversidade visual entre vizinhas",
                  "coherence": "Coerência de cores do conjunto",
                  "preference": "Preferências aprendidas nas referências"}
        new_w = {k: st.slider(labels[k], 0, 100, int(weights.get(k, v)), 5) for k, v in DEFAULT_FEED_WEIGHTS.items()}
        if st.form_submit_button("Salvar critérios"):
            set_setting(db, "feed_weights", new_w)
            done("Critérios salvos.")
    if not model.ready:
        st.caption(
            f"Preferências ainda neutras: avalie {preferences.MIN_REFERENCES} referências para ativar este critério."
        )

# --- 3. Rascunho atual --------------------------------------------------------------------------------

draft = st.session_state.get(DRAFT)
if draft:
    kept = [pid for pid in draft["sequence"] if pid in photos]
    if kept != draft["sequence"]:
        draft["reasons"] = {}  # as explicações são por posição: deixam de valer
    draft["sequence"] = kept
    draft["pinned"] = [pid for pid in draft["pinned"] if pid in kept]

st.subheader("3. Sequência")
a, b = st.columns([1, 2], vertical_alignment="bottom")
max_slots = min(30, len(pool))
# O valor escolhido fica guardado; só é ajustado quando sai dos limites atuais.
default_slots = len(draft["sequence"]) if draft else 9
st.session_state[SLOTS] = min(max_slots, max(2, int(st.session_state.get(SLOTS, default_slots))))
slots = a.number_input("Posições na grade", min_value=2, max_value=max_slots, step=1, key=SLOTS)
if b.button("Gerar sugestão" if not draft else "Gerar nova sugestão (mantém as fixadas)",
            type="primary", icon=":material/auto_awesome:"):
    pins = {draft["sequence"].index(pid): pid for pid in draft["pinned"]} if draft else {}
    honoured = {pos: pid for pos, pid in pins.items() if pos < int(slots)}
    if len(honoured) < len(pins):
        flash(f"{len(pins) - len(honoured)} foto(s) fixada(s) além da posição {int(slots)} foram soltas.", "warning")
    plan = fp.plan_feed(list(photos.values()), int(slots), honoured, weights)
    st.session_state[DRAFT] = {"sequence": plan.sequence, "pinned": list(honoured.values()),
                               "reasons": plan.reasons, "version_id": draft.get("version_id") if draft else None}
    st.rerun()

if not draft:
    st.info("Toque em “Gerar sugestão” para montar a primeira sequência ou carregue uma versão salva abaixo.")
else:
    seq = draft["sequence"]

    def move(index: int, delta: int) -> None:
        j = index + delta
        if 0 <= j < len(seq):
            seq[index], seq[j] = seq[j], seq[index]
            draft["reasons"] = {}

    def toggle_pin(pid: int) -> None:
        draft["pinned"] = [p for p in draft["pinned"] if p != pid] if pid in draft["pinned"] else draft["pinned"] + [pid]

    def remove(index: int) -> None:
        pid = seq.pop(index)
        draft["pinned"] = [p for p in draft["pinned"] if p != pid]
        draft["reasons"] = {}

    # A grade é desenhada como uma imagem única: mantém as 3 colunas em qualquer tela.
    pinned_now = {i for i, pid in enumerate(seq) if pid in draft["pinned"]}
    st.image(fp.grid_preview_png(storage, [by_id[pid] for pid in seq], cell=240, pinned_positions=pinned_now),
             width="stretch")
    st.caption("Marcador amarelo = posição fixada. Toque no número para mover, fixar ou retirar a foto.")
    with st.container(horizontal=True, gap="small"):
        for pos, pid in enumerate(seq):
            pinned = pid in draft["pinned"]
            with st.popover(f"{pos + 1}{' 📌' if pinned else ''}"):
                data = tile_bytes(by_id[pid])
                if data:
                    st.image(data, width=120)
                st.caption(f"{by_id[pid].get('original_name') or ''} · {by_id[pid]['technical_score']:.0f}/100")
                st.button("◀ Mover para antes", key=f"l_{pos}", on_click=move, args=(pos, -1),
                          disabled=pos == 0, width="stretch")
                st.button("Mover para depois ▶", key=f"r_{pos}", on_click=move, args=(pos, 1),
                          disabled=pos == len(seq) - 1, width="stretch")
                st.button("Soltar posição" if pinned else "📌 Fixar nesta posição", key=f"p_{pos}",
                          on_click=toggle_pin, args=(pid,), width="stretch")
                st.button("✕ Tirar da sequência", key=f"x_{pos}", on_click=remove, args=(pos,),
                          width="stretch")

    missing = [pid for pid in photos if pid not in seq]
    if missing:
        a, b = st.columns([3, 1], vertical_alignment="bottom")
        add = a.selectbox("Adicionar foto ao fim", missing,
                          format_func=lambda pid: f"{by_id[pid].get('original_name') or pid} · "
                                                  f"{by_id[pid]['technical_score']:.0f}/100")
        if b.button("Adicionar", width="stretch"):
            seq.append(add)
            st.rerun()

    seq_photos = [photos[pid] for pid in seq]
    ev = fp.evaluate_sequence(seq_photos, weights)
    metric_grid([
        ("Equilíbrio geral", f"{ev.overall:.0f}"),
        ("Qualidade", f"{ev.quality:.0f}"),
        ("Diversidade", f"{ev.diversity:.0f}"),
        ("Coerência de cor", f"{ev.coherence:.0f}"),
        ("Preferência", f"{ev.preference:.0f}"),
    ], width=140)
    st.caption("Indicadores de 0 a 100 para comparar sequências entre si — não preveem desempenho.")

    notes = list(dict.fromkeys(
        fp.repetition_warnings(seq_photos) + ev.adjacent_alerts + fp.alternation_suggestions(seq_photos)
    ))
    if notes:
        with st.container(border=True):
            st.markdown("**Sugestões para esta sequência**")
            st.markdown("\n".join(f"- {n}" for n in notes[:8]))
            if len(notes) > 8:
                st.caption(f"+ {len(notes) - 8} observação(ões) semelhantes.")
    if draft.get("reasons"):
        with st.expander("Por que cada foto está nessa posição"):
            for pos, reasons in sorted(draft["reasons"].items()):
                st.markdown(f"**{pos + 1}.** " + " ".join(reasons))

    # --- Salvar e exportar ---
    rows = [by_id[pid] for pid in seq]
    pinned_positions = {seq.index(p) for p in draft["pinned"]}
    items = [{"image_id": pid, "pinned": pid in draft["pinned"]} for pid in seq]
    with st.container(border=True):
        a, b = st.columns([2, 1], vertical_alignment="bottom")
        name = a.text_input("Nome da versão", value=f"Versão {len(feeds_repo.list_versions(db)) + 1}", max_chars=80)
        if b.button("Salvar como nova versão", icon=":material/save:", width="stretch"):
            try:
                vid = feeds_repo.save_version(db, name, items, {"weights": weights})
            except ValueError as exc:
                st.error(str(exc))
            else:
                draft["version_id"] = vid
                done("Versão salva.")
        if draft.get("version_id") and st.button("Atualizar a versão carregada", icon=":material/sync:"):
            try:
                feeds_repo.update_version(db, draft["version_id"], items, {"weights": weights})
            except ValueError as exc:
                draft["version_id"] = None
                st.error(f"{exc} Use “Salvar como nova versão”.")
            else:
                done("Versão atualizada.")
    a, b, c = st.columns(3)
    a.download_button("Sequência (CSV)", to_csv_bytes(fp.sequence_dataframe(rows, pinned_positions)),
                      "sequencia_feed.csv", "text/csv", icon=":material/download:", width="stretch")
    b.download_button("Prévia da grade (PNG)", fp.grid_preview_png(storage, rows), "previa_grade.png",
                      "image/png", icon=":material/image:", width="stretch")
    # O ZIP preparado só vale para a sequência exata em que foi gerado.
    fingerprint = (tuple(seq), tuple(sorted(draft["pinned"])))
    prepared = st.session_state.get(ZIP)
    if prepared and prepared["fingerprint"] != fingerprint:
        st.session_state.pop(ZIP, None)
        prepared = None
    if c.button("Preparar ZIP com fotos", icon=":material/folder_zip:", width="stretch"):
        prepared = {"fingerprint": fingerprint, "data": fp.export_zip(storage, rows, pinned_positions)}
        st.session_state[ZIP] = prepared
    if prepared:
        st.download_button("Baixar ZIP (fotos na ordem de publicação)", prepared["data"],
                           "feed_ordem_publicacao.zip", "application/zip", type="primary",
                           on_click=lambda: st.session_state.pop(ZIP, None))
    st.caption("No ZIP, os arquivos vêm numerados na ordem de publicação: publique o 01 primeiro.")

# --- 4. Versões salvas e comparação ---------------------------------------------------------------------

render_versions(draft, weights)
