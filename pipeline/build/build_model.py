"""Step 1c - build the Wflow model with HydroMT-Wflow.

Fills the placeholders in wflow_build.yml from config.yml, runs
``hydromt build wflow_sbm`` against the static data catalog, then writes
the upstream area of each snapped forecast point back into
web/public/data/network.geojson so the site shows model values.

    python pipeline/build/build_model.py
"""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import xarray as xr
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import PIPELINE, WEB_DATA, bbox, config, log, paths  # noqa: E402

HERE = PIPELINE / "build"


def resolved_recipe() -> Path:
    cfg = config()
    outlets = cfg["region"]["outlets"].values()
    text = (HERE / "wflow_build.yml").read_text()
    for key, value in {
        "<res_deg>": cfg["model"]["res_deg"],
        "<outlets>": [[x for x, _ in outlets], [y for _, y in outlets]],
        "<bbox>": list(bbox()),
        "<river_upa_km2>": cfg["model"]["river_upa_km2"],
        "<forecast_points>": str(HERE / "forecast_points.csv"),
    }.items():
        text = text.replace(key, json.dumps(value) if not isinstance(value, str) else value)
    out = paths.model.parent / "wflow_build.resolved.yml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    yaml.safe_load(text)  # fail early on a bad substitution
    return out


def update_network() -> None:
    """Upstream area at each forecast point, taken from the built model."""
    ds = xr.open_dataset(paths.model / "staticmaps.nc")
    gauges = ds["gauges_forecast_points"]
    upa = ds["meta_upstream_area"]
    points = pd.read_csv(HERE / "forecast_points.csv")
    area = {}
    for row in points.itertuples():
        cell = upa.where(gauges == row.id)
        area[row.reach] = int(round(float(cell.max())))
    path = WEB_DATA / "network.geojson"
    net = json.loads(path.read_text())
    for f in net["features"]:
        f["properties"]["upstream_area_km2"] = area[f["properties"]["id"]]
    path.write_text(json.dumps(net, separators=(",", ":")))
    log.info("upstream areas from the model: %s", area)


def main() -> None:
    if not (HERE / "forecast_points.csv").exists():
        subprocess.run([sys.executable, str(HERE / "forecast_points.py")], check=True)
    recipe = resolved_recipe()
    cmd = [
        "hydromt", "build", "wflow_sbm", str(paths.model),
        "-i", str(recipe),
        "-d", str(paths.static / "data_catalog.yml"),
        "--fo", "-v",
    ]
    log.info("running %s", " ".join(cmd))
    subprocess.run(cmd, check=True)
    update_network()


if __name__ == "__main__":
    main()
