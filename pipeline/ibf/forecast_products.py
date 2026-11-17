"""Per-lead-day impact products for a forecast (one SFINCS run per scenario).

For every scenario and lead day: building depths (polygons kept), people and
buildings affected, damage, per ward; flood-depth and affected-population
overlays. All buildings go into one PMTiles file whose properties hold the depth
of every scenario/day, so the site restyles them without reloading. Writes to
<out>/ (the site's data/ibf/forecast/):

  manifest.json                 issue date, days, scenarios, hydrographs, totals per day, overlay corners
  wards.json                    people / buildings / damage per ward, scenario and lead day
  admin.geojson                 ward polygons (ids match wards.json)
  buildings.pmtiles             all building footprints: pop, and depth [cm] as "<scenario>_<day>"
  population.png                all people (background, people per ha)
  <scenario>/depth_dNN.png      flood depth on lead day NN
  <scenario>/pop_dNN.png        people in flooded cells on lead day NN

Run with the hydromt-sfincs environment (rasterio, geopandas) and tippecanoe on PATH.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401,E402
import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from rasterio import features  # noqa: E402
from scipy import ndimage  # noqa: E402

from impact import population_on_grid  # noqa: E402
from products import DEPTH_COLORS, POP_COLORS, _colorize, _save_png  # noqa: E402
from trigger import load_config  # noqa: E402
from vulnerability import damage_factor  # noqa: E402

BG_POP_COLORS = [(1, (205, 205, 200)), (5, (170, 170, 165)), (15, (135, 135, 130)), (40, (100, 100, 96))]


def _read_depth(tif: Path):
    with rasterio.open(tif) as src:
        d = np.nan_to_num(src.read(1), nan=0.0).astype("float32")
        d[d > 30] = 0.0                       # gorge / artefact cells, as in products.py
        return d, src.transform, src.crs, src


def build(depths: dict[str, list[Path]], exposure: Path, polygons: Path, pop_tif: Path, admin: Path,
          out: Path, manifest: dict) -> dict:
    """depths: scenario -> list of per-day 30 m depth GeoTIFFs (same grid)."""
    cfg = load_config()
    thr, vuln = cfg["flood_depth_m"], cfg["vulnerability"]["class"]
    out.mkdir(parents=True, exist_ok=True)
    first = next(iter(depths.values()))[0]
    _, transform, crs, like = _read_depth(first)
    with rasterio.open(first) as like:
        pop = population_on_grid(pop_tif, like)
        shape = (like.height, like.width)
    cell_km2 = abs(transform.a * transform.e) * 1e-6

    # Buildings: centroid grid cell (for depth sampling) and ward.
    b = gpd.read_parquet(exposure).to_crs(crs)
    cols, rows = (~transform) * (b.geometry.x.to_numpy(), b.geometry.y.to_numpy())
    rows, cols = np.floor(rows).astype(int), np.floor(cols).astype(int)
    ok = (rows >= 0) & (rows < shape[0]) & (cols >= 0) & (cols < shape[1])
    b, rows, cols = b[ok].reset_index(drop=True), rows[ok], cols[ok]
    wards = gpd.read_file(admin)
    wid = features.rasterize(zip(wards.to_crs(crs).geometry, wards["id"]), out_shape=shape, transform=transform,
                             fill=0, dtype="int32")
    bward = wid[rows, cols]
    n = int(wards["id"].max()) + 1

    bdepth_cm = {}                                    # "<scen>_<day>" -> int16 depth per building (cm)
    ward_rows, totals = [], {}
    corners = None
    for scen, tifs in depths.items():
        (out / scen).mkdir(exist_ok=True)
        totals[scen] = []
        for day, tif in enumerate(tifs, start=1):
            d = _read_depth(tif)[0]
            flooded = d >= thr
            bd = ndimage.maximum_filter(d, size=3)[rows, cols]   # max depth within ~30 m of the centroid
            hit = bd >= thr
            df = np.where(hit, damage_factor(bd, vuln), 0.0)
            bdepth_cm[f"{scen}_{day}"] = np.where(hit, np.round(bd * 100), 0).astype("int16")
            people_w = np.bincount(wid[flooded], weights=pop[flooded], minlength=n)
            bld_w = np.bincount(bward[hit], minlength=n)
            dmg_w = np.bincount(bward[hit], weights=df[hit], minlength=n)
            for i in wards["id"]:
                if people_w[i] > 0.5 or bld_w[i] > 0:
                    ward_rows.append({"scenario": scen, "day": day, "id": int(i), "people": round(float(people_w[i])),
                                      "buildings": int(bld_w[i]), "loss_equiv": round(float(dmg_w[i]), 1)})
            totals[scen].append({"day": day, "people": round(float(pop[flooded].sum())), "buildings": int(hit.sum()),
                                 "loss_equiv": round(float(df.sum()), 1),
                                 "flooded_km2": round(float(flooded.sum() * cell_km2), 1),
                                 "max_depth_m": round(float(d.max()), 2)})
            corners = _save_png(_colorize(d, DEPTH_COLORS), transform, crs, out / scen / f"depth_d{day:02d}.png")
            pop_ha = np.where(flooded, pop / (cell_km2 * 100), 0.0)
            _save_png(_colorize(pop_ha, POP_COLORS), transform, crs, out / scen / f"pop_d{day:02d}.png")
            print(f"  {scen} day {day:2d}: {totals[scen][-1]['people']:>8,} people, {totals[scen][-1]['buildings']:>6,} buildings")

    # Background population (everyone, dimmed) for reference.
    _save_png(_colorize(pop / (cell_km2 * 100), BG_POP_COLORS), transform, crs, out / "population.png")

    # Wards: polygons + per-day table (with ward totals for context).
    pop_w = np.bincount(wid.ravel(), weights=pop.ravel(), minlength=n)
    bld_total_w = np.bincount(bward, minlength=n)
    w = wards.copy()
    w["pop_total"] = [round(float(pop_w[i])) for i in w["id"]]
    w["buildings_total"] = [int(bld_total_w[i]) for i in w["id"]]
    w["geometry"] = w.geometry.simplify(0.0005)
    w.to_file(out / "admin.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
    (out / "wards.json").write_text(json.dumps({
        "wards": w.drop(columns="geometry").to_dict("records"), "rows": ward_rows}, separators=(",", ":")))

    _buildings_pmtiles(b, bdepth_cm, polygons, out / "buildings.pmtiles")
    manifest = {**manifest, "corners": corners, "totals": totals, "flood_depth_threshold_m": thr,
                "depth_legend_m": [c[0] for c in DEPTH_COLORS], "pop_legend_per_ha": [c[0] for c in POP_COLORS],
                "vulnerability": {"source": cfg["vulnerability"]["source"], "class": vuln},
                "buildings_in_domain": int(len(b)), "population_in_domain": round(float(pop.sum()))}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def _buildings_pmtiles(b: gpd.GeoDataFrame, depth_cm: dict, polygons: Path, out: Path) -> None:
    """All footprints with population and only the non-zero depths (keeps the tiles small)."""
    poly = gpd.read_parquet(polygons, columns=["id", "geometry"]).set_index("id")
    g = gpd.GeoDataFrame({"id": b["id"], "pop": b["pop"].round(1)}, geometry=poly.loc[b["id"], "geometry"].values,
                         crs=poly.crs).to_crs(4326)
    keys = list(depth_cm)
    stack = np.stack([depth_cm[k] for k in keys], axis=1)
    g["fmax"] = stack.max(axis=1)                      # max depth over all scenarios/days (cm), for quick filtering
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "buildings.geojsonl"
        with src.open("w") as f:
            for i, (geom, p, fm) in enumerate(zip(g.geometry, g["pop"], g["fmax"])):
                props = {"pop": float(p), "fmax": int(fm)}
                if fm > 0:
                    props |= {k: int(v) for k, v in zip(keys, stack[i]) if v > 0}
                f.write(json.dumps({"type": "Feature", "properties": props,
                                    "geometry": geom.__geo_interface__}, separators=(",", ":")) + "\n")
        subprocess.run(["tippecanoe", "-o", str(out), "--force", "-l", "buildings", "-Z11", "-z15",
                        "--drop-densest-as-needed", "--extend-zooms-if-still-dropping", "--no-tile-size-limit",
                        "-P", str(src)], check=True, capture_output=True)
    print(f"  buildings.pmtiles: {len(g):,} footprints, {out.stat().st_size / 1e6:.1f} MB")
