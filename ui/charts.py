"""Gráficos Altair com estilo sóbrio (linhas finas, grade discreta, tooltip).

Paleta categórica validada para daltonismo (azul, laranja, aqua). Dados reais
usam linha contínua; estimativas usam linha tracejada e legenda explícita.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
POSITIVE, NEGATIVE = "#2a78d6", "#e34948"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
GOAL = "#52514e"


def _style(chart: alt.Chart, height: int = 280) -> alt.Chart:
    return (
        chart.properties(height=height, background="transparent")
        .configure_axis(
            gridColor=GRID,
            gridWidth=1,
            domainColor=AXIS,
            tickColor=AXIS,
            labelColor=INK_MUTED,
            titleColor=INK_MUTED,
            labelFontSize=12,
            titleFontSize=12,
        )
        .configure_view(strokeWidth=0)
        .configure_legend(orient="top", labelColor="#52514e", titleColor="#52514e", labelFontSize=12)
    )


def followers_chart(df: pd.DataFrame, target: int | None = None) -> alt.Chart:
    """Seguidores registrados ao longo do tempo (série única = sem legenda)."""
    data = df[["date", "followers"]].rename(columns={"date": "Data", "followers": "Seguidores"})
    base = alt.Chart(data).encode(
        x=alt.X("Data:T", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0)),
        y=alt.Y("Seguidores:Q", title="Seguidores", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("Data:T", format="%d/%m/%Y"), alt.Tooltip("Seguidores:Q", format=",d")],
    )
    line = base.mark_line(color=SERIES[0], strokeWidth=2, strokeCap="round", strokeJoin="round")
    points = base.mark_point(
        filled=True, size=70, color=SERIES[0], stroke="white", strokeWidth=2, opacity=1
    )
    last = data.tail(1)
    label = (
        alt.Chart(last)
        .mark_text(align="left", dx=8, dy=-8, color="#0b0b0b", fontSize=12)
        .encode(x="Data:T", y="Seguidores:Q", text=alt.Text("Seguidores:Q", format=",d"))
    )
    layers = [line, points, label]
    if target:
        rule = alt.Chart(pd.DataFrame({"Meta": [target]})).mark_rule(color=GOAL, strokeWidth=1)
        layers.append(rule.encode(y="Meta:Q", tooltip=[alt.Tooltip("Meta:Q", format=",d")]))
    return _style(alt.layer(*layers))


def projection_chart(projections: pd.DataFrame, target: int) -> alt.Chart:
    """Cenários projetados (colunas: Data, Cenário, Seguidores). Todas são estimativas."""
    order = ["Conservador", "Intermediário", "Otimista"]
    color = alt.Color(
        "Cenário:N",
        scale=alt.Scale(domain=order, range=SERIES),
        legend=alt.Legend(title="Estimativa por cenário"),
    )
    base = alt.Chart(projections).encode(
        x=alt.X("Data:T", title=None, axis=alt.Axis(format="%m/%Y", labelAngle=0)),
        y=alt.Y("Seguidores:Q", title="Seguidores (estimados)"),
        color=color,
        tooltip=[
            "Cenário:N",
            alt.Tooltip("Data:T", format="%d/%m/%Y"),
            alt.Tooltip("Seguidores:Q", format=",.0f"),
        ],
    )
    lines = base.mark_line(strokeWidth=2, strokeDash=[6, 4])
    ends = projections.sort_values("Data").groupby("Cenário", as_index=False).tail(1)
    end_points = (
        alt.Chart(ends)
        .mark_point(filled=True, size=70, stroke="white", strokeWidth=2, opacity=1)
        .encode(x="Data:T", y="Seguidores:Q", color=color)
    )
    end_labels = (
        alt.Chart(ends)
        .mark_text(align="left", dx=8, color="#52514e", fontSize=12)
        .encode(x="Data:T", y="Seguidores:Q", text="Cenário:N")
    )
    rule = (
        alt.Chart(pd.DataFrame({"Meta": [target]}))
        .mark_rule(color=GOAL, strokeWidth=1)
        .encode(y="Meta:Q", tooltip=[alt.Tooltip("Meta:Q", format=",d")])
    )
    return _style(alt.layer(lines, end_points, end_labels, rule), height=300)


def weekly_gain_chart(table: pd.DataFrame) -> alt.Chart:
    """Ganho líquido por semana: azul = ganho, vermelho = perda."""
    data = table.dropna(subset=["ganho_liquido"]).copy()
    data["Semana"] = pd.to_datetime(data["semana_ate"])
    data["Ganho"] = data["ganho_liquido"].astype(int)
    data["Sinal"] = data["Ganho"].map(lambda v: "Ganho" if v >= 0 else "Perda")
    chart = (
        alt.Chart(data)
        .mark_bar(size=18, cornerRadiusEnd=4)
        .encode(
            x=alt.X("Semana:T", title=None, axis=alt.Axis(format="%d/%m", labelAngle=0)),
            y=alt.Y("Ganho:Q", title="Seguidores líquidos"),
            color=alt.Color(
                "Sinal:N",
                scale=alt.Scale(domain=["Ganho", "Perda"], range=[POSITIVE, NEGATIVE]),
                legend=alt.Legend(title=None),
            ),
            tooltip=[alt.Tooltip("Semana:T", title="Semana até", format="%d/%m/%Y"), "Ganho:Q"],
        )
    )
    return _style(chart, height=220)
