"""Perfis de interesse, acompanhamento, métricas manuais e planejador de conteúdo."""

from datetime import date, timedelta

import pytest

from services import content_planner as cp
from services import follows, interests, metrics_log
from services.handles import normalize_url, normalize_username, parse_tags, profile_url

TODAY = date(2026, 10, 10)


# --- Nomes de usuário e URLs ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("@Joao.Silva", "joao.silva"),
        ("joao_silva", "joao_silva"),
        ("https://www.instagram.com/joao.silva/?igsh=abc", "joao.silva"),
        ("instagram.com/joao.silva", "joao.silva"),
        ("  @joao  ", "joao"),
    ],
)
def test_normalize_username(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize("raw", ["", "a b", "x" * 31, "joão", "https://instagram.com/p/ABC123/", "<script>"])
def test_invalid_usernames(raw):
    with pytest.raises(ValueError):
        normalize_username(raw)


def test_urls():
    assert normalize_url("") is None
    assert normalize_url("instagram.com/x") == "https://instagram.com/x"
    for bad in ["javascript:alert(1)", "ftp://x.com", "https://", "http://a b.com", "h" * 400]:
        with pytest.raises(ValueError):
            normalize_url(bad)
    assert profile_url("joao") == "https://www.instagram.com/joao/"
    assert profile_url("joao", "javascript:alert(1)") == "https://www.instagram.com/joao/"
    assert profile_url("joao", "https://example.com/joao") == "https://example.com/joao"
    assert parse_tags("#Praia, verão; praia\nmoda") == ["praia", "verão", "moda"]


# --- Perfis de interesse ------------------------------------------------------------------------------


def test_interest_crud_search_filter_sort(db):
    a = interests.add_interest(db, {"username": "@alpha", "category": "Viagens", "priority": "baixa",
                                    "reason": "Fotos de arquitetura", "tags": "europa, cidade", "added_at": date(2026, 1, 1)})
    b = interests.add_interest(db, {"username": "beta", "category": "Fotografia", "priority": "alta",
                                    "status": "interessante", "added_at": date(2026, 2, 1)})
    with pytest.raises(ValueError, match="já está"):
        interests.add_interest(db, {"username": "ALPHA"})
    with pytest.raises(ValueError):
        interests.add_interest(db, {"username": "ok", "priority": "urgente"})

    assert [r["username"] for r in interests.list_interests(db)] == ["beta", "alpha"]
    assert [r["username"] for r in interests.list_interests(db, sort="prioridade")] == ["beta", "alpha"]
    assert [r["username"] for r in interests.list_interests(db, sort="usuario")] == ["alpha", "beta"]
    assert [r["username"] for r in interests.list_interests(db, search="arquitetura")] == ["alpha"]
    assert [r["username"] for r in interests.list_interests(db, search="europa")] == ["alpha"]
    assert [r["username"] for r in interests.list_interests(db, categories=["Fotografia"])] == ["beta"]
    assert [r["username"] for r in interests.list_interests(db, tag="cidade")] == ["alpha"]
    assert interests.all_tags(db) == ["cidade", "europa"]

    interests.update_interest(db, a, {"notes": "rever", "url": "instagram.com/alpha"})
    assert interests.get_interest(db, a)["url"] == "https://instagram.com/alpha"
    interests.set_status(db, a, "arquivado")
    assert [r["username"] for r in interests.list_interests(db, statuses=["novo", "revisar", "interessante"])] == ["beta"]
    with pytest.raises(ValueError):
        interests.update_interest(db, a, {"username": "beta"})

    df = interests.to_dataframe(interests.list_interests(db))
    assert list(df["status"]) == ["Interessante", "Arquivado"]
    assert interests.delete_interest(db, b)
    assert len(interests.list_interests(db)) == 1


# --- Acompanhamento -------------------------------------------------------------------------------------


def test_follow_tracking_flow(db):
    a = follows.add_follow(db, {"username": "@um", "followed_at": TODAY - timedelta(days=20)})
    b = follows.add_follow(db, {"username": "dois", "followed_at": TODAY - timedelta(days=2), "status": "seguiu_de_volta"})
    c = follows.add_follow(db, {"username": "tres", "followed_at": TODAY - timedelta(days=40), "status": "nao_seguiu_de_volta"})
    with pytest.raises(ValueError):
        follows.add_follow(db, {"username": "x", "status": "automatico"})

    stats = follows.summary(follows.list_follows(db), TODAY)
    assert stats["counts"]["pendente"] == 1
    assert stats["followback_rate"] == pytest.approx(50)
    assert [r["username"] for r in stats["stale_pending"]] == ["um"]
    assert stats["followed_last_7_days"] == 1

    follows.mark_reviewed(db, a, "seguiu_de_volta")
    row = follows.get_follow(db, a)
    assert row["status"] == "seguiu_de_volta" and row["last_reviewed_at"]

    recent = follows.list_follows(db, start=TODAY - timedelta(days=30), end=TODAY)
    assert {r["username"] for r in recent} == {"um", "dois"}
    assert [r["username"] for r in follows.list_follows(db, statuses=["nao_seguiu_de_volta"])] == ["tres"]

    follows.set_archived(db, c)
    assert "tres" not in {r["username"] for r in follows.list_follows(db)}
    assert "tres" in {r["username"] for r in follows.list_follows(db, include_archived=True)}
    assert follows.to_dataframe(follows.list_follows(db, include_archived=True)).shape[0] == 3
    assert follows.delete_follow(db, b) and follows.get_follow(db, b) is None
    assert follows.summary([], TODAY)["followback_rate"] is None


# --- Métricas manuais ------------------------------------------------------------------------------------


def test_metric_upsert_and_delete(db):
    mid, created = metrics_log.upsert_metric(db, {"date": TODAY, "followers": 69, "reach": ""})
    assert created
    mid2, created = metrics_log.upsert_metric(db, {"date": TODAY, "followers": 70})
    assert mid2 == mid and not created
    assert metrics_log.list_metrics(db)[0]["followers"] == 70
    with pytest.raises(ValueError):
        metrics_log.upsert_metric(db, {"date": TODAY, "followers": -1})
    with pytest.raises(ValueError):
        metrics_log.upsert_metric(db, {"date": TODAY, "followers": 1, "reach": -3})
    with pytest.raises(ValueError):
        metrics_log.upsert_metric(db, {"followers": 1})
    assert metrics_log.delete_metric(db, mid)
    assert metrics_log.list_metrics(db) == []


# --- Planejador de conteúdo ------------------------------------------------------------------------------


def test_content_crud_and_publish(db):
    item = cp.add_item(db, {"planned_date": TODAY, "content_type": "reels", "theme": "Praia"})
    with pytest.raises(ValueError):
        cp.add_item(db, {"planned_date": TODAY, "content_type": "tiktok"})
    with pytest.raises(ValueError):
        cp.add_item(db, {"content_type": "reels"})
    cp.update_item(db, item, {"status": "publicado"})
    row = cp.get_item(db, item)
    assert row["status"] == "publicado" and row["published_date"] == TODAY.isoformat()
    cp.update_item(db, item, {"reach": 400, "likes": 30, "comments": 5, "saves": 3, "shares": 2, "follows_gained": 4})
    row = cp.get_item(db, item)
    assert cp.interactions(row) == 40 and cp.engagement(row) == pytest.approx(10)
    assert cp.published_since(db, TODAY - timedelta(days=14)) == 1
    with pytest.raises(ValueError):
        cp.update_item(db, item, {"likes": -1})
    assert cp.delete_item(db, item) and cp.list_items(db) == []


def test_generate_schedule_respects_frequency():
    freq = {"reels": 2, "carrossel": 1, "foto": 0, "stories": 3, "weekdays": ["Ter", "Qui", "Sáb"]}
    monday = date(2026, 10, 12)
    items = cp.generate_schedule(monday, 2, freq, ["Praia", "Esporte"])
    feed = [i for i in items if i["content_type"] != "stories"]
    stories = [i for i in items if i["content_type"] == "stories"]
    assert len(feed) == 6 and len(stories) == 6
    assert {i["planned_date"].weekday() for i in feed} == {1, 3, 5}
    assert all(i["planned_date"].weekday() not in {1, 3, 5} for i in stories)
    assert [i["content_type"] for i in feed[:3]] == ["reels", "carrossel", "reels"]
    assert {i["theme"] for i in items} == {"Praia", "Esporte"}
    assert all(i["planned_date"] >= monday for i in items)
    mid_week = cp.generate_schedule(date(2026, 10, 15), 1, freq, [])  # quinta: dias anteriores ignorados
    assert all(i["planned_date"] >= date(2026, 10, 15) for i in mid_week)


def test_frequency_warnings():
    assert cp.frequency_warnings({"reels": 2, "carrossel": 1, "stories": 3, "weekdays": ["Ter"]}) == []
    assert cp.frequency_warnings({"reels": 0, "weekdays": ["Ter"]})
    assert any("Mais de uma" in w for w in cp.frequency_warnings({"reels": 6, "carrossel": 3, "weekdays": ["Ter"]}))
    assert any("dia da semana" in w for w in cp.frequency_warnings({"reels": 1, "weekdays": []}))


def test_results_tables(db):
    for theme, reach, likes in [("Praia", 1000, 100), ("Praia", 500, 25), ("Esporte", 400, 20)]:
        iid = cp.add_item(db, {"planned_date": TODAY, "content_type": "reels", "theme": theme, "status": "publicado"})
        cp.update_item(db, iid, {"reach": reach, "likes": likes})
    cp.add_item(db, {"planned_date": TODAY, "content_type": "foto", "theme": "Ideia"})
    items = cp.list_items(db)
    table = cp.results_table(items)
    assert len(table) == 3
    assert list(table["engajamento_pct"]) == [10.0, 5.0, 5.0]
    assert table["vs_media_pp"].iloc[0] == pytest.approx(10 - 20 / 3, abs=0.01)
    by_theme = cp.best_groups(items, "tema")
    assert by_theme.iloc[0]["tema"] == "Praia" and by_theme.iloc[0]["publicacoes"] == 2
    assert len(cp.to_dataframe(items)) == 4
    assert cp.list_items(db, statuses=["ideia"])[0]["theme"] == "Ideia"
