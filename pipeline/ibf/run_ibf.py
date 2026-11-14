"""Run the impact chain for the IbF tab and write its web products.

  demo   a past event: Wflow hydrographs (event_hydrograph.py) around the peak of the inflow reaches
  live   the latest hazard forecast: p50 and p95 ensemble hydrographs of the alerted inflow reaches

Each scenario: SFINCS build + run -> 30 m max depth -> impact (products.py). Output goes to
web/public/data/ibf/<mode>/<scenario>/ plus manifest.json, which the IbF tab reads.

    python pipeline/ibf/run_ibf.py demo --hydro <wflow_q.csv> --title "..." [--from D --to D | --peak-days 12]
    python pipeline/ibf/run_ibf.py live [--latest web/public/data/latest]

Needs the 30 m DEM (fetch_dem.py) and exposure (exposure.py) under --data-root, and SFINCS
(a WSL distro on Windows, or the `sfincs` binary on Linux). Run with the hydromt-sfincs environment.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd  # noqa: E402

from trigger import ROOT, load_config, triggered_domains  # noqa: E402

WEB_IBF = ROOT / "web" / "public" / "data" / "ibf"


def iso(idx) -> list[str]:
    return [t.strftime("%Y-%m-%dT%H:%MZ") for t in idx]


def forecast_hydrographs(reaches: list[str], scenario: str, latest: Path) -> pd.DataFrame:
    """Forecast discharge [m3/s] per reach for one ensemble quantile ('p50', 'p95', ...), from the site JSON."""
    cols = {}
    for r in reaches:
        f = json.loads((latest / "reaches" / f"{r}.json").read_text())["forecast"]
        cols[r] = pd.Series(f[scenario], index=pd.to_datetime(f["times"]).tz_localize(None))
    return pd.DataFrame(cols)


def run_scenario(domain: str, q: pd.DataFrame, out: Path, work: Path, data_root: Path, meta: dict, res: float | None) -> dict:
    import products  # heavy GIS imports only when a scenario is actually run
    import sfincs_model

    dem = data_root / "sfincs" / f"dem_{domain}_fabdem30.tif"
    exp = data_root / "ibf" / "exposure"
    work.mkdir(parents=True, exist_ok=True)
    sfincs_model.build(domain, q, dem, work, res)
    sfincs_model.run(work)
    depth = sfincs_model.depth30(work, dem, work / "depth30.tif")
    s = products.build(depth, exp / f"exposure_{domain}.parquet", exp / f"population_{domain}.tif", out, meta)
    print(f"  {out.name}: {s['people_affected']:,.0f} people, {s['buildings_affected']:,} buildings, "
          f"{s['flooded_area_km2']:.0f} km2, max depth {s['max_depth_m']:.1f} m")
    return {"hydrograph": {"times": iso(q.index), "series": {c: [round(float(v), 1) for v in q[c]] for c in q.columns}}}


def domain_info(domain: str) -> dict:
    d = load_config()["domains"][domain]
    return {"id": domain, "name": domain.replace("_", " ").title(), "bbox": d["bbox"]}


def write_manifest(mode: str, manifest: dict) -> None:
    (WEB_IBF / mode).mkdir(parents=True, exist_ok=True)
    (WEB_IBF / mode / "manifest.json").write_text(json.dumps(manifest, indent=1))


def demo(a) -> None:
    domain = a.domain
    inflow = load_config()["domains"][domain]["inflow_reaches"]
    q = pd.read_csv(a.hydro, index_col=0, parse_dates=True)[inflow]
    if a.start:
        t0, t1 = pd.Timestamp(a.start), pd.Timestamp(a.end)
    else:
        peak = q.sum(axis=1).loc[a.search_from:a.search_to].idxmax()
        t0, t1 = peak - pd.Timedelta(days=a.peak_days), peak + pd.Timedelta(days=a.peak_days)
    q = q.loc[t0:t1]
    work = a.data_root / "ibf" / "runs" / f"demo_{domain}"
    meta = {"kind": "demo", "domain": domain, "peak_inflow_m3s": {c: round(float(q[c].max()), 1) for c in q.columns}}
    sc = run_scenario(domain, q, WEB_IBF / "demo" / "event", work, a.data_root, meta, a.res)
    write_manifest("demo", {
        "kind": "demo", "title": a.title, "description": a.description, "period": iso([q.index[0], q.index[-1]]),
        "domain": domain_info(domain), "status": "ok",
        "scenarios": [{"id": "event", "label": "Event reconstruction", "dir": "event", **sc}],
    })


def live(a) -> None:
    cfg = load_config()
    latest = Path(a.latest)
    fc = json.loads((latest / "forecast.json").read_text())
    trig = triggered_domains(fc, cfg)
    base = {"kind": "live", "issued": fc["issued"]}
    if not trig:
        write_manifest("live", {**base, "title": "Live impact forecast", "description": "", "domain": domain_info(next(iter(cfg["domains"]))),
                                "status": "not_triggered", "scenarios": []})
        print("no domain triggered")
        return
    domain = next(iter(trig))                  # one domain for now
    inflow = cfg["domains"][domain]["inflow_reaches"]
    scenarios = []
    for scen in cfg["scenarios"]:
        q = forecast_hydrographs(inflow, scen, latest)
        work = a.data_root / "ibf" / "runs" / f"live_{domain}_{scen}"
        meta = {"kind": "live", "domain": domain, "scenario": scen, "issued": fc["issued"]}
        sc = run_scenario(domain, q, WEB_IBF / "live" / scen, work, a.data_root, meta, a.res)
        label = {"p50": "Median forecast", "p95": "Severe case (95th percentile)"}.get(scen, scen)
        scenarios.append({"id": scen, "label": label, "dir": scen, **sc})
    write_manifest("live", {**base, "title": "Live impact forecast", "description": "", "domain": domain_info(domain),
                            "status": "ok", "scenarios": scenarios})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["demo", "live"])
    ap.add_argument("--data-root", type=Path, default=Path(os.environ.get("WRFF_DATA_ROOT", ROOT / ".cache" / "data")))
    ap.add_argument("--domain", default="ruvu_lower")
    ap.add_argument("--res", type=float, help="SFINCS grid resolution [m], default from config")
    ap.add_argument("--hydro", type=Path, help="demo: daily Wflow discharge CSV")
    ap.add_argument("--title", default="Demo event")
    ap.add_argument("--description", default="")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--search-from", default="2024-03-01")
    ap.add_argument("--search-to", default="2024-05-31")
    ap.add_argument("--peak-days", type=int, default=12)
    ap.add_argument("--latest", default=str(ROOT / "web" / "public" / "data" / "latest"))
    a = ap.parse_args()
    demo(a) if a.mode == "demo" else live(a)
