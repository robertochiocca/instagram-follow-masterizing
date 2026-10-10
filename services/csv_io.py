"""Importação e exportação CSV.

- Importação de métricas: aceita cabeçalhos em português ou inglês, separador
  vírgula, ponto e vírgula ou tabulação (detectado pelo cabeçalho), datas
  AAAA-MM-DD ou DD/MM/AAAA, arquivos UTF-8, UTF-16 ou ANSI (Windows) e finais
  de linha de qualquer sistema.
- Exportação: ponto e vírgula, vírgula decimal e todos os campos entre aspas
  (padrão do Excel em português), UTF-8 com BOM e proteção contra "CSV
  injection" (textos iniciados por = + - @ recebem um apóstrofo).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from config import MAX_CSV_BYTES, today
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
    "interactions": ["interactions", "interacoes"],
    "notes": ["notes", "observacoes", "notas", "obs"],
}
REQUIRED_METRIC_COLUMNS = ("date", "followers")
MAX_COUNT = 10**12  # nenhuma métrica do Instagram chega perto disso
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
    if number > MAX_COUNT:
        raise ValueError(f"número grande demais (“{text[:20]}”)")
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


def decode_csv(data: bytes) -> str:
    if len(data) > MAX_CSV_BYTES:
        raise ValueError(f"CSV maior que {MAX_CSV_BYTES // (1024 * 1024)} MB.")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    else:
        # cp1252 é o "ANSI" do Excel no Windows; latin-1 nunca falha (último recurso).
        encodings = ("utf-8-sig", "cp1252", "latin-1")
    for encoding in encodings:
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Não foi possível ler a codificação do arquivo. Salve como CSV UTF-8.")
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # Windows, Mac antigo e Linux
    if not text.strip():
        raise ValueError("O arquivo CSV está vazio.")
    return text


def read_csv_rows(data: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Cabeçalho e linhas (com o número da linha física onde cada registro começa)."""
    text = decode_csv(data)
    first_line = text.lstrip("\n").split("\n", 1)[0]
    counts = {sep: first_line.count(sep) for sep in (";", ",", "\t")}
    delimiter = max(counts, key=counts.get)
    if counts[delimiter] == 0:
        raise ValueError("Não foi possível identificar o separador. Use vírgula ou ponto e vírgula.")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: list[tuple[int, list[str]]] = []
    header: list[str] | None = None
    try:
        last_line = 0
        for row in reader:
            start_line, last_line = last_line + 1, reader.line_num
            if not any(cell.strip() for cell in row):
                continue  # linhas em branco
            if header is None:
                header = [cell.strip() for cell in row]
                continue
            rows.append((start_line, row))
            if len(rows) > MAX_CSV_ROWS:
                raise ValueError(f"O CSV tem mais de {MAX_CSV_ROWS} linhas.")
    except csv.Error as exc:
        raise ValueError("Não foi possível ler o CSV. Verifique o separador e as aspas.") from exc
    if header is None:
        raise ValueError("O arquivo CSV está vazio.")
    return header, rows


def import_metrics_csv(db: Database, data: bytes, overwrite: bool = True) -> ImportReport:
    """Importa métricas; cada data é única (sobrescreve ou ignora se já existir)."""
    header, rows = read_csv_rows(data)
    aliases = _alias_map()
    columns: dict[str, int] = {}
    for position, name in enumerate(header):
        canonical = aliases.get(_norm_header(name))
        if canonical and canonical not in columns:
            columns[canonical] = position
    missing = [c for c in REQUIRED_METRIC_COLUMNS if c not in columns]
    if missing:
        names = {"date": "data", "followers": "seguidores"}
        raise ValueError("Colunas obrigatórias ausentes: " + ", ".join(names[m] for m in missing))

    report = ImportReport()
    parsed: dict[str, dict] = {}
    last_day = today()
    for line, row in rows:
        try:
            extra = row[len(header):]
            if any(cell.strip() for cell in extra):
                raise ValueError(
                    "há mais valores que colunas no cabeçalho (números com vírgula de milhar "
                    "precisam estar entre aspas)"
                )
            row = row + [""] * (len(header) - len(row))
            value = lambda col: row[columns[col]]  # noqa: E731
            day = parse_date(value("date"))
            if day > last_day:
                raise ValueError(f"data no futuro ({day:%d/%m/%Y})")
            record = {"date": day.isoformat()}
            followers = parse_count(value("followers"))
            if followers is None:
                raise ValueError("seguidores é obrigatório")
            record["followers"] = followers
            for col in ("following", "posts", "reach", "views", "profile_visits", "interactions"):
                if col in columns:
                    record[col] = parse_count(value(col))
            if "notes" in columns and value("notes").strip():
                record["notes"] = value("notes").strip()[:500]
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
    """CSV para Excel/Planilhas em português: “;”, vírgula decimal e campos entre aspas.

    Com todos os campos entre aspas, um “;” ou “,” dentro de um texto nunca cria
    uma célula nova que escape da proteção contra fórmulas.
    """
    safe = df.copy()
    for col in safe.columns:
        if safe[col].dtype == object or pd.api.types.is_string_dtype(safe[col]):
            safe[col] = safe[col].map(_sanitize_cell)
    return safe.to_csv(index=False, sep=";", decimal=",", quoting=csv.QUOTE_ALL).encode("utf-8-sig")
