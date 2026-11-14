"""Build and run a SFINCS model for one domain, forced with forecast hydrographs.

Written against the hydromt-sfincs 2.0 component API. NOT YET EXECUTED: it needs
the SFINCS executable (Windows exe, or Docker/Singularity on Linux), which was not
available when this was written. Expect to fix small API details on first run.

    python pipeline/ibf/fetch_dem.py ruvu_lower        # 30 m FABDEM mosaic
    python pipeline/ibf/sfincs_model.py ruvu_lower --dem .cache/data/sfincs/dem_ruvu_lower_fabdem30.tif --vm docker
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from hydromt_sfincs import SfincsModel
from hydromt_sfincs.run import run_sfincs

from trigger import ROOT, load_config

LATEST = ROOT / "web" / "public" / "data" / "latest"


def hydrographs(reaches: list[str], scenario: str, latest: Path = LATEST) -> pd.DataFrame:
    """Forecast discharge [m3/s] per inflow reach for one ensemble quantile (e.g. 'p50')."""
    cols = {}
    for r in reaches:
        f = json.loads((latest / "reaches" / f"{r}.json").read_text())["forecast"]
        cols[r] = pd.Series(f[scenario], index=pd.to_datetime(f["times"]).tz_localize(None))
    return pd.DataFrame(cols)


def build(domain: str, dem: Path, root: Path, cfg: dict, tstart, tstop) -> SfincsModel:
    dom = cfg["domains"][domain]
    mod = SfincsModel(root=str(root), mode="w")
    mod.config.update({"tref": tstart, "tstart": tstart, "tstop": tstop, "dtout": 3600, "dthisout": 3600})

    mod.grid.create_from_region(region={"bbox": dom["bbox"]}, res=cfg["res_m"], crs="utm", rotated=False)
    mod.elevation.create(elevation_list=[{"elevation": str(dem), "reproj_method": "bilinear"}])
    # Land above the sea level is active; the coast (cells at or below sea level) is the water-level boundary.
    mod.mask.create_active(zmin=-5.0, fill_area=10.0)
    mod.mask.create_boundary(btype="waterlevel", zmax=dom["sea_level_m"] + 1.0)
    mod.roughness.create(manning_land=0.05, manning_sea=0.02)
    mod.subgrid.create(elevation_list=[{"elevation": str(dem)}], nr_subgrid_pixels=5)
    return mod


def run_scenario(domain: str, dem: Path, scenario: str, out: Path, vm: str | None, exe: Path | None) -> Path:
    cfg = load_config()
    dom = cfg["domains"][domain]
    q = hydrographs(dom["inflow_reaches"], scenario)
    root = out / domain / scenario
    mod = build(domain, dem, root, cfg, q.index[0].to_pydatetime(), q.index[-1].to_pydatetime())

    # Discharge enters where each inflow reach meets the domain boundary: use the reach outlet.
    net = json.loads((ROOT / "web" / "public" / "data" / "network.geojson").read_text())
    outlets = {f["properties"]["id"]: f["properties"]["outlet"] for f in net["features"]}
    import geopandas as gpd
    locs = gpd.GeoDataFrame(
        {"index": range(1, len(q.columns) + 1)},
        geometry=gpd.points_from_xy(*zip(*[outlets[r] for r in q.columns], strict=True)),
        crs=4326,
    ).to_crs(mod.crs).set_index("index")
    q.columns = locs.index
    mod.discharge_points.create(timeseries=q, locations=locs, merge=False)

    mod.write()
    run_sfincs(root, sfincs_exe=exe, vm=vm)
    return root


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--dem", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "data" / "sfincs")
    ap.add_argument("--vm", choices=["docker", "singularity"])
    ap.add_argument("--exe", type=Path)
    a = ap.parse_args()
    for s in load_config()["scenarios"]:
        print(run_scenario(a.domain, a.dem, s, a.out, a.vm, a.exe))
