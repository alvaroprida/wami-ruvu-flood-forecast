"""ECMWF IFS ENS (open data): daily precipitation for the 50 perturbed members.

Total precipitation (``tp``) is accumulated from the start of the run, so
only the 24-hourly steps are needed: daily totals are the differences of
steps 24, 48, ... 360. That is 15 steps x 50 members of global 0.25 deg
GRIB fields (~1 GB), cropped to the region straight after download.
"""

import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from ecmwf.opendata import Client

from common import bbox, log


def latest_run(client: Client) -> datetime:
    """Most recent 00 UTC ENS run that is complete up to 360 h."""
    return client.latest(stream="enfo", type="pf", param="tp", step=360, time=0)


def fetch(run: datetime, lead_days: int, source: str = "ecmwf") -> xr.DataArray:
    """Daily precipitation [mm/day], dims (number, time, lat, lon).

    ``time`` labels the UTC day the total belongs to; number = member 1-50.
    """
    client = Client(source=source)
    steps = [24 * d for d in range(1, lead_days + 1)]
    w, s, e, n = bbox()
    with tempfile.TemporaryDirectory() as tmp:
        log.info("ENS %s: downloading tp for %d steps", run.isoformat(), len(steps))
        # Open data carries tp for the 50 perturbed members only (no control run).
        target = Path(tmp) / "tp.grib2"
        client.retrieve(
            date=run.date(), time=run.hour, stream="enfo", type="pf",
            param="tp", step=steps, target=str(target),
        )
        ds = xr.open_dataset(target, engine="cfgrib", backend_kwargs={"indexpath": ""})
        tp = ds["tp"].sel(latitude=slice(n + 0.25, s - 0.25), longitude=slice(w - 0.25, e + 0.25)).load()
    if "step" not in tp.dims:
        tp = tp.expand_dims("step")
    acc = tp.transpose("number", "step", "latitude", "longitude")  # accumulated [m]
    zero = xr.zeros_like(acc.isel(step=0))
    daily = xr.concat([zero, acc], "step").diff("step") * 1000.0  # [mm/day]
    # Drop GRIB scalar coords (run time, valid_time, surface) before renaming step -> time.
    daily = daily.drop_vars([c for c in daily.coords if c not in ("number", "step", "latitude", "longitude")])
    days = pd.date_range(pd.Timestamp(run.date()), periods=lead_days, freq="D")
    daily = daily.assign_coords(step=days).rename({"step": "time", "latitude": "lat", "longitude": "lon"})
    return daily.clip(min=0).astype(np.float32).rename("precip").transpose("number", "time", "lat", "lon")
