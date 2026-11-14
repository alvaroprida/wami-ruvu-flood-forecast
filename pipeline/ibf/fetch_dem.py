"""30 m FABDEM mosaic for one IbF domain.

Tiles are reused from the Wflow build (static/hydrography/fabdem_tiles) when present,
otherwise downloaded with range requests from the 10x10 deg zips (as static/fetch_static.py).

    python pipeline/ibf/fetch_dem.py ruvu_lower [--data-root .cache/data]
"""

import argparse
import math
import zipfile
from pathlib import Path

import fsspec
import rasterio
from rasterio.merge import merge

from trigger import ROOT, load_config

FABDEM_URL = "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/{pkg}_FABDEM_V1-2.zip"


def _ns(v: int, pos: str, neg: str, width: int) -> str:
    return f"{pos if v >= 0 else neg}{abs(v):0{width}d}"


def fetch_tiles(bbox, tiles_dir: Path) -> None:
    w, s, e, n = bbox
    tiles_dir.mkdir(parents=True, exist_ok=True)
    for lat in range(math.floor(s), math.ceil(n)):
        for lon in range(math.floor(w), math.ceil(e)):
            name = f"{_ns(lat, 'N', 'S', 2)}{_ns(lon, 'E', 'W', 3)}_FABDEM_V1-2.tif"
            if (tiles_dir / name).exists():
                continue
            la, lo = math.floor(lat / 10) * 10, math.floor(lon / 10) * 10
            pkg = (f"{_ns(la, 'N', 'S', 2)}{_ns(lo, 'E', 'W', 3)}-"
                   f"{_ns(la + 10, 'N', 'S', 2)}{_ns(lo + 10, 'E', 'W', 3)}")
            print("downloading", name)
            with fsspec.open(FABDEM_URL.format(pkg=pkg), block_size=2**22) as f, zipfile.ZipFile(f) as z:
                (tiles_dir / name).write_bytes(z.read(name))


def mosaic(domain: str, data_root: Path) -> Path:
    bbox = load_config()["domains"][domain]["bbox"]
    tiles_dir = data_root / "static" / "hydrography" / "fabdem_tiles"
    fetch_tiles(bbox, tiles_dir)
    w, s, e, n = bbox
    srcs = [rasterio.open(p) for p in sorted(tiles_dir.glob("*.tif"))]
    # Keep sea at its FABDEM value (0 m): SFINCS takes the coast from the elevation threshold.
    arr, transform = merge(srcs, bounds=(w, s, e, n), nodata=-9999.0)
    meta = {"driver": "GTiff", "height": arr.shape[1], "width": arr.shape[2], "count": 1, "dtype": "float32",
            "crs": "EPSG:4326", "transform": transform, "nodata": -9999.0, "compress": "deflate", "tiled": True}
    for s_ in srcs:
        s_.close()
    out = data_root / "sfincs" / f"dem_{domain}_fabdem30.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **meta) as dst:
        dst.write(arr[0].astype("float32"), 1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--data-root", type=Path, default=ROOT / ".cache" / "data")
    a = ap.parse_args()
    print(mosaic(a.domain, a.data_root))
