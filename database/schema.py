"""Schema do SQLite e migrações versionadas por `PRAGMA user_version`.

Para alterar o schema no futuro, acrescente uma nova entrada em `MIGRATIONS`
(nunca edite uma migração já publicada).
"""

from __future__ import annotations

import sqlite3

from config import now_iso
from models.vocab import DEFAULT_CATEGORIES

MIGRATION_1 = """
CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('own', 'reference')),
    filename TEXT NOT NULL UNIQUE,
    thumb_filename TEXT NOT NULL UNIQUE,
    original_name TEXT,
    format TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    file_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    technical_score REAL,
    score_breakdown TEXT NOT NULL DEFAULT '{}',
    observations TEXT NOT NULL DEFAULT '[]',
    dhash TEXT,
    framing TEXT,
    lighting TEXT,
    context TEXT,
    clothing_style TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    user_rating INTEGER CHECK (user_rating IS NULL OR user_rating BETWEEN 1 AND 5),
    reaction TEXT CHECK (reaction IS NULL OR reaction IN ('gosto', 'neutro', 'nao_gosto')),
    comment TEXT,
    favorite INTEGER NOT NULL DEFAULT 0,
    in_feed_pool INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (kind, sha256)
);
CREATE INDEX idx_images_kind ON images(kind);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL
);

CREATE TABLE image_categories (
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (image_id, category_id)
);

CREATE TABLE feed_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    notes TEXT,
    params TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE feed_items (
    version_id INTEGER NOT NULL REFERENCES feed_versions(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    pinned INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (version_id, position)
);

CREATE TABLE profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    display_name TEXT,
    username TEXT,
    bio TEXT,
    account_category TEXT,
    bio_link TEXT,
    followers INTEGER,
    following INTEGER,
    posts INTEGER,
    highlights TEXT,
    goals TEXT,
    audience TEXT,
    bio_languages TEXT NOT NULL DEFAULT '["pt"]',
    location TEXT,
    occupation TEXT,
    activities TEXT,
    interests TEXT,
    updated_at TEXT
);

CREATE TABLE interest_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    url TEXT,
    category TEXT,
    reason TEXT,
    added_at TEXT NOT NULL,
    source TEXT,
    priority TEXT NOT NULL DEFAULT 'media' CHECK (priority IN ('baixa', 'media', 'alta')),
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'novo'
        CHECK (status IN ('novo', 'revisar', 'interessante', 'arquivado')),
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE follow_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    url TEXT,
    followed_at TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'pendente'
        CHECK (status IN ('pendente', 'seguiu_de_volta', 'nao_seguiu_de_volta', 'encerrado')),
    last_reviewed_at TEXT,
    notes TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_follow_status ON follow_tracking(status);

CREATE TABLE metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    followers INTEGER NOT NULL CHECK (followers >= 0),
    following INTEGER CHECK (following IS NULL OR following >= 0),
    posts INTEGER CHECK (posts IS NULL OR posts >= 0),
    reach INTEGER CHECK (reach IS NULL OR reach >= 0),
    views INTEGER CHECK (views IS NULL OR views >= 0),
    profile_visits INTEGER CHECK (profile_visits IS NULL OR profile_visits >= 0),
    interactions INTEGER CHECK (interactions IS NULL OR interactions >= 0),
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv')),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE content_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planned_date TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('reels', 'carrossel', 'foto', 'stories')),
    theme TEXT,
    objective TEXT,
    caption TEXT,
    status TEXT NOT NULL DEFAULT 'ideia' CHECK (status IN ('ideia', 'planejado', 'publicado')),
    published_date TEXT,
    reach INTEGER,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    saves INTEGER,
    shares INTEGER,
    follows_gained INTEGER,
    result_notes TEXT,
    learnings TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_content_date ON content_plan(planned_date);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

MIGRATIONS: dict[int, str] = {1: MIGRATION_1}
SCHEMA_VERSION = max(MIGRATIONS)


def seed_defaults(conn: sqlite3.Connection) -> None:
    """Insere categorias iniciais e a linha única do perfil (idempotente)."""
    ts = now_iso()
    conn.executemany(
        "INSERT OR IGNORE INTO categories (name, description, weight, created_at) VALUES (?, ?, 1.0, ?)",
        [(name, desc, ts) for name, desc in DEFAULT_CATEGORIES],
    )
    conn.execute("INSERT OR IGNORE INTO profile (id, updated_at) VALUES (1, ?)", (ts,))


def _statements(script: str) -> list[str]:
    return [stmt.strip() for stmt in script.split(";") if stmt.strip()]


def migrate(conn: sqlite3.Connection) -> int:
    """Aplica migrações pendentes e devolve a versão final do schema.

    Tudo roda numa única transação com trava de escrita (BEGIN IMMEDIATE): dois
    processos abrindo um banco novo ao mesmo tempo não colidem, e uma interrupção
    nunca deixa o schema (nem os dados iniciais) pela metade.
    """
    previous = conn.isolation_level
    conn.isolation_level = None  # controle manual da transação
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    "O banco de dados foi criado por uma versão mais nova da aplicação. "
                    "Atualize o código antes de continuar."
                )
            for version in sorted(v for v in MIGRATIONS if v > current):
                for statement in _statements(MIGRATIONS[version]):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {version}")
            if current == 0:
                # Só na criação do banco (na mesma transação): categorias padrão que o
                # usuário apagar depois não voltam sozinhas.
                seed_defaults(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.isolation_level = previous
    return conn.execute("PRAGMA user_version").fetchone()[0]
