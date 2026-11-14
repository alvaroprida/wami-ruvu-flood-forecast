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
