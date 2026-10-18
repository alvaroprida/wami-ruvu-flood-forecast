"""ERA5 temperature and De Bruin potential evaporation (Copernicus CDS).

Built from ERA5 *monthly means*: one CDS request covers all years, where daily
statistics need a request per variable-year, each waiting minutes to hours in
the CDS queue. Daily values are interpolated between mid-month values. In these
basins that loses little: PET varies mostly with the season, and temperature
only drives snow, which the model does not use.

Used for the historical run, and for the day-of-year climatology that fills
temperature/PET in the daily runs (ERA5 arrives ~5 days late, which a daily
scheduled job cannot wait for).

Needs a CDS API key in ~/.cdsapirc.
"""

import zipfile
from pathlib import Path

import cdsapi
import numpy as np
import pandas as pd
import xarray as xr
from hydromt.model.processes.meteo import pet_debruin

from common import bbox, log

DATASET = "reanalysis-era5-single-levels-monthly-means"
VARIABLES = {
    "2m_temperature": "t2m",
    "surface_pressure": "sp",
    "surface_solar_radiation_downwards": "ssrd",
    "toa_incident_solar_radiation": "tisr",
}


def _open(path: Path) -> xr.Dataset:
    """CDS returns either a netCDF file or a zip holding several."""
    if zipfile.is_zipfile(path):
        out = path.with_suffix("")
        with zipfile.ZipFile(path) as z:
            z.extractall(out)
        # Instant and accumulated fields come in separate files stamped 00 and 06 UTC
        # of the same month: align them on the day before merging.
        parts = []
        for p in sorted(out.glob("*.nc")):
            ds = xr.open_dataset(p)
            parts.append(ds.assign_coords(valid_time=ds["valid_time"].dt.floor("D")))
        return xr.merge(parts, compat="override")
    return xr.open_dataset(path)


def monthly(years: list[int], out_dir: Path) -> xr.Dataset:
    """Monthly mean temperature [degC] and PET [mm/day], all years in one request."""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"era5_monthly_{years[0]}_{years[-1]}.download"
    if not raw.exists():
        w, s, e, n = bbox()
        log.info("ERA5 monthly means %d-%d (one CDS request, may queue)", years[0], years[-1])
        tmp = raw.with_suffix(".part")
        cdsapi.Client().retrieve(DATASET, {
            "product_type": ["monthly_averaged_reanalysis"],
            "variable": list(VARIABLES),
            "year": [str(y) for y in years],
            "month": [f"{m:02d}" for m in range(1, 13)],
            "time": ["00:00"],
            "data_format": "netcdf",
            "download_format": "unarchived",
            "area": [n + 0.25, w - 0.25, s - 0.25, e + 0.25],
        }, str(tmp))
        tmp.rename(raw)
    ds = _open(raw)
    ds = ds.rename({"valid_time": "time"}) if "valid_time" in ds.dims else ds
    ds = ds.drop_vars([c for c in ds.coords if c not in ("time", "latitude", "longitude")])
    temp = ds["t2m"] - 273.15
    press = ds["sp"] / 100.0                      # Pa -> hPa
    # Monthly means of accumulated fields are mean daily totals [J m-2 day-1] -> W m-2.
    k_in, k_ext = ds["ssrd"] / 86400.0, ds["tisr"] / 86400.0
    if not 100 < float(k_ext.mean()) < 500:
        raise ValueError(f"unexpected TOA radiation {float(k_ext.mean()):.0f} W m-2: check ERA5 units")
    pet = pet_debruin(temp, press, k_in, k_ext, timestep=86400)
    out = xr.Dataset({"temp": temp.astype(np.float32), "pet": pet.astype(np.float32)})
    return out.rename({"latitude": "lat", "longitude": "lon"})


def daily_temp_pet(year: int, monthly_ds: xr.Dataset, out_dir: Path) -> Path:
    """Daily temperature/PET for one year, interpolated between mid-month values."""
    path = out_dir / f"era5_temp_pet_{year}.nc"
    if path.exists():
        return path
    mid = monthly_ds.assign_coords(time=pd.DatetimeIndex(monthly_ds.time.values) + pd.Timedelta(days=14))
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    daily = mid.interp(time=days, method="linear", kwargs={"fill_value": "extrapolate"})
    daily.astype(np.float32).to_netcdf(path)
    return path


def climatology(files: list[Path], out: Path) -> Path:
    """Day-of-year mean temperature and PET (366 days)."""
    ds = xr.open_mfdataset(files, combine="by_coords")
    clim = ds.groupby("time.dayofyear").mean().load()
    clim.to_netcdf(out)
    log.info("wrote %s", out)
    return out


def from_climatology(clim_path: Path, times) -> xr.Dataset:
    """Temperature/PET for the given dates, taken from the day-of-year climatology."""
    clim = xr.open_dataset(clim_path)
    doy = xr.DataArray([t.dayofyear for t in times], dims="time", coords={"time": times})
    return clim.sel(dayofyear=doy).drop_vars("dayofyear")
