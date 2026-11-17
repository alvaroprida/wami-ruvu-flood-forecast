"""Build, run and post-process a SFINCS model for one domain, forced with discharge hydrographs.

Uses hydromt-sfincs 1.2.x (hydromt 0.10) and runs the SFINCS Linux binary in a WSL distro
(Windows) or natively (Linux, e.g. the deltares/sfincs-cpu image on CI). Inflow is imposed at the
domain boundary where the inflow reaches enter; the coast is a fixed water-level boundary.

    python pipeline/ibf/sfincs_model.py build ruvu_lower <hydrographs.csv> <run_dir> --dem <dem.tif>
    python pipeline/ibf/sfincs_model.py run <run_dir>
    python pipeline/ibf/sfincs_model.py depth <run_dir> <dem.tif> <depth30.tif>
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401,E402
import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
import yaml  # noqa: E402
from hydromt_sfincs import SfincsModel  # noqa: E402
from hydromt_sfincs.utils import downscale_floodmap  # noqa: E402
from shapely.geometry import Point, box  # noqa: E402
from trigger import ROOT, load_config  # noqa: E402

SEA_LEVEL_M = 0.0
SEA_DEM_M = 0.05         # DEM cells at or below this elevation are sea, not floodplain
WARMUP_DAYS = 3          # constant initial inflow so the river is filled when the event starts
SNAP_RADIUS_M = 600      # inflow points are moved to the lowest DEM cell within this distance


def reach_outlets() -> dict[str, tuple[float, float]]:
    net = json.loads((ROOT / "web" / "public" / "data" / "network.geojson").read_text())
    return {f["properties"]["id"]: tuple(f["properties"]["outlet"]) for f in net["features"]}


def hourly(q: pd.DataFrame) -> pd.DataFrame:
    """Daily or 6-hourly discharge -> hourly, linear in time, plus a constant warm-up before the first value."""
    q = q.resample("1h").interpolate("linear")
    pre = pd.date_range(q.index[0] - pd.Timedelta(days=WARMUP_DAYS), q.index[0], freq="1h", inclusive="left")
    return pd.concat([pd.DataFrame(q.iloc[0].to_dict(), index=pre), q])


def snap_to_lowest(dem_tif: Path, lon: float, lat: float, radius_m: float = SNAP_RADIUS_M) -> tuple[float, float]:
    with rasterio.open(dem_tif) as src:
        r = radius_m / 111_000
        win = rasterio.windows.from_bounds(lon - r, lat - r, lon + r, lat + r, src.transform)
        a = src.read(1, window=win, masked=True)
        i, j = np.unravel_index(np.argmin(a.filled(np.inf)), a.shape)
        x, y = src.xy(int(win.row_off) + i, int(win.col_off) + j)
    return x, y


def build(domain: str, q: pd.DataFrame, dem: Path, root: Path, res_m: float | None = None,
          map_every_s: int = 6 * 3600) -> SfincsModel:
    """q: discharge [m3/s], columns = inflow reach ids, datetime index.
    map_every_s: interval of the water-level maps (3 h for per-lead-day flood maps)."""
    cfg = load_config()
    dom = cfg["domains"][domain]
    res = res_m or cfg["res_m"]
    q = hourly(q)
    root.mkdir(parents=True, exist_ok=True)

    cat = {"fabdem": dict(data_type="RasterDataset", path=str(dem.resolve()), driver="raster", crs=4326, nodata=-9999)}
    (root / "catalog.yml").write_text(yaml.safe_dump(cat))
    logging.basicConfig(level=logging.WARNING)
    sf = SfincsModel(root=str(root), mode="w+", data_libs=[str(root / "catalog.yml")], logger=logging.getLogger("sfincs"))

    region = gpd.GeoDataFrame(geometry=[box(*dom["bbox"])], crs=4326)
    sf.setup_grid_from_region(region={"geom": region}, res=res, crs="utm", rotated=False, align=True)
    fmt = "%Y%m%d %H%M%S"
    sf.setup_config(tref=q.index[0].strftime(fmt), tstart=q.index[0].strftime(fmt), tstop=q.index[-1].strftime(fmt),
                    dtmapout=map_every_s, dthisout=3600, dtmaxout=int((q.index[-1] - q.index[0]).total_seconds()),
                    storemaxwaterlevel=1, dtrstout=0)
    sf.setup_dep(datasets_dep=[{"elevtn": "fabdem"}])
    sf.setup_mask_active(zmin=-5.0, reset_mask=True, fill_area=10.0)
    sf.setup_mask_bounds(btype="waterlevel", zmax=0.05, reset_bounds=True)
    sf.setup_manning_roughness(manning_land=0.05, manning_sea=0.02)
    sf.setup_subgrid(datasets_dep=[{"elevtn": "fabdem"}], nr_subgrid_pixels=6, manning_land=0.05, manning_sea=0.02,
                     write_dep_tif=False, write_man_tif=False)

    # Inflow points: reach outlets snapped onto the DEM's lowest cell (the channel) nearby.
    outlets = reach_outlets()
    pts = [Point(*snap_to_lowest(dem, *outlets[r])) for r in q.columns]
    loc = gpd.GeoDataFrame({"index": range(1, len(pts) + 1)}, geometry=pts, crs=4326).set_index("index").to_crs(sf.crs)
    ts = q.copy()
    ts.columns = loc.index
    sf.setup_discharge_forcing(locations=loc, timeseries=ts, merge=False)

    t = pd.date_range(q.index[0], q.index[-1], freq="1h")
    wl = gpd.GeoDataFrame({"index": [1]}, geometry=[Point(dom["bbox"][2] - 0.01, (dom["bbox"][1] + dom["bbox"][3]) / 2)],
                          crs=4326).set_index("index").to_crs(sf.crs)
    sf.setup_waterlevel_forcing(timeseries=pd.DataFrame({1: SEA_LEVEL_M}, index=t), locations=wl, buffer=200_000)
    sf.write()
    return sf


def _wsl(path: Path) -> str:
    p = path.resolve().as_posix()
    return f"/mnt/{p[0].lower()}{p[2:]}" if len(p) > 1 and p[1] == ":" else p


def run(root: Path, wsl_distro: str | None = None) -> None:
    """Run SFINCS. On Windows a WSL distro with `sfincs` on PATH is used; the model is copied to the Linux
    filesystem first (much faster I/O than /mnt/c) and the results are copied back."""
    root = root.resolve()
    out = root / "out"
    out.mkdir(exist_ok=True)
    if os.name == "nt":
        distro = wsl_distro or os.environ.get("SFINCS_WSL_DISTRO", "sfincs")
        tmp = f"/data/ibf_{root.parent.name}_{root.name}"
        script = (f"rm -rf {tmp} && mkdir -p /data && cp -r '{_wsl(root)}' {tmp} && cd {tmp} && "
                  f"export OMP_NUM_THREADS=${{OMP_NUM_THREADS:-8}} && sfincs > run_stdout.txt 2>&1; rc=$?; "
                  f"cp -f sfincs_map.nc sfincs_his.nc sfincs_log.txt run_stdout.txt '{_wsl(out)}/' 2>/dev/null; exit $rc")
        # SFINCS can exit non-zero after a complete run, so success is judged by its output, not its exit code.
        subprocess.run(["wsl", "-d", distro, "--", "bash", "-c", script])
        done = (out / "run_stdout.txt").exists() and "Simulation finished" in (out / "run_stdout.txt").read_text(errors="ignore")
        if not done or not (out / "sfincs_map.nc").exists():
            raise RuntimeError(f"SFINCS did not finish: see {out / 'run_stdout.txt'}")
    else:
        # Native binary if installed (Linux CI image), otherwise the Docker image (macOS: emulated amd64).
        cmd = ["sfincs"] if shutil.which("sfincs") else [
            "docker", "run", "--rm", "--platform", "linux/amd64", "-v", f"{root}:/data", "deltares/sfincs-cpu"]
        with (out / "run_stdout.txt").open("w") as log:
            subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        if "Simulation finished" not in (out / "run_stdout.txt").read_text(errors="ignore"):
            raise RuntimeError(f"SFINCS did not finish: see {out / 'run_stdout.txt'}")
        for f in ("sfincs_map.nc", "sfincs_his.nc", "sfincs_log.txt"):
            if (root / f).exists():
                shutil.copy(root / f, out / f)


def depth30(root: Path, dem: Path, out_tif: Path, hmin: float = 0.05) -> Path:
    """Maximum depth [m] on the 30 m DEM, downscaled from the subgrid-aware maximum water level."""
    import rioxarray as rxr

    root = root.resolve()
    shutil.copy(root / "out" / "sfincs_map.nc", root / "sfincs_map.nc")
    sf = SfincsModel(root=str(root), mode="r")
    sf.read_results()
    zs = sf.results["zsmax"]
    zs = zs.max("timemax") if "timemax" in zs.dims else zs
    d = rxr.open_rasterio(dem).squeeze(drop=True)
    d = d.where(d > -9000).rio.reproject(zs.raster.crs, resolution=30.0)
    depth = downscale_floodmap(zsmax=zs, dep=d, hmin=hmin, nrmax=2000)
    # The sea is not flooding: FABDEM holds the ocean at exactly 0 m, so those cells are dropped (the coastal
    # water-level boundary can raise the nearshore sea a little). Permanent river water stays in the map.
    depth = depth.where(d > SEA_DEM_M, 0.0)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    depth.rio.to_raster(out_tif, compress="deflate")
    return out_tif


def depth30_daily(root: Path, dem: Path, out_dir: Path, days: pd.DatetimeIndex, hmin: float = 0.05) -> list[Path]:
    """One 30 m depth map per day: the maximum of that day's water-level maps, downscaled like depth30."""
    import rioxarray as rxr

    root = root.resolve()
    shutil.copy(root / "out" / "sfincs_map.nc", root / "sfincs_map.nc")
    sf = SfincsModel(root=str(root), mode="r")
    sf.read_results()
    zs = sf.results["zs"]
    d = rxr.open_rasterio(dem).squeeze(drop=True)
    d = d.where(d > -9000).rio.reproject(zs.raster.crs, resolution=30.0)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, day in enumerate(days, start=1):
        sel = zs.sel(time=slice(day, day + pd.Timedelta(hours=23, minutes=59)))
        if sel.sizes["time"] == 0:
            raise ValueError(f"no SFINCS map output on {day:%Y-%m-%d}")
        depth = downscale_floodmap(zsmax=sel.max("time"), dep=d, hmin=hmin, nrmax=2000)
        depth = depth.where(d > SEA_DEM_M, 0.0)
        path = out_dir / f"depth_d{i:02d}.tif"
        depth.rio.to_raster(path, compress="deflate")
        paths.append(path)
    return paths


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("domain")
    b.add_argument("hydrographs", type=Path)
    b.add_argument("root", type=Path)
    b.add_argument("--dem", type=Path, required=True)
    b.add_argument("--res", type=float)
    r = sub.add_parser("run")
    r.add_argument("root", type=Path)
    d = sub.add_parser("depth")
    d.add_argument("root", type=Path)
    d.add_argument("dem", type=Path)
    d.add_argument("out", type=Path)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.domain, pd.read_csv(a.hydrographs, index_col=0, parse_dates=True), a.dem, a.root, a.res)
    elif a.cmd == "run":
        run(a.root)
    else:
        print(depth30(a.root, a.dem, a.out))
