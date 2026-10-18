"""Write Wflow run configurations and execute them with Wflow.jl.

Time convention used throughout the pipeline: data for "day D" is the
UTC day D. Wflow forcing at time t drives the step that ends at t, so a
day-D total is stamped D+1 00:00 in the forcing file, the run starts at
first_day 00:00 (the state time) and ends at last_day+1 00:00. Output at
time t is therefore the flow of day t-1; ``read_output`` shifts it back.
"""

import shutil
import subprocess
import tomllib
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import tomli_w

from common import PIPELINE, log, paths

JULIA_PROJECT = PIPELINE / "julia"
GAUGE_MAP = "gauges_forecast_points"


def write_run(
    run_dir: Path,
    first_day: date,
    last_day: date,
    forcing: Path,
    state_in: Path | None,
    save_state: bool,
) -> Path:
    cfg = tomllib.loads((paths.model / "wflow_sbm.toml").read_text())
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg["dir_output"] = str(run_dir)
    cfg["time"]["starttime"] = f"{first_day.isoformat()}T00:00:00"
    cfg["time"]["endtime"] = f"{(last_day + timedelta(days=1)).isoformat()}T00:00:00"
    cfg["time"]["timestepsecs"] = 86400
    cfg["input"]["path_forcing"] = str(forcing)
    # The pipeline writes its own forcing, so HydroMT never filled this section.
    cfg["input"]["forcing"] = {
        "atmosphere_water__precipitation_volume_flux": "precip",
        "land_surface_water__potential_evaporation_volume_flux": "pet",
        "atmosphere_air__temperature": "temp",
    }
    cfg["input"]["path_static"] = str(paths.model / "staticmaps.nc")
    cfg["model"]["cold_start__flag"] = state_in is None
    cfg["state"]["path_input"] = str(state_in or paths.model / "instate" / "instates.nc")
    cfg["state"]["path_output"] = str(run_dir / "outstates.nc") if save_state else str(run_dir / "unused_outstates.nc")
    # Only discharge at the forecast points: no gridded output, no outlets.
    cfg["output"] = {
        "csv": {
            "path": "output.csv",
            "column": [{"header": "Q", "map": GAUGE_MAP, "parameter": "river_water__volume_flow_rate"}],
        }
    }
    path = run_dir / "wflow_sbm.toml"
    path.write_bytes(tomli_w.dumps(cfg).encode())
    return path


def run(tomls: list[Path]) -> None:
    julia = shutil.which("julia") or "julia"
    # Wflow parallelises its land and river computations over Julia threads.
    cmd = [julia, "--threads=auto", f"--project={JULIA_PROJECT}", str(JULIA_PROJECT / "run_wflow.jl"), *map(str, tomls)]
    log.info("Wflow: %d run(s)", len(tomls))
    subprocess.run(cmd, check=True)


def read_output(run_dir: Path) -> pd.DataFrame:
    """Daily discharge [m3/s], index = day, columns = forecast point ids."""
    df = pd.read_csv(run_dir / "output.csv", parse_dates=["time"], index_col="time")
    df = df[[c for c in df.columns if c.startswith("Q")]]
    df.columns = [int(c.rsplit("_", 1)[-1]) for c in df.columns]
    df.index = (df.index - pd.Timedelta(days=1)).normalize()
    return df.sort_index(axis=1)


def forcing_times(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Forcing timestamps for daily totals (see module docstring)."""
    return days + pd.Timedelta(days=1)
