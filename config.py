"""Configuração da aplicação lida de variáveis de ambiente.

Nenhum segredo fica no código. Todas as variáveis são opcionais e têm padrões
seguros; veja `.env.example`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_TIMEZONE = "America/Sao_Paulo"

DEFAULT_MAX_UPLOAD_MB = 15
# Teto absoluto, também aplicado pelo servidor em .streamlit/config.toml.
HARD_MAX_UPLOAD_MB = 50
# Proteção contra "bombas de descompressão" (imagens com dimensões absurdas).
MAX_IMAGE_PIXELS = 60_000_000
MAX_CSV_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    max_upload_mb: int
    app_password: str | None
    log_level: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "growth_tool.sqlite3"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"


def _load_dotenv(path: Path) -> None:
    """Carrega um arquivo .env simples (CHAVE=valor) sem sobrescrever o ambiente.

    Implementação mínima para evitar uma dependência extra. Aceita: linhas de
    comentário, prefixo “export ”, aspas simples ou duplas, comentário no fim de
    valores sem aspas (“ # ...”) e arquivos salvos com BOM (Bloco de Notas).
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logging.getLogger(__name__).warning("Valor inválido em %s; usando padrão.", name)
        return default
    return max(minimum, min(maximum, value))


def load_config() -> AppConfig:
    _load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.environ.get("IGT_DATA_DIR", "").strip() or PROJECT_ROOT / "data")
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()
    password = os.environ.get("IGT_APP_PASSWORD", "").strip() or None
    level = os.environ.get("IGT_LOG_LEVEL", "INFO").strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        level = "INFO"
    return AppConfig(
        data_dir=data_dir,
        max_upload_mb=_int_env("IGT_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB, 1, HARD_MAX_UPLOAD_MB),
        app_password=password,
        log_level=level,
    )


def _tz():
    name = os.environ.get("IGT_TIMEZONE", "").strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def now() -> datetime:
    """Data e hora atuais no fuso configurado (padrão: America/Sao_Paulo).

    Servidores remotos costumam rodar em UTC; usar o fuso do usuário evita que
    registros feitos à noite caiam no dia seguinte.
    """
    return datetime.now(_tz())


def today() -> date:
    return now().date()


def now_iso() -> str:
    return now().replace(tzinfo=None).isoformat(timespec="seconds")
