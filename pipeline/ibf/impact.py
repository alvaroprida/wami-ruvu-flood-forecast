"""Flood depth + exposure -> people and buildings affected.

`impact_from_depth` is pure numpy so it can be tested without GIS libraries;
`population_on_grid` and `building_cells` do the raster/vector alignment
(rasterio, geopandas) and are imported lazily.
"""

import numpy as np

from vulnerability import damage_factor


def _class_label(lo: float, hi: float | None) -> str:
    return f">{lo:g} m" if hi is None else f"{lo:g}-{hi:g} m"


def impact_from_depth(
    depth: np.ndarray,
    pop: np.ndarray,
    bld_rc: tuple[np.ndarray, np.ndarray],
    threshold: float = 0.1,
    classes: list[float] = (0.1, 0.5, 1.0),
    vuln_class: str = "I",
) -> dict:
    """depth, pop: 2-D arrays on the same grid (m, people per cell).
    bld_rc: (row, col) grid index of each building centroid.
    vuln_class: Englhardt et al. (2019) curve applied to every building (informal = "I")."""
    d = np.nan_to_num(depth, nan=0.0)
    p = np.nan_to_num(pop, nan=0.0)
    rows, cols = bld_rc
    bd = d[rows, cols]
    df = damage_factor(bd, vuln_class)

    edges = [*classes, None]
    by_class = {}
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        pm = (d >= lo) if hi is None else (d >= lo) & (d < hi)
        bm = (bd >= lo) if hi is None else (bd >= lo) & (bd < hi)
        by_class[_class_label(lo, hi)] = {"people": float(p[pm].sum()), "buildings": int(bm.sum())}

    return {
        "people_affected": float(p[d >= threshold].sum()),
        "buildings_affected": int((bd >= threshold).sum()),
        # Mean damage factor over the flooded buildings, and the same expressed as whole buildings lost.
        "mean_damage_factor": float(df[bd >= threshold].mean()) if (bd >= threshold).any() else 0.0,
        "building_loss_equivalents": float(df[bd >= threshold].sum()),
        "flooded_area_km2": None,  # set by the caller, which knows the cell size
        "max_depth_m": float(d.max()) if d.size else 0.0,
        "by_depth_class": by_class,
    }


def population_on_grid(pop_tif, like):
    """People per cell of the grid `like` (rasterio dataset or anything with transform/crs/shape).

    WorldPop cells (~100 m) are converted to a density, resampled to the finer grid and multiplied by the
    cell area, so the total is preserved. Cell area is taken in the grid's CRS (metres)."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    with rasterio.open(pop_tif) as src:
        pop = src.read(1, masked=True).filled(0.0).astype("float64")
        # cell area of each WorldPop row in m2 (latitude-dependent), from the cell size in degrees
        lat = src.xy(np.arange(src.height), np.zeros(src.height, dtype=int))[1]
        dy = abs(src.transform.e) * 110_574.0
        dx = abs(src.transform.a) * 111_320.0 * np.cos(np.radians(lat))
        density = pop / (dx * dy)[:, None]
        out = np.zeros(like.shape, dtype="float64")
        reproject(density, out, src_transform=src.transform, src_crs=src.crs, dst_transform=like.transform,
                  dst_crs=like.crs, resampling=Resampling.nearest, src_nodata=None, dst_nodata=0)
    cell_area = abs(like.transform.a * like.transform.e)
    return out * cell_area


def building_cells(buildings_parquet, like):
    """(row, col) of every building centroid that falls inside the grid `like`."""
    import geopandas as gpd

    gdf = gpd.read_parquet(buildings_parquet).to_crs(like.crs)
    c = gdf.geometry.centroid
    rows, cols = rasterio_index(like, c.x.to_numpy(), c.y.to_numpy())
    ok = (rows >= 0) & (rows < like.height) & (cols >= 0) & (cols < like.width)
    return rows[ok], cols[ok]


def rasterio_index(like, x, y):
    inv = ~like.transform
    cols, rows = inv * (x, y)
    return np.floor(rows).astype(int), np.floor(cols).astype(int)
