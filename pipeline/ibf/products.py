"""Depth + exposure -> impact summary and the web products (map overlays, affected buildings).

Writes to <out>:
  summary.json        people / buildings affected, by depth class, damage, flooded area
  depth.png           flood-depth overlay (EPSG:4326) + depth.json with its corner coordinates
  population.png      population in the flooded area (people per ha) overlay
  buildings.geojson   affected buildings (centroids) with depth, damage factor and people

    python pipeline/ibf/products.py <depth30.tif> <exposure.parquet> <population.tif> <out_dir> --meta meta.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401,E402
import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from PIL import Image  # noqa: E402
from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: E402
from scipy import ndimage  # noqa: E402

from impact import impact_from_depth, population_on_grid  # noqa: E402
from trigger import load_config  # noqa: E402
from vulnerability import damage_factor  # noqa: E402

DEPTH_COLORS = [(0.1, (166, 206, 227)), (0.5, (66, 146, 198)), (1.0, (33, 102, 172)), (2.0, (8, 48, 107))]
POP_COLORS = [(1, (254, 217, 118)), (5, (253, 141, 60)), (15, (227, 26, 28)), (40, (128, 0, 38))]   # people per ha


def _colorize(a: np.ndarray, classes) -> np.ndarray:
    rgba = np.zeros((*a.shape, 4), dtype="uint8")
    for lo, rgb in classes:
        rgba[a >= lo] = (*rgb, 200)
    return rgba


def _to_wgs84(arr, src_transform, src_crs, resolution_deg=0.00027, nodata=0.0):
    h, w = arr.shape
    left, bottom, right, top = rasterio.transform.array_bounds(h, w, src_transform)
    t, ow, oh = calculate_default_transform(src_crs, "EPSG:4326", w, h, left, bottom, right, top, resolution=resolution_deg)
    out = np.full((oh, ow), nodata, dtype=arr.dtype)
    reproject(arr, out, src_transform=src_transform, src_crs=src_crs, dst_transform=t, dst_crs="EPSG:4326",
              resampling=Resampling.nearest, dst_nodata=nodata)
    return out, rasterio.transform.array_bounds(oh, ow, t)


def _save_png(rgba_utm, transform, crs, path: Path) -> list:
    rgba = np.stack([_to_wgs84(rgba_utm[..., i], transform, crs)[0] for i in range(4)], axis=-1)
    _, (w, s, e, n) = _to_wgs84(rgba_utm[..., 3], transform, crs)
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)
    return [[w, n], [e, n], [e, s], [w, s]]


def _by_ward(admin: Path, out: Path, depth, pop, transform, crs, rc, bd, hit, damage, thr, cell_km2):
    """Aggregate impact per ward; writes admin.geojson (all wards, for the choropleths) and returns the
    wards with any impact, worst first, plus a district roll-up."""
    from rasterio import features

    wards = gpd.read_file(admin)
    ids = features.rasterize(zip(wards.to_crs(crs).geometry, wards["id"]), out_shape=depth.shape,
                             transform=transform, fill=0, dtype="int32")
    n = int(wards["id"].max()) + 1
    flooded = depth >= thr
    rows, cols = rc
    bid = ids[rows, cols]
    w = wards.set_index("id")
    count = lambda m: np.bincount(m, minlength=n)                       # noqa: E731
    people = np.bincount(ids[flooded], weights=pop[flooded], minlength=n)
    w["people"] = people[w.index].round(0)
    w["pop_total"] = np.bincount(ids.ravel(), weights=pop.ravel(), minlength=n)[w.index].round(0)
    w["buildings"] = count(bid[hit])[w.index]
    w["buildings_total"] = count(bid)[w.index]
    w["area_km2"] = (count(ids[flooded])[w.index] * cell_km2).round(2)
    w["max_depth"] = [float(depth[ids == i].max()) if (ids == i).any() else 0.0 for i in w.index]
    w["max_depth"] = w["max_depth"].round(2)
    dmg = np.bincount(bid[hit], weights=damage, minlength=n)
    w["damage"] = np.where(w["buildings"] > 0, dmg[w.index] / np.maximum(w["buildings"], 1), 0.0).round(2)
    w = w.reset_index()
    w["geometry"] = w.geometry.simplify(0.0005)
    w.to_file(out / "admin.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)

    keep = ["id", "ward", "district", "people", "buildings", "area_km2", "max_depth", "damage", "pop_total", "buildings_total"]
    areas = w[(w.people > 0) | (w.buildings > 0)].sort_values("people", ascending=False)[keep]
    dist = (w.groupby("district")[["people", "buildings", "pop_total", "buildings_total"]].sum()
            .reset_index().sort_values("people", ascending=False))
    dist = dist[(dist.people > 0) | (dist.buildings > 0)]
    return areas.to_dict("records"), dist.to_dict("records")


def build(depth_tif: Path, exposure: Path, pop_tif: Path, out: Path, meta: dict, admin: Path | None = None) -> dict:
    cfg = load_config()
    thr, classes = cfg["flood_depth_m"], cfg["depth_classes_m"]
    vuln = cfg["vulnerability"]["class"]
    out.mkdir(parents=True, exist_ok=True)

    with rasterio.open(depth_tif) as src:
        depth = np.nan_to_num(src.read(1), nan=0.0).astype("float32")
        depth[depth > 30] = 0.0              # a few gorge / artefact cells; nothing physical is this deep
        transform, crs = src.transform, src.crs
        like = src
        pop = population_on_grid(pop_tif, like)
    cell_km2 = abs(transform.a * transform.e) * 1e-6

    # buildings: maximum depth within ~30 m of the centroid
    dmax = ndimage.maximum_filter(depth, size=3)
    b = gpd.read_parquet(exposure)
    bu = b.to_crs(crs)
    cols, rows = (~transform) * (bu.geometry.x.to_numpy(), bu.geometry.y.to_numpy())
    rows, cols = np.floor(rows).astype(int), np.floor(cols).astype(int)
    ok = (rows >= 0) & (rows < depth.shape[0]) & (cols >= 0) & (cols < depth.shape[1])
    b, rows, cols = b[ok].copy(), rows[ok], cols[ok]
    bd = dmax[rows, cols]

    res = impact_from_depth(depth, pop, (rows, cols), threshold=thr, classes=classes, vuln_class=vuln,
                            bld_depth=dmax)
    res["flooded_area_km2"] = float((depth >= thr).sum() * cell_km2)
    res["buildings_in_domain"] = int(len(b))

    # affected buildings
    hit = bd >= thr
    a = b[hit].copy()
    a["depth"] = bd[hit].round(2)
    a["damage"] = damage_factor(a["depth"].to_numpy(), vuln).round(2)
    a["pop"] = a["pop"].round(1)
    a = a[["depth", "damage", "pop", "geometry"]]
    a.geometry = a.geometry.set_precision(1e-5)
    a.to_file(out / "buildings.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)

    if admin is not None:
        res["areas"], res["districts"] = _by_ward(admin, out, depth, pop, transform, crs, (rows, cols), bd, hit,
                                                  a["damage"].to_numpy(), thr, cell_km2)

    # overlays
    depth_rgba = _colorize(depth, DEPTH_COLORS)
    corners = _save_png(depth_rgba, transform, crs, out / "depth.png")
    pop_ha = np.where(depth >= thr, pop / (cell_km2 * 100), 0.0)      # people per hectare
    _save_png(_colorize(pop_ha, POP_COLORS), transform, crs, out / "population.png")
    (out / "depth.json").write_text(json.dumps({"corners": corners}))

    summary = {**meta, **res,
               "flood_depth_threshold_m": thr, "vulnerability": {"source": cfg["vulnerability"]["source"], "class": vuln},
               "population_note": "People from the WorldPop 2025 100 m constrained grid in flooded cells (conserves the total).",
               "depth_legend_m": [c[0] for c in DEPTH_COLORS]}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("depth", type=Path)
    ap.add_argument("exposure", type=Path)
    ap.add_argument("population", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--meta", type=Path)
    ap.add_argument("--admin", type=Path, help="ward polygons from admin.py")
    a = ap.parse_args()
    s = build(a.depth, a.exposure, a.population, a.out, json.loads(a.meta.read_text()) if a.meta else {}, a.admin)
    print({k: s[k] for k in ("people_affected", "buildings_affected", "flooded_area_km2", "max_depth_m",
                              "mean_damage_factor", "building_loss_equivalents")})
