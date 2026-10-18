"""ECMWF IFS HRES day-1 precipitation, used for the few most recent days
that CHIRPS has not published yet (its prelim product lags ~6 days).

The 00 UTC run's 0-24 h total for day D is a good short-range proxy for
the rainfall of day D. ECMWF's own server keeps only ~4 days of runs, so
the cloud mirrors (which keep an archive) are tried first.
"""

import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from ecmwf.opendata import Client

from common import bbox, log

SOURCES = ("google", "azure", "ecmwf")  # Azure throttles bursts (HTTP 429)


def fetch_day(day: date) -> xr.DataArray:
    """Day-1 precipitation [mm/day] of the 00 UTC run started on ``day``."""
    w, s, e, n = bbox()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "tp.grib2"
        for source in SOURCES:
            try:
                Client(source=source).retrieve(date=day, time=0, stream="oper", type="fc",
                                               param="tp", step=24, target=str(target))
                break
            except Exception as exc:  # mirror missing the date or throttling: try the next one
                log.warning("HRES %s from %s failed: %s", day, source, exc)
        else:
            raise RuntimeError(f"HRES {day} not available from {SOURCES}")
        ds = xr.open_dataset(target, engine="cfgrib", backend_kwargs={"indexpath": ""})
        tp = ds["tp"].sel(latitude=slice(n + 0.25, s - 0.25), longitude=slice(w - 0.25, e + 0.25)).load()
    tp = (tp * 1000.0).clip(min=0).astype(np.float32)                       # m -> mm
    tp = tp.drop_vars([c for c in tp.coords if c not in ("latitude", "longitude")])
    return tp.rename({"latitude": "lat", "longitude": "lon"}).expand_dims(time=[pd.Timestamp(day)]).rename("precip")
