"""Importação e exportação CSV.

- Importação de métricas: aceita cabeçalhos em português ou inglês, separador
  vírgula ou ponto e vírgula, datas AAAA-MM-DD ou DD/MM/AAAA.
- Exportação: UTF-8 com BOM (abre corretamente no Excel) e proteção contra
  "CSV injection" (textos iniciados por = + - @ recebem um apóstrofo).
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from config import MAX_CSV_BYTES
from database import crud
from database.connection import Database

MAX_CSV_ROWS = 10_000

METRIC_ALIASES = {
    "date": ["date", "data", "dia"],
    "followers": ["followers", "seguidores"],
    "following": ["following", "seguindo"],
    "posts": ["posts", "publicacoes", "publicações", "posts_total"],
    "reach": ["reach", "alcance", "contas_alcancadas"],
    "views": ["views", "visualizacoes", "impressoes", "impressions"],
    "profile_visits": ["profile_visits", "visitas_perfil", "visitas_ao_perfil", "visitas"],
    "interactions": ["interactions", "interacoes", "engajamento"],
    "notes": ["notes", "observacoes", "notas", "obs"],
}
REQUIRED_METRIC_COLUMNS = ("date", "followers")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _norm_header(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def _alias_map() -> dict[str, str]:
    mapping = {}
    for canonical, aliases in METRIC_ALIASES.items():
        for alias in aliases:
            mapping[_norm_header(alias)] = canonical
    return mapping


def parse_date(value) -> date:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida “{text[:20]}” (use AAAA-MM-DD ou DD/MM/AAAA)")


def parse_count(value) -> int | None:
    """Inteiro não negativo; aceita separador de milhar (1.234 ou 1,234)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(" ", "")
    if text == "" or text.lower() in {"nan", "none", "-"}:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", text):
        text = re.sub(r"[.,]", "", text)
    try:
        number = float(text.replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"número inválido “{text[:20]}”") from exc
    if number < 0 or not number.is_integer():
        raise ValueError(f"use números inteiros e não negativos (“{text[:20]}”)")
    return int(number)


@dataclass
class ImportReport:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors or (self.inserted + self.updated) > 0


def read_csv_bytes(data: bytes) -> pd.DataFrame:
    if len(data) > MAX_CSV_BYTES:
        raise ValueError(f"CSV maior que {MAX_CSV_BYTES // (1024 * 1024)} MB.")
    if not data.strip():
        raise ValueError("O arquivo CSV está vazio.")
    text = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        df = pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise ValueError("Não foi possível ler o CSV. Verifique o separador e o cabeçalho.") from exc
    if len(df) > MAX_CSV_ROWS:
        raise ValueError(f"O CSV tem mais de {MAX_CSV_ROWS} linhas.")
    return df


def import_metrics_csv(db: Database, data: bytes, overwrite: bool = True) -> ImportReport:
    """Importa métricas; cada data é única (sobrescreve ou ignora se já existir)."""
    df = read_csv_bytes(data)
    aliases = _alias_map()
    rename = {}
    for col in df.columns:
        canonical = aliases.get(_norm_header(col))
        if canonical and canonical not in rename.values():
            rename[col] = canonical
    df = df.rename(columns=rename)
    missing = [c for c in REQUIRED_METRIC_COLUMNS if c not in df.columns]
    if missing:
        names = {"date": "data", "followers": "seguidores"}
        raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(names[m] for m in missing))

    report = ImportReport()
    parsed: dict[str, dict] = {}
    for idx, row in df.iterrows():
        line = idx + 2  # +1 cabeçalho, +1 base 1
        try:
            record = {"date": parse_date(row["date"]).isoformat()}
            followers = parse_count(row["followers"])
            if followers is None:
                raise ValueError("seguidores é obrigatório")
            record["followers"] = followers
            for col in ("following", "posts", "reach", "views", "profile_visits", "interactions"):
                if col in df.columns:
                    record[col] = parse_count(row[col])
            if "notes" in df.columns and str(row["notes"]).strip():
                record["notes"] = str(row["notes"]).strip()[:500]
        except ValueError as exc:
            report.errors.append(f"Linha {line}: {exc}.")
            continue
        parsed[record["date"]] = record  # datas repetidas no arquivo: vale a última

    with db.connect() as conn:
        for day, record in parsed.items():
            existing = conn.execute("SELECT id FROM metrics WHERE date = ?", (day,)).fetchone()
            record["source"] = "csv"
            if existing:
                if overwrite:
                    crud.update(conn, "metrics", existing["id"], record)
                    report.updated += 1
                else:
                    report.skipped += 1
            else:
                crud.insert(conn, "metrics", record)
                report.inserted += 1
    return report


def metrics_template_csv() -> bytes:
    sample = pd.DataFrame(
        [
            {"data": "2026-10-01", "seguidores": 69, "seguindo": 180, "publicacoes": 12, "alcance": 350,
             "visualizacoes": 900, "visitas_perfil": 40, "interacoes": 55, "observacoes": "exemplo"},
            {"data": "2026-10-08", "seguidores": 74, "seguindo": 182, "publicacoes": 14, "alcance": 420,
             "visualizacoes": 1100, "visitas_perfil": 52, "interacoes": 61, "observacoes": ""},
        ]
    )
    return to_csv_bytes(sample)


def _sanitize_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    safe = df.copy()
    for col in safe.columns:
        if safe[col].dtype == object or pd.api.types.is_string_dtype(safe[col]):
            safe[col] = safe[col].map(_sanitize_cell)
    return safe.to_csv(index=False).encode("utf-8-sig")
