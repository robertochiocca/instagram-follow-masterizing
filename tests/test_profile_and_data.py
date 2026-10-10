"""Sugestões de perfil, exportação completa e exclusão de dados."""

import io
import json
import zipfile

from conftest import encode, scene
from database import images as images_repo
from database.settings import get_profile, get_setting, save_profile, set_setting
from models.vocab import DEFAULT_CATEGORIES, HIGHLIGHT_NAME_LIMIT, INSTAGRAM_BIO_LIMIT
from services import data_management, follows, interests, metrics_log, photo_library
from services import profile_suggestions as ps

MB = 1024 * 1024
PROFILE = {
    "occupation": "Estudante de Engenharia", "location": "São Paulo", "activities": "natação, futevôlei",
    "interests": "viagens, arquitetura, moda", "bio_languages": ["pt", "en"], "bio_link": "https://exemplo.com",
    "bio": "good vibes ✌️ #sp #vida", "highlights": "Viagens de 2024 pela Europa\nAmigos",
    "followers": 69, "following": 300, "posts": 6, "goals": "", "audience": "", "account_category": "Pessoal",
}


def test_bios_use_only_given_facts_and_fit_limit():
    bios = ps.generate_bios(PROFILE)
    assert {b.style for b in bios} == set(ps.BIO_STYLES)
    assert {b.language for b in bios} == {"pt", "en"}
    allowed_words = ("engenharia", "são paulo", "natação", "futevôlei", "swimming", "footvolley", "viagens",
                     "travel", "arquitetura", "architecture", "moda", "style", "estudante", "pt", "en")
    for b in bios:
        assert 0 < b.length <= INSTAGRAM_BIO_LIMIT
        lower = b.text.lower()
        assert "influencer" not in lower and "seguidores" not in lower
        assert any(w in lower for w in allowed_words)
        assert b.text.endswith("↓")  # há link na bio
    en = next(b for b in bios if b.style == "curta" and b.language == "en")
    assert "Swimming" in en.text and en.notes


def test_bios_with_missing_information():
    bios = ps.generate_bios({"bio_languages": ["pt"]})
    sport = next(b for b in bios if b.style == "esportes")
    assert sport.text == "" and "esportes" in sport.notes[0]
    assert any("Preencha" in n for b in bios for n in b.notes)


def test_bio_checklist():
    checks = {c.label: c.ok for c in ps.check_bio(PROFILE["bio"], PROFILE)}
    assert not checks["Sem frases genéricas ou pedidos de follow"]
    assert not checks["No máximo 1 hashtag"]
    best = max(ps.generate_bios(PROFILE), key=lambda b: ps.bio_score(b.text, PROFILE))
    assert ps.bio_score(best.text, PROFILE) > ps.bio_score(PROFILE["bio"], PROFILE)
    assert ps.bio_score("", PROFILE) == 0
    assert not ps.check_bio("x" * 200, PROFILE)[0].ok


def test_highlights():
    weights = {"Fitness e esportes": 1.5, "Viagens e arquitetura": 1.0, "Luxo discreto": 0.0}
    suggestions = ps.suggest_highlights(PROFILE, weights, {"praia": 4})
    names = [h.name_pt for h in suggestions]
    assert names[0] == "Viagens"
    assert "Natação" in names and "Futevôlei" in names and "Esportes" not in names
    assert all(len(h.name_pt) <= HIGHLIGHT_NAME_LIMIT and len(h.name_en) <= HIGHLIGHT_NAME_LIMIT for h in suggestions)
    assert len(suggestions) <= 6
    notes = ps.review_existing_highlights(PROFILE["highlights"])
    assert any("27 caracteres" in n for n in notes)


def test_captions():
    for theme in ps.CAPTION_THEMES:
        for lang in ("pt", "en"):
            caps = ps.generate_captions(theme, lang, place="Positano", sport="natação", with_cta=True)
            assert caps and all("{" not in c for c in caps)
    no_place = ps.generate_captions("viagem", "pt", count=10)
    assert all("{lugar}" not in c and "Positano" not in c for c in no_place)
    assert ps.generate_captions("praia", "pt", seed=1) == ps.generate_captions("praia", "pt", seed=1)
    tagged = ps.generate_captions("esporte", "pt", with_hashtags=True)
    assert all("#" in c for c in tagged)


def test_ideas_and_diagnosis():
    ideas = ps.content_ideas({"Fitness e esportes": 2.0, "Luxo discreto": 0.0})
    assert ideas[0][0] == "Fitness e esportes"
    assert all(cat != "Luxo discreto" for cat, _, _ in ideas)
    diagnosis = ps.diagnose(PROFILE, avg_daily_gain=0, published_last_14_days=0)
    text = " ".join(t for _, t in diagnosis)
    assert "6 publicações" in text and "segue 300" in text and "Contas profissionais" in text
    assert ps.diagnose({"bio": "Engenharia · SP", "posts": 20, "highlights": "a\nb\nc", "goals": "x",
                        "audience": "y"})[0][0] == "ok"


# --- Exportação e exclusão -------------------------------------------------------------------------


def seed_everything(db, storage):
    own = photo_library.import_image(db, storage, encode(scene(seed=1)), "eu.jpg", "own", 5 * MB)
    photo_library.import_image(db, storage, encode(scene(seed=2)), "ref.jpg", "reference", 5 * MB)
    images_repo.update_image(db, own.image_id, {"tags": ["praia"]}, category_ids=[1])
    interests.add_interest(db, {"username": "perfil.um", "tags": "x"})
    follows.add_follow(db, {"username": "perfil.dois"})
    metrics_log.upsert_metric(db, {"date": "2026-10-01", "followers": 69})
    save_profile(db, {"username": "eu", "bio": "minha bio"})
    set_setting(db, "target_followers", 3000)
    images_repo.add_category(db, "Minha categoria")


def test_export_all_zip(db, storage):
    seed_everything(db, storage)
    with zipfile.ZipFile(io.BytesIO(data_management.export_all_zip(db, storage, include_images=True))) as zf:
        names = zf.namelist()
        payload = json.loads(zf.read("dados.json"))
    assert "csv/interest_profiles.csv" in names and "csv/metrics.csv" in names
    assert sum(n.startswith("imagens/minhas_fotos/") for n in names) == 1
    assert sum(n.startswith("imagens/referencias/") for n in names) == 1
    tables = payload["tabelas"]
    assert tables["interest_profiles"][0]["username"] == "perfil.um"
    assert tables["profile"][0]["bio"] == "minha bio"
    assert tables["images"][0]["tags"] == ["praia"]
    with zipfile.ZipFile(io.BytesIO(data_management.export_all_zip(db, storage, include_images=False))) as zf:
        assert not any(n.startswith("imagens/") for n in zf.namelist())


def test_delete_all_data(db, storage):
    seed_everything(db, storage)
    counts = data_management.summary_counts(db)
    assert counts["own_images"] == 1 and counts["metrics"] == 1
    data_management.delete_all_data(db, storage)
    counts = data_management.summary_counts(db)
    assert all(v == 0 for k, v in counts.items() if k != "categories")
    assert counts["categories"] == len(DEFAULT_CATEGORIES)  # padrões recriados
    assert storage.usage() == (0, 0)
    assert get_profile(db)["bio"] is None
    assert get_setting(db, "target_followers") == 1000
    # o banco continua utilizável depois da limpeza
    assert photo_library.import_image(db, storage, encode(scene(seed=5)), "n.jpg", "own", 5 * MB).ok
