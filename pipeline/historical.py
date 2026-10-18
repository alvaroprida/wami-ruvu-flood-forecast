"""Step 2 - historical simulation and return-period thresholds.

Runs Wflow over the historical period (CHIRPS final + ERA5), one year at a
time with the state carried over, then fits a Gumbel distribution
(L-moments) to the annual maxima of daily discharge at each forecast point.

Outputs (small, committed so the daily job can use them):
  pipeline/ops/thresholds.json   2/5/20/50-year flows per reach
  pipeline/ops/era5_clim.nc      day-of-year temperature/PET climatology
and in <data_root>:
  products/historical_q.csv      simulated daily discharge per reach
  state/                         end-of-period model state (seeds the daily runs)

    python pipeline/historical.py [--years 2001 2002 ...]
"""

import argparse
import json
import shutil
from datetime import date

import numpy as np
import pandas as pd
import xarray as xr

from common import PIPELINE, config, log, model_grid, paths, to_model_grid, write_forcing
from forcing import chirps, era5
from run import wflow

OPS = PIPELINE / "ops"
EULER = 0.5772156649


def gumbel_lmoments(annual_max: np.ndarray, return_periods: list[int]) -> dict[str, float]:
    """Gumbel quantiles from the first two sample L-moments."""
    x = np.sort(annual_max[np.isfinite(annual_max)])
    n = len(x)
    b0 = x.mean()
    b1 = np.sum(np.arange(n) / (n - 1) * x) / n
    l1, l2 = b0, 2 * b1 - b0
    alpha = l2 / np.log(2)
    xi = l1 - EULER * alpha
    return {f"rp{t}": round(float(xi - alpha * np.log(-np.log(1 - 1 / t))), 1) for t in return_periods}


def thresholds(q: pd.DataFrame, reaches: dict[int, str]) -> dict:
    cfg = config()
    q = q[q.index > pd.Timestamp(cfg["historical"]["spinup_end"])]
    complete = q.groupby(q.index.year).size() >= 365   # a partial year would bias the maxima low
    q = q[q.index.year.isin(complete[complete].index)]
    amax = q.groupby(q.index.year).max()
    out = {
        "method": "Gumbel (L-moments) fit to annual maxima of simulated daily discharge",
        "period": [str(amax.index.min()), str(amax.index.max())],
        "reaches": {reaches[pid]: gumbel_lmoments(amax[pid].to_numpy(), cfg["forecast"]["return_periods"])
                    for pid in amax.columns},
    }
    return out


def main() -> None:
    cfg = config()["historical"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", type=int)
    args = ap.parse_args()
    years = args.years or list(range(int(cfg["start"][:4]), int(cfg["end"][:4]) + 1))

    # Temperature/PET first (one request); rainfall is fetched year by year in the
    # loop so the model runs overlap the slow CHIRPS downloads. All steps resume.
    end = date.fromisoformat(cfg["end"])
    era5_monthly = era5.monthly(years, paths.forcing / "era5")
    era5_files = [era5.daily_temp_pet(y, era5_monthly, paths.forcing / "era5") for y in years]
    OPS.mkdir(parents=True, exist_ok=True)
    era5.climatology(era5_files, OPS / "era5_clim.nc")

    grid = model_grid()
    state = None
    q_parts = []
    for year, f_tp in zip(years, era5_files):
        run_dir = paths.runs / "historical" / str(year)
        if (run_dir / "done").exists():  # written only after a successful run
            q_parts.append(wflow.read_output(run_dir))
            state = run_dir / "outstates.nc"
            continue
        f_p = chirps.fetch_years([year], paths.forcing / "chirps", end=end)[0]
        precip = xr.open_dataarray(f_p)
        tp = xr.open_dataset(f_tp).sel(time=precip.time)
        days = pd.DatetimeIndex(precip.time.values)
        forcing = paths.forcing / f"wflow_forcing_{year}.nc"
        write_forcing(
            forcing, grid,
            to_model_grid(precip, grid).assign_coords(time=wflow.forcing_times(days)),
            to_model_grid(tp["temp"], grid).assign_coords(time=wflow.forcing_times(days)),
            to_model_grid(tp["pet"], grid).assign_coords(time=wflow.forcing_times(days)),
        )
        toml = wflow.write_run(run_dir, days[0].date(), days[-1].date(), forcing, state, save_state=True)
        wflow.run([toml])
        q_parts.append(wflow.read_output(run_dir))
        state = run_dir / "outstates.nc"
        (run_dir / "done").touch()
        forcing.unlink()  # ~200 MB per year; regenerated if needed
        log.info("historical %d done", year)

    q = pd.concat(q_parts)
    points = pd.read_csv(PIPELINE / "build" / "forecast_points.csv")
    reaches = dict(zip(points.id, points.reach))
    paths.products.mkdir(parents=True, exist_ok=True)
    q.rename(columns=reaches).to_csv(paths.products / "historical_q.csv", float_format="%.2f")

    thr = thresholds(q, reaches)
    (OPS / "thresholds.json").write_text(json.dumps(thr, indent=1))
    log.info("thresholds: %s", thr["reaches"])

    # Seed the daily warm-state run with the end-of-period state.
    paths.state.mkdir(parents=True, exist_ok=True)
    shutil.copy(state, paths.state / "instates.nc")
    last_day = q.index.max().date()
    (paths.state / "meta.json").write_text(json.dumps({"last_day": last_day.isoformat()}))
    q.rename(columns=reaches).tail(30).to_csv(paths.state / "sim_history.csv", float_format="%.2f")
    log.info("state seeded at end of %s", last_day)


if __name__ == "__main__":
    main()
