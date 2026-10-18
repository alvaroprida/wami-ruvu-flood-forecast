"""Step 1a - fetch and crop the static datasets for the model build.

Everything is cropped to the region bbox on the fly, so the global archives
never need to be stored:

  hydrography/   FABDEM V1-2 (30 m) resampled to 3 arcsec, rivers burned in, and
                 flow direction / upstream area / basins / stream order / slope /
                 river width derived with pyflwdir (MERIT Hydro-style layers)
  soilgrids/     SoilGrids 2020 (6 depth intervals) + depth to bedrock from SoilGrids 2017
  esa_worldcover.tif   ESA WorldCover 2021, resampled to ~100 m (majority)
  hydrolakes.gpkg      HydroLAKES v1.0 lakes and reservoirs in the region
  data_catalog.yml     HydroMT catalog pointing at the files above

    python pipeline/static/fetch_static.py [--only hydrography soil landcover lakes]
"""

import argparse
import math
import sys
import zipfile
from pathlib import Path

import fsspec
import geopandas as gpd
import numpy as np
import pyflwdir
import rasterio
import rasterio.features
import rasterio.warp
import yaml
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PIPELINE, WEB_DATA, bbox, log, paths  # noqa: E402

FABDEM_URL = "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/{pkg}_FABDEM_V1-2.zip"
HYDRO_RES = 1 / 1200      # 3 arcsec
BURN_DEPTH_M = 10.0       # depth the OSM rivers are carved in before routing
RIVWTH_A, RIVWTH_B = 1.0, 0.4   # width [m] = A * upstream_area[km2] ** B
QBF_A, QBF_B = 0.3, 0.75        # bankfull discharge [m3/s] = A * upstream_area[km2] ** B
RIVER_MIN_UPA_KM2 = 10          # river vectors (model river mask starts at 30 km2)

SOILGRIDS_URL = "https://files.isric.org/soilgrids/latest/data/{prop}/{prop}_{depth}_mean.vrt"
SOILGRIDS_DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm", "100-200cm"]
# SoilGrids 2020 property -> (HydroMT name, factor to HydroMT units)
SOILGRIDS_PROPS = {
    "bdod": ("bd", 0.01),      # cg/cm3 -> g/cm3
    "clay": ("clyppt", 0.1),   # g/kg -> %
    "silt": ("sltppt", 0.1),
    "sand": ("sndppt", 0.1),
    "soc": ("oc", 0.01),       # dg/kg -> %
    "phh2o": ("ph", 0.1),      # pH*10 -> pH
}
BEDROCK_URL = "https://files.isric.org/soilgrids/former/2017-03-10/data/BDRICM_M_250m_ll.tif"
SOIL_RES = 0.0025  # 250 m

WORLDCOVER_URL = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
WORLDCOVER_RES = 0.001  # ~100 m; the model is ~1 km so 10 m is not needed

HYDROLAKES_URL = (
    "/vsizip//vsicurl/https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip"
    "/HydroLAKES_polys_v10_shp/HydroLAKES_polys_v10.shp"
)


def _tiles(step: int, fmt) -> list[str]:
    """Names of the step x step deg tiles (lower-left corner naming) covering the bbox."""
    w, s, e, n = bbox()
    out = []
    for lat in range(math.floor(s / step) * step, math.ceil(n / step) * step, step):
        for lon in range(math.floor(w / step) * step, math.ceil(e / step) * step, step):
            out.append(fmt(lat, lon))
    return out


def _write(path: Path, arr: np.ndarray, transform, nodata, dtype=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = arr.astype(dtype or arr.dtype)
    with rasterio.open(
        path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=arr.dtype,
        crs="EPSG:4326", transform=transform, nodata=nodata, compress="deflate", tiled=True,
    ) as dst:
        dst.write(arr, 1)


def fetch_hydrography() -> None:
    """FABDEM tiles -> 3 arcsec DEM -> flow directions and derived layers.

    Layers mirror the MERIT Hydro set HydroMT expects (elv, dir, upa, bas,
    sto, slp, wth), so the build recipe works with either source.
    """
    out = paths.static / "hydrography"
    tiles_dir = out / "fabdem_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    # 1x1 deg tiles named by their south-west corner, inside 10x10 deg zips.
    w, s, e, n = bbox()
    for lat in range(math.floor(s), math.ceil(n)):
        for lon in range(math.floor(w), math.ceil(e)):
            name = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}_FABDEM_V1-2.tif"
            if (tiles_dir / name).exists():
                continue
            la, lo = math.floor(lat / 10) * 10, math.floor(lon / 10) * 10
            pkg = (f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}-"
                   f"{'N' if la + 10 >= 0 else 'S'}{abs(la + 10):02d}{'E' if lo + 10 >= 0 else 'W'}{abs(lo + 10):03d}")
            url = FABDEM_URL.format(pkg=pkg)
            log.info("FABDEM %s", name)
            # Range requests: only this member is downloaded from the 2 GB zip.
            with fsspec.open(url, block_size=2**22) as f, zipfile.ZipFile(f) as z:
                (tiles_dir / name).write_bytes(z.read(name))

    # Mosaic, crop and average to 3 arcsec (~90 m, as MERIT Hydro).
    width, height = round((e - w) / HYDRO_RES), round((n - s) / HYDRO_RES)
    transform = rasterio.transform.from_bounds(w, s, e, n, width, height)
    srcs = [rasterio.open(p) for p in sorted(tiles_dir.glob("*.tif"))]
    mosaic, mtransform = merge(srcs, bounds=(w, s, e, n), nodata=-9999.0)
    [src.close() for src in srcs]
    dem = np.full((height, width), -9999.0, dtype="float32")
    rasterio.warp.reproject(
        mosaic[0], dem, src_transform=mtransform, src_crs="EPSG:4326", src_nodata=-9999.0,
        dst_transform=transform, dst_crs="EPSG:4326", dst_nodata=-9999.0, resampling=Resampling.average,
    )
    dem[dem <= 0] = -9999.0  # sea: FABDEM keeps 0 m over the ocean
    _write(out / "dem_raw.tif", dem, transform, -9999.0)

    # Burn the mapped rivers so flat floodplains route along the real channels.
    rivers = gpd.read_file(WEB_DATA / "network.geojson")
    on_river = rasterio.features.rasterize(
        ((g, 1) for g in rivers.geometry), out_shape=dem.shape, transform=transform, all_touched=True, dtype="uint8",
    ).astype(bool)
    burned = np.where(on_river & (dem != -9999.0), dem - BURN_DEPTH_M, dem)

    log.info("deriving flow directions on %d x %d cells", width, height)
    elv, d8 = pyflwdir.dem.fill_depressions(burned, outlets="edge", nodata=-9999.0)
    flw = pyflwdir.from_array(d8, ftype="d8", transform=transform, latlon=True)
    upa = flw.upstream_area(unit="km2").astype("float32")
    sto = flw.stream_order().astype("uint8")
    bas = flw.basins().astype("int32")
    slp = pyflwdir.dem.slope(dem, nodata=-9999.0, latlon=True, transform=transform).astype("float32")
    # No measured widths: power law on upstream area (~70 m at the Wami mouth).
    wth = np.where(upa > 0, RIVWTH_A * np.power(np.maximum(upa, 0), RIVWTH_B), -9999.0).astype("float32")
    # Remove the burn from the stored elevation so slopes/levels stay realistic.
    elv = np.where(on_river & (elv != -9999.0), elv + BURN_DEPTH_M, elv).astype("float32")

    _write(out / "elv.tif", elv, transform, -9999.0)
    _write(out / "dir.tif", d8.astype("uint8"), transform, 247)
    _write(out / "upa.tif", upa, transform, -9999.0)
    _write(out / "bas.tif", bas, transform, 0)
    _write(out / "sto.tif", sto, transform, 255)
    _write(out / "slp.tif", slp, transform, -9999.0)
    _write(out / "wth.tif", wth, transform, -9999.0)

    # River vectors with width and bankfull discharge: HydroMT only sets the
    # river width/depth maps from a vector source (river_geom_fn).
    qbf = np.where(upa > 0, QBF_A * np.power(np.maximum(upa, 0), QBF_B), -9999.0).astype("float32")
    feats = flw.streams(mask=upa >= RIVER_MIN_UPA_KM2, max_len=20, uparea=upa, rivwth=wth, qbankfull=qbf)
    gpd.GeoDataFrame.from_features(feats, crs=4326).to_file(out.parent / "rivers.gpkg", driver="GPKG")
    log.info("hydrography ready in %s (largest basin %.0f km2)", out, float(upa.max()))


def _read_warped(url: str, res: float, resampling=Resampling.average) -> tuple[np.ndarray, object]:
    """Read a remote raster cropped/reprojected to the bbox at ``res`` deg."""
    w, s, e, n = bbox()
    width, height = round((e - w) / res), round((n - s) / res)
    transform = rasterio.transform.from_bounds(w, s, e, n, width, height)
    with rasterio.open(url) as src, WarpedVRT(
        src, crs="EPSG:4326", transform=transform, width=width, height=height, resampling=resampling,
    ) as vrt:
        return vrt.read(1, masked=True), transform


def fetch_soil() -> None:
    out = paths.static / "soilgrids"
    for prop, (name, factor) in SOILGRIDS_PROPS.items():
        for i, depth in enumerate(SOILGRIDS_DEPTHS, start=1):
            target = out / f"{name}_sl{i}.tif"
            if target.exists():
                continue
            log.info("SoilGrids %s %s", prop, depth)
            arr, transform = _read_warped(f"/vsicurl/{SOILGRIDS_URL.format(prop=prop, depth=depth)}", SOIL_RES)
            _write(target, (arr.astype("float32") * factor).filled(-9999.0), transform, -9999.0)

    if not (out / "soilthickness.tif").exists():
        log.info("SoilGrids 2017 depth to bedrock")
        # Same grid as the 2020 layers: HydroMT stacks them into one dataset.
        arr, transform = _read_warped(f"/vsicurl/{BEDROCK_URL}", SOIL_RES)
        _write(out / "soilthickness.tif", arr.astype("float32").filled(-9999.0), transform, -9999.0)
    log.info("SoilGrids ready in %s", out)


def fetch_landcover() -> None:
    target = paths.static / "esa_worldcover.tif"
    if target.exists():
        return
    tiles = _tiles(3, lambda lat, lon: f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}")
    w, s, e, n = bbox()
    width, height = round((e - w) / WORLDCOVER_RES), round((n - s) / WORLDCOVER_RES)
    transform = rasterio.transform.from_bounds(w, s, e, n, width, height)
    mosaic = np.zeros((height, width), dtype="uint8")
    for tile in tiles:
        log.info("WorldCover %s", tile)
        with rasterio.open(f"/vsicurl/{WORLDCOVER_URL.format(tile=tile)}") as src, WarpedVRT(
            src, crs="EPSG:4326", transform=transform, width=width, height=height,
            resampling=Resampling.mode, nodata=0,
        ) as vrt:
            arr = vrt.read(1)
        mosaic = np.where(arr > 0, arr, mosaic)
    _write(target, mosaic, transform, 0)


def fetch_lakes() -> None:
    target = paths.static / "hydrolakes.gpkg"
    if target.exists():
        return
    log.info("HydroLAKES (streams the global shapefile once, keeps only the region)")
    gdf = gpd.read_file(HYDROLAKES_URL, bbox=bbox(), engine="pyogrio")
    gdf.to_file(target, driver="GPKG")
    log.info("HydroLAKES: %d lakes/reservoirs in the region", len(gdf))


def write_catalog() -> None:
    """HydroMT v1 data catalog for the cropped datasets."""
    catalog = {
        "meta": {"roots": [str(paths.static)], "hydromt_version": ">=1.0,<2", "name": "wami_ruvu_static"},
        "fabdem_hydro": {
            "data_type": "RasterDataset",
            "uri": "hydrography/*.tif",   # variable names from the file stems
            "driver": {"name": "rasterio"},
            "metadata": {"crs": 4326, "url": "https://doi.org/10.5523/bris.s5hqmjcdj8yo2ibzi9b4ew3sn",
                         "license": "CC BY-NC-SA 4.0", "paper_doi": "10.1088/1748-9326/ac4d4f",
                         "notes": "FABDEM V1-2 at 3 arcsec, rivers burned, flow layers derived with pyflwdir"},
            "data_adapter": {"rename": {"bas": "basins", "dir": "flwdir", "elv": "elevtn", "slp": "lndslp",
                                        "sto": "strord", "upa": "uparea", "wth": "rivwth"}},
        },
        "soilgrids_2020": {
            "data_type": "RasterDataset",
            "uri": "soilgrids/*.tif",
            "driver": {"name": "rasterio"},
            "metadata": {"crs": 4326, "url": "https://www.isric.org/explore/soilgrids", "license": "CC-BY 4.0",
                         "notes": "units converted to HydroMT soilgrids conventions in fetch_static.py"},
        },
        "fabdem_rivers": {
            "data_type": "GeoDataFrame",
            "uri": "rivers.gpkg",
            "driver": {"name": "pyogrio"},
            "metadata": {"crs": 4326, "notes": "stream segments from the FABDEM flow network; "
                                                "width and bankfull discharge are power laws on upstream area"},
        },
        "esa_worldcover": {
            "data_type": "RasterDataset",
            "uri": "esa_worldcover.tif",
            "driver": {"name": "rasterio"},
            "metadata": {"crs": 4326, "url": "https://esa-worldcover.org", "license": "CC-BY 4.0"},
            "data_adapter": {"rename": {"esa_worldcover": "landuse"}},
        },
        "hydro_lakes": {
            "data_type": "GeoDataFrame",
            "uri": "hydrolakes.gpkg",
            "driver": {"name": "pyogrio"},
            "metadata": {"crs": 4326, "url": "https://www.hydrosheds.org/products/hydrolakes", "license": "CC-BY 4.0"},
            "data_adapter": {
                "unit_mult": {"Area_avg": 1e6, "Vol_avg": 1e6},
                "rename": {"Hylak_id": "waterbody_id", "Lake_area": "Area_avg", "Vol_total": "Vol_avg",
                           "Depth_avg": "Depth_avg", "Dis_avg": "Dis_avg", "Pour_long": "xout", "Pour_lat": "yout"},
            },
        },
        "lai_mapping_esa_worldcover": {
            "data_type": "DataFrame",
            "uri": str(PIPELINE / "static" / "lai_mapping_esa_worldcover.csv"),
            "driver": {"name": "pandas", "options": {"index_col": 0}},
        },
    }
    path = paths.static / "data_catalog.yml"
    path.write_text(yaml.safe_dump(catalog, sort_keys=False))
    log.info("wrote %s", path)


STEPS = {"hydrography": fetch_hydrography, "soil": fetch_soil, "landcover": fetch_landcover, "lakes": fetch_lakes}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=list(STEPS), help="run only these datasets")
    args = ap.parse_args()
    paths.static.mkdir(parents=True, exist_ok=True)
    for name in args.only or STEPS:
        STEPS[name]()
    write_catalog()


if __name__ == "__main__":
    main()
