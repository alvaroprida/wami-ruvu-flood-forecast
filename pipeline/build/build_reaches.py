"""Step 1d - river geometry for the site, from the model's own flow network.

Replaces the hand-assembled OpenStreetMap reaches with lines traced on the
FABDEM-derived network (3 arcsec) that the Wflow model is built from, so the
map shows exactly what the model routes:

  network.geojson   one line per forecast reach: the main channel from its
                    forecast point upstream to the next forecast point, or to
                    the headwaters (main channel = largest upstream area)
  rivers.geojson    background network (>= MIN_UPA_KM2) inside the model domain,
                    with upstream area for line width

    python pipeline/build/build_reaches.py
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyflwdir
import rasterio
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import WEB_DATA, log, paths  # noqa: E402

MIN_UPA_KM2 = 100        # background rivers
HEADWATER_UPA_KM2 = 20   # main-channel trace stops below this upstream area
SNAP_WINDOW = 12         # cells (~1 km at 3 arcsec) to look for the point on the fine network
SIMPLIFY_DEG = 0.0015    # ~150 m


def main() -> None:
    hydro = paths.static / "hydrography"
    with rasterio.open(hydro / "dir.tif") as src:
        d8, transform = src.read(1), src.transform
    with rasterio.open(hydro / "upa.tif") as src:
        upa = src.read(1)
    flw = pyflwdir.from_array(d8, ftype="d8", transform=transform, latlon=True)
    main_up = flw.main_upstream(uparea=upa).ravel()
    ncol = upa.shape[1]

    net = json.loads((WEB_DATA / "network.geojson").read_text())
    gauges = gpd.read_file(paths.model / "staticgeoms" / "gauges_forecast_points.geojson").set_index("reach")

    # Forecast points on the fine network: the cell near the model gauge whose
    # upstream area best matches the model's value for that point.
    point_idx = {}
    for f in net["features"]:
        rid, target = f["properties"]["id"], f["properties"]["upstream_area_km2"]
        g = gauges.loc[rid].geometry
        r0, c0 = rasterio.transform.rowcol(transform, g.x, g.y)
        win = upa[r0 - SNAP_WINDOW:r0 + SNAP_WINDOW + 1, c0 - SNAP_WINDOW:c0 + SNAP_WINDOW + 1]
        rr, cc = np.unravel_index(np.argmin(np.abs(win - target)), win.shape)
        r, c = r0 - SNAP_WINDOW + rr, c0 - SNAP_WINDOW + cc
        point_idx[rid] = r * ncol + c
        log.info("%-12s model %6d km2  fine network %8.0f km2", rid, target, upa[r, c])

    stops = set(point_idx.values())
    for f in net["features"]:
        rid = f["properties"]["id"]
        idx, path = point_idx[rid], [point_idx[rid]]
        while True:
            up = main_up[idx]
            if up < 0 or upa.flat[up] < HEADWATER_UPA_KM2 or up in stops:
                if up in stops:
                    path.append(up)  # join the reach upstream without a gap
                break
            path.append(up)
            idx = up
        rows, cols = np.divmod(np.array(path[::-1]), ncol)
        xs, ys = rasterio.transform.xy(transform, rows, cols)
        line = LineString(zip(xs, ys)).simplify(SIMPLIFY_DEG)
        f["geometry"] = {"type": "MultiLineString",
                         "coordinates": [[[round(x, 5), round(y, 5)] for x, y in line.coords]]}
        x, y = rasterio.transform.xy(transform, *divmod(point_idx[rid], ncol))
        f["properties"]["outlet"] = [round(x, 5), round(y, 5)]
    net["attribution"] = "River geometry derived from FABDEM V1-2 (Hawker et al. 2022) with pyflwdir"
    (WEB_DATA / "network.geojson").write_text(json.dumps(net, separators=(",", ":")))

    # Background network, clipped to the model domain.
    region = gpd.read_file(paths.model / "staticgeoms" / "region.geojson").to_crs(4326)
    rivers = gpd.read_file(paths.static / "rivers.gpkg")
    rivers = rivers[rivers["uparea"] >= MIN_UPA_KM2]
    rivers = gpd.clip(rivers, region.union_all())
    rivers["geometry"] = rivers.geometry.simplify(SIMPLIFY_DEG)
    rivers["uparea"] = rivers["uparea"].round().astype(int)
    rivers[["uparea", "geometry"]].to_file(WEB_DATA / "rivers.geojson", driver="GeoJSON", COORDINATE_PRECISION=5)
    log.info("wrote network.geojson (%d reaches) and rivers.geojson (%d segments)", len(net["features"]), len(rivers))


if __name__ == "__main__":
    main()
