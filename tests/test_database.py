import sqlite3

import pytest

from database import Database, crud
from database import feeds as feeds_repo
from database import images as images_repo
from database.schema import SCHEMA_VERSION
from database.settings import get_profile, get_setting, reset_setting, save_profile, set_setting
from models.vocab import DEFAULT_CATEGORIES


def test_initialize_creates_schema_and_seeds(db):
    with db.connect() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert crud.TABLES <= tables
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert len(images_repo.list_categories(db)) == len(DEFAULT_CATEGORIES)
    assert get_profile(db)["id"] == 1


def test_initialize_is_idempotent(db):
    assert db.initialize() == SCHEMA_VERSION
    assert len(images_repo.list_categories(db)) == len(DEFAULT_CATEGORIES)


def test_persistence_after_restart(tmp_path):
    path = tmp_path / "persist.sqlite3"
    first = Database(path)
    first.initialize()
    set_setting(first, "target_followers", 3000)
    save_profile(first, {"username": "eu", "followers": 69})
    with first.connect() as conn:
        crud.insert(conn, "metrics", {"date": "2026-10-01", "followers": 69})

    second = Database(path)  # simula reinício da aplicação
    second.initialize()
    assert get_setting(second, "target_followers") == 3000
    assert get_profile(second)["followers"] == 69
    with second.connect() as conn:
        assert crud.count(conn, "metrics") == 1


def test_crud_rejects_unknown_tables_and_columns(db):
    with db.connect() as conn:
        with pytest.raises(ValueError):
            crud.insert(conn, "sqlite_master", {"name": "x"})
        with pytest.raises(ValueError):
            crud.insert(conn, "metrics", {"date": "2026-01-01", "followers": 1, "evil; DROP TABLE metrics": 1})
        with pytest.raises(ValueError):
            crud.select(conn, "metrics", order_by="followers; DROP TABLE metrics")


def test_crud_create_update_delete_and_json(db):
    with db.connect() as conn:
        rid = crud.insert(conn, "interest_profiles", {"username": "a", "added_at": "2026-01-01", "tags": ["x", "y"]})
        row = crud.get(conn, "interest_profiles", rid)
        assert row["tags"] == ["x", "y"]
        assert row["created_at"] and row["updated_at"]
        assert crud.update(conn, "interest_profiles", rid, {"notes": "ok", "tags": ["z"]})
        assert crud.get(conn, "interest_profiles", rid)["tags"] == ["z"]
        assert crud.delete(conn, "interest_profiles", rid)
        assert crud.get(conn, "interest_profiles", rid) is None
        assert not crud.delete(conn, "interest_profiles", rid)


def test_check_constraints(db):
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            crud.insert(conn, "metrics", {"date": "2026-01-01", "followers": -5})
        with pytest.raises(sqlite3.IntegrityError):
            crud.insert(conn, "follow_tracking", {"username": "a", "followed_at": "2026-01-01", "status": "hacked"})


def _image_record(n: int) -> dict:
    return {
        "kind": "own", "filename": f"{n:032x}.jpg", "thumb_filename": f"{n + 1000:032x}.jpg",
        "format": "JPEG", "width": 10, "height": 10, "file_size": 1, "sha256": str(n),
    }


def test_cascade_delete_removes_links(db):
    image_id = images_repo.add_image(db, _image_record(1), category_ids=[1, 2])
    feeds_repo.save_version(db, "v1", [{"image_id": image_id, "pinned": True}])
    assert images_repo.get_image(db, image_id)["category_ids"] == [1, 2]
    images_repo.delete_image_row(db, image_id)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM image_categories").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0] == 0


def test_categories_crud(db):
    cid = images_repo.add_category(db, "Teste", "desc", 2.0)
    with pytest.raises(ValueError):
        images_repo.add_category(db, "teste")  # nome único, sem diferenciar maiúsculas
    with pytest.raises(ValueError):
        images_repo.add_category(db, "  ")
    images_repo.update_category(db, cid, name="Novo nome", weight=9)
    cat = next(c for c in images_repo.list_categories(db) if c["id"] == cid)
    assert cat["name"] == "Novo nome" and cat["weight"] == 3.0  # peso limitado a 3
    assert images_repo.delete_category(db, cid)


def test_feed_versions_crud(db):
    a = images_repo.add_image(db, _image_record(1))
    b = images_repo.add_image(db, _image_record(2))
    vid = feeds_repo.save_version(db, "Minha versão", [{"image_id": a}, {"image_id": b, "pinned": True}])
    version = feeds_repo.get_version(db, vid)
    assert [i["image_id"] for i in version["items"]] == [a, b]
    assert version["items"][1]["pinned"] is True
    feeds_repo.update_version(db, vid, [{"image_id": b}, {"image_id": a}], name="Renomeada")
    version = feeds_repo.get_version(db, vid)
    assert version["name"] == "Renomeada"
    assert [i["image_id"] for i in version["items"]] == [b, a]
    assert feeds_repo.list_versions(db)[0]["item_count"] == 2
    with pytest.raises(ValueError):
        feeds_repo.save_version(db, "", [{"image_id": a}])
    with pytest.raises(ValueError):
        feeds_repo.save_version(db, "vazia", [])
    assert feeds_repo.delete_version(db, vid)


def test_settings_defaults_merge_and_reset(db):
    weights = get_setting(db, "score_weights")
    assert weights["sharpness"] == 25
    set_setting(db, "score_weights", {"sharpness": 40})
    merged = get_setting(db, "score_weights")
    assert merged["sharpness"] == 40 and merged["exposure"] == 20  # chaves novas completadas
    reset_setting(db, "score_weights")
    assert get_setting(db, "score_weights")["sharpness"] == 25


def test_refuses_database_from_newer_version(tmp_path):
    path = tmp_path / "future.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(RuntimeError):
        Database(path).initialize()


def test_backup_copies_data(db, tmp_path):
    set_setting(db, "target_followers", 1234)
    raw = db.backup_bytes()
    assert raw.startswith(b"SQLite format 3")
    copy = db.backup_to(tmp_path / "bkp" / "copy.sqlite3")
    restored = Database(copy)
    assert get_setting(restored, "target_followers") == 1234
