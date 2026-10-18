"""Step 1b - place one forecast point on each reach.

Each point sits ``point_offset_m`` upstream of the reach outlet along the
OSM river line, so it never lands on a confluence where snapping to the
model river could jump to the neighbouring river. HydroMT later snaps the
points onto the Wflow river network (setup_gauges).

Writes pipeline/build/forecast_points.csv (id, reach, x, y).

    python pipeline/build/forecast_points.py
"""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PIPELINE, WEB_DATA, config, log  # noqa: E402

OUT = PIPELINE / "build" / "forecast_points.csv"
UTM = 32737  # UTM 37S, metres


def point_upstream(geom: MultiLineString, outlet: Point, offset: float) -> Point:
    merged = linemerge(geom)
    parts = list(merged.geoms) if isinstance(merged, MultiLineString) else [merged]
    # The reach part that ends at the outlet, oriented so it ends there.
    line = min(parts, key=lambda ln: min(Point(ln.coords[0]).distance(outlet), Point(ln.coords[-1]).distance(outlet)))
    if Point(line.coords[0]).distance(outlet) < Point(line.coords[-1]).distance(outlet):
        line = LineString(line.coords[::-1])
    return line.interpolate(max(line.length - offset, 0.5 * line.length))


def main() -> None:
    offset = config()["forecast"]["point_offset_m"]
    reaches = gpd.read_file(WEB_DATA / "network.geojson").to_crs(UTM)
    rows = []
    for i, r in enumerate(reaches.itertuples(), start=1):
        outlet = gpd.GeoSeries([Point(r.outlet)], crs=4326).to_crs(UTM).iloc[0]
        pt = gpd.GeoSeries([point_upstream(r.geometry, outlet, offset)], crs=UTM).to_crs(4326).iloc[0]
        rows.append({"id": i, "reach": r.id, "x": round(pt.x, 5), "y": round(pt.y, 5)})
    pd.DataFrame(rows).to_csv(OUT, index=False)
    log.info("wrote %s (%d points)", OUT.relative_to(PIPELINE.parent), len(rows))


if __name__ == "__main__":
    main()
