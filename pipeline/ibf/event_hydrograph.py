"""Wflow hydrographs for a past event: CHIRPS final rainfall, cold start with a spin-up period.

Writes daily discharge [m3/s] at every forecast point to <data_root>/ibf/<name>/wflow_q.csv.
Temperature and PET come from the ERA5 day-of-year climatology (as in the daily forecast).
Needs Julia + Wflow (pipeline/julia) and the built model under <data_root>/model.

    python pipeline/ibf/event_hydrograph.py april2024 --start 2023-10-01 --end 2024-05-31
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import PIPELINE, log, model_grid, paths, to_model_grid, write_forcing  # noqa: E402
from forcing import chirps  # noqa: E402
from run import wflow  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--start", type=date.fromisoformat, required=True, help="cold start, includes spin-up")
    ap.add_argument("--end", type=date.fromisoformat, required=True)
    a = ap.parse_args()

    out = paths.root / "ibf" / a.name
    grid = model_grid()
    precip = chirps.fetch_iri(a.start, a.end)
    days = pd.DatetimeIndex(precip.time.values)
    # Day-of-year climatology (same selection as forcing.era5.from_climatology, which needs hydromt).
    doy = xr.DataArray(days.dayofyear.to_numpy(), dims="time", coords={"time": days})
    clim = xr.open_dataset(PIPELINE / "ops" / "era5_clim.nc").sel(dayofyear=doy).drop_vars("dayofyear")
    t = wflow.forcing_times(days)
    forcing = out / "forcing.nc"
    write_forcing(
        forcing, grid,
        to_model_grid(precip, grid).assign_coords(time=t),
        to_model_grid(clim["temp"], grid).assign_coords(time=t),
        to_model_grid(clim["pet"], grid).assign_coords(time=t),
    )
    run_dir = out / "wflow"
    wflow.run([wflow.write_run(run_dir, a.start, a.end, forcing, None, save_state=False)])

    points = pd.read_csv(PIPELINE / "build" / "forecast_points.csv")
    q = wflow.read_output(run_dir).rename(columns=dict(zip(points.id, points.reach, strict=True)))
    q.to_csv(out / "wflow_q.csv", float_format="%.2f")
    precip.mean(("lat", "lon")).to_series().to_csv(out / "chirps_basin_mean.csv", float_format="%.2f")
    log.info("peak daily Q per reach:\n%s", q.idxmax().to_frame("date").join(q.max().rename("q")))


if __name__ == "__main__":
    main()
