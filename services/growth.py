"""Métricas de crescimento, projeções de meta e simulação de cenários.

Fórmulas (exibidas também na interface):

- Ganho líquido no período = seguidores no fim − seguidores no início.
- Crescimento % = ganho líquido / seguidores no início × 100.
- Ganho médio diário = ganho líquido / dias entre os dois registros.
- Engajamento sobre alcance = interações / contas alcançadas × 100.
- Cenários, a partir do ritmo base r (seguidores líquidos/dia) e da margem m:
    conservador r_c = r − m·|r|;  intermediário r_i = r;  otimista r_o = r + m·|r|.
- Variação mensal do ritmo g: no dia d o ritmo é r·(1 + g)^(d/30). Os
  seguidores são acumulados dia a dia até atingir a meta ou o horizonte.
Projeções são estimativas, nunca garantias.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

MAX_HORIZON_DAYS = 5 * 365
METRIC_COLUMNS = [
    "followers",
    "following",
    "posts",
    "reach",
    "views",
    "profile_visits",
    "interactions",
]


def metrics_dataframe(rows: list[dict]) -> pd.DataFrame:
    """Registros de métricas como DataFrame ordenado por data (coluna `date` datetime)."""
    columns = ["id", "date", *METRIC_COLUMNS, "source", "notes"]
    df = pd.DataFrame(rows or [], columns=columns)
    if df.empty:
        df["date"] = pd.to_datetime(df["date"])
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for col in METRIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def net_gain(start_followers: float, end_followers: float) -> int:
    return int(end_followers - start_followers)


def growth_percent(start_followers: float, end_followers: float) -> float | None:
    if not start_followers:
        return None
    return (end_followers - start_followers) / start_followers * 100


def engagement_rate(interactions: float | None, reach: float | None) -> float | None:
    if interactions is None or reach is None or pd.isna(interactions) or pd.isna(reach) or reach <= 0:
        return None
    return float(interactions) / float(reach) * 100


@dataclass
class PeriodSummary:
    start_date: date | None
    end_date: date | None
    start_followers: int | None
    current_followers: int | None
    net_gain: int | None
    growth_pct: float | None
    avg_daily_gain: float | None
    posts_published: int | None
    records: int


def period_summary(df: pd.DataFrame, days: int | None, today: date) -> PeriodSummary:
    """Resumo do período [hoje − days, hoje]; `days=None` usa todo o histórico.

    A base é o último registro até o início do período (ou o primeiro dentro
    dele), para que o ganho reflita o período inteiro. Sem dois registros
    distintos para comparar, ganho, crescimento e ritmo ficam vazios (None) em
    vez de mostrar um falso “0”.
    """
    empty = PeriodSummary(None, None, None, None, None, None, None, None, 0)
    if df.empty:
        return empty
    end_ts = pd.Timestamp(today)
    data = df[df["date"] <= end_ts]
    if data.empty:
        return empty
    last = data.iloc[-1]
    if days is None:
        base = data.iloc[0]
        window = data
    else:
        start_ts = end_ts - pd.Timedelta(days=days)
        before = data[data["date"] <= start_ts]
        window = data[data["date"] > start_ts]
        if window.empty:  # nenhum registro novo no período
            return PeriodSummary(None, last["date"].date(), None, int(last["followers"]),
                                 None, None, None, None, 0)
        base = before.iloc[-1] if not before.empty else window.iloc[0]
    span = (last["date"] - base["date"]).days
    if span <= 0:  # só um registro: não há com o que comparar
        return PeriodSummary(base["date"].date(), last["date"].date(), int(base["followers"]),
                             int(last["followers"]), None, None, None, None, len(window))
    gain = net_gain(base["followers"], last["followers"])
    posts = None
    if pd.notna(base.get("posts")) and pd.notna(last.get("posts")):
        posts = int(last["posts"] - base["posts"])
    return PeriodSummary(
        start_date=base["date"].date(),
        end_date=last["date"].date(),
        start_followers=int(base["followers"]),
        current_followers=int(last["followers"]),
        net_gain=gain,
        growth_pct=growth_percent(base["followers"], last["followers"]),
        avg_daily_gain=gain / span,
        posts_published=posts,
        records=len(window),
    )


def _period_table(df: pd.DataFrame, freq: str, label: str, gap_label: str) -> pd.DataFrame:
    """Último valor de cada período com registro.

    Quando há períodos sem registro entre duas linhas, o ganho acumulado é
    mostrado junto com o intervalo (`gap_label`) e a média por período, para não
    atribuir várias semanas/meses de crescimento a um só.
    """
    columns = [label, "seguidores", "ganho_liquido", gap_label, "ganho_medio_periodo", "crescimento_pct",
               "alcance", "visualizacoes", "visitas_perfil", "engajamento_pct"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    full = df.set_index("date").resample(freq).agg(
        {
            "followers": "last",
            "reach": "last",
            "views": "last",
            "profile_visits": "last",
            "interactions": "last",
        }
    )
    present = full["followers"].notna().to_numpy()
    positions = pd.Series(range(len(full)), dtype="float64")[present].to_numpy()
    agg = full[present]
    prev = agg["followers"].shift(1)
    gain = agg["followers"] - prev
    gaps = pd.Series(positions).diff().to_numpy()
    out = pd.DataFrame(
        {
            label: agg.index.date,
            "seguidores": agg["followers"].astype(int).values,
            "ganho_liquido": gain.values,
            gap_label: gaps,
            "ganho_medio_periodo": (gain.values / gaps).round(2),
            # Base zero não tem crescimento percentual definido (fica vazio, como nos cartões).
            "crescimento_pct": (gain / prev.where(prev > 0) * 100).round(2).values,
            "alcance": agg["reach"].values,
            "visualizacoes": agg["views"].values,
            "visitas_perfil": agg["profile_visits"].values,
            "engajamento_pct": [
                engagement_rate(i, r) for i, r in zip(agg["interactions"], agg["reach"])
            ],
        },
        columns=columns,
    )
    out["engajamento_pct"] = pd.to_numeric(out["engajamento_pct"]).round(2)
    return out.reset_index(drop=True)


def weekly_table(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por semana com registro (rótulo = domingo de fechamento)."""
    return _period_table(df, "W-SUN", "semana_ate", "semanas_desde_anterior")


def monthly_table(df: pd.DataFrame) -> pd.DataFrame:
    return _period_table(df, "ME", "mes_ate", "meses_desde_anterior")


def average_daily_gain(
    df: pd.DataFrame, window_days: int | None = None, today: date | None = None
) -> float | None:
    """Ganho líquido médio por dia.

    Com `window_days`, considera a janela que termina em `today` (ou no último
    registro, se `today` não for informado) e exige ao menos um registro dentro
    dela; registros antigos sozinhos não produzem um “ritmo atual”.
    """
    if len(df) < 2:
        return None
    data = df
    if window_days:
        anchor = pd.Timestamp(today) if today else df["date"].iloc[-1]
        start = anchor - pd.Timedelta(days=window_days)
        inside = df[(df["date"] > start) & (df["date"] <= anchor)]
        if inside.empty:
            return None
        before = df[df["date"] <= start]
        data = pd.concat([before.tail(1), inside])
    if len(data) < 2:
        return None
    span = (data["date"].iloc[-1] - data["date"].iloc[0]).days
    if span <= 0:
        return None
    return float(data["followers"].iloc[-1] - data["followers"].iloc[0]) / span


# --- Projeções ---------------------------------------------------------------------


def days_to_goal(
    current: float,
    target: float,
    daily_rate: float,
    monthly_change: float = 0.0,
    max_days: int = MAX_HORIZON_DAYS,
) -> int | None:
    """Dias até a meta, ou None se não for atingida no horizonte.

    Sem variação mensal: d = ⌈(meta − atual) / r⌉ (apenas se r > 0).
    Com variação g: acumula r·(1+g)^(d/30) dia a dia.
    """
    if current >= target:
        return 0
    if monthly_change == 0:
        if daily_rate <= 0:
            return None
        # round() evita erros de ponto flutuante (21 / 0,35 = 60,000000000000014).
        days = math.ceil(round((target - current) / daily_rate, 9))
        return days if days <= max_days else None
    followers = float(current)
    for day in range(1, max_days + 1):
        followers += daily_rate * (1 + monthly_change) ** (day / 30)
        if followers >= target:
            return day
    return None


def projection_series(
    current: float, daily_rate: float, monthly_change: float, days: int
) -> list[float]:
    """Seguidores projetados para os dias 0..days (nunca abaixo de zero)."""
    values = [float(current)]
    followers = float(current)
    for day in range(1, days + 1):
        followers = max(0.0, followers + daily_rate * (1 + monthly_change) ** (day / 30))
        values.append(followers)
    return values


@dataclass
class Scenario:
    key: str
    label: str
    daily_rate: float
    days: int | None
    reach_date: date | None

    @property
    def weekly_rate(self) -> float:
        return self.daily_rate * 7


SCENARIO_LABELS = {
    "conservador": "Conservador",
    "intermediario": "Intermediário",
    "otimista": "Otimista",
}


def scenario_rates(base_rate: float, margin: float = 0.5) -> dict[str, float]:
    spread = abs(base_rate) * margin
    return {
        "conservador": base_rate - spread,
        "intermediario": base_rate,
        "otimista": base_rate + spread,
    }


def build_scenarios(
    current: float,
    target: float,
    base_rate: float,
    start: date,
    margin: float = 0.5,
    monthly_change: float = 0.0,
) -> list[Scenario]:
    out = []
    for key, rate in scenario_rates(base_rate, margin).items():
        days = days_to_goal(current, target, rate, monthly_change)
        out.append(
            Scenario(
                key=key,
                label=SCENARIO_LABELS[key],
                daily_rate=rate,
                days=days,
                reach_date=(start + timedelta(days=days)) if days is not None else None,
            )
        )
    return out


def required_daily_rate(current: float, target: float, days: int) -> float:
    """Seguidores líquidos por dia necessários para atingir a meta em `days` dias."""
    if days <= 0:
        raise ValueError("O prazo deve ser de pelo menos 1 dia.")
    return max(0.0, (target - current) / days)


def milestones(current: int, target: int) -> list[int]:
    steps = [100, 250, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000]
    out = [s for s in steps if current < s < target]
    if target > current:
        out.append(target)
    return out
