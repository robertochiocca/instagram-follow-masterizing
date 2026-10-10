"""Testes da interface com o AppTest do Streamlit (sem navegador).

Cada página é executada de verdade: com banco vazio, com dados e com
interações (formulários, botões e confirmações).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
from conftest import encode, scene
from database import Database
from database import images as images_repo
from services import follows, interests, metrics_log, photo_library
from services.image_storage import ImageStorage

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted(f"views/{p.name}" for p in (ROOT / "views").glob("*.py"))
TIMEOUT = 60
MB = 1024 * 1024


def run(path: str, **state) -> AppTest:
    at = AppTest.from_file(str(ROOT / path), default_timeout=TIMEOUT)
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def button(at: AppTest, label: str):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"botão não encontrado: {label}"
    return matches[0]


def assert_ok(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


@pytest.fixture
def seeded(app_data_dir):
    db = Database(app_data_dir / "growth_tool.sqlite3")
    db.initialize()
    storage = ImageStorage(app_data_dir / "images")
    ids = []
    for i in range(6):
        out = photo_library.import_image(db, storage, encode(scene(seed=i, warm=i % 2 == 0)), f"{i}.jpg", "own", 5 * MB)
        images_repo.update_image(db, out.image_id, {"tags": ["praia" if i % 2 else "retrato"], "in_feed_pool": True,
                                                    "user_rating": 1 + i % 5}, category_ids=[1 + i % 3])
        ids.append(out.image_id)
    for i in range(5):
        out = photo_library.import_image(db, storage, encode(scene(seed=10 + i)), f"r{i}.jpg", "reference", 5 * MB)
        images_repo.update_image(db, out.image_id, {"reaction": "gosto" if i < 3 else "nao_gosto",
                                                    "context": "praia" if i < 3 else "cidade"}, category_ids=[1])
    interests.add_interest(db, {"username": "inspiracao.um", "category": "Viagens"})
    follows.add_follow(db, {"username": "amigo.dois", "followed_at": config.today() - timedelta(days=10)})
    for k, f in enumerate([69, 72, 71, 78]):
        metrics_log.upsert_metric(db, {"date": config.today() - timedelta(days=7 * (3 - k)), "followers": f})
    return db, storage, ids


@pytest.mark.parametrize("path", ["app.py", *PAGES])
def test_pages_render_empty(app_data_dir, path):
    assert_ok(run(path))


@pytest.mark.parametrize("path", ["app.py", *PAGES])
def test_pages_render_with_data(seeded, path):
    assert_ok(run(path))


def test_dashboard_registers_metric(app_data_dir):
    at = run("views/dashboard.py")
    followers = next(n for n in at.number_input if n.label == "Seguidores *")
    followers.set_value(80)
    button(at, "Salvar registro").click()
    at.run()
    assert_ok(at)
    db = Database(app_data_dir / "growth_tool.sqlite3")
    assert metrics_log.list_metrics(db)[-1]["followers"] == 80
    assert any(m.label == "Seguidores atuais" and m.value == "80" for m in at.metric)


def test_interest_add_and_register_follow(app_data_dir):
    at = run("views/perfis_interesse.py")
    next(t for t in at.text_input if t.label.startswith("Nome de usuário")).input("@Novo.Perfil")
    button(at, "Salvar").click()
    at.run()
    assert_ok(at)
    db = Database(app_data_dir / "growth_tool.sqlite3")
    assert [r["username"] for r in interests.list_interests(db)] == ["novo.perfil"]
    button(at, "Registrar que segui").click()
    at.run()
    assert_ok(at)
    assert follows.list_follows(db)[0]["username"] == "novo.perfil"


def test_interest_invalid_username_shows_error(app_data_dir):
    at = run("views/perfis_interesse.py")
    next(t for t in at.text_input if t.label.startswith("Nome de usuário")).input("nome com espaço")
    button(at, "Salvar").click()
    at.run()
    assert_ok(at)
    assert any("inválido" in e.value for e in at.error)


def test_follow_mark_reviewed_and_delete(seeded):
    db, _, _ = seeded
    at = run("views/acompanhamento.py")
    button(at, "Marcar como revisado").click()
    at.run()
    assert_ok(at)
    assert follows.list_follows(db)[0]["last_reviewed_at"] == config.today().isoformat()
    button(at, "Apagar registro").click()
    at.run()
    button(at, "Sim, excluir").click()
    at.run()
    assert_ok(at)
    assert follows.list_follows(db, include_archived=True) == []


def test_photo_detail_and_delete_with_confirmation(seeded):
    db, storage, ids = seeded
    target = ids[0]
    at = run("views/minhas_fotos.py", selected_image_own=target)
    assert_ok(at)
    assert any("Pontuação técnica" in m.label for m in at.metric)
    button(at, "Excluir esta foto").click()
    at.run()
    assert images_repo.get_image(db, target) is not None  # ainda pede confirmação
    button(at, "Sim, excluir").click()
    at.run()
    assert_ok(at)
    assert images_repo.get_image(db, target) is None


def test_reference_detail_view(seeded):
    db, _, _ = seeded
    ref_id = images_repo.list_images(db, "reference")[0]["id"]
    assert_ok(run("views/minhas_referencias.py", selected_image_reference=ref_id))


def test_feed_generate_move_and_save(seeded):
    db, _, ids = seeded
    at = run("views/organizador_feed.py")
    button(at, "Gerar sugestão").click()
    at.run()
    assert_ok(at)
    draft = at.session_state["feed_draft"]
    assert sorted(draft["sequence"]) == sorted(ids)
    first, second = draft["sequence"][:2]
    at.button(key="r_0").click()
    at.run()
    assert at.session_state["feed_draft"]["sequence"][:2] == [second, first]
    at.button(key="p_0").click()
    at.run()
    assert at.session_state["feed_draft"]["pinned"] == [second]
    button(at, "Salvar como nova versão").click()
    at.run()
    assert_ok(at)
    from database import feeds as feeds_repo

    versions = feeds_repo.list_versions(db)
    assert len(versions) == 1
    saved = feeds_repo.get_version(db, versions[0]["id"])
    assert saved["items"][0] == {"image_id": second, "pinned": True}


def test_profile_save_and_suggestions(app_data_dir):
    at = run("views/meu_perfil.py")
    next(t for t in at.text_input if t.label == "Ocupação ou estudo").input("Estudante de Direito")
    next(t for t in at.text_input if t.label.startswith("Esportes")).input("natação, futevôlei")
    button(at, "Salvar perfil").click()
    at.run()
    assert_ok(at)
    from database.settings import get_profile

    profile = get_profile(Database(app_data_dir / "growth_tool.sqlite3"))
    assert profile["occupation"] == "Estudante de Direito"
    assert any("Natação" in c.value for c in at.code)


def test_content_routine_generation(app_data_dir):
    at = run("views/planejador_conteudo.py")
    button(at, "Gerar prévia da rotina").click()
    at.run()
    preview = at.session_state["schedule_preview"]
    assert preview
    button(at, f"Adicionar {len(preview)} itens ao calendário").click()
    at.run()
    assert_ok(at)
    from services import content_planner

    assert len(content_planner.list_items(Database(app_data_dir / "growth_tool.sqlite3"))) == len(preview)


def test_settings_wipe_all_requires_typed_confirmation(seeded):
    db, storage, _ = seeded
    at = run("views/configuracoes.py")
    go = button(at, "Apagar tudo definitivamente")
    assert go.disabled
    next(t for t in at.text_input if t.label.startswith("Para confirmar")).input("APAGAR")
    at.run()
    button(at, "Apagar tudo definitivamente").click()
    at.run()
    assert_ok(at)
    assert images_repo.count_images(db, "own") == 0
    assert storage.usage() == (0, 0)
    assert metrics_log.list_metrics(db) == []


def test_password_gate(app_data_dir, monkeypatch):
    monkeypatch.setenv("IGT_APP_PASSWORD", "segredo-forte")
    at = run("app.py")
    assert_ok(at)
    assert at.title[0].value == "Instagram Growth Tool"
    assert not at.metric  # o dashboard não foi exibido
    at.text_input[0].input("errada")
    button(at, "Entrar").click()
    at.run()
    assert any("incorreta" in e.value for e in at.error)
    at.text_input[0].input("segredo-forte")
    button(at, "Entrar").click()
    at.run()
    assert_ok(at)
    assert any(t.value == "Dashboard" for t in at.title)


@pytest.mark.parametrize("page", ["views/configuracoes.py", "views/dashboard.py", "views/minhas_fotos.py"])
def test_password_gate_cannot_be_skipped_by_opening_a_page_directly(app_data_dir, monkeypatch, page):
    # Regressão: com uma pasta "pages/" o Streamlit executava a página sem passar pelo app.py.
    monkeypatch.setenv("IGT_APP_PASSWORD", "segredo-forte")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.switch_page(page)
    at.run()
    assert_ok(at)
    assert any(t.label == "Senha de acesso" for t in at.text_input)
    assert not any("exportação" in b.label.lower() for b in at.button)
    assert not at.metric


def test_no_streamlit_auto_pages_directory():
    # Uma pasta "pages/" ao lado do app.py liga o modo multipágina legado do Streamlit.
    assert not (ROOT / "pages").exists()
