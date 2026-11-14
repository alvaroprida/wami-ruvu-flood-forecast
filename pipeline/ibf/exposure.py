"""Exposure for one domain: Overture building footprints and WorldPop population.

Buildings get a population estimate: each WorldPop cell's people are shared among the building
centroids in the cell, proportional to footprint area (mass-conserving per cell). WorldPop is
read through /vsicurl, so only the domain window is downloaded.

    python pipeline/ibf/exposure.py ruvu_lower [--out .cache/data/ibf/exposure]
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401,E402
import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import requests  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402
from trigger import ROOT, load_config  # noqa: E402

MIN_FOOTPRINT_M2 = 15       # slivers / sheds


def fetch_buildings(bbox, out: Path) -> Path:
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        w, s, e, n = bbox
        subprocess.run([sys.executable, "-m", "overturemaps.cli", "download", f"--bbox={w},{s},{e},{n}",
                        "-f", "geoparquet", "--type=building", "-o", str(out)], check=True)
    return out


def fetch_population(url: str, bbox, out: Path) -> Path:
    """Crop WorldPop to the domain. The server has no range requests, so the national file (~140 MB) is downloaded once."""
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        full = out.with_name(Path(url).name)
        if not full.exists():
            with requests.get(url, stream=True, timeout=600) as r, full.open("wb") as f:
                r.raise_for_status()
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        with rasterio.open(full) as src:
            win = from_bounds(*bbox, src.transform).round_offsets().round_lengths()
            arr = src.read(1, window=win)
            prof = src.profile | {"height": arr.shape[0], "width": arr.shape[1], "transform": src.window_transform(win),
                                  "compress": "deflate"}
        with rasterio.open(out, "w", **prof) as dst:
            dst.write(arr, 1)
    return out


def buildings_with_population(buildings: Path, pop_tif: Path) -> gpd.GeoDataFrame:
    g = gpd.read_parquet(buildings)
    if "is_underground" in g:
        g = g[~g.is_underground.fillna(False)]
    utm = g.estimate_utm_crs()
    g = g.assign(area_m2=g.to_crs(utm).geometry.area)
    g = g[g.area_m2 >= MIN_FOOTPRINT_M2][["id", "area_m2", "geometry"]].copy()
    cen = g.geometry.centroid
    g["geometry"] = cen                                  # points are enough for depth sampling
    with rasterio.open(pop_tif) as src:
        arr = src.read(1, masked=True).filled(0.0)
        rows, cols = rasterio.transform.rowcol(src.transform, cen.x.to_numpy(), cen.y.to_numpy())
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
    g = g[ok].copy()
    rows, cols = rows[ok], cols[ok]
    cell = rows.astype("int64") * arr.shape[1] + cols
    area_sum = np.bincount(cell, weights=g.area_m2.to_numpy(), minlength=arr.size)
    g["pop"] = arr[rows, cols] * g.area_m2.to_numpy() / area_sum[cell]
    return g.reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "data" / "ibf" / "exposure")
    a = ap.parse_args()
    cfg = load_config()
    bbox = cfg["domains"][a.domain]["bbox"]
    b = fetch_buildings(bbox, a.out / f"buildings_{a.domain}.parquet")
    p = fetch_population(cfg["exposure"]["population"], bbox, a.out / f"population_{a.domain}.tif")
    g = buildings_with_population(b, p)
    g.to_parquet(a.out / f"exposure_{a.domain}.parquet")
    with rasterio.open(p) as src:
        tot = float(src.read(1, masked=True).sum())
    print(f"{len(g):,} buildings, {g['pop'].sum():,.0f} people on buildings (WorldPop window total {tot:,.0f})")
