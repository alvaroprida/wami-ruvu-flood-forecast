"""Generate a synthetic ensemble forecast so the web app can be built
before the Wflow pipeline exists.

Writes the same files the operational pipeline will produce:

    web/public/data/latest/forecast.json        issue metadata + per-reach summary
    web/public/data/latest/reaches/<id>.json    hydrograph ensemble, thresholds, rainfall

The scenario is a short-rains storm over the Uluguru Mountains: the Ruvu
headwaters exceed the 20-year flow, the rest of the network responds less.
All values are invented. Standard library only.

    python pipeline/mock/generate_forecast.py
"""

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "public" / "data"

ISSUED = datetime(2026, 10, 16, 0, tzinfo=timezone.utc)
N_MEMBERS = 51
STEP_H = 6
LEAD_DAYS = 15
HISTORY_DAYS = 10
RETURN_PERIODS = (2, 5, 20, 50)
SEED = 20261016

# Alert rule: the highest level whose return-period flow is exceeded
# by at least this share of members at any lead time.
ALERT_RULE = [(3, 20, 0.30), (2, 5, 0.30), (1, 2, 0.50)]

# Scenario per reach: median peak as a multiple of the 2-year flow,
# and time of peak in hours after issue.
SCENARIO = {
    "kinyasungwe": (0.35, 96),
    "mkondoa": (0.95, 90),
    "mkata": (0.80, 108),
    "wami_upper": (0.85, 132),
    "wami_lower": (1.05, 168),
    "ruvu_upper": (2.45, 66),
    "mvuha": (1.90, 60),
    "ruvu_middle": (1.85, 96),
    "ngerengere": (1.20, 84),
    "ruvu_lower": (1.55, 132),
}


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%MZ")


def pulse(t: float, t_peak: float, k: float = 3.0) -> float:
    """Unit-peak gamma-shaped hydrograph pulse."""
    if t <= 0:
        return 0.0
    x = t / t_peak
    return (x ** k) * math.exp(k * (1 - x))


def quantile(sorted_vals: list[float], q: float) -> float:
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def r1(x: float) -> float:
    return round(x, 1)


def build_reach(rid: str, area: float, rng: random.Random) -> tuple[dict, dict]:
    peak_factor, t_peak = SCENARIO[rid]

    # Return-period flows scale sub-linearly with upstream area.
    q2 = 0.55 * area ** 0.7
    thresholds = {f"rp{rp}": r1(q2 * (1 + 0.62 * math.log(rp / 2) ** 1.1)) for rp in RETURN_PERIODS}
    base = 0.10 * q2

    k = 3.0 if area > 10_000 else 4.0
    n_hist = HISTORY_DAYS * 24 // STEP_H
    n_fc = LEAD_DAYS * 24 // STEP_H
    times = [ISSUED + timedelta(hours=STEP_H * i) for i in range(-n_hist, n_fc + 1)]

    # Past simulation from the warm-state run: recession from an earlier small event.
    history = []
    for i in range(-n_hist, 1):
        h = i * STEP_H
        history.append(base * (1 + 0.9 * math.exp(h / 70)) + 0.18 * q2 * pulse(h + 200, 60, 3))
    q_now = history[-1]

    members = []
    for _ in range(N_MEMBERS):
        f = peak_factor * math.exp(rng.gauss(0, 0.28))
        shift = rng.gauss(0, 10)
        tp = max(24.0, t_peak + shift)
        series = []
        for i in range(0, n_fc + 1):
            h = i * STEP_H
            recession = (q_now - base) * math.exp(-h / 60)
            event = (f * q2 - base) * pulse(h, tp, k)
            noise = 1 + rng.gauss(0, 0.015)
            series.append(max(base * 0.6, (base + recession + event) * noise))
        members.append(series)

    # Ensemble quantiles per forecast step.
    qs = {"p05": [], "p25": [], "p50": [], "p75": [], "p95": []}
    for i in range(n_fc + 1):
        col = sorted(m[i] for m in members)
        for key, q in (("p05", 0.05), ("p25", 0.25), ("p50", 0.5), ("p75", 0.75), ("p95", 0.95)):
            qs[key].append(r1(quantile(col, q)))

    # Exceedance probabilities over the full forecast window.
    peaks = [max(m) for m in members]
    prob = {f"rp{rp}": round(sum(p > thresholds[f"rp{rp}"] for p in peaks) / N_MEMBERS, 2)
            for rp in RETURN_PERIODS}
    level = next((lvl for lvl, rp, share in ALERT_RULE if prob[f"rp{rp}"] >= share), 0)

    i_peak = max(range(len(qs["p50"])), key=lambda i: qs["p50"][i])

    # Daily catchment-mean rainfall (mm/day): storm two to three days ahead.
    storm = peak_factor * 22
    rain = {"days": [], "p10": [], "p50": [], "p90": []}
    for d in range(LEAD_DAYS):
        centre = max(0.0, storm * math.exp(-((d - t_peak / 24 + 1.5) ** 2) / 1.6)) + rng.uniform(0.5, 3)
        rain["days"].append(iso(ISSUED + timedelta(days=d)))
        rain["p10"].append(r1(centre * 0.35))
        rain["p50"].append(r1(centre))
        rain["p90"].append(r1(centre * (1.8 + 0.06 * d)))

    detail = {
        "id": rid,
        "issued": iso(ISSUED),
        "units": "m3/s",
        "history": {"times": [iso(t) for t in times[: n_hist + 1]], "q": [r1(v) for v in history]},
        "forecast": {
            "times": [iso(t) for t in times[n_hist:]],
            **qs,
            "members": [[r1(v) for v in m] for m in members],
        },
        "thresholds": thresholds,
        "rainfall": rain,
    }
    summary = {
        "alert_level": level,
        "prob_exceed": prob,
        "peak_q50": qs["p50"][i_peak],
        "peak_time": detail["forecast"]["times"][i_peak],
        "thresholds": thresholds,
    }
    return summary, detail


def main() -> None:
    network = json.loads((DATA / "network.geojson").read_text())
    rng = random.Random(SEED)
    out_dir = DATA / "latest" / "reaches"
    out_dir.mkdir(parents=True, exist_ok=True)

    reaches = {}
    for feat in network["features"]:
        p = feat["properties"]
        summary, detail = build_reach(p["id"], p["upstream_area_km2"], rng)
        reaches[p["id"]] = summary
        (out_dir / f"{p['id']}.json").write_text(json.dumps(detail, separators=(",", ":")))

    forecast = {
        "issued": iso(ISSUED),
        "mock": True,
        "model": "Wflow.jl (sbm) — synthetic output",
        "forcing": "ECMWF ENS open data, 51 members — synthetic",
        "members": N_MEMBERS,
        "timestep_hours": STEP_H,
        "lead_days": LEAD_DAYS,
        "alert_rule": [
            {"level": lvl, "return_period": rp, "min_probability": share} for lvl, rp, share in ALERT_RULE
        ],
        "reaches": reaches,
    }
    (DATA / "latest" / "forecast.json").write_text(json.dumps(forecast, indent=1))
    for rid, s in reaches.items():
        print(f"{rid:13s} level={s['alert_level']}  P(>RP2/5/20)="
              f"{s['prob_exceed']['rp2']:.2f}/{s['prob_exceed']['rp5']:.2f}/{s['prob_exceed']['rp20']:.2f}"
              f"  peak={s['peak_q50']:7.1f} at {s['peak_time']}")


if __name__ == "__main__":
    main()
