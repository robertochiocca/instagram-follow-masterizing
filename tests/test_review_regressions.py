"""Regressões dos problemas encontrados na revisão multiagente (cada teste reproduz um caso real)."""

from __future__ import annotations

import csv
import io
import math
import tomllib
import zipfile
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import config
from conftest import encode, scene
from database import Database
from database import feeds as feeds_repo
from database import images as images_repo
from database.settings import get_setting
from services import content_planner as cp
from services import csv_io, growth, metrics_log, photo_library, preferences
from services import feed_planner as fp
from services.image_storage import ImageStorage

ROOT = Path(__file__).resolve().parent.parent
MB = 1024 * 1024
TODAY = config.today()


# --- Importação CSV ---------------------------------------------------------------------------------


def test_trailing_separator_rows_are_imported(db):
    report = csv_io.import_metrics_csv(db, b"data;seguidores\n01/10/2026;69;\n08/10/2026;74;\n")
    assert report.inserted == 2 and not report.errors


def test_unquoted_thousands_is_a_line_error_not_a_crash(db):
    report = csv_io.import_metrics_csv(db, b"data,seguidores\n2026-10-01,1,234\n2026-10-02,70\n")
    assert report.inserted == 1
    assert report.errors == [report.errors[0]] and report.errors[0].startswith("Linha 2")
    assert "aspas" in report.errors[0]


@pytest.mark.parametrize(
    "payload",
    [
        b"data;seguidores\r01/10/2026;69\r08/10/2026;74\r",  # Excel para Mac antigo (só CR)
        b"data;seguidores\r\n01/10/2026;69\r\n08/10/2026;74\r\n",  # Windows
        "data;seguidores\n01/10/2026;69\n08/10/2026;74\n".encode("utf-16"),  # UTF-16 com BOM
    ],
)
def test_line_endings_and_utf16(db, payload):
    report = csv_io.import_metrics_csv(db, payload)
    assert report.inserted == 2 and not report.errors


def test_windows_ansi_notes_are_decoded_as_cp1252(db):
    data = "data;seguidores;observacoes\n01/10/2026;69;Reels – “top”\n".encode("cp1252")
    csv_io.import_metrics_csv(db, data)
    assert metrics_log.list_metrics(db)[0]["notes"] == "Reels – “top”"


def test_huge_numbers_and_future_dates_are_rejected_per_line(db):
    future = (TODAY + timedelta(days=3)).isoformat()
    data = f"data,seguidores\n2026-10-01,99999999999999999999\n{future},70\n2026-10-02,71\n".encode()
    report = csv_io.import_metrics_csv(db, data)
    assert report.inserted == 1
    assert "grande demais" in report.errors[0] and "futuro" in report.errors[1]


def test_engagement_percent_column_is_not_mapped_to_interactions(db):
    report = csv_io.import_metrics_csv(db, "data;seguidores;engajamento\n01/10/2026;69;4,5%\n".encode())
    assert report.inserted == 1 and not report.errors
    assert metrics_log.list_metrics(db)[0]["interactions"] is None


def test_error_line_numbers_count_blank_lines_and_multiline_notes(db):
    data = b'data,seguidores,observacoes\n2026-10-01,69,"duas\nlinhas"\n\n2026-10-03,abc,\n'
    report = csv_io.import_metrics_csv(db, data)
    assert report.errors == ["Linha 5: número inválido “abc”."]


def test_unreadable_csv_gives_friendly_error(db):
    with pytest.raises(ValueError, match="separador"):
        csv_io.import_metrics_csv(db, b"apenas uma coluna\nsem separador\n")


# --- Exportação CSV ------------------------------------------------------------------------------------


def test_export_uses_semicolon_quotes_and_decimal_comma():
    df = pd.DataFrame([{"texto": "meta batida;=1+1", "valor": 3.5, "n": 7}])
    raw = csv_io.to_csv_bytes(df).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw), delimiter=";"))
    assert rows[0] == ["texto", "valor", "n"]
    assert rows[1] == ["meta batida;=1+1", "3,5", "7"]  # o “;” não cria célula nova
    assert raw.splitlines()[1] == '"meta batida;=1+1";"3,5";"7"'  # todos os campos entre aspas


def test_feed_zip_csv_is_sanitized(db, storage):
    out = photo_library.import_image(db, storage, encode(scene(seed=7)), "x.jpg", "own", 5 * MB)
    images_repo.update_image(db, out.image_id, {"tags": ['=hyperlink("http://ev.il")']})
    with zipfile.ZipFile(io.BytesIO(fp.export_zip(storage, [images_repo.get_image(db, out.image_id)]))) as zf:
        text = zf.read("sequencia.csv").decode("utf-8-sig")
    assert "'=hyperlink" in text


# --- Crescimento ---------------------------------------------------------------------------------------


def _df(points):
    return growth.metrics_dataframe(
        [{"id": i, "date": d.isoformat(), "followers": f} for i, (d, f) in enumerate(points)]
    )


def test_summary_without_comparison_is_empty_not_zero():
    single = growth.period_summary(_df([(TODAY, 69)]), 30, TODAY)
    assert single.current_followers == 69 and single.net_gain is None and single.growth_pct is None
    stale = growth.period_summary(_df([(TODAY - timedelta(days=60), 50), (TODAY - timedelta(days=40), 80)]), 30, TODAY)
    assert stale.current_followers == 80 and stale.net_gain is None and stale.avg_daily_gain is None


def test_recent_rate_needs_recent_records():
    old = _df([(TODAY - timedelta(days=60), 50), (TODAY - timedelta(days=40), 80)])
    assert growth.average_daily_gain(old, window_days=30, today=TODAY) is None
    recent = _df([(TODAY - timedelta(days=40), 50), (TODAY, 90)])
    assert growth.average_daily_gain(recent, window_days=30, today=TODAY) == pytest.approx(1.0)


def test_weekly_gaps_are_spread_over_the_interval():
    start = pd.Timestamp("2026-09-06").date()  # domingo
    weekly = growth.weekly_table(_df([(start, 100), (start + timedelta(days=28), 140)]))
    assert list(weekly["ganho_liquido"].fillna(0)) == [0, 40]
    assert weekly.loc[1, "semanas_desde_anterior"] == 4
    assert weekly.loc[1, "ganho_medio_periodo"] == 10


def test_zero_base_growth_is_not_infinite():
    weekly = growth.weekly_table(_df([(TODAY - timedelta(days=7), 0), (TODAY, 5)]))
    assert not any(math.isinf(v) for v in weekly["crescimento_pct"].dropna())


def test_days_to_goal_has_no_float_off_by_one():
    assert growth.days_to_goal(979, 1000, 0.35) == 60
    assert growth.days_to_goal(145, 290, 0.29) == 500


# --- Dados -------------------------------------------------------------------------------------------


def test_saving_followers_keeps_other_metrics_of_the_day(db):
    metrics_log.upsert_metric(db, {"date": TODAY, "followers": 70, "reach": 1234, "notes": "semana boa"})
    metrics_log.upsert_metric(db, {"date": TODAY, "followers": 72})
    row = metrics_log.list_metrics(db)[0]
    assert (row["followers"], row["reach"], row["notes"]) == (72, 1234, "semana boa")


def test_early_publication_is_not_dated_in_the_future(db):
    item = cp.add_item(db, {"planned_date": TODAY + timedelta(days=2), "content_type": "reels"})
    cp.update_item(db, item, {"status": "publicado"})
    assert cp.get_item(db, item)["published_date"] == TODAY.isoformat()


def test_zero_weight_categories_are_ignored_in_insights():
    refs = [{"context": "praia", "reaction": "gosto", "user_rating": 5, "category_ids": [1], "tags": [],
             "metrics": {}} for _ in range(5)]
    model = preferences.learn_preferences(refs, {1: "Cat"}, category_weights={"Cat": 0.0},
                                          group_weights={"context": 0.0})
    text = " ".join(preferences.insights(model))
    assert "Cat" not in text and "praia" not in text


def test_update_of_deleted_feed_version_raises_clear_error(db):
    out = photo_library.import_image(db, ImageStorage(db.path.parent / "img"), encode(scene()), "a.jpg", "own", 5 * MB)
    vid = feeds_repo.save_version(db, "v", [{"image_id": out.image_id}])
    feeds_repo.delete_version(db, vid)
    with pytest.raises(ValueError, match="não existe"):
        feeds_repo.update_version(db, vid, [{"image_id": out.image_id}])


# --- Configuração e segurança ---------------------------------------------------------------------------


def test_dotenv_accepts_export_bom_and_inline_comments(tmp_path, monkeypatch):
    for key in ("IGT_A", "IGT_B", "IGT_C"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("﻿IGT_A=primeira\nexport IGT_B='com export'\nIGT_C=valor  # comentário\n",
                   encoding="utf-8")
    config._load_dotenv(env)
    import os

    assert (os.environ["IGT_A"], os.environ["IGT_B"], os.environ["IGT_C"]) == ("primeira", "com export", "valor")


def test_server_listens_only_on_localhost_by_default():
    settings = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert settings["server"]["address"] == "localhost"


def test_env_example_has_no_usable_password():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "IGT_APP_PASSWORD=" in lines


# --- Interface (AppTest) ----------------------------------------------------------------------------------


@pytest.fixture
def feed_app(app_data_dir):
    db = Database(app_data_dir / "growth_tool.sqlite3")
    db.initialize()
    storage = ImageStorage(app_data_dir / "images")
    for i in range(4):
        out = photo_library.import_image(db, storage, encode(scene(seed=i)), f"{i}.jpg", "own", 5 * MB)
        images_repo.update_image(db, out.image_id, {"in_feed_pool": True, "favorite": i < 2})
    return db


def _run(path: str) -> AppTest:
    return AppTest.from_file(str(ROOT / path), default_timeout=60).run()


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_updating_a_deleted_version_does_not_crash(feed_app):
    at = _run("views/organizador_feed.py")
    _button(at, "Gerar sugestão").click()
    at.run()
    _button(at, "Salvar como nova versão").click()
    at.run()
    _button(at, "Excluir").click()
    at.run()
    _button(at, "Sim, excluir").click()
    at.run()
    assert not at.exception
    assert not any(b.label == "Atualizar a versão carregada" for b in at.button)


def test_pool_checkboxes_follow_bulk_actions(feed_app):
    at = _run("views/organizador_feed.py")
    _button(at, "Limpar seleção").click()
    at.run()
    assert [c.value for c in at.checkbox] == [False] * 4
    _button(at, "Selecionar favoritas").click()
    at.run()
    db_state = {r["id"]: bool(r["in_feed_pool"]) for r in images_repo.list_images(feed_app, "own")}
    ui_state = {int(c.key.split("_")[1]): c.value for c in at.checkbox}
    assert ui_state == db_state


def test_saved_versions_are_reachable_with_empty_pool(feed_app):
    ids = [r["id"] for r in images_repo.list_images(feed_app, "own")]
    feeds_repo.save_version(feed_app, "Minha versão", [{"image_id": i} for i in ids[:3]])
    images_repo.set_feed_pool(feed_app, ids, False)
    at = _run("views/organizador_feed.py")
    assert any(b.label == "Carregar" for b in at.button)
    _button(at, "Carregar").click()
    at.run()
    assert not at.exception
    assert at.session_state["feed_draft"]["sequence"] == ids[:3]


def test_pins_beyond_the_grid_size_are_released(feed_app):
    at = _run("views/organizador_feed.py")
    _button(at, "Gerar sugestão").click()
    at.run()
    last = at.session_state["feed_draft"]["sequence"][-1]
    at.button(key="p_3").click()  # fixa a última (posição 4)
    at.run()
    assert at.session_state["feed_draft"]["pins"] == {last: 3}
    at.number_input(key="feed_slots").set_value(2)
    at.run()
    _button(at, "Gerar nova sugestão (mantém as fixadas)").click()
    at.run()
    assert not at.exception
    assert at.session_state["feed_draft"]["pins"] == {}
    assert len(at.session_state["feed_draft"]["sequence"]) == 2


def test_restore_defaults_resets_the_sliders(app_data_dir):
    at = _run("views/configuracoes.py")
    exposure = next(s for s in at.slider if s.label == "Exposição (brilho)")
    exposure.set_value(50)
    at.run()
    next(b for b in at.button if b.label == "Restaurar padrão").click()
    at.run()
    assert not at.exception
    assert next(s for s in at.slider if s.label == "Exposição (brilho)").value == 20
    db = Database(app_data_dir / "growth_tool.sqlite3")
    assert get_setting(db, "score_weights")["exposure"] == 20


# --- Segunda rodada da revisão ------------------------------------------------------------------------


def test_completing_a_past_date_keeps_its_followers(app_data_dir):
    db = Database(app_data_dir / "growth_tool.sqlite3")
    db.initialize()
    week_ago = TODAY - timedelta(days=7)
    metrics_log.upsert_metric(db, {"date": week_ago, "followers": 69})
    metrics_log.upsert_metric(db, {"date": TODAY, "followers": 74})
    at = _run("views/dashboard.py")
    assert next(n for n in at.number_input if n.label == "Seguidores").value is None
    at.date_input[0].set_value(week_ago)
    next(n for n in at.number_input if n.label == "Contas alcançadas").set_value(350)
    _button(at, "Salvar registro").click()
    at.run()
    assert not at.exception
    rows = {r["date"]: r for r in metrics_log.list_metrics(db)}
    assert (rows[week_ago.isoformat()]["followers"], rows[week_ago.isoformat()]["reach"]) == (69, 350)


def test_new_date_requires_followers(db):
    with pytest.raises(ValueError, match="seguidores"):
        metrics_log.upsert_metric(db, {"date": TODAY, "reach": 100})


@pytest.mark.parametrize("weekday_offset", range(7))
def test_schedule_always_covers_full_weeks(weekday_offset):
    freq = {"reels": 2, "carrossel": 1, "foto": 0, "stories": 3, "weekdays": ["Ter", "Qui", "Sáb"]}
    start = pd.Timestamp("2026-10-12").date() + timedelta(days=weekday_offset)  # seg a dom
    items = cp.generate_schedule(start, 4, freq, ["A"])
    assert len(items) == 4 * (3 + 3)
    assert min(i["planned_date"] for i in items) >= start
    assert max(i["planned_date"] for i in items) < start + timedelta(weeks=4)
    assert all(i["planned_date"].weekday() in {1, 3, 5} for i in items if i["content_type"] != "stories")


def test_unbalanced_quote_is_rejected_instead_of_swallowing_rows(db):
    data = 'data;seguidores;observacoes\n01/10/2026;69;ok\n02/10/2026;70;"Viagem\n03/10/2026;72;x\n'.encode()
    with pytest.raises(ValueError, match="aspas"):
        csv_io.import_metrics_csv(db, data)
    assert metrics_log.list_metrics(db) == []


def test_delimiter_detection_ignores_commas_inside_quoted_headers(db):
    data = b'data;seguidores;"obs, notas, livres, extra"\n01/10/2026;69;a, b\n'
    report = csv_io.import_metrics_csv(db, data)
    assert report.inserted == 1 and not report.errors


def test_dotenv_quoted_value_with_comment(tmp_path, monkeypatch):
    import os

    monkeypatch.delenv("IGT_Q", raising=False)
    monkeypatch.delenv("IGT_H", raising=False)
    env = tmp_path / ".env"
    env.write_text('IGT_Q="minha senha" # trocar depois\nIGT_H="Casa #42 forte"\n', encoding="utf-8")
    config._load_dotenv(env)
    assert os.environ["IGT_Q"] == "minha senha"
    assert os.environ["IGT_H"] == "Casa #42 forte"


def test_invalid_timezone_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("IGT_TIMEZONE", "America/Sao Paulo")
    assert str(config.now().tzinfo) == config.DEFAULT_TIMEZONE


def test_concurrent_first_initialization(tmp_path):
    import threading

    path = tmp_path / "novo.sqlite3"
    errors, barrier = [], threading.Barrier(4)

    def init():
        try:
            barrier.wait()
            Database(path).initialize()
        except Exception as exc:  # pragma: no cover - só em caso de falha
            errors.append(exc)

    threads = [threading.Thread(target=init) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(images_repo.list_categories(Database(path))) == 8


def test_deleted_default_category_does_not_come_back(db):
    first = images_repo.list_categories(db)[0]
    images_repo.delete_category(db, first["id"])
    db.initialize()
    assert first["name"] not in {c["name"] for c in images_repo.list_categories(db)}


def test_deleting_all_photos_removes_empty_feed_versions(db, storage):
    ids = [photo_library.import_image(db, storage, encode(scene(seed=i)), f"{i}.jpg", "own", 5 * MB).image_id
           for i in range(2)]
    feeds_repo.save_version(db, "só a primeira", [{"image_id": ids[0]}])
    feeds_repo.save_version(db, "as duas", [{"image_id": i} for i in ids])
    photo_library.delete_image(db, storage, ids[0])
    assert [v["name"] for v in feeds_repo.list_versions(db)] == ["as duas"]
    photo_library.delete_all_images(db, storage, "own")
    assert feeds_repo.list_versions(db) == []


@pytest.mark.parametrize(
    "raw,expected",
    [("instagram.com/_u/fulano", "fulano"), ("https://www.instagram.com/_u/fulano/", "fulano")],
)
def test_app_deep_links_resolve_to_the_profile(raw, expected):
    from services.handles import normalize_username

    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", [".", "..", "a..b", "abc."])
def test_dot_only_or_invalid_dot_usernames_are_rejected(raw):
    from services.handles import normalize_username

    with pytest.raises(ValueError):
        normalize_username(raw)


def test_follow_exactly_seven_days_old_is_not_stale(db):
    from services import follows

    follows.add_follow(db, {"username": "sete", "followed_at": TODAY - timedelta(days=7)})
    follows.add_follow(db, {"username": "oito", "followed_at": TODAY - timedelta(days=8)})
    stale = follows.summary(follows.list_follows(db), TODAY)["stale_pending"]
    assert [r["username"] for r in stale] == ["oito"]


def test_full_export_keeps_headers_and_integers(db, storage):
    from services import data_management

    metrics_log.upsert_metric(db, {"date": "2026-10-01", "followers": 69, "following": 180})
    metrics_log.upsert_metric(db, {"date": "2026-10-02", "followers": 70})
    with zipfile.ZipFile(io.BytesIO(data_management.export_all_zip(db, storage))) as zf:
        metrics = zf.read("csv/metrics.csv").decode("utf-8-sig")
        feed_items = zf.read("csv/feed_items.csv").decode("utf-8-sig")
    assert '"180"' in metrics and "180,0" not in metrics
    assert feed_items.strip() == '"version_id";"position";"image_id";"pinned"'
    exported = csv_io.to_csv_bytes(metrics_log.export_dataframe(metrics_log.list_metrics(db))).decode("utf-8-sig")
    assert "180,0" not in exported


def test_apply_pins_keeps_fixed_positions():
    seq, pins = fp.apply_pins([1, 2, 4, 5, 6], {3: 2})  # a foto 3 saiu; nenhuma fixada some
    assert pins == {} and seq == [1, 2, 4, 5, 6]
    seq, pins = fp.apply_pins([2, 3, 4, 5], {3: 2})  # a foto 1 saiu: a fixada 3 fica na posição 3
    assert seq[2] == 3 and pins == {3: 2}
    seq, pins = fp.apply_pins([2, 3], {3: 5})  # posição além do tamanho: fixação descartada
    assert seq == [2, 3] and pins == {}


def test_pinned_photo_stays_when_an_earlier_photo_is_removed(feed_app):
    at = _run("views/organizador_feed.py")
    _button(at, "Gerar sugestão").click()
    at.run()
    third = at.session_state["feed_draft"]["sequence"][2]
    at.button(key="p_2").click()
    at.run()
    at.button(key="x_0").click()  # tira a primeira foto
    at.run()
    assert not at.exception
    assert at.session_state["feed_draft"]["sequence"][2] == third
    assert at.session_state["feed_draft"]["pins"] == {third: 2}
    assert at.button(key="l_2").disabled and at.button(key="r_2").disabled


def test_profile_ctas_and_highlights_are_copyable(app_data_dir):
    from database.settings import save_profile

    db = Database(app_data_dir / "growth_tool.sqlite3")
    db.initialize()
    save_profile(db, {"activities": "natação, futevôlei", "interests": "viagens"})
    at = _run("views/meu_perfil.py")
    codes = [c.value for c in at.code]
    from services.profile_suggestions import CTAS

    assert all(cta in codes for group in CTAS["pt"].values() for cta in group)
    assert any("Natação" in c and "\n" in c for c in codes)  # lista de destaques para copiar
