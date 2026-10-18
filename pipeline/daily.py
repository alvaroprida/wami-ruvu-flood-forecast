"""Steps 3 + 4 - daily warm-state update and ensemble forecast.

1. Warm state: advance the persisted model state through every day that
   CHIRPS has published (final where available, else prelim), with
   temperature/PET from the ERA5 climatology.
2. Provisional days: CHIRPS prelim lags ~6 days, so the days up to the
   forecast start use the ECMWF HRES day-1 forecast. They are re-run with
   CHIRPS once it is published, so that state is not persisted.
3. Forecast: one Wflow run per ECMWF ENS member, 15 days ahead.
4. Products: per-reach ensemble quantiles, exceedance probabilities, alert
   levels and catchment rainfall, written as the site's JSON files.

    python pipeline/daily.py [--out web/public/data/latest]
"""

import argparse
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyflwdir
import xarray as xr
from ecmwf.opendata import Client

from common import PIPELINE, WEB_DATA, config, log, model_grid, paths, to_model_grid, write_forcing
from forcing import chirps, era5, ens, hres
from run import wflow

OPS = PIPELINE / "ops"


def _clim_forcing(days: pd.DatetimeIndex, grid: xr.Dataset) -> tuple[xr.DataArray, xr.DataArray]:
    clim = era5.from_climatology(OPS / "era5_clim.nc", days)
    t = wflow.forcing_times(days)
    return (to_model_grid(clim["temp"], grid).assign_coords(time=t),
            to_model_grid(clim["pet"], grid).assign_coords(time=t))


def _run_observed(name: str, days: list[date], precip: xr.DataArray, state, grid, save_state: bool):
    idx = pd.DatetimeIndex(days)
    temp, pet = _clim_forcing(idx, grid)
    forcing = paths.runs / name / "forcing.nc"
    write_forcing(forcing, grid, to_model_grid(precip, grid).assign_coords(time=wflow.forcing_times(idx)), temp, pet)
    run_dir = paths.runs / name
    toml = wflow.write_run(run_dir, days[0], days[-1], forcing, state, save_state=save_state)
    wflow.run([toml])
    return run_dir


def warm_state(run_start: date, grid: xr.Dataset) -> tuple:
    """Return (state at run_start, simulated history) and persist the firm state."""
    meta = json.loads((paths.state / "meta.json").read_text())
    last = date.fromisoformat(meta["last_day"])
    history = pd.read_csv(paths.state / "sim_history.csv", index_col=0, parse_dates=True)
    reaches = _reach_names()

    # Firm days: published by CHIRPS. Long catch-ups come from IRI in one
    # request; the newest days (not yet at IRI) are read from CHC one by one.
    firm = []
    d = last + timedelta(days=1)
    iri_last = chirps.iri_last_day() if (run_start - d).days > 10 else d - timedelta(days=1)
    while d < run_start and (d <= iri_last or chirps.available("final", d) or chirps.available("prelim", d)):
        firm.append(d)
        d += timedelta(days=1)
    state = paths.state / "instates.nc"
    if firm:
        log.info("warm state: %s .. %s on CHIRPS", firm[0], firm[-1])
        parts = []
        bulk = [day for day in firm if day <= iri_last]
        if bulk:
            parts.append(chirps.fetch_iri(bulk[0], bulk[-1]))
        # Newest days one at a time from CHC (it throttles bursts). If a read fails,
        # the firm period ends there and the remaining days become provisional.
        for day in (day for day in firm if day > iri_last):
            try:
                parts.append(chirps.fetch_day("final" if chirps.available("final", day) else "prelim", day))
            except Exception as exc:  # noqa: BLE001 - any CHC failure: fall back, don't stop the forecast
                log.warning("CHIRPS %s unreadable (%s): later days use HRES", day, exc)
                firm = firm[: firm.index(day)]
                break
    if firm:
        precip = xr.concat(parts, "time")
        run_dir = _run_observed("warm", firm, precip, state, grid, save_state=True)
        shutil.copy(run_dir / "outstates.nc", state)
        history = pd.concat([history, wflow.read_output(run_dir).rename(columns=reaches)])
        meta["last_day"] = firm[-1].isoformat()
        (paths.state / "meta.json").write_text(json.dumps(meta))
        history.tail(60).to_csv(paths.state / "sim_history.csv", float_format="%.2f")

    # Provisional days up to the forecast start (not persisted).
    prov = [date.fromisoformat(meta["last_day"]) + timedelta(days=i + 1)
            for i in range((run_start - date.fromisoformat(meta["last_day"])).days - 1)]
    if prov:
        log.info("provisional: %s .. %s on HRES day-1 forecasts", prov[0], prov[-1])
        fields = []
        for day in prov:
            try:
                fields.append(hres.fetch_day(day))
            except RuntimeError:
                log.warning("no HRES for %s: using the previous ENS day-1 mean", day)
                fallback = xr.open_dataarray(paths.state / "ens_day1_mean.nc")
                fields.append(fallback.expand_dims(time=[pd.Timestamp(day)]))
        # CHIRPS (0.05 deg) and HRES (0.25 deg) grids differ; each is regridded to the model.
        precip = xr.concat([to_model_grid(f, grid) for f in fields], "time")
        run_dir = _run_observed("provisional", prov, precip, state, grid, save_state=True)
        state = run_dir / "outstates.nc"
        history = pd.concat([history, wflow.read_output(run_dir).rename(columns=reaches)])
    return state, history


def _reach_names() -> dict[int, str]:
    pts = pd.read_csv(PIPELINE / "build" / "forecast_points.csv")
    return dict(zip(pts.id, pts.reach))


def upstream_masks(grid: xr.Dataset) -> dict[str, xr.DataArray]:
    """Full upstream catchment of each forecast point on the model grid."""
    ds = xr.open_dataset(paths.model / "staticmaps.nc")
    ylat, xlon = grid.attrs["model_dims"]
    ldd = ds["local_drain_direction"].rename({ylat: "y", xlon: "x"})
    gauges = ds[wflow.GAUGE_MAP].rename({ylat: "y", xlon: "x"})
    # Basin delineation only needs the topology, not the cell geometry.
    flw = pyflwdir.from_array(ldd.fillna(255).astype("uint8").values, ftype="ldd")
    masks = {}
    for pid, reach in _reach_names().items():
        idx = np.flatnonzero(gauges.values.ravel() == pid)
        basin = flw.basins(idxs=idx)
        masks[reach] = xr.DataArray(basin > 0, dims=("y", "x"), coords={"y": grid.y, "x": grid.x})
    return masks


def forecast(run, grid: xr.Dataset, state) -> tuple[dict[str, np.ndarray], pd.DatetimeIndex, xr.DataArray]:
    cfg = config()["forecast"]
    precip = ens.fetch(run, cfg["lead_days"])                        # (number, time, lat, lon)
    days = pd.DatetimeIndex(precip.time.values)
    temp, pet = _clim_forcing(days, grid)
    tomls = []
    for m in precip.number.values:
        run_dir = paths.runs / "forecast" / f"m{int(m):02d}"
        forcing = run_dir / "forcing.nc"
        member = to_model_grid(precip.sel(number=m, drop=True), grid).assign_coords(time=wflow.forcing_times(days))
        write_forcing(forcing, grid, member, temp, pet)
        tomls.append(wflow.write_run(run_dir, days[0].date(), days[-1].date(), forcing, state, save_state=False))
    wflow.run(tomls)
    reaches = _reach_names()
    q = {r: np.stack([wflow.read_output(t.parent)[pid].to_numpy() for t in tomls]) for pid, r in reaches.items()}
    # Day-1 ensemble mean: last-resort forcing if HRES is unavailable tomorrow.
    precip.isel(time=0).mean("number").to_netcdf(paths.state / "ens_day1_mean.nc")
    return q, days, precip


def iso(t) -> str:
    return pd.Timestamp(t).strftime("%Y-%m-%dT%H:%MZ")


def products(run, days, q: dict, precip: xr.DataArray, history: pd.DataFrame, grid, out_dir) -> None:
    cfg = config()["forecast"]
    thr = json.loads((OPS / "thresholds.json").read_text())["reaches"]
    masks = upstream_masks(grid)
    rule = cfg["alert_rule"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reaches").mkdir(exist_ok=True)
    hist = history.tail(cfg["history_days"])

    summaries = {}
    for reach, members in q.items():                                  # members: (n_members, n_days)
        pct = {f"p{p:02d}": np.percentile(members, p, axis=0) for p in (5, 25, 50, 75, 95)}
        peaks = members.max(axis=1)
        prob = {k: round(float((peaks > v).mean()), 2) for k, v in thr[reach].items()}
        level = next((lvl for lvl, rp, share in rule if prob[f"rp{rp}"] >= share), 0)
        i_peak = int(np.argmax(pct["p50"]))

        # Catchment-mean rainfall per member and day.
        rain = to_model_grid(precip, grid).where(masks[reach]).mean(("y", "x")).values  # (number, time)
        detail = {
            "id": reach,
            "issued": iso(run),
            "units": "m3/s",
            "history": {"times": [iso(t) for t in hist.index], "q": [round(float(v), 1) for v in hist[reach]]},
            "forecast": {
                "times": [iso(t) for t in days],
                **{k: [round(float(v), 1) for v in a] for k, a in pct.items()},
                "members": [[round(float(v), 1) for v in m] for m in members],
            },
            "thresholds": thr[reach],
            "rainfall": {
                "days": [iso(t) for t in days],
                **{f"p{p}": [round(float(v), 1) for v in np.percentile(rain, p, axis=0)] for p in (10, 50, 90)},
            },
        }
        (out_dir / "reaches" / f"{reach}.json").write_text(json.dumps(detail, separators=(",", ":")))
        summaries[reach] = {
            "alert_level": level,
            "prob_exceed": prob,
            "peak_q50": round(float(pct["p50"][i_peak]), 1),
            "peak_time": iso(days[i_peak]),
            "thresholds": thr[reach],
        }

    (out_dir / "forecast.json").write_text(json.dumps({
        "issued": iso(run),
        "mock": False,
        "model": "Wflow.jl (sbm), 1 km, daily",
        "forcing": f"ECMWF ENS open data, {precip.sizes['number']} members",
        "members": int(precip.sizes["number"]),
        "timestep_hours": 24,
        "lead_days": cfg["lead_days"],
        "alert_rule": [{"level": lvl, "return_period": rp, "min_probability": s} for lvl, rp, s in rule],
        "reaches": summaries,
    }, indent=1))
    log.info("products written to %s", out_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(WEB_DATA / "latest"))
    args = ap.parse_args()

    run = ens.latest_run(Client(source="ecmwf"))
    log.info("latest complete ENS run: %s", run)
    grid = model_grid()
    state, history = warm_state(run.date(), grid)
    q, days, precip = forecast(run, grid, state)
    products(run, days, q, precip, history, grid, Path(args.out))


if __name__ == "__main__":
    main()
