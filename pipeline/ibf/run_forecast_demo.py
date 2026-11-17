"""IbF demo driven by a real past forecast: impacts for every lead day.

Takes the p50 / p95 discharge forecast of hindcast_forecast.py for the domain's
inflow reaches, runs SFINCS once per scenario with 3-hourly water-level maps,
turns each lead day into a 30 m depth map and writes the per-day impact products
(forecast_products.py) to web/public/data/ibf/forecast/.

    python pipeline/ibf/run_forecast_demo.py 2024-01-15 [--domain ruvu_lower] [--reuse]

Run with the hydromt-sfincs environment; SFINCS runs natively or in Docker.
"""

import argparse
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
    a = ap.parse_args()
    cfg = load_config()
    dom = cfg["domains"][a.domain]
    fc_dir = a.data_root / "ibf" / f"forecast_{a.issue.replace('-', '')}"
    dem = a.data_root / "sfincs" / f"dem_{a.domain}_fabdem30.tif"
    exp = a.data_root / "ibf" / "exposure"

    depths, scenarios = {}, []
    for scen in cfg["scenarios"]:
        q = pd.read_csv(fc_dir / f"{scen}.csv", index_col=0, parse_dates=True)[dom["inflow_reaches"]]
        work = a.data_root / "ibf" / "runs" / f"forecast_{a.issue}_{a.domain}_{scen}"
        if not (a.reuse and (work / "out" / "sfincs_map.nc").exists()):
            sfincs_model.build(a.domain, q, dem, work, map_every_s=3 * 3600)
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
    out = ROOT / "web" / "public" / "data" / "ibf" / "forecast"
    forecast_products.build(depths, exp / f"exposure_{a.domain}.parquet", exp / f"buildings_{a.domain}.parquet",
                            exp / f"population_{a.domain}.tif", exp / f"admin_{a.domain}.geojson", out, manifest)
    print(f"products in {out}")


if __name__ == "__main__":
    main()
