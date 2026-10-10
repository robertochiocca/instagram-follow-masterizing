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
from ui.components import confirm_button, done, empty_state, fmt_date, page_header
from ui.state import get_db, get_storage

db = get_db()
storage = get_storage()
DRAFT = "feed_draft"

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

# --- 1. Seleção das fotos consideradas ------------------------------------------------------------


def toggle_pool(image_id: int) -> None:
    images_repo.set_feed_pool(db, [image_id], st.session_state[f"pool_{image_id}"])


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
    cols = st.columns(4)
    for i, r in enumerate(own):
        with cols[i % 4]:
            data = tile_bytes(r)
            if data:
                st.image(data, width="stretch")
            st.checkbox(f"{r['technical_score']:.0f}/100", value=bool(r.get("in_feed_pool")),
                        key=f"pool_{r['id']}", on_change=toggle_pool, args=(r["id"],))

if len(pool) < 2:
    st.info("Selecione pelo menos 2 fotos para montar uma sequência.")
    st.stop()

# --- 2. Parâmetros ----------------------------------------------------------------------------------

model, cat_names = preferences.load_model(db)
pref_values = {
    r["id"]: (preferences.affinity(r, model, cat_names).percent / 100 if model.ready else None) for r in pool
}
photos = {r["id"]: fp.FeedPhoto.from_row(r, pref_values[r["id"]]) for r in pool}
weights = get_setting(db, "feed_weights")

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
    draft["sequence"] = [pid for pid in draft["sequence"] if pid in photos]
    draft["pinned"] = [pid for pid in draft["pinned"] if pid in draft["sequence"]]

st.subheader("3. Sequência")
a, b = st.columns([1, 2], vertical_alignment="bottom")
max_slots = min(30, len(pool))
slots = a.number_input("Posições na grade", min_value=2, max_value=max_slots,
                       value=min(max_slots, 9 if not draft else max(2, len(draft["sequence"]))), step=1)
if b.button("Gerar sugestão" if not draft else "Gerar nova sugestão (mantém as fixadas)",
            type="primary", icon=":material/auto_awesome:"):
    pins = {draft["sequence"].index(pid): pid for pid in draft["pinned"]} if draft else {}
    plan = fp.plan_feed(list(photos.values()), int(slots), pins, weights)
    st.session_state[DRAFT] = {"sequence": plan.sequence, "pinned": list(pins.values()),
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

    for start in range(0, len(seq), fp.GRID_COLUMNS):
        cols = st.columns(fp.GRID_COLUMNS, gap="small")
        for offset, col in enumerate(cols):
            pos = start + offset
            if pos >= len(seq):
                continue
            pid = seq[pos]
            with col.container(border=True):
                data = tile_bytes(by_id[pid])
                if data:
                    st.image(data, width="stretch")
                pinned = pid in draft["pinned"]
                st.markdown(f"**{pos + 1}** {'📌' if pinned else ''} · {by_id[pid]['technical_score']:.0f}/100")
                c1, c2, c3, c4 = st.columns(4, gap="small")
                c1.button("◀", key=f"l_{pos}", on_click=move, args=(pos, -1), disabled=pos == 0,
                          help="Mover para antes", width="stretch")
                c2.button("▶", key=f"r_{pos}", on_click=move, args=(pos, 1), disabled=pos == len(seq) - 1,
                          help="Mover para depois", width="stretch")
                c3.button("📌", key=f"p_{pos}", on_click=toggle_pin, args=(pid,),
                          help="Fixar/soltar nesta posição", type="primary" if pinned else "secondary",
                          width="stretch")
                c4.button("✕", key=f"x_{pos}", on_click=remove, args=(pos,), help="Tirar da sequência",
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
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Equilíbrio geral", f"{ev.overall:.0f}")
    m2.metric("Qualidade", f"{ev.quality:.0f}")
    m3.metric("Diversidade", f"{ev.diversity:.0f}")
    m4.metric("Coerência de cor", f"{ev.coherence:.0f}")
    m5.metric("Preferência", f"{ev.preference:.0f}")
    st.caption("Indicadores de 0 a 100 para comparar sequências entre si — não preveem desempenho.")

    notes = ev.adjacent_alerts + fp.repetition_warnings(seq_photos) + fp.alternation_suggestions(seq_photos)
    if notes:
        with st.container(border=True):
            st.markdown("**Sugestões para esta sequência**")
            st.markdown("\n".join(f"- {n}" for n in dict.fromkeys(notes)))
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
            feeds_repo.update_version(db, draft["version_id"], items, {"weights": weights})
            done("Versão atualizada.")
    a, b, c = st.columns(3)
    a.download_button("Sequência (CSV)", to_csv_bytes(fp.sequence_dataframe(rows, pinned_positions)),
                      "sequencia_feed.csv", "text/csv", icon=":material/download:", width="stretch")
    b.download_button("Prévia da grade (PNG)", fp.grid_preview_png(storage, rows), "previa_grade.png",
                      "image/png", icon=":material/image:", width="stretch")
    if c.button("Preparar ZIP com fotos", icon=":material/folder_zip:", width="stretch"):
        st.session_state["feed_zip"] = fp.export_zip(storage, rows, pinned_positions)
    if st.session_state.get("feed_zip"):
        st.download_button("Baixar ZIP (fotos na ordem de publicação)", st.session_state["feed_zip"],
                           "feed_ordem_publicacao.zip", "application/zip", type="primary",
                           on_click=lambda: st.session_state.pop("feed_zip", None))
    st.caption("No ZIP, os arquivos vêm numerados na ordem de publicação: publique o 01 primeiro.")

# --- 4. Versões salvas e comparação ---------------------------------------------------------------------

st.subheader("4. Versões salvas")
versions = feeds_repo.list_versions(db)
if not versions:
    st.caption("Nenhuma versão salva ainda.")
else:
    for v in versions:
        with st.container(border=True):
            a, b, c = st.columns([3, 1, 1], vertical_alignment="center")
            a.markdown(f"**{v['name']}** · {v['item_count']} fotos · atualizada em {fmt_date(v['updated_at'])}")
            if b.button("Carregar", key=f"load_{v['id']}", width="stretch"):
                full = feeds_repo.get_version(db, v["id"])
                images_repo.set_feed_pool(db, [i["image_id"] for i in full["items"]], True)
                st.session_state[DRAFT] = {
                    "sequence": [i["image_id"] for i in full["items"]],
                    "pinned": [i["image_id"] for i in full["items"] if i["pinned"]],
                    "reasons": {}, "version_id": v["id"],
                }
                done(f"“{v['name']}” carregada.")
            with c:
                if confirm_button("Excluir", f"del_version_{v['id']}", f"Excluir a versão “{v['name']}”?"):
                    feeds_repo.delete_version(db, v["id"])
                    done("Versão excluída.")

    st.markdown("**Comparar sequências**")
    choices = st.multiselect("Escolha até 3 versões", [v["id"] for v in versions], max_selections=3,
                             format_func=lambda vid: next(v["name"] for v in versions if v["id"] == vid))
    compare = []
    if draft:
        compare.append(("Rascunho atual", draft["sequence"]))
    for vid in choices:
        full = feeds_repo.get_version(db, vid)
        compare.append((full["name"], [i["image_id"] for i in full["items"]]))
    if len(compare) >= 2:
        all_rows = images_repo.get_images_by_ids(db, {pid for _, s in compare for pid in s})
        table = []
        for name, seq_ids in compare:
            fps = [fp.FeedPhoto.from_row(all_rows[pid], pref_values.get(pid)) for pid in seq_ids if pid in all_rows]
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
    elif choices or versions:
        st.caption("Selecione versões (e/ou tenha um rascunho) para comparar lado a lado.")
