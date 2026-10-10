"""Crescimento, projeções de metas e importação/exportação CSV."""

from datetime import date, timedelta

import pandas as pd
import pytest

from services import csv_io, growth, metrics_log

TODAY = date(2026, 10, 10)


def make_df(values, step_days=7, end=TODAY):
    n = len(values)
    rows = [{"id": i, "date": (end - timedelta(days=step_days * (n - 1 - i))).isoformat(), "followers": v}
            for i, v in enumerate(values)]
    return growth.metrics_dataframe(rows)


def test_net_gain_and_percent():
    assert growth.net_gain(69, 80) == 11
    assert growth.net_gain(80, 69) == -11
    assert growth.growth_percent(100, 110) == pytest.approx(10)
    assert growth.growth_percent(0, 10) is None
    assert growth.engagement_rate(50, 1000) == pytest.approx(5)
    assert growth.engagement_rate(50, 0) is None
    assert growth.engagement_rate(None, 100) is None


def test_period_summary_uses_baseline_before_window():
    df = make_df([60, 69, 75, 80])  # datas: -21, -14, -7, 0
    s = growth.period_summary(df, 14, TODAY)
    assert s.start_followers == 69 and s.current_followers == 80
    assert s.net_gain == 11 and s.avg_daily_gain == pytest.approx(11 / 14)
    whole = growth.period_summary(df, None, TODAY)
    assert whole.net_gain == 20 and whole.records == 4
    assert growth.period_summary(growth.metrics_dataframe([]), 30, TODAY).net_gain is None


def test_period_summary_negative_growth():
    s = growth.period_summary(make_df([100, 90]), 30, TODAY)
    assert s.net_gain == -10 and s.growth_pct == pytest.approx(-10)


def test_weekly_and_monthly_tables():
    df = make_df([69, 70, 68, 75, 81], step_days=7)
    weekly = growth.weekly_table(df)
    assert list(weekly["seguidores"]) == [69, 70, 68, 75, 81]
    assert pd.isna(weekly.loc[0, "ganho_liquido"])
    assert list(weekly["ganho_liquido"][1:]) == [1, -2, 7, 6]
    monthly = growth.monthly_table(df)
    assert monthly["seguidores"].iloc[-1] == 81
    assert growth.weekly_table(growth.metrics_dataframe([])).empty


def test_average_daily_gain():
    df = make_df([60, 70, 80, 90], step_days=10)
    assert growth.average_daily_gain(df) == pytest.approx(1.0)
    assert growth.average_daily_gain(df, window_days=10) == pytest.approx(1.0)
    assert growth.average_daily_gain(make_df([60])) is None


def test_days_to_goal():
    assert growth.days_to_goal(69, 1000, 5) == 187  # ceil(931 / 5)
    assert growth.days_to_goal(1000, 1000, 0) == 0
    assert growth.days_to_goal(69, 1000, 0) is None
    assert growth.days_to_goal(69, 1000, -2) is None
    assert growth.days_to_goal(69, 1000, 0.1) is None  # passaria do horizonte de 5 anos
    faster = growth.days_to_goal(69, 1000, 2, monthly_change=0.10)
    assert faster is not None and faster < growth.days_to_goal(69, 1000, 2)
    assert growth.days_to_goal(69, 1000, 2, monthly_change=-0.5) is None


def test_scenarios_order_even_with_negative_rate():
    rates = growth.scenario_rates(2.0, 0.5)
    assert rates == {"conservador": 1.0, "intermediario": 2.0, "otimista": 3.0}
    neg = growth.scenario_rates(-2.0, 0.5)
    assert neg["conservador"] < neg["intermediario"] < neg["otimista"]
    scenarios = growth.build_scenarios(69, 1000, 2.0, TODAY)
    assert [s.key for s in scenarios] == ["conservador", "intermediario", "otimista"]
    inter = scenarios[1]
    assert inter.days == 466 and inter.reach_date == TODAY + timedelta(days=466)
    assert inter.weekly_rate == 14


def test_projection_series_never_negative():
    series = growth.projection_series(10, -1, 0, 30)
    assert len(series) == 31 and series[0] == 10 and min(series) == 0


def test_required_rate_and_milestones():
    assert growth.required_daily_rate(69, 1000, 365) == pytest.approx(931 / 365)
    assert growth.required_daily_rate(1200, 1000, 30) == 0
    with pytest.raises(ValueError):
        growth.required_daily_rate(69, 1000, 0)
    assert growth.milestones(69, 1000) == [100, 250, 500, 750, 1000]
    assert growth.milestones(69, 3000)[-1] == 3000
    assert growth.milestones(1000, 900) == []


# --- CSV ----------------------------------------------------------------------------------------------


def test_import_portuguese_semicolon_csv(db):
    data = "data;seguidores;seguindo;alcance;observações\n01/10/2026;69;180;1.234;primeira\n08/10/2026;74;;;\n"
    report = csv_io.import_metrics_csv(db, data.encode("utf-8"))
    assert (report.inserted, report.updated, report.errors) == (2, 0, [])
    rows = metrics_log.list_metrics(db)
    assert rows[0]["date"] == "2026-10-01" and rows[0]["reach"] == 1234 and rows[0]["notes"] == "primeira"
    assert rows[1]["following"] is None and rows[1]["source"] == "csv"


def test_import_english_headers_and_errors(db):
    data = (
        "Date,Followers,Reach\n"
        "2026-10-01,69,300\n"
        "2026-13-01,70,300\n"     # data inválida
        "2026-10-03,-5,300\n"     # negativo
        "2026-10-04,abc,300\n"    # não numérico
        "2026-10-05,72,\n"
    )
    report = csv_io.import_metrics_csv(db, data.encode())
    assert report.inserted == 2 and len(report.errors) == 3
    assert report.errors[0].startswith("Linha 3")
    assert report.ok


def test_import_overwrite_and_skip(db):
    csv_io.import_metrics_csv(db, b"data,seguidores\n2026-10-01,69\n")
    report = csv_io.import_metrics_csv(db, b"data,seguidores\n2026-10-01,70\n", overwrite=False)
    assert report.skipped == 1 and metrics_log.list_metrics(db)[0]["followers"] == 69
    report = csv_io.import_metrics_csv(db, b"data,seguidores\n2026-10-01,71\n2026-10-01,72\n")
    assert report.updated == 1 and metrics_log.list_metrics(db)[0]["followers"] == 72


def test_import_rejects_bad_files(db):
    with pytest.raises(ValueError, match="obrigatórias"):
        csv_io.import_metrics_csv(db, b"dia_errado,valor\n1,2\n")
    with pytest.raises(ValueError, match="vazio"):
        csv_io.import_metrics_csv(db, b"   ")
    with pytest.raises(ValueError, match="MB"):
        csv_io.import_metrics_csv(db, b"a" * (3 * 1024 * 1024))


def test_export_import_roundtrip(db, tmp_path):
    from database import Database

    metrics_log.upsert_metric(db, {"date": date(2026, 10, 1), "followers": 69, "reach": 500, "notes": "=HYPERLINK()"})
    metrics_log.upsert_metric(db, {"date": date(2026, 10, 8), "followers": 75, "interactions": 40})
    exported = csv_io.to_csv_bytes(metrics_log.export_dataframe(metrics_log.list_metrics(db)))
    assert exported.startswith(b"\xef\xbb\xbf")  # BOM para o Excel
    assert b"'=HYPERLINK()" in exported  # proteção contra CSV injection

    other = Database(tmp_path / "other.sqlite3")
    other.initialize()
    report = csv_io.import_metrics_csv(other, exported)
    assert report.inserted == 2 and not report.errors
    rows = metrics_log.list_metrics(other)
    assert [r["followers"] for r in rows] == [69, 75] and rows[0]["reach"] == 500
    assert rows[1]["interactions"] == 40


def test_template_is_importable(db):
    report = csv_io.import_metrics_csv(db, csv_io.metrics_template_csv())
    assert report.inserted == 2 and not report.errors


def test_parse_helpers():
    assert csv_io.parse_count("1.234") == 1234
    assert csv_io.parse_count("1,234") == 1234
    assert csv_io.parse_count("") is None
    assert csv_io.parse_count("12.0") == 12
    with pytest.raises(ValueError):
        csv_io.parse_count("1.5")
    assert csv_io.parse_date("31/12/2026") == date(2026, 12, 31)
    with pytest.raises(ValueError):
        csv_io.parse_date("ontem")
