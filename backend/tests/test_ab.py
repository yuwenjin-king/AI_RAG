from types import SimpleNamespace

from app.eval.ab import pick_variant, variant_key


def test_no_variants():
    assert pick_variant(SimpleNamespace(variants=None), "k") is None
    assert pick_variant(SimpleNamespace(variants=[]), "k") is None


def test_deterministic():
    scene = SimpleNamespace(variants=[{"name": "A", "weight": 1}, {"name": "B", "weight": 1}])
    assert pick_variant(scene, "user-42") == pick_variant(scene, "user-42")


def test_weight_all_to_heavy():
    scene = SimpleNamespace(variants=[{"name": "A", "weight": 0}, {"name": "B", "weight": 9}])
    for i in range(20):
        assert pick_variant(scene, f"u{i}")["name"] == "B"


def test_distribution_roughly_balanced():
    scene = SimpleNamespace(variants=[{"name": "A", "weight": 1}, {"name": "B", "weight": 1}])
    counts = {"A": 0, "B": 0}
    for i in range(200):
        counts[pick_variant(scene, f"u{i}")["name"]] += 1
    # 50/50 权重 → 大致各半（允许 ±25%）
    assert 60 < counts["A"] < 140
    assert 60 < counts["B"] < 140


def test_variant_key_stable():
    assert variant_key("t", "s", "u") == "t:s:u"
    assert variant_key("t", None, None) == "t:default:anon"
