"""Aprendizado de preferências e organizador do feed."""

import io
import zipfile

import pytest

from conftest import encode, scene
from database import images as images_repo
from services import feed_planner as fp
from services import photo_library, preferences

MB = 1024 * 1024
CATS = {1: "Mediterrâneo e verão europeu", 2: "Viagens e arquitetura"}


def ref(context, reaction=None, rating=None, cats=(), lighting=None, tags=()):
    return {"context": context, "reaction": reaction, "user_rating": rating, "category_ids": list(cats),
            "lighting": lighting, "tags": list(tags), "framing": None, "clothing_style": None, "metrics": {}}


def test_image_signal():
    assert preferences.image_signal({"user_rating": 5}) == 1.0
    assert preferences.image_signal({"user_rating": 1}) == -1.0
    assert preferences.image_signal({"reaction": "neutro"}) == 0.0
    assert preferences.image_signal({"user_rating": 5, "reaction": "nao_gosto"}) == 0.0
    assert preferences.image_signal({}) is None


def test_learning_and_insights():
    refs = [ref("praia", "gosto", 5, [1], "natural_dia") for _ in range(4)]
    refs += [ref("cidade", "nao_gosto", 1, [2], "noite") for _ in range(3)]
    refs.append(ref("praia"))  # sem avaliação: ignorada
    model = preferences.learn_preferences(refs, CATS)
    assert model.evaluated == 7 and model.ready
    beach = model.stats[("context", "praia")]
    city = model.stats[("context", "cidade")]
    assert beach.preference > 0.5 and city.preference < -0.5
    assert beach.preference == pytest.approx(4 / 6)  # soma 4 / (4 + 2)
    text = " ".join(preferences.insights(model))
    assert "praia" in text and "luz natural" in text
    assert "avaliar pior" in text


def test_not_ready_and_smoothing():
    model = preferences.learn_preferences([ref("praia", "gosto")], CATS)
    assert not model.ready and preferences.insights(model) == []
    assert model.stats[("context", "praia")].preference == pytest.approx(1 / 3)


def test_affinity_and_comparison():
    refs = [ref("praia", "gosto", 5, [1]) for _ in range(4)] + [ref("cidade", "nao_gosto", 1, [2]) for _ in range(3)]
    model = preferences.learn_preferences(refs, CATS)
    beach_photo = ref("praia", cats=[1])
    city_photo = ref("cidade", cats=[2])
    assert preferences.affinity(beach_photo, model, CATS).percent > 75
    assert preferences.affinity(city_photo, model, CATS).percent < 25
    aff = preferences.affinity(beach_photo, model, CATS)
    assert aff.positives and aff.coverage == 1.0
    recs = preferences.compare_with_own_photos([city_photo, city_photo], model, CATS)
    assert any("só 0%" in r for r in recs)
    assert any("avaliar pior" in r for r in recs)


def test_category_weight_zero_is_ignored():
    refs = [ref("praia", "gosto", 5, [1]) for _ in range(5)]
    model = preferences.learn_preferences(refs, CATS, category_weights={CATS[1]: 0.0},
                                          group_weights={"context": 0.0})
    photo = ref("praia", cats=[1])
    assert preferences.affinity(photo, model, CATS).score == 0.0


def test_load_model_from_database(db, storage):
    for i in range(5):
        out = photo_library.import_image(db, storage, encode(scene(seed=i, warm=True)), f"{i}.jpg", "reference", 5 * MB)
        images_repo.update_image(db, out.image_id, {"reaction": "gosto", "context": "praia"}, category_ids=[1])
    model, names = preferences.load_model(db)
    assert model.ready and names[1].startswith("Mediterrâneo")
    assert model.stats[("temperature", "quente")].count == 5
    assert model.preferred_palette


# --- Feed ------------------------------------------------------------------------------------------


def photo(pid, quality=0.8, tags=(), dhash="0" * 16, lab=(50, 0, 0), brightness=0.5, warmth=0.0):
    return fp.FeedPhoto(
        id=pid, name=str(pid), quality=quality, preference=0.5,
        labels=frozenset(f"tag:{t}" for t in tags), tags=tuple(tags), lighting=None, framing=None,
        context=None, dhash=dhash, brightness=brightness, warmth=warmth, lab=lab,
        technical_score=quality * 100,
    )


def test_neighbors_in_three_column_grid():
    assert sorted(fp.neighbors(0, 9)) == [1, 3]
    assert sorted(fp.neighbors(4, 9)) == [1, 3, 5, 7]
    assert sorted(fp.neighbors(2, 9)) == [1, 5]
    assert sorted(fp.neighbors(3, 5)) == [0, 4]
    assert fp.neighbors(0, 1) == []


def test_plan_respects_pins_and_size():
    photos = [photo(i, quality=0.5 + i / 20) for i in range(8)]
    plan = fp.plan_feed(photos, 6, pins={0: 1, 4: 2})
    assert len(plan.sequence) == 6 and len(set(plan.sequence)) == 6
    assert plan.sequence[0] == 1 and plan.sequence[4] == 2
    assert plan.reasons[0] == ["Posição fixada por você."]
    # pin inválido (foto inexistente ou fora do tamanho) é ignorado
    assert len(fp.plan_feed(photos, 3, pins={7: 3, 0: 999}).sequence) == 3
    assert len(fp.plan_feed(photos, 50).sequence) == 8


def test_plan_prefers_quality_without_diversity():
    photos = [photo(1, 0.2), photo(2, 0.9), photo(3, 0.6)]
    plan = fp.plan_feed(photos, 3, weights={"quality": 100, "diversity": 0, "coherence": 0, "preference": 0})
    assert plan.sequence == [2, 3, 1]


def test_plan_separates_near_duplicates():
    dup = "f0f0f0f0f0f0f0f0"
    photos = [photo(1, 0.95, ["praia"], dup), photo(2, 0.94, ["praia"], dup),
              photo(3, 0.7, ["retrato"], "0f0f0f0f0f0f0f0f", lab=(70, 20, 20)),
              photo(4, 0.7, ["esporte"], "ffff0000ffff0000", lab=(30, -20, 10))]
    plan = fp.plan_feed(photos, 4)
    seq = plan.sequence
    pos = {pid: i for i, pid in enumerate(seq)}
    assert pos[2] not in fp.neighbors(pos[1], 4)
    alerts = fp.repetition_warnings([photos[0], photos[1], photos[2], photos[3]])
    assert any("quase iguais" in a for a in alerts)


def test_evaluate_sequence_and_alerts():
    same = [photo(i, 0.8, ["praia"], "f0f0f0f0f0f0f0f0") for i in range(3)]
    varied = [photo(1, 0.8, ["praia"], "f0f0f0f0f0f0f0f0"), photo(2, 0.8, ["retrato"], "0f0f0f0f0f0f0f0f"),
              photo(3, 0.8, ["esporte"], "ffff0000ffff0000")]
    e_same, e_var = fp.evaluate_sequence(same), fp.evaluate_sequence(varied)
    assert e_same.diversity < e_var.diversity
    assert e_same.adjacent_alerts and not e_var.adjacent_alerts
    for value in (e_var.quality, e_var.overall, e_var.coherence, e_var.preference):
        assert 0 <= value <= 100
    assert fp.evaluate_sequence([]).overall == 0


def test_repetition_and_alternation():
    photos = [photo(i, tags=["praia"], dhash=f"{i:016x}" * 1) for i in range(1, 7)]
    warnings = fp.repetition_warnings(photos)
    assert any("praia" in w for w in warnings)
    assert any("iluminação semelhante" in w for w in warnings)
    suggestions = fp.alternation_suggestions(photos)
    assert any("Temas ausentes" in s for s in suggestions)
    assert any("linha 1" in s for s in suggestions)
    untagged = fp.alternation_suggestions([photo(1), photo(2)])
    assert any("sem tags" in s for s in untagged)


def test_hex_to_lab():
    l, a, b = fp.hex_to_lab("#ffffff")
    assert l == pytest.approx(100, abs=0.5) and abs(a) < 1 and abs(b) < 1
    assert fp.hex_to_lab("#000000")[0] == pytest.approx(0, abs=0.5)


def test_feed_exports(db, storage):
    rows = []
    for i in range(4):
        out = photo_library.import_image(db, storage, encode(scene(seed=i)), f"p{i}.jpg", "own", 5 * MB)
        rows.append(images_repo.get_image(db, out.image_id))
    df = fp.sequence_dataframe(rows, {0})
    assert list(df["posicao_grade"]) == [1, 2, 3, 4]
    assert list(df["ordem_publicacao"]) == [4, 3, 2, 1]
    assert df.loc[0, "fixada"] == "sim"
    png = fp.grid_preview_png(storage, rows)
    assert png.startswith(b"\x89PNG")
    with zipfile.ZipFile(io.BytesIO(fp.export_zip(storage, rows))) as zf:
        names = zf.namelist()
    assert "publicar_01_grade_04.jpg" in names and "publicar_04_grade_01.jpg" in names
    assert {"sequencia.csv", "previa_grade.png", "LEIA-ME.txt"} <= set(names)
    real = [fp.FeedPhoto.from_row(r) for r in rows]
    assert all(0 <= p.quality <= 1 and p.preference == 0.5 for p in real)
