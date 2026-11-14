"""Administrative units (wards with their district) for one domain, from geoBoundaries (open, CC BY 4.0).

Wards are ADM3 (2015 vintage, 3,644 units), districts ADM2 (2021). Both are simplified geoBoundaries
products, good enough to aggregate impact; they are not an official cadastre.

    python pipeline/ibf/admin.py ruvu_lower [--out .cache/data/ibf/exposure]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _env  # noqa: F401,E402
import geopandas as gpd  # noqa: E402
import requests  # noqa: E402
from shapely.geometry import box  # noqa: E402
from trigger import ROOT, load_config  # noqa: E402

API = "https://www.geoboundaries.org/api/current/gbOpen/TZA/{level}/"


def _fetch(level: str, bbox) -> gpd.GeoDataFrame:
    meta = requests.get(API.format(level=level), timeout=60).json()
    gdf = gpd.read_file(meta["simplifiedGeometryGeoJSON"])
    return gdf[gdf.intersects(box(*bbox))][["shapeName", "geometry"]].copy()


def fetch_admin(bbox, out: Path) -> Path:
    if not out.exists():
        wards, districts = _fetch("ADM3", bbox), _fetch("ADM2", bbox)
        pts = wards.copy()
        pts["geometry"] = wards.representative_point()
        joined = gpd.sjoin(pts, districts.rename(columns={"shapeName": "district"}), how="left", predicate="within")
        wards["district"] = joined["district"].reindex(wards.index).fillna("")
        wards = wards.rename(columns={"shapeName": "ward"})
        wards["id"] = range(1, len(wards) + 1)
        out.parent.mkdir(parents=True, exist_ok=True)
        wards[["id", "ward", "district", "geometry"]].to_file(out, driver="GeoJSON")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("domain")
    ap.add_argument("--out", type=Path, default=ROOT / ".cache" / "data" / "ibf" / "exposure")
    a = ap.parse_args()
    p = fetch_admin(load_config()["domains"][a.domain]["bbox"], a.out / f"admin_{a.domain}.geojson")
    g = gpd.read_file(p)
    print(f"{len(g)} wards in {g.district.nunique()} districts: {', '.join(sorted(g.district.unique())[:8])} ...")
