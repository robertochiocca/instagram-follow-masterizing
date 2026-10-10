"""Camada de persistência (SQLite). Não depende do Streamlit."""

from database.connection import Database

__all__ = ["Database"]
