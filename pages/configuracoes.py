"""Configurações: categorias, listas, pesos, limites, exportação, backup e exclusão de dados."""

from __future__ import annotations

import streamlit as st

from config import HARD_MAX_UPLOAD_MB, now
from database import images as images_repo
from database.settings import get_setting, reset_setting, set_setting
from models.defaults import DEFAULT_PREFERENCE_GROUP_WEIGHTS, DEFAULT_SCORE_WEIGHTS
from services import data_management, photo_library
from services.image_analysis import SCORE_LABELS
from services.preferences import GROUP_LABELS
from ui.components import confirm_button, done, fmt_bytes, metric_grid, page_header, typed_confirmation
from ui.state import get_config, get_db, get_storage, max_upload_mb

db = get_db()
storage = get_storage()
cfg = get_config()

page_header("Configurações", "Personalize categorias, pesos e limites. Gerencie e apague seus dados.")

tab_cat, tab_lists, tab_weights, tab_general, tab_data = st.tabs(
    ["Categorias", "Listas", "Pesos", "Geral", "Dados e privacidade"]
)

# --- Categorias estéticas ----------------------------------------------------------------------

with tab_cat:
    st.caption(
        "Categorias usadas para classificar fotos e referências. A importância (0 a 3) pondera o "
        "aprendizado de preferências e as sugestões de destaques e ideias; 0 = ignorar."
    )
    for cat in images_repo.list_categories(db):
        with st.expander(f"{cat['name']} · importância {cat['weight']:.1f} · {cat['usage']} imagem(ns)"):
            with st.form(f"cat_{cat['id']}"):
                name = st.text_input("Nome", value=cat["name"], max_chars=60)
                desc = st.text_input("Descrição", value=cat.get("description") or "", max_chars=200)
                weight = st.slider("Importância", 0.0, 3.0, float(cat["weight"]), 0.1)
                if st.form_submit_button("Salvar categoria", type="primary"):
                    try:
                        images_repo.update_category(db, cat["id"], name=name, description=desc, weight=weight)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        done("Categoria atualizada.")
            if confirm_button("Remover categoria", f"del_cat_{cat['id']}",
                              "A categoria será removida das imagens classificadas com ela (as imagens continuam)."):
                images_repo.delete_category(db, cat["id"])
                done("Categoria removida.")
    with st.form("new_category", clear_on_submit=True):
        st.markdown("**Nova categoria**")
        name = st.text_input("Nome", max_chars=60)
        desc = st.text_input("Descrição (opcional)", max_chars=200)
        weight = st.slider("Importância", 0.0, 3.0, 1.0, 0.1)
        if st.form_submit_button("Criar categoria", icon=":material/add:"):
            try:
                images_repo.add_category(db, name, desc, weight)
            except ValueError as exc:
                st.error(str(exc))
            else:
                done("Categoria criada.")

# --- Listas editáveis -------------------------------------------------------------------------------

with tab_lists:
    with st.form("lists"):
        interest_cats = st.text_area(
            "Categorias de perfis de interesse (uma por linha)",
            "\n".join(get_setting(db, "interest_categories")), height=180,
        )
        tags = st.text_area(
            "Tags sugeridas para fotos (uma por linha)", "\n".join(get_setting(db, "photo_tags")), height=180,
        )
        if st.form_submit_button("Salvar listas", type="primary"):
            clean = lambda text: list(dict.fromkeys(  # noqa: E731
                line.strip()[:60] for line in text.splitlines() if line.strip()))
            cats, tag_list = clean(interest_cats), [t.lower() for t in clean(tags)]
            if not cats:
                st.error("Mantenha ao menos uma categoria de perfil.")
            else:
                set_setting(db, "interest_categories", cats)
                set_setting(db, "photo_tags", tag_list)
                done("Listas salvas.")

# --- Pesos -----------------------------------------------------------------------------------------

with tab_weights:
    st.markdown("#### Pontuação técnica das fotos")
    st.caption("Pesos relativos (são normalizados para somar 100%). Ao salvar, todas as fotos são reavaliadas.")
    current = get_setting(db, "score_weights")
    with st.form("score_weights"):
        new_weights = {
            key: st.slider(label, 0, 50, int(current.get(key, DEFAULT_SCORE_WEIGHTS[key])), 1)
            for key, label in SCORE_LABELS.items()
        }
        a, b = st.columns(2)
        save = a.form_submit_button("Salvar e reavaliar", type="primary")
        restore = b.form_submit_button("Restaurar padrão")
    if save or restore:
        if save and sum(new_weights.values()) == 0:
            st.error("Pelo menos um peso precisa ser maior que zero.")
        else:
            if restore:
                reset_setting(db, "score_weights")
            else:
                set_setting(db, "score_weights", new_weights)
            total = photo_library.rescore_all(db, get_setting(db, "score_weights"))
            done(f"Pesos salvos; {total} imagem(ns) reavaliada(s).")

    st.markdown("#### Aprendizado de preferências")
    st.caption("Quanto cada grupo de características influencia a afinidade com suas referências.")
    current = get_setting(db, "preference_group_weights")
    with st.form("pref_weights"):
        new_pref = {
            key: st.slider(GROUP_LABELS[key], 0.0, 2.0, float(current.get(key, default)), 0.1)
            for key, default in DEFAULT_PREFERENCE_GROUP_WEIGHTS.items()
        }
        a, b = st.columns(2)
        save = a.form_submit_button("Salvar pesos", type="primary")
        restore = b.form_submit_button("Restaurar padrão")
    if save:
        set_setting(db, "preference_group_weights", new_pref)
        done("Pesos de preferência salvos.")
    if restore:
        reset_setting(db, "preference_group_weights")
        done("Pesos de preferência restaurados.")

# --- Geral ------------------------------------------------------------------------------------------

with tab_general:
    with st.form("general"):
        upload = st.number_input(
            f"Tamanho máximo por imagem (MB, até {HARD_MAX_UPLOAD_MB})",
            min_value=1, max_value=HARD_MAX_UPLOAD_MB, value=max_upload_mb(),
        )
        target = st.number_input("Meta de seguidores", min_value=1,
                                 value=int(get_setting(db, "target_followers")), step=50)
        if st.form_submit_button("Salvar", type="primary"):
            set_setting(db, "max_upload_mb", int(upload))
            set_setting(db, "target_followers", int(target))
            done("Configurações salvas.")
    st.caption(f"Padrão do servidor (IGT_MAX_UPLOAD_MB): {cfg.max_upload_mb} MB.")

# --- Dados e privacidade ----------------------------------------------------------------------------

with tab_data:
    counts = data_management.summary_counts(db)
    files, size = storage.usage()
    metric_grid([
        ("Minhas fotos", counts["own_images"]),
        ("Referências", counts["reference_images"]),
        ("Espaço das imagens", fmt_bytes(size)),
    ])
    st.caption(
        f"Perfis de interesse: {counts['interest_profiles']} · Acompanhamento: {counts['follow_tracking']} · "
        f"Métricas: {counts['metrics']} · Conteúdos planejados: {counts['content_plan']} · "
        f"Versões de feed: {counts['feed_versions']}"
    )
    st.markdown(f"Pasta de dados: `{cfg.data_dir}`")

    st.markdown("#### Exportar e fazer backup")
    include_images = st.checkbox("Incluir as imagens na exportação", value=True)
    if st.button("Preparar exportação completa (ZIP)", icon=":material/folder_zip:"):
        with st.spinner("Gerando arquivo…"):
            st.session_state["export_zip"] = data_management.export_all_zip(db, storage, include_images)
    if st.session_state.get("export_zip"):
        st.download_button(
            "Baixar exportação", st.session_state["export_zip"],
            f"growth_tool_export_{now():%Y%m%d_%H%M}.zip", "application/zip",
            icon=":material/download:", type="primary",
            on_click=lambda: st.session_state.pop("export_zip", None),
        )
    if st.button("Preparar backup do banco de dados", icon=":material/database:"):
        st.session_state["db_backup"] = db.backup_bytes()
    if st.session_state.get("db_backup"):
        st.download_button(
            "Baixar backup (.sqlite3)", st.session_state["db_backup"],
            f"growth_tool_backup_{now():%Y%m%d_%H%M}.sqlite3", "application/octet-stream",
            icon=":material/download:",
            on_click=lambda: st.session_state.pop("db_backup", None),
        )
    st.caption("O backup do banco não inclui as imagens; para elas, use a exportação ZIP ou copie a pasta de dados.")

    st.markdown("#### Apagar dados")
    if confirm_button("Apagar todas as minhas fotos", "del_all_own",
                      "Todas as suas fotos, análises e versões de feed que as usam serão apagadas."):
        n = photo_library.delete_all_images(db, storage, "own")
        done(f"{n} foto(s) apagada(s).")
    if confirm_button("Apagar todas as referências", "del_all_refs",
                      "Todas as referências e o aprendizado de preferências serão apagados."):
        n = photo_library.delete_all_images(db, storage, "reference")
        done(f"{n} referência(s) apagada(s).")
    with st.expander("Apagar TODOS os dados", icon=":material/warning:"):
        st.warning(
            "Remove imagens, perfil, listas, métricas, planejamento e configurações. Não pode ser "
            "desfeito. Considere exportar antes."
        )
        if typed_confirmation("Apagar tudo definitivamente", "wipe_all"):
            data_management.delete_all_data(db, storage)
            st.session_state.clear()
            done("Todos os dados foram apagados.")

    st.markdown("#### Privacidade")
    st.markdown(
        "- Tudo fica nesta pasta de dados (banco SQLite e imagens). Nada é enviado a serviços externos.\n"
        "- As imagens são gravadas sem metadados EXIF (incluindo localização GPS) e com nomes gerados.\n"
        "- Em ambientes remotos (como GitHub Codespaces), os arquivos ficam na infraestrutura do "
        "provedor enquanto o ambiente existir. Não há privacidade absoluta: apague os dados e o "
        "ambiente quando não precisar mais.\n"
        "- Os logs não registram imagens, senhas, tokens nem o conteúdo dos seus registros."
    )
