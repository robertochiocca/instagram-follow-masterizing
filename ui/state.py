"""Acesso a recursos compartilhados (configuração, banco e armazenamento)."""

from __future__ import annotations

import logging

import streamlit as st

from config import AppConfig, HARD_MAX_UPLOAD_MB, load_config
from database import Database
from database.settings import get_setting
from services.image_storage import ImageStorage


def get_config() -> AppConfig:
    return load_config()


@st.cache_resource(show_spinner=False)
def _resources(data_dir: str, db_path: str) -> tuple[Database, ImageStorage]:
    """Inicializa o banco e limpa temporários uma vez por pasta de dados."""
    db = Database(db_path)
    db.initialize()
    storage = ImageStorage(f"{data_dir}/images")
    removed = storage.cleanup_temp()
    if removed:
        logging.getLogger(__name__).info("Temporários removidos: %s", removed)
    return db, storage


def get_db() -> Database:
    cfg = get_config()
    return _resources(str(cfg.data_dir), str(cfg.db_path))[0]


def get_storage() -> ImageStorage:
    cfg = get_config()
    return _resources(str(cfg.data_dir), str(cfg.db_path))[1]


def max_upload_mb() -> int:
    """Limite por imagem: configuração salva na interface ou variável de ambiente."""
    saved = get_setting(get_db(), "max_upload_mb")
    value = int(saved) if saved else get_config().max_upload_mb
    return max(1, min(HARD_MAX_UPLOAD_MB, value))
