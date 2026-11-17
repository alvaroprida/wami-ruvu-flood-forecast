"""Discharge forecast for a past date, as the live system would have issued it.

Warm state: Wflow from the end-of-2023 historical state, driven by CHIRPS up to
the day before the issue date. Forecast: the archived ECMWF ENS run of the issue
date (50 members, 15 days). Writes to <data_root>/ibf/forecast_<YYYYMMDD>/:

  members.csv      daily discharge per member and reach (long format)
  p50.csv, p95.csv ensemble quantiles per reach (the IbF scenarios)
  gauges_p50.csv, gauges_p95.csv   the same for the virtual gauges
  observed.csv     simulated discharge on observed rainfall for the SPINUP_DAYS before the issue date
                   (SFINCS spin-up, so the floodplain is not pre-filled at the forecast's first value)
  rain.csv         ensemble-median basin-mean rainfall per lead day [mm/day]

Run with the main pipeline environment (hydromt 1.x + Julia/Wflow).

    python pipeline/ibf/hindcast_forecast.py 2024-01-15
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PIPELINE, config, log, model_grid, paths, to_model_grid, write_forcing  # noqa: E402
from forcing import ens  # noqa: E402
from run import wflow  # noqa: E402

ARCHIVE_SOURCE = "google"     # ECMWF open-data mirror that keeps past runs
SPINUP_DAYS = 7


def _clim(days: pd.DatetimeIndex, grid) -> tuple:
    doy = xr.DataArray(days.dayofyear.to_numpy(), dims="time", coords={"time": days})
    clim = xr.open_dataset(PIPELINE / "ops" / "era5_clim.nc").sel(dayofyear=doy).drop_vars("dayofyear")
    t = wflow.forcing_times(days)
    return (to_model_grid(clim["temp"], grid).assign_coords(time=t),
            to_model_grid(clim["pet"], grid).assign_coords(time=t))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("issue", type=date.fromisoformat)
    ap.add_argument("--resol", default=None, help="ENS grid; default 0p4-beta before Feb 2024, else 0p25")
    a = ap.parse_args()
    issue = a.issue
    resol = a.resol or ("0p4-beta" if issue < date(2024, 2, 1) else "0p25")
    lead = config()["forecast"]["lead_days"]
    out = paths.root / "ibf" / f"forecast_{issue:%Y%m%d}"
    out.mkdir(parents=True, exist_ok=True)
    grid = model_grid()
    names = dict(pd.read_csv(PIPELINE / "build" / "forecast_points.csv")[["id", "reach"]].values)

    # 1. Warm state: end-of-previous-year historical state + CHIRPS up to the day before the issue date.
    state = paths.runs / "historical" / str(issue.year - 1) / "outstates.nc"
    first = date(issue.year, 1, 1)
    if issue > first:
        last = issue - timedelta(days=1)
        precip = xr.open_dataarray(paths.forcing / "chirps" / f"chirps_{issue.year}.nc").sel(time=slice(str(first), str(last)))
        days = pd.DatetimeIndex(precip.time.values)
        temp, pet = _clim(days, grid)
        forcing = out / "warm" / "forcing.nc"
        write_forcing(forcing, grid, to_model_grid(precip, grid).assign_coords(time=wflow.forcing_times(days)), temp, pet)
        wflow.run([wflow.write_run(out / "warm", first, last, forcing, state, save_state=True)])
        state = out / "warm" / "outstates.nc"
        log.info("warm state %s .. %s on CHIRPS", first, last)
        warm_q = wflow.read_output(out / "warm").rename(columns=names)
    else:
        warm_q = pd.DataFrame()
    # Observed-rainfall discharge before the issue date: historical run + this year's warm run.
    hist = pd.read_csv(paths.products / "historical_q.csv", index_col=0, parse_dates=True)
    obs = pd.concat([hist, warm_q]).sort_index()
    obs = obs[~obs.index.duplicated(keep="last")]
    obs.loc[pd.Timestamp(issue) - pd.Timedelta(days=SPINUP_DAYS):pd.Timestamp(issue) - pd.Timedelta(days=1)].to_csv(
        out / "observed.csv", float_format="%.2f")

    # 2. Ensemble forecast from the archived ENS run of the issue date.
    precip = ens.fetch(datetime(issue.year, issue.month, issue.day), lead, source=ARCHIVE_SOURCE, resol=resol)
    days = pd.DatetimeIndex(precip.time.values)
    temp, pet = _clim(days, grid)
    tomls = []
    for m in precip.number.values:
        run_dir = out / "members" / f"m{int(m):02d}"
        member = to_model_grid(precip.sel(number=m, drop=True), grid).assign_coords(time=wflow.forcing_times(days))
        write_forcing(run_dir / "forcing.nc", grid, member, temp, pet)
        tomls.append(wflow.write_run(run_dir, days[0].date(), days[-1].date(), run_dir / "forcing.nc", state, save_state=False))
    wflow.run(tomls)

    rows, grows = [], []
    for t in tomls:
        q = wflow.read_output(t.parent).rename(columns=names)
        q.index.name = "time"
        rows.append(q.reset_index().melt(id_vars="time", var_name="reach", value_name="q").assign(member=t.parent.name))
        g = wflow.read_output(t.parent, "Qv")
        if g.shape[1]:
            g.index.name = "time"
            grows.append(g.reset_index().melt(id_vars="time", var_name="gauge", value_name="q").assign(member=t.parent.name))
        (t.parent / "forcing.nc").unlink()          # ~25 MB each; the discharge is all that is kept
    members = pd.concat(rows)
    members.to_csv(out / "members.csv", index=False, float_format="%.2f")
    wide = members.pivot_table(index=["time", "member"], columns="reach", values="q")
    for qname, qv in (("p50", 0.5), ("p95", 0.95)):
        wide.groupby(level="time").quantile(qv).to_csv(out / f"{qname}.csv", float_format="%.2f")
    if grows:
        gw = pd.concat(grows).pivot_table(index=["time", "member"], columns="gauge", values="q")
        for qname, qv in (("p50", 0.5), ("p95", 0.95)):
            gw.groupby(level="time").quantile(qv).to_csv(out / f"gauges_{qname}.csv", float_format="%.2f")
    rain = precip.mean(("lat", "lon")).median("number").to_series()
    rain.to_csv(out / "rain.csv", float_format="%.2f")
    log.info("forecast %s written to %s; p95 peak per reach:\n%s", issue, out,
             pd.read_csv(out / "p95.csv", index_col=0).max().round(0))


if __name__ == "__main__":
    main()
