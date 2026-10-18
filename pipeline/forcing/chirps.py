"""CHIRPS v2.0 daily precipitation (Climate Hazards Center, UC Santa Barbara).

  final   ~3.5 months latency, station-blended   -> historical run
  prelim  ~6 days latency                        -> daily warm state

Only the region is read: the final product is published as Cloud-Optimised
GeoTIFFs (window reads of a few kB); the prelim files are gzipped GeoTIFFs
streamed through GDAL. No account needed.
"""

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
import xarray as xr
from rasterio.windows import from_bounds

from common import bbox, log

# Let GDAL retry transient HTTP errors itself (the CHC server throttles bursts).
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "3")

BASE = "https://data.chc.ucsb.edu/products/CHIRPS-2.0"
URLS = {
    "final": BASE + "/global_daily/cogs/p05/{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.cog",
    "prelim": BASE + "/prelim/global_daily/tifs/p05/{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.tif.gz",
}


def _url(kind: str, day: date) -> str:
    return URLS[kind].format(y=day.year, m=day.month, d=day.day)


@cache
def _listing(kind: str, year: int) -> frozenset[str]:
    """File names published for one year (one directory request)."""
    url = _url(kind, date(year, 1, 1)).rsplit("/", 1)[0] + "/"
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
    except requests.RequestException as exc:
        # Missing year (404) or CHC refusing us (403 after bursts): treat as not
        # published, so those days fall through to the provisional forcing.
        log.warning("CHIRPS %s listing for %d unavailable: %s", kind, year, exc)
        return frozenset()
    return frozenset(part.split('"')[0] for part in r.text.split('href="')[1:])


def available(kind: str, day: date) -> bool:
    return _url(kind, day).rsplit("/", 1)[1] in _listing(kind, day.year)


def fetch_day(kind: str, day: date) -> xr.DataArray:
    """Daily precipitation [mm/day] for one day, cropped to the region."""
    url = _url(kind, day)
    path = f"/vsigzip//vsicurl/{url}" if url.endswith(".gz") else f"/vsicurl/{url}"
    w, s, e, n = bbox()
    for attempt in range(4):
        try:
            with rasterio.open(path) as src:
                win = from_bounds(w, s, e, n, src.transform).round_offsets().round_lengths()
                arr = src.read(1, window=win).astype("float32")
                transform = src.window_transform(win)
            break
        except rasterio.errors.RasterioIOError:
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    arr[arr < 0] = np.nan  # ocean is -9999 without a declared nodata
    ny, nx = arr.shape
    lon = transform.c + transform.a * (np.arange(nx) + 0.5)
    lat = transform.f + transform.e * (np.arange(ny) + 0.5)
    return xr.DataArray(arr[None], dims=("time", "lat", "lon"),
                        coords={"time": [pd.Timestamp(day)], "lat": lat, "lon": lon}, name="precip")


def fetch_period(kind: str, start: date, end: date, workers: int = 8) -> xr.DataArray:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as pool:
        return xr.concat(list(pool.map(lambda d: fetch_day(kind, d), days)), "time")


IRI_URL = (
    "https://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.daily-improved/.global/.0p05/.prcp"
    "/X/{w}/{e}/RANGEEDGES/Y/{s}/{n}/RANGEEDGES/T/({t0})/({t1})/RANGEEDGES/data.nc"
)
IRI_LAST_URL = (
    "https://iridl.ldeo.columbia.edu/SOURCES/.UCSB/.CHIRPS/.v2p0/.daily-improved/.global/.0p05/.prcp"
    "/T/last/VALUE/X/37/VALUE/Y/-6/VALUE/data.nc"
)


def _julian_to_days(t) -> pd.DatetimeIndex:
    return pd.to_datetime(np.asarray(t, dtype="float64") - 2440587.5, unit="D").normalize()


def _iri_get(url: str) -> bytes:
    for attempt in range(4):
        try:
            r = requests.get(url.replace(" ", "%20"), timeout=1800)
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(30 * (attempt + 1))


def iri_last_day() -> date:
    """Last day the IRI Data Library holds (it lags CHC by a few weeks)."""
    with tempfile.NamedTemporaryFile(suffix=".nc") as tmp:
        Path(tmp.name).write_bytes(_iri_get(IRI_LAST_URL))
        with xr.open_dataset(tmp.name, decode_times=False) as ds:
            return _julian_to_days(ds["T"].values)[-1].date()


def fetch_iri(start: date, end: date) -> xr.DataArray:
    """CHIRPS [mm/day] for a period in one request (server-side subset by IRI/LDEO).

    Used for long periods: reading hundreds of daily files from the CHC server
    gets the client throttled.
    """
    w, s, e, n = bbox()
    url = IRI_URL.format(w=w, e=e, s=s, n=n, t0=start.strftime("%-d %b %Y"), t1=end.strftime("%-d %b %Y"))
    with tempfile.NamedTemporaryFile(suffix=".nc") as tmp:
        Path(tmp.name).write_bytes(_iri_get(url))
        with xr.open_dataset(tmp.name, decode_times=False) as ds:
            da = (ds["prcp"].rename({"T": "time", "Y": "lat", "X": "lon"})
                  .assign_coords(time=_julian_to_days(ds["T"].values)).astype("float32").rename("precip").load())
    if da.sizes["time"] != (end - start).days + 1:
        raise ValueError(f"CHIRPS {start}..{end}: got {da.sizes['time']} days")
    return da


def fetch_years(years: list[int], out_dir: Path, end: date | None = None) -> list[Path]:
    """CHIRPS, one file per year (the last cut at ``end``); resumable."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for y in years:
        path = out_dir / f"chirps_{y}.nc"
        if not path.exists():
            log.info("CHIRPS %d (IRI Data Library)", y)
            tmp = path.with_suffix(".part")
            fetch_iri(date(y, 1, 1), min(date(y, 12, 31), end or date(y, 12, 31))).to_netcdf(tmp)
            tmp.rename(path)
        files.append(path)
    return files
