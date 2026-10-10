"""Acesso ao SQLite: uma conexão curta por operação.

Conexões curtas evitam problemas de thread com o Streamlit (cada sessão roda
em uma thread própria) e garantem que o arquivo fique consistente.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from database.schema import migrate


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão, faz commit ao final ou rollback em caso de erro."""
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> int:
        """Cria a pasta e o banco se necessário e aplica migrações."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            return migrate(conn)

    def backup_to(self, destination: Path | str) -> Path:
        """Cópia consistente do banco usando a API de backup do SQLite."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as src:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
            finally:
                dst.close()
        return destination

    def backup_bytes(self) -> bytes:
        """Conteúdo de uma cópia consistente do banco (para download)."""
        with self.connect() as src:
            mem = sqlite3.connect(":memory:")
            try:
                src.backup(mem)
                return mem.serialize()
            finally:
                mem.close()
