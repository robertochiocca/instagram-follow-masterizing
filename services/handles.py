"""Normalização de nomes de usuário e URLs informados manualmente.

Nenhuma URL é acessada pelo servidor: os links só são abertos pelo navegador
do usuário quando ele toca no botão. Não há scraping.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")
INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
_RESERVED_PATHS = {"p", "reel", "reels", "stories", "explore", "accounts", "direct", "tv"}
MAX_URL_LENGTH = 300


def normalize_username(text: str) -> str:
    """Aceita “@usuario”, “usuario” ou URL do perfil; devolve o usuário em minúsculas."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Informe o nome de usuário.")
    if "instagram.com" in raw.lower():
        url = raw if "://" in raw else "https://" + raw
        parts = [p for p in urlparse(url).path.split("/") if p]
        if not parts or parts[0].lower() in _RESERVED_PATHS:
            raise ValueError("A URL não parece ser de um perfil do Instagram.")
        raw = parts[0]
    username = raw.lstrip("@").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Nome de usuário inválido: use até 30 caracteres entre letras, números, ponto e sublinhado."
        )
    return username


def normalize_url(url: str | None) -> str | None:
    """Valida uma URL opcional (apenas http/https)."""
    text = (url or "").strip()
    if not text:
        return None
    if len(text) > MAX_URL_LENGTH:
        raise ValueError("URL longa demais.")
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or " " in text:
        raise ValueError("URL inválida. Use um endereço começando com https://")
    return text


def profile_url(username: str, url: str | None = None) -> str:
    """URL a abrir no navegador: a informada pelo usuário ou o perfil público padrão."""
    if url:
        try:
            safe = normalize_url(url)
        except ValueError:
            safe = None
        if safe:
            return safe
    return f"https://www.instagram.com/{username}/"


def parse_tags(text: str | list | None) -> list[str]:
    """Tags normalizadas (minúsculas, sem duplicadas, sem “#”)."""
    if isinstance(text, list):
        items = text
    else:
        items = re.split(r"[,;\n]", text or "")
    out = []
    for item in items:
        tag = str(item).strip().lstrip("#").lower()[:40]
        if tag and tag not in out:
            out.append(tag)
    return out[:20]
