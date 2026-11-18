"""Step 1e - virtual river gauges along the main rivers.

Picks Wflow river cells with at least MIN_UPA_KM2 upstream, spaced at least
SPACING_KM apart (greedy from the largest rivers down), adds them to the model
as the map ``gauges_virtual`` (Wflow writes their discharge alongside the
forecast points) and writes web/public/data/gauges.geojson for the site.

Thresholds come from the historical run (historical.py writes
pipeline/ops/thresholds_gauges.json).

    python pipeline/build/make_gauges.py
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import xarray as xr
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import WEB_DATA, log, paths  # noqa: E402

MIN_UPA_KM2 = 1000
SPACING_KM = 20
GAUGE_MAP = "gauges_virtual"
SITE_BASINS = ["Ruvu"]


def main() -> None:
    path = paths.model / "staticmaps.nc"
    ds = xr.load_dataset(path)
    ylat = "latitude" if "latitude" in ds.dims else "y"
    xlon = "longitude" if "longitude" in ds.dims else "x"
    upa = ds["meta_upstream_area"].where(ds["river_mask"] > 0)
    yy, xx = np.meshgrid(ds[ylat].values, ds[xlon].values, indexing="ij")
    cand = np.argwhere((upa >= MIN_UPA_KM2).values)
    order = np.argsort(-upa.values[cand[:, 0], cand[:, 1]])        # largest rivers first

    # Existing forecast points count as already placed, so gauges do not duplicate them.
    pts = ds["gauges_forecast_points"].values
    taken = [(yy[i, j], xx[i, j]) for i, j in np.argwhere(np.isfinite(pts) & (pts > 0))]
    chosen = []
    coslat = np.cos(np.radians(np.nanmean(ds[ylat].values)))
    for k in order:
        i, j = cand[k]
        y, x = yy[i, j], xx[i, j]
        if all(((y - ty) * 111) ** 2 + ((x - tx) * 111 * coslat) ** 2 >= SPACING_KM ** 2 for ty, tx in taken):
            taken.append((y, x))
            chosen.append((i, j))

    gmap = np.full(upa.shape, np.nan, dtype="float32")
    for gid, (i, j) in enumerate(chosen, start=1):
        gmap[i, j] = gid
    ds[GAUGE_MAP] = ((ylat, xlon), gmap)
    ds[GAUGE_MAP].attrs["_FillValue"] = np.nan
    tmp = path.with_suffix(".tmp.nc")
    ds.to_netcdf(tmp)
    tmp.replace(path)

    # Site layer: basin and nearest named reach for the popup.
    net = gpd.read_file(WEB_DATA / "network.geojson").to_crs(32737)
    rows = []
    for gid, (i, j) in enumerate(chosen, start=1):
        p = gpd.GeoSeries([Point(xx[i, j], yy[i, j])], crs=4326).to_crs(32737).iloc[0]
        d = net.distance(p)
        near = net.loc[d.idxmin()]
        rows.append({"id": gid, "upstream_area_km2": int(round(float(upa.values[i, j]))),
                     "basin": near["basin"], "reach": near["id"] if d.min() < 2000 else None,
                     "geometry": Point(round(float(xx[i, j]), 5), round(float(yy[i, j]), 5))})
    # The model writes all gauges; the site shows the Ruvu basin's only (the IbF case study).
    site = gpd.GeoDataFrame(rows, crs=4326)
    site[site["basin"].isin(SITE_BASINS)].to_file(WEB_DATA / "gauges.geojson", driver="GeoJSON")
    log.info("%d virtual gauges (>= %d km2, >= %d km apart) added as %s", len(chosen), MIN_UPA_KM2, SPACING_KM, GAUGE_MAP)


if __name__ == "__main__":
    main()
