"""IbF demo driven by a real past forecast: impacts for every lead day.

Takes the p50 / p95 discharge forecast of hindcast_forecast.py for the domain's
inflow reaches, runs SFINCS once per scenario with 3-hourly water-level maps
(spun up on the observed-rainfall discharge of the week before the issue date),
turns each lead day into a 30 m depth map and writes the per-day impact products
(forecast_products.py) to web/public/data/ibf/forecast/<issue>/, and lists the event in
web/public/data/ibf/forecast/events.json (the site's event selector).

    python pipeline/ibf/run_forecast_demo.py 2024-01-03 --label "January 2024" [--reuse]

Run with the hydromt-sfincs environment; SFINCS runs natively or in Docker.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd  # noqa: E402

from trigger import ROOT, load_config  # noqa: E402

LABELS = {"p50": "Median forecast", "p95": "Severe case (95th percentile)"}


def main() -> None:
    import forecast_products
    import sfincs_model

    ap = argparse.ArgumentParser()
    ap.add_argument("issue")
    ap.add_argument("--domain", default="ruvu_lower")
    ap.add_argument("--data-root", type=Path, default=Path(os.environ.get("WRFF_DATA_ROOT", ROOT / ".cache" / "data")))
    ap.add_argument("--reuse", action="store_true", help="skip SFINCS when a finished run exists")
    ap.add_argument("--label", help="short event name for the site's selector, e.g. 'April 2024'")
    a = ap.parse_args()
    cfg = load_config()
    dom = cfg["domains"][a.domain]
    fc_dir = a.data_root / "ibf" / f"forecast_{a.issue.replace('-', '')}"
    dem = a.data_root / "sfincs" / f"dem_{a.domain}_fabdem30.tif"
    exp = a.data_root / "ibf" / "exposure"

    obs = pd.read_csv(fc_dir / "observed.csv", index_col=0, parse_dates=True)[dom["inflow_reaches"]]
    depths, scenarios = {}, []
    for scen in cfg["scenarios"]:
        q = pd.read_csv(fc_dir / f"{scen}.csv", index_col=0, parse_dates=True)[dom["inflow_reaches"]]
        work = a.data_root / "ibf" / "runs" / f"forecast_{a.issue}_{a.domain}_{scen}"
        if not (a.reuse and (work / "out" / "sfincs_map.nc").exists()):
            # Spin-up on observed-rainfall discharge, then the forecast: the floodplain holds the water that
            # actually arrived before the issue date instead of a constant warm-up at the forecast's first value.
            sfincs_model.build(a.domain, pd.concat([obs, q]), dem, work, map_every_s=3 * 3600)
            sfincs_model.run(work)
        depths[scen] = sfincs_model.depth30_daily(work, dem, work / "depth_daily", q.index)
        scenarios.append({"id": scen, "label": LABELS.get(scen, scen), "dir": scen,
                          "hydrograph": {c: [round(float(v), 1) for v in q[c]] for c in q.columns}})
        print(f"{scen}: SFINCS + {len(depths[scen])} daily depth maps done")

    days = pd.read_csv(fc_dir / "p50.csv", index_col=0, parse_dates=True).index
    rain = pd.read_csv(fc_dir / "rain.csv", index_col=0).iloc[:, 0]
    manifest = {
        "kind": "forecast", "issued": f"{a.issue}T00:00Z",
        "title": f"Forecast issued {pd.Timestamp(a.issue):%-d %B %Y}, lower Ruvu",
        "description": ("Impact-based forecast as it would have been issued: ECMWF ENS (50 members) through Wflow, "
                        "median and 95th-percentile inflows through SFINCS, then exposure and vulnerability for "
                        "every lead day."),
        "days": [t.strftime("%Y-%m-%dT%H:%MZ") for t in days],
        "rain_mm": [round(float(v), 1) for v in rain],
        "domain": {"id": a.domain, "name": a.domain.replace("_", " ").title(), "bbox": dom["bbox"]},
        "scenarios": scenarios,
    }
    manifest["observed"] = {"times": [t.strftime("%Y-%m-%dT%H:%MZ") for t in obs.index],
                            "series": {c: [round(float(v), 1) for v in obs[c]] for c in obs.columns}}
    root = ROOT / "web" / "public" / "data" / "ibf" / "forecast"
    out = root / a.issue
    out.mkdir(parents=True, exist_ok=True)
    domain_rivers(dom["bbox"], a.data_root, root / "rivers.geojson")
    gauges = gauge_products(fc_dir, cfg["scenarios"], dom["inflow_reaches"], a.data_root, obs.index[0], days[-1])
    if gauges:
        (out / "gauges.json").write_text(json.dumps(gauges, separators=(",", ":")))
        manifest["has_gauges"] = True
    forecast_products.build(depths, exp / f"exposure_{a.domain}.parquet", exp / f"buildings_{a.domain}.parquet",
                            exp / f"population_{a.domain}.tif", exp / f"admin_{a.domain}.geojson", out, manifest)
    events_path = root / "events.json"
    events = json.loads(events_path.read_text()) if events_path.exists() else []
    events = [e for e in events if e["id"] != a.issue] + [{
        "id": a.issue, "label": a.label or pd.Timestamp(a.issue).strftime("%B %Y"), "issued": manifest["issued"],
        "title": manifest["title"]}]
    events_path.write_text(json.dumps(sorted(events, key=lambda e: e["id"]), indent=1))
    print(f"products in {out}")


def domain_rivers(bbox, data_root: Path, out: Path, min_upa_km2: float = 20) -> None:
    """River centrelines of the model's flow network (FABDEM-derived) inside the flood domain."""
    import geopandas as gpd
    from shapely.geometry import box

    r = gpd.read_file(data_root / "static" / "rivers.gpkg")
    r = gpd.clip(r[r["uparea"] >= min_upa_km2], box(*bbox))
    r = r[r.geom_type.isin(["LineString", "MultiLineString"])]
    r["geometry"] = r.geometry.simplify(0.0003)
    r["uparea"] = r["uparea"].round().astype(int)
    r[["uparea", "geometry"]].to_file(out, driver="GeoJSON", COORDINATE_PRECISION=5)


def gauge_products(fc_dir: Path, scenarios: list[str], inflow_reaches: list[str], data_root: Path,
                   t0: pd.Timestamp, t1: pd.Timestamp) -> dict | None:
    """Forecast discharge per gauge, scenario and day, with its return-period thresholds.
    Gauges = forecast points + virtual gauges of the basin the IbF domain drains (needs
    ops/thresholds_gauges.json); gauges of other basins are left to the live map."""
    ops = ROOT / "pipeline" / "ops"
    if not (ops / "thresholds_gauges.json").exists() or not (fc_dir / "gauges_p50.csv").exists():
        print("no gauge thresholds yet: skipping gauges.json")
        return None
    thr_p = json.loads((ops / "thresholds.json").read_text())["reaches"]
    thr_g = json.loads((ops / "thresholds_gauges.json").read_text())["reaches"]
    net = json.loads((ROOT / "web" / "public" / "data" / "network.geojson").read_text())["features"]
    vg = json.loads((ROOT / "web" / "public" / "data" / "gauges.geojson").read_text())["features"]
    meta = [{"id": f["properties"]["id"], "kind": "point", "name": f["properties"]["name"], "basin": f["properties"]["basin"],
             "lonlat": f["properties"]["outlet"], "upa": f["properties"]["upstream_area_km2"], "thr": thr_p[f["properties"]["id"]]}
            for f in net]
    meta += [{"id": f"g{f['properties']['id']}", "kind": "virtual", "name": f"Gauge {f['properties']['id']}",
              "basin": f["properties"]["basin"], "lonlat": f["geometry"]["coordinates"],
              "upa": f["properties"]["upstream_area_km2"], "thr": thr_g[str(f["properties"]["id"])]} for f in vg]
    basins = {f["properties"]["basin"] for f in net if f["properties"]["id"] in inflow_reaches}
    meta = [g for g in meta if g["basin"] in basins]
    keep = {g["id"] for g in meta}
    q = {}
    for scen in scenarios:
        pts = pd.read_csv(fc_dir / f"{scen}.csv", index_col=0)
        gs = pd.read_csv(fc_dir / f"gauges_{scen}.csv", index_col=0)
        q[scen] = {k: v for k, v in {**{c: [round(float(v), 1) for v in pts[c]] for c in pts.columns},
                                     **{f"g{c}": [round(float(v), 1) for v in gs[c]] for c in gs.columns}}.items() if k in keep}
    # Full hydrographs for the site: forecast spread per gauge, and the discharge simulated on observed
    # (CHIRPS) rainfall over the spin-up week + forecast window, for comparison.
    spread = {}
    for qn in ("p05", "p25", "p50", "p75", "p95"):
        pts = pd.read_csv(fc_dir / f"{qn}.csv", index_col=0)
        gs = pd.read_csv(fc_dir / f"gauges_{qn}.csv", index_col=0)
        spread[qn] = {**{c: [round(float(x), 1) for x in pts[c]] for c in pts.columns if c in keep},
                      **{f"g{c}": [round(float(x), 1) for x in gs[c]] for c in gs.columns if f"g{c}" in keep}}
    hp = pd.read_csv(data_root / "products" / "historical_q.csv", index_col=0, parse_dates=True).loc[t0:t1]
    hg = pd.read_csv(data_root / "products" / "historical_q_gauges.csv", index_col=0, parse_dates=True).loc[t0:t1]
    reference = {"times": [t.strftime("%Y-%m-%dT%H:%MZ") for t in hp.index],
                 "q": {**{c: [round(float(x), 1) for x in hp[c]] for c in hp.columns if c in keep},
                       **{f"g{c}": [round(float(x), 1) for x in hg[c]] for c in hg.columns if f"g{c}" in keep}}}
    return {"gauges": meta, "q": q, "spread": spread, "reference": reference}


if __name__ == "__main__":
    main()
