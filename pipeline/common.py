"""Shared paths, configuration and small helpers for the pipeline steps."""

import logging
import os
from functools import cache
from pathlib import Path

import numpy as np
import xarray as xr
import yaml
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"
WEB_DATA = ROOT / "web" / "public" / "data"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("wrff")


@cache
def config() -> dict:
    return yaml.safe_load((PIPELINE / "config.yml").read_text())


def data_root() -> Path:
    p = Path(os.environ.get("WRFF_DATA_ROOT", config()["data_root"]))
    return p if p.is_absolute() else ROOT / p


class Paths:
    """Fixed layout under data_root."""

    @property
    def root(self) -> Path:
        return data_root()

    @property
    def static(self) -> Path:  # cropped global datasets + data catalog
        return self.root / "static"

    @property
    def model(self) -> Path:  # HydroMT-built Wflow model
        return self.root / "model"

    @property
    def forcing(self) -> Path:
        return self.root / "forcing"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def state(self) -> Path:  # persisted between daily runs
        return self.root / "state"

    @property
    def products(self) -> Path:  # thresholds, climatology
        return self.root / "products"


paths = Paths()


def bbox() -> tuple[float, float, float, float]:
    return tuple(config()["region"]["bbox"])


def model_grid() -> xr.Dataset:
    """Coordinates and mask of the Wflow grid, read from the built staticmaps."""
    ds = xr.open_dataset(paths.model / "staticmaps.nc")
    ylat = "latitude" if "latitude" in ds.dims else "y"
    xlon = "longitude" if "longitude" in ds.dims else "x"
    grid = ds[["local_drain_direction"]].rename({ylat: "y", xlon: "x"}).load()
    grid.attrs["model_dims"] = (ylat, xlon)  # restored when writing model inputs
    return grid


def _fill_nearest(da: xr.DataArray) -> xr.DataArray:
    """Fill gaps (e.g. CHIRPS sea and lake pixels) from the nearest valid pixel,
    so interpolation does not carry them onto coastal model cells."""
    gaps = da.isnull()
    while gaps.ndim > 2:  # the gap pattern is the same at every time step
        gaps = gaps.any(gaps.dims[0])
    if not gaps.any():
        return da
    _, (iy, ix) = distance_transform_edt(gaps.transpose("y", "x").values, return_indices=True)
    return da.isel(y=xr.DataArray(iy, dims=("y", "x")), x=xr.DataArray(ix, dims=("y", "x"))).assign_coords(
        y=da.y, x=da.x)


def to_model_grid(da: xr.DataArray, grid: xr.Dataset) -> xr.DataArray:
    """Bilinear interpolation of a lat/lon field onto the model grid.

    Source fields (0.1-0.25 deg) are much coarser than the model (~1 km),
    so bilinear is a reasonable stand-in for conservative remapping.
    """
    da = da.rename({k: v for k, v in {"latitude": "y", "lat": "y", "longitude": "x", "lon": "x"}.items() if k in da.dims})
    da = _fill_nearest(da)
    da = da.sortby("y").interp(y=np.sort(grid.y.values), x=grid.x.values, method="linear")
    da = da.sortby("y", ascending=bool(grid.y[0] < grid.y[-1]))
    return da.where(grid.local_drain_direction.notnull())


def write_forcing(path: Path, grid: xr.Dataset, precip: xr.DataArray, temp: xr.DataArray, pet: xr.DataArray) -> None:
    """Write a Wflow forcing file (daily, mm/day and degC) on the model grid."""
    ds = xr.Dataset({"precip": precip.clip(min=0), "temp": temp, "pet": pet.clip(min=0)})
    ylat, xlon = grid.attrs["model_dims"]
    ds = ds.rename({"y": ylat, "x": xlon})
    enc = {v: {"zlib": True, "complevel": 1, "dtype": "float32", "_FillValue": -9999.0} for v in ds.data_vars}
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.transpose("time", ...).to_netcdf(path, encoding=enc)
