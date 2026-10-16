"""Build the forecast-reach network used by the mock data.

Pulls the named rivers of the Wami and Ruvu basins from OpenStreetMap
(Overpass API), groups the ways into forecast reaches, simplifies the
geometry and writes ``web/public/data/network.geojson``.

This is a stand-in for the real network, which will come from the Wflow
model build (hydromt_wflow river cells). Standard library only.

    python pipeline/mock/build_network.py            # fetch from Overpass
    python pipeline/mock/build_network.py --osm-json rivers.json
"""

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "public" / "data" / "network.geojson"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
BBOX = (-7.8, 35.6, -5.3, 39.1)  # south, west, north, east
SIMPLIFY_TOL_DEG = 0.002  # ~200 m

# Mock upstream areas (km2): rough orders of magnitude, replaced by the
# Wflow upstream-area map once the model is built.
REACHES = [
    # id, display name, basin, upstream area, outlet rule
    ("kinyasungwe", "Kinyasungwe", "Wami", 9_500, "east"),
    ("mkondoa", "Mkondoa", "Wami", 15_000, "east"),
    ("mkata", "Mkata", "Wami", 24_000, "north"),
    ("wami_upper", "Wami (upper)", "Wami", 33_000, "east"),
    ("wami_lower", "Wami (lower)", "Wami", 43_000, "east"),
    ("ruvu_upper", "Ruvu (upper)", "Ruvu", 2_200, "east"),
    ("mvuha", "Mvuha", "Ruvu", 1_100, "east"),
    ("ruvu_middle", "Ruvu (middle)", "Ruvu", 7_500, "east"),
    ("ngerengere", "Ngerengere", "Ruvu", 2_900, "south"),
    ("ruvu_lower", "Ruvu (lower)", "Ruvu", 17_700, "east"),
]


def assign_reach(name: str, lons: list[float], lats: list[float]) -> str | None:
    """Map an OSM way to a forecast reach id, or None to drop it."""
    n = name.lower()
    if n.startswith("kinyasungwe"):
        return "kinyasungwe"
    if n.startswith("mkondoa"):
        return "mkondoa"
    if n.startswith("mkata"):
        return "mkata"
    if n.startswith("mvuha"):
        return "mvuha"
    if n.startswith("ngerengere"):
        return "ngerengere"
    if n in ("wami river",):
        return "wami_upper" if max(lons) <= 38.105 else "wami_lower"
    if n == "ruvu":
        if max(lons) <= 38.105:
            return "ruvu_upper"
        if max(lats) < -7.0:
            return "ruvu_middle"
        return "ruvu_lower"
    return None


def fetch_osm() -> dict:
    s, w, n, e = BBOX
    query = f'[out:json][timeout:150];way["waterway"="river"]({s},{w},{n},{e});out tags geom;'
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "wami-ruvu-flood-forecast/0.1"},
    )
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.load(resp)


def _perp_dist(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** 0.5


def simplify(coords: list, tol: float) -> list:
    """Douglas-Peucker line simplification."""
    if len(coords) < 3:
        return coords
    idx, dmax = 0, 0.0
    for i in range(1, len(coords) - 1):
        d = _perp_dist(coords[i], coords[0], coords[-1])
        if d > dmax:
            idx, dmax = i, d
    if dmax <= tol:
        return [coords[0], coords[-1]]
    return simplify(coords[: idx + 1], tol)[:-1] + simplify(coords[idx:], tol)


def outlet(lines: list, rule: str) -> list[float]:
    pts = [p for line in lines for p in line]
    key = {
        "east": lambda p: p[0],
        "north": lambda p: p[1],
        "south": lambda p: -p[1],
    }[rule]
    return max(pts, key=key)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm-json", type=Path, help="cached Overpass response")
    args = ap.parse_args()

    osm = json.loads(args.osm_json.read_text()) if args.osm_json else fetch_osm()

    lines: dict[str, list] = {r[0]: [] for r in REACHES}
    for el in osm["elements"]:
        name = el.get("tags", {}).get("name")
        if not name or len(el.get("geometry", [])) < 2:
            continue
        lons = [p["lon"] for p in el["geometry"]]
        lats = [p["lat"] for p in el["geometry"]]
        reach = assign_reach(name, lons, lats)
        if reach:
            coords = [[round(x, 5), round(y, 5)] for x, y in zip(lons, lats)]
            lines[reach].append(simplify(coords, SIMPLIFY_TOL_DEG))

    features = []
    for rid, label, basin, area, rule in REACHES:
        if not lines[rid]:
            raise SystemExit(f"no OSM ways matched reach {rid!r}")
        features.append({
            "type": "Feature",
            "properties": {
                "id": rid,
                "name": label,
                "basin": basin,
                "upstream_area_km2": area,
                "outlet": outlet(lines[rid], rule),
            },
            "geometry": {"type": "MultiLineString", "coordinates": lines[rid]},
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "type": "FeatureCollection",
        "attribution": "River geometry © OpenStreetMap contributors (ODbL)",
        "features": features,
    }, separators=(",", ":")))
    n_pts = sum(len(l) for f in features for l in f["geometry"]["coordinates"])
    print(f"wrote {OUT.relative_to(ROOT)}: {len(features)} reaches, {n_pts} vertices")


if __name__ == "__main__":
    main()
