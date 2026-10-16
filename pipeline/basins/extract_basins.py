"""Delineate the Wami and Ruvu basins from HydroBASINS and plot them.

Downloads HydroBASINS v1c (Africa, level 7), selects every level-7
sub-basin draining to each river mouth by walking the NEXT_DOWN topology
upstream, and writes:

    web/public/data/basins.geojson   basin outlines, level-7 sub-basins, label points
    docs/basins.png                  overview map

Needs geopandas, matplotlib and contextily.

    python pipeline/basins/extract_basins.py [--cache-dir DIR]
"""

import argparse
import urllib.request
import zipfile
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
LEVEL = 7  # ~200-1,000 km2 sub-basins; level 6 leaves the Ruvu as a single unit
URL = f"https://data.hydrosheds.org/file/hydrobasins/standard/hybas_af_lev{LEVEL:02d}_v1c.zip"

# River mouths (lon, lat), from the OSM river network.
MOUTHS = {"Wami": (38.818, -6.115), "Ruvu": (38.869, -6.400)}

TOWNS = {
    "Dodoma": (35.74, -6.17),
    "Morogoro": (37.66, -6.82),
    "Kilosa": (36.99, -6.83),
    "Bagamoyo": (38.90, -6.44),
}

# Reference palette: categorical slots 1 and 2 (light mode).
COLORS = {"Wami": "#2a78d6", "Ruvu": "#eb6834"}
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"


def load_level(cache: Path) -> gpd.GeoDataFrame:
    zpath = cache / Path(URL).name
    if not zpath.exists():
        print(f"downloading {URL}")
        req = urllib.request.Request(URL, headers={"User-Agent": "wami-ruvu-flood-forecast/0.1"})
        with urllib.request.urlopen(req) as r, open(zpath, "wb") as f:
            f.write(r.read())
    shp = f"hybas_af_lev{LEVEL:02d}_v1c.shp"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(cache, members=[m for m in z.namelist() if m.startswith(shp[:-4])])
    return gpd.read_file(cache / shp)


def upstream_of(gdf: gpd.GeoDataFrame, outlet_id: int) -> gpd.GeoDataFrame:
    """All sub-basins whose flow path reaches ``outlet_id``."""
    children: dict[int, list[int]] = {}
    for hid, down in zip(gdf.HYBAS_ID, gdf.NEXT_DOWN):
        children.setdefault(down, []).append(hid)
    keep, stack = set(), [outlet_id]
    while stack:
        hid = stack.pop()
        keep.add(hid)
        stack.extend(children.get(hid, []))
    return gdf[gdf.HYBAS_ID.isin(keep)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=ROOT / ".cache" / "hydrobasins")
    args = ap.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    lev = load_level(args.cache_dir)
    metric = lev.to_crs(32737)  # UTM 37S for distances and areas

    subs = []
    for name, (lon, lat) in MOUTHS.items():
        mouth = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(32737).iloc[0]
        # Nearest basin that drains straight to the sea (excluding lumped coastal strips).
        sinks = metric[(metric.NEXT_DOWN == 0) & (metric.COAST == 0)]
        outlet = lev.loc[sinks.distance(mouth).idxmin()]
        sel = upstream_of(lev, int(outlet.HYBAS_ID)).copy()
        sel["basin"] = name
        subs.append(sel)
        print(f"{name}: {len(sel)} level-{LEVEL} sub-basins, {sel.SUB_AREA.sum():,.0f} km2")

    subs = gpd.GeoDataFrame(gpd.pd.concat(subs), crs=lev.crs)[["HYBAS_ID", "basin", "SUB_AREA", "UP_AREA", "geometry"]]
    basins = subs.dissolve("basin", as_index=False, aggfunc={"SUB_AREA": "sum"}).rename(columns={"SUB_AREA": "area_km2"})

    # Web layer: simplified outlines + sub-basins in one file, tagged by kind.
    polys = gpd.GeoDataFrame(
        gpd.pd.concat([
            basins.assign(kind="basin", HYBAS_ID=None),
            subs.rename(columns={"SUB_AREA": "area_km2"}).assign(kind="subbasin"),
        ]),
        crs=4326,
    )
    polys["geometry"] = polys.geometry.simplify(0.003, preserve_topology=True)
    # One label point per basin: a polygon label would repeat on every part of a multipolygon.
    labels = basins.assign(kind="label", HYBAS_ID=None, geometry=basins.to_crs(32737).representative_point().to_crs(4326))
    out = gpd.GeoDataFrame(gpd.pd.concat([polys, labels]), crs=4326)
    web_path = ROOT / "web" / "public" / "data" / "basins.geojson"
    out[["kind", "basin", "HYBAS_ID", "area_km2", "geometry"]].to_file(web_path, driver="GeoJSON", COORDINATE_PRECISION=5)
    print(f"wrote {web_path.relative_to(ROOT)}")

    plot(basins, subs, ROOT / "docs" / "basins.png")


def plot(basins: gpd.GeoDataFrame, subs: gpd.GeoDataFrame, path: Path) -> None:
    rivers = gpd.read_file(ROOT / "web" / "public" / "data" / "network.geojson")
    b3857, s3857, r3857 = basins.to_crs(3857), subs.to_crs(3857), rivers.to_crs(3857)

    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
    for _, row in b3857.iterrows():
        c = COLORS[row.basin]
        gpd.GeoSeries([row.geometry]).plot(ax=ax, color=c, alpha=0.12, linewidth=0)
        s3857[s3857.basin == row.basin].boundary.plot(ax=ax, color=MUTED, linewidth=0.5)
        gpd.GeoSeries([row.geometry]).boundary.plot(ax=ax, color=c, linewidth=2)
        p = row.geometry.representative_point()
        ax.annotate(f"{row.basin} basin\n{row.area_km2:,.0f} km²", (p.x, p.y), ha="center", va="center",
                    fontsize=11, fontweight="semibold", color=INK,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.8))
    r3857.plot(ax=ax, color=INK_2, linewidth=1.2)

    xmin, ymin, xmax, ymax = b3857.total_bounds
    pad = 0.06 * max(xmax - xmin, ymax - ymin)
    ax.set_xlim(xmin - pad, xmax + pad)
    ax.set_ylim(ymin - pad, ymax + pad)
    cx.add_basemap(ax, source=cx.providers.Esri.WorldShadedRelief, attribution=False, zorder=0)
    for town, (lon, lat) in TOWNS.items():
        x, y = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(3857).iloc[0].coords[0]
        ax.plot(x, y, "o", ms=4, color=INK, mec="white", mew=1, zorder=5)
        ax.annotate(town, (x, y), xytext=(5, 3), textcoords="offset points", fontsize=8, color=INK, zorder=5)
    ax.set_axis_off()

    ax.legend(
        handles=[
            Patch(facecolor=COLORS["Wami"] + "33", edgecolor=COLORS["Wami"], linewidth=2, label="Wami basin"),
            Patch(facecolor=COLORS["Ruvu"] + "33", edgecolor=COLORS["Ruvu"], linewidth=2, label="Ruvu basin"),
            Line2D([], [], color=MUTED, linewidth=0.8, label=f"HydroBASINS level-{LEVEL} sub-basin"),
            Line2D([], [], color=INK_2, linewidth=1.2, label="Main rivers (OSM)"),
        ],
        loc="lower left", frameon=True, framealpha=0.9, edgecolor="none", fontsize=9, labelcolor=INK_2,
    )
    ax.set_title("Wami and Ruvu river basins, eastern Tanzania", loc="left", fontsize=13, color=INK, pad=10)
    fig.text(0.01, 0.01, "Basins: HydroSHEDS HydroBASINS v1c · Rivers: © OpenStreetMap contributors · "
             "Relief: Esri", fontsize=7, color=MUTED)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
