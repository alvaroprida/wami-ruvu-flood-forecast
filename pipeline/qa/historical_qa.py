"""QA/QC plots of the historical simulation.

For a set of reaches: daily hydrographs, mean monthly regime, annual maxima,
and a rainfall-runoff check (CHIRPS catchment rainfall vs simulated runoff
depth). Works on whatever years have finished, so it can run while the
historical simulation is still going.

    python pipeline/qa/historical_qa.py [--out docs/qa]
"""

import argparse
import sys
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ROOT, config, model_grid, paths, to_model_grid  # noqa: E402
from daily import _reach_names, upstream_masks  # noqa: E402
from run import wflow  # noqa: E402

REACHES = ["kinyasungwe", "mkondoa", "wami_upper", "wami_lower", "ruvu_upper", "ngerengere", "ruvu_middle", "ruvu_lower"]
LABELS = {"kinyasungwe": "Kinyasungwe", "mkondoa": "Mkondoa", "wami_upper": "Wami (upper)", "wami_lower": "Wami (lower)",
          "ruvu_upper": "Ruvu (upper)", "ngerengere": "Ngerengere", "ruvu_middle": "Ruvu (middle)", "ruvu_lower": "Ruvu (lower)"}

# Reference palette (dataviz skill): series blue, secondary ink, hairline grid.
BLUE, ORANGE, INK, INK2, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "axes.titlesize": 10, "axes.titleweight": "semibold",
    "axes.titlecolor": INK, "axes.titlelocation": "left",
})


def load_q() -> pd.DataFrame:
    names = _reach_names()
    parts = [wflow.read_output(d) for d in sorted((paths.runs / "historical").iterdir())
             if (d / "done").exists()]
    return pd.concat(parts).rename(columns=names)


def catchment_rain(q_years: list[int]) -> pd.DataFrame:
    """Daily CHIRPS rainfall averaged over each reach's upstream catchment [mm/day]."""
    grid = model_grid()
    masks = upstream_masks(grid)
    out = []
    for y in q_years:
        da = to_model_grid(xr.open_dataarray(paths.forcing / "chirps" / f"chirps_{y}.nc"), grid)
        out.append(pd.DataFrame({r: da.where(m).mean(("y", "x")).to_series() for r, m in masks.items()}))
    return pd.concat(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "qa"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)

    q = load_q()
    years = sorted(set(q.index.year))
    area = {r: a for r, a in zip(*[pd.read_json(ROOT / "web/public/data/network.geojson")["features"]
                                     .map(lambda f: f["properties"][k]) for k in ("id", "upstream_area_km2")])}
    spin = pd.Timestamp(config()["historical"]["spinup_end"])
    qs = q[q.index > spin]
    span = f"{qs.index.min():%Y}–{qs.index.max():%Y}"

    # 1. Daily hydrographs (small multiples, one axis each).
    fig, axes = plt.subplots(len(REACHES), 1, figsize=(11, 1.55 * len(REACHES)), sharex=True)
    for ax, r in zip(axes, REACHES):
        ax.plot(q.index, q[r], color=BLUE, lw=0.8)
        ax.axvspan(q.index.min(), spin, color=GRID, alpha=0.5, lw=0)
        ax.set_title(f"{LABELS[r]}  ·  {area[r]:,} km²", fontsize=9, pad=2)
        ax.set_ylabel("m³/s")
        ax.set_ylim(bottom=0)
    axes[0].text(q.index.min(), axes[0].get_ylim()[1] * 0.92, " spin-up", color=MUTED, fontsize=8, va="top")
    axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle(f"Simulated daily discharge, {years[0]}–{years[-1]} (uncalibrated Wflow, CHIRPS + ERA5)",
                 x=0.01, ha="left", fontsize=11, fontweight="semibold", color=INK)
    fig.tight_layout()
    fig.savefig(out / "hydrographs_daily.png", dpi=130)
    plt.close(fig)

    # 2. Mean monthly regime and 3. annual maxima.
    fig, axes = plt.subplots(2, 4, figsize=(11, 5))
    for ax, r in zip(axes.flat, REACHES):
        monthly = qs[r].groupby(qs.index.month).mean()
        ax.bar(monthly.index, monthly.values, width=0.7, color=BLUE)
        ax.set_xticks(range(1, 13), list("JFMAMJJASOND"))
        ax.set_title(LABELS[r], fontsize=9)
        ax.set_ylabel("m³/s" if ax in axes[:, 0] else "")
    fig.suptitle(f"Mean monthly discharge, {span}", x=0.01, ha="left", fontsize=11, fontweight="semibold", color=INK)
    fig.tight_layout()
    fig.savefig(out / "regime_monthly.png", dpi=130)
    plt.close(fig)

    amax = qs.groupby(qs.index.year).max()
    fig, axes = plt.subplots(2, 4, figsize=(11, 5))
    for ax, r in zip(axes.flat, REACHES):
        ax.bar(amax.index, amax[r], width=0.7, color=BLUE)
        ax.set_title(LABELS[r], fontsize=9)
        ax.set_ylabel("m³/s" if ax in axes[:, 0] else "")
        ax.xaxis.set_major_locator(plt.MaxNLocator(4, integer=True))
    fig.suptitle(f"Annual maximum daily discharge, {span}", x=0.01, ha="left", fontsize=11, fontweight="semibold", color=INK)
    fig.tight_layout()
    fig.savefig(out / "annual_maxima.png", dpi=130)
    plt.close(fig)

    # 4. Rainfall-runoff check per reach (mean annual totals over complete post-spin-up years).
    rain = catchment_rain([y for y in years if pd.Timestamp(f"{y}-12-31") > spin])
    rows = []
    for r in REACHES:
        runoff_mm = qs[r].mean() * 86400 * 365.25 / (area[r] * 1e6) * 1000
        rain_mm = rain[r].mean() * 365.25
        rows.append({"reach": LABELS[r], "area_km2": area[r], "mean_Q_m3s": round(qs[r].mean(), 1),
                     "rain_mm_yr": round(rain_mm), "runoff_mm_yr": round(runoff_mm),
                     "runoff_coefficient": round(runoff_mm / rain_mm, 2)})
    table = pd.DataFrame(rows)
    table.to_csv(out / "water_balance.csv", index=False)

    fig, ax = plt.subplots(figsize=(8, 3.6))
    y = np.arange(len(table))[::-1]
    ax.barh(y + 0.2, table.rain_mm_yr, height=0.36, color=MUTED, label="Rainfall (CHIRPS)")
    ax.barh(y - 0.2, table.runoff_mm_yr, height=0.36, color=BLUE, label="Simulated runoff")
    for yi, row in zip(y, table.itertuples()):
        ax.text(row.runoff_mm_yr + 15, yi - 0.2, f"{row.runoff_coefficient:.0%}", va="center", fontsize=8, color=INK2)
    ax.set_yticks(y, table.reach)
    ax.set_xlabel("mm per year")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    ax.set_title(f"Catchment water balance, {span} (label: runoff coefficient)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "water_balance.png", dpi=130)
    plt.close(fig)
    print(table.to_string(index=False))
    print(f"figures in {out}")


if __name__ == "__main__":
    main()
