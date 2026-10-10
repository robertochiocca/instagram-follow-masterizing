"""Dashboard de crescimento: indicadores, histórico, registro de métricas e simulador de metas."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from config import today
from database.settings import get_profile, get_setting, set_setting
from services import csv_io, growth, metrics_log
from ui import charts
from ui.components import (
    confirm_button,
    data_badge,
    done,
    metric_grid,
    empty_state,
    fmt_date,
    fmt_int,
    fmt_num,
    page_header,
)
from ui.state import get_db

db = get_db()
page_header(
    "Dashboard",
    "Acompanhe seus números reais e simule metas. Projeções são estimativas, nunca garantias.",
)

rows = metrics_log.list_metrics(db)
df = growth.metrics_dataframe(rows)
profile = get_profile(db)
target = int(get_setting(db, "target_followers") or 1000)
day = today()

# --- Indicadores ------------------------------------------------------------------

if df.empty:
    empty_state(
        "Nenhuma métrica registrada ainda",
        "Registre hoje quantos seguidores você tem (seção “Registrar métricas” abaixo) ou importe "
        "um CSV. Com dois ou mais registros em datas diferentes, o dashboard calcula ganho "
        "líquido, crescimento e ritmo médio.",
        icon="📈",
    )
else:
    period_label = st.segmented_control(
        "Período",
        ["7 dias", "30 dias", "90 dias", "Tudo"],
        default="30 dias",
        key="dash_period",
    ) or "30 dias"
    days = {"7 dias": 7, "30 dias": 30, "90 dias": 90, "Tudo": None}[period_label]
    summary = growth.period_summary(df, days, day)
    last = df.iloc[-1]

    data_badge(estimate=False)
    metric_grid([
        ("Seguidores atuais", fmt_int(summary.current_followers),
         f"Último registro: {fmt_date(last['date'].date())}"),
        ("Meta", fmt_int(target)),
        ("Ganho líquido", fmt_int(summary.net_gain) if summary.net_gain is not None else "—",
         "Seguidores no fim do período − seguidores no início (pode ser negativo)."),
        ("Crescimento", fmt_num(summary.growth_pct, 1, "%") if summary.growth_pct is not None else "—",
         "Ganho líquido ÷ seguidores no início do período × 100."),
    ])
    if summary.start_date:
        st.caption(
            f"Período comparado: {fmt_date(summary.start_date)} → {fmt_date(summary.end_date)}"
            + (f" · ritmo médio {fmt_num(summary.avg_daily_gain, 2)} seguidores/dia"
               if summary.avg_daily_gain is not None else "")
        )
    progress = min(1.0, max(0.0, (summary.current_followers or 0) / target)) if target else 0
    st.progress(progress, text=f"{progress:.0%} da meta de {fmt_int(target)} seguidores")

    rate = growth.engagement_rate(last["interactions"], last["reach"])
    metric_grid([
        ("Novos posts",
         fmt_int(summary.posts_published) if summary.posts_published is not None else "—",
         "Diferença no total de publicações informado no período."),
        ("Alcance", fmt_int(last["reach"]), "Contas alcançadas (último registro)."),
        ("Visualizações", fmt_int(last["views"]), "Último registro."),
        ("Visitas ao perfil", fmt_int(last["profile_visits"]), "Último registro."),
        ("Engajamento", fmt_num(rate, 1, "%") if rate is not None else "—",
         "Interações ÷ contas alcançadas × 100 (precisa dos dois valores)."),
    ])

    st.subheader("Evolução de seguidores")
    if len(df) >= 2:
        st.altair_chart(charts.followers_chart(df, target), width="stretch")
    else:
        st.info("Registre pelo menos mais um dia para ver o gráfico de evolução.")

    weekly = growth.weekly_table(df)
    monthly = growth.monthly_table(df)
    tab_w, tab_m = st.tabs(["Semanal", "Mensal"])
    column_config = {
        "seguidores": st.column_config.NumberColumn("Seguidores", format="%d"),
        "ganho_liquido": st.column_config.NumberColumn("Ganho líquido", format="%+d"),
        "crescimento_pct": st.column_config.NumberColumn("Cresc. %", format="%.2f%%"),
        "alcance": st.column_config.NumberColumn("Alcance", format="%d"),
        "visualizacoes": st.column_config.NumberColumn("Visualizações", format="%d"),
        "visitas_perfil": st.column_config.NumberColumn("Visitas", format="%d"),
        "engajamento_pct": st.column_config.NumberColumn("Engaj. %", format="%.2f%%"),
    }
    with tab_w:
        if weekly["ganho_liquido"].notna().any():
            st.altair_chart(charts.weekly_gain_chart(weekly), width="stretch")
        st.dataframe(
            weekly, hide_index=True, width="stretch", placeholder="—",
            column_config={"semana_ate": st.column_config.DateColumn("Semana até", format="DD/MM/YYYY"),
                           **column_config},
        )
        st.download_button("Exportar tabela semanal (CSV)", csv_io.to_csv_bytes(weekly),
                           "semanal.csv", "text/csv", icon=":material/download:")
    with tab_m:
        st.dataframe(
            monthly, hide_index=True, width="stretch", placeholder="—",
            column_config={"mes_ate": st.column_config.DateColumn("Mês até", format="DD/MM/YYYY"),
                           **column_config},
        )
        st.download_button("Exportar tabela mensal (CSV)", csv_io.to_csv_bytes(monthly),
                           "mensal.csv", "text/csv", icon=":material/download:")

# --- Registro manual e importação ------------------------------------------------------

st.divider()
st.subheader("Registrar métricas")
tab_form, tab_csv, tab_list = st.tabs(["Registro do dia", "Importar / exportar CSV", "Registros"])

with tab_form:
    st.caption(
        "Copie os números do app (Painel profissional → Insights). Use sempre o mesmo período "
        "para alcance e visualizações (recomendado: últimos 7 dias). Campos vazios ficam sem valor."
    )
    default_followers = int(df.iloc[-1]["followers"]) if not df.empty else int(profile.get("followers") or 0)
    with st.form("metric_form", clear_on_submit=False):
        a, b = st.columns(2)
        m_date = a.date_input("Data", value=day, max_value=day, format="DD/MM/YYYY")
        m_followers = b.number_input("Seguidores *", min_value=0, value=default_followers, step=1)
        a, b, c = st.columns(3)
        m_following = a.number_input("Seguindo", min_value=0, value=None, step=1)
        m_posts = b.number_input("Publicações (total)", min_value=0, value=None, step=1)
        m_reach = c.number_input("Contas alcançadas", min_value=0, value=None, step=1)
        a, b, c = st.columns(3)
        m_views = a.number_input("Visualizações", min_value=0, value=None, step=1)
        m_visits = b.number_input("Visitas ao perfil", min_value=0, value=None, step=1)
        m_inter = c.number_input("Interações", min_value=0, value=None, step=1)
        m_notes = st.text_input("Observações", max_chars=500)
        if st.form_submit_button("Salvar registro", type="primary", icon=":material/save:"):
            try:
                _, created = metrics_log.upsert_metric(db, {
                    "date": m_date, "followers": m_followers, "following": m_following,
                    "posts": m_posts, "reach": m_reach, "views": m_views,
                    "profile_visits": m_visits, "interactions": m_inter, "notes": m_notes,
                })
            except ValueError as exc:
                st.error(str(exc))
            else:
                done("Registro salvo." if created else "Registro da data atualizado.")

with tab_csv:
    st.markdown(
        "Colunas aceitas: **data** e **seguidores** (obrigatórias), seguindo, publicacoes, "
        "alcance, visualizacoes, visitas_perfil, interacoes, observacoes. Separador vírgula ou "
        "ponto e vírgula; datas AAAA-MM-DD ou DD/MM/AAAA."
    )
    st.download_button("Baixar modelo de CSV", csv_io.metrics_template_csv(), "modelo_metricas.csv",
                       "text/csv", icon=":material/description:")
    uploaded = st.file_uploader("Arquivo CSV", type=["csv"], key="metrics_csv")
    overwrite = st.checkbox("Substituir registros de datas que já existem", value=True)
    if uploaded is not None and st.button("Importar CSV", type="primary", icon=":material/upload:"):
        try:
            report = csv_io.import_metrics_csv(db, uploaded.getvalue(), overwrite=overwrite)
        except ValueError as exc:
            st.error(str(exc))
        else:
            msg = f"Importação: {report.inserted} novos, {report.updated} atualizados, {report.skipped} ignorados."
            if report.errors:
                st.warning(msg + f" {len(report.errors)} linha(s) com erro:")
                st.write("\n".join(f"- {e}" for e in report.errors[:20]))
            else:
                done(msg)
    if rows:
        st.download_button(
            "Exportar todas as métricas (CSV)",
            csv_io.to_csv_bytes(metrics_log.export_dataframe(rows)),
            "metricas.csv", "text/csv", icon=":material/download:",
        )

with tab_list:
    if not rows:
        st.caption("Nenhum registro.")
    for r in reversed(rows[-60:]):
        with st.container(border=True):
            a, b = st.columns([3, 1], vertical_alignment="center", wrap=False)
            extras = [f"{lbl} {fmt_int(r[k])}" for k, lbl in
                      (("reach", "alcance"), ("views", "visualizações"), ("profile_visits", "visitas"))
                      if r.get(k) is not None]
            a.markdown(f"**{fmt_date(r['date'])}** · {fmt_int(r['followers'])} seguidores"
                       + (" · " + " · ".join(extras) if extras else "")
                       + (" · _importado_" if r["source"] == "csv" else ""))
            with b:
                if confirm_button("Excluir", f"del_metric_{r['id']}", "Excluir este registro?"):
                    metrics_log.delete_metric(db, r["id"])
                    done("Registro excluído.")

# --- Simulador de metas ------------------------------------------------------------------

st.divider()
st.subheader("Simulador de metas")
data_badge(estimate=True)
st.caption(
    "Crescimento orgânico oscila: há semanas sem ganho e até com perda. Use os cenários para "
    "planejar, não como promessa."
)

hist_rate = growth.average_daily_gain(df, window_days=30) if not df.empty else None
current_default = (
    int(df.iloc[-1]["followers"]) if not df.empty else int(profile.get("followers") or 69)
)
a, b = st.columns(2)
sim_current = a.number_input("Seguidores atuais", min_value=0, value=current_default, step=1)
preset = b.segmented_control("Meta rápida", ["1.000", "3.000"], default=None, key="goal_preset")
goal_default = {"1.000": 1000, "3.000": 3000}.get(preset or "", target)
sim_target = b.number_input("Meta de seguidores", min_value=1, value=goal_default, step=50)
if sim_target != target and st.button("Salvar como minha meta", icon=":material/flag:"):
    set_setting(db, "target_followers", int(sim_target))
    done("Meta salva.")

a, b, c = st.columns(3)
rate_help = (
    f"Seu ritmo nos últimos 30 dias foi {fmt_num(hist_rate, 2)} por dia."
    if hist_rate is not None else "Sem histórico suficiente; informe uma estimativa."
)
base_rate = a.number_input(
    "Ganho líquido médio por dia", value=round(hist_rate, 2) if hist_rate is not None else 1.0,
    step=0.1, format="%.2f", help=rate_help,
)
margin = b.slider("Margem entre cenários (%)", 0, 100, 50, step=5,
                  help="Conservador = r − m·|r|; otimista = r + m·|r|.") / 100
monthly_change = c.slider("Variação mensal do ritmo (%)", -30, 30, 0, step=1,
                          help="Positivo: o ritmo acelera a cada mês; negativo: desacelera.") / 100

scenarios = growth.build_scenarios(sim_current, sim_target, base_rate, day, margin, monthly_change)
scenario_df = pd.DataFrame(
    [
        {
            "Cenário": s.label,
            "Seguidores/dia": round(s.daily_rate, 2),
            "Seguidores/semana": round(s.weekly_rate, 1),
            "Dias até a meta": s.days if s.days is not None else None,
            "Data estimada": fmt_date(s.reach_date) if s.reach_date else "Não atinge em 5 anos",
        }
        for s in scenarios
    ]
)
st.dataframe(scenario_df, hide_index=True, width="stretch", placeholder="—")
if base_rate <= 0:
    st.warning(
        "Com ritmo zero ou negativo a meta não é atingida. Veja no plano abaixo o ritmo necessário."
    )

reached = [s.days for s in scenarios if s.days]
horizon = min(730, max(60, int(max(reached) * 1.1))) if reached else 365
records = []
for s in scenarios:
    values = growth.projection_series(sim_current, s.daily_rate, monthly_change, horizon)
    step = max(1, horizon // 120)
    for d in range(0, horizon + 1, step):
        records.append({"Data": pd.Timestamp(day + timedelta(days=d)), "Cenário": s.label,
                        "Seguidores": values[d]})
proj = pd.DataFrame(records)
st.altair_chart(charts.projection_chart(proj, int(sim_target)), width="stretch")

with st.expander("Fórmulas usadas"):
    st.markdown(
        "- **Ritmo base** *r*: ganho líquido médio diário (histórico dos últimos 30 dias ou valor informado).\n"
        "- **Cenários** com margem *m*: conservador = r − m·|r|; intermediário = r; otimista = r + m·|r|.\n"
        "- **Sem variação mensal**: dias até a meta = ⌈(meta − atual) ÷ ritmo⌉ (só se o ritmo for positivo).\n"
        "- **Com variação mensal g**: no dia *d* o ganho é r·(1 + g)^(d/30), somado dia a dia até a meta "
        "(horizonte máximo de 5 anos).\n"
        "- **Ganho líquido** = novos seguidores − pessoas que deixaram de seguir. Pode ser negativo."
    )

st.markdown("#### Plano realista")
plan = []
for months in (3, 6, 12, 18):
    need = growth.required_daily_rate(sim_current, sim_target, months * 30)
    plan.append({"Prazo": f"{months} meses", "Seguidores/dia": round(need, 2),
                 "Seguidores/semana": round(need * 7, 1)})
st.dataframe(pd.DataFrame(plan), hide_index=True, width="stretch")
inter = next(s for s in scenarios if s.key == "intermediario")
marks = []
for m in growth.milestones(int(sim_current), int(sim_target)):
    d = growth.days_to_goal(sim_current, m, inter.daily_rate, monthly_change)
    marks.append({"Marco": fmt_int(m),
                  "Estimativa (cenário intermediário)": fmt_date(day + timedelta(days=d)) if d else "—"})
if marks:
    st.dataframe(pd.DataFrame(marks), hide_index=True, width="stretch")
st.caption(
    "Hábitos que costumam sustentar crescimento orgânico: publicar com regularidade (ex.: 2–3 "
    "vídeos curtos por semana), Stories frequentes, responder comentários, interagir de verdade "
    "com perfis do seu nicho e manter perfil claro (bio, destaques e grade coerente). Evite "
    "comprar seguidores, follow/unfollow em massa e automações — violam as regras do Instagram "
    "e prejudicam o alcance."
)
