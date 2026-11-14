"""Decide which SFINCS domains to run from the hazard forecast.

    python pipeline/ibf/trigger.py [web/public/data/latest/forecast.json]
"""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_config() -> dict:
    return yaml.safe_load((ROOT / "pipeline" / "config.yml").read_text())["ibf"]


def triggered_domains(forecast: dict, cfg: dict) -> dict[str, dict[str, int]]:
    """Domain -> {inflow reach: alert level}, for domains with any inflow reach alerted."""
    out = {}
    for name, dom in cfg["domains"].items():
        levels = {r: forecast["reaches"][r]["alert_level"] for r in dom["inflow_reaches"]}
        if max(levels.values()) >= cfg["min_alert_level"]:
            out[name] = levels
    return out


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "web/public/data/latest/forecast.json")
    result = triggered_domains(json.loads(path.read_text()), load_config())
    print(json.dumps(result, indent=2) if result else "No domain triggered.")
