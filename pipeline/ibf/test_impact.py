import numpy as np

from impact import impact_from_depth


def test_counts_and_classes():
    depth = np.array([[0.0, 0.05, 0.2], [0.6, 1.5, np.nan]])
    pop = np.full(depth.shape, 10.0)
    rows, cols = np.array([0, 0, 1, 1, 1]), np.array([1, 2, 0, 1, 2])
    r = impact_from_depth(depth, pop, (rows, cols))
    assert r["people_affected"] == 30.0           # cells 0.2, 0.6, 1.5
    assert r["buildings_affected"] == 3           # 0.2, 0.6, 1.5 (0.05 and NaN excluded)
    assert r["max_depth_m"] == 1.5
    c = r["by_depth_class"]
    assert c["0.1-0.5 m"] == {"people": 10.0, "buildings": 1}
    assert c["0.5-1 m"] == {"people": 10.0, "buildings": 1}
    assert c[">1 m"] == {"people": 10.0, "buildings": 1}


def test_dry():
    r = impact_from_depth(np.zeros((2, 2)), np.ones((2, 2)), (np.array([0]), np.array([0])))
    assert r["people_affected"] == 0 and r["buildings_affected"] == 0


def test_damage_factor_curves():
    from vulnerability import damage_factor

    assert damage_factor(np.array([0.0, 1.0, 1.3, 5.0]), "I").tolist() == [0.0, 0.9, 1.0, 1.0]
    assert damage_factor(np.array([2.5, 10.0]), "II").tolist() == [1.0, 1.0]
    d = np.linspace(0, 3, 100)
    for c in ("I", "II"):
        assert np.all(np.diff(damage_factor(d, c)) >= 0)
    assert np.all(damage_factor(d, "I") >= damage_factor(d, "II") - 1e-9)   # I is the more vulnerable


def test_impact_damage():
    depth = np.array([[0.1, 1.3]])
    r = impact_from_depth(depth, np.ones((1, 2)), (np.array([0, 0]), np.array([0, 1])))
    assert abs(r["building_loss_equivalents"] - 1.15) < 1e-9     # 0.15 + 1.0
    assert abs(r["mean_damage_factor"] - 0.575) < 1e-9
