# Pipeline

Four steps: the first two run once on a workstation; the last two run every day on GitHub Actions.

| Step | Script | Runs | Output |
|---|---|---|---|
| 1. Model build | `static/fetch_static.py`, `build/forecast_points.py`, `build/build_model.py` | once | Wflow model (1 km, both basins, 10 forecast points) |
| 2. Historical run + thresholds | `historical.py` | once | `ops/thresholds.json`, `ops/era5_clim.nc`, seed model state |
| 3. Warm state | `daily.py` | daily | model state up to yesterday |
| 4. Ensemble forecast | `daily.py` | daily | `forecast.json` + one JSON per reach for the site |

All large files live under `data_root` (`.cache/data` by default, set in `config.yml` or with `WRFF_DATA_ROOT`).

## Setup

```bash
# Python (3.11+)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r pipeline/requirements.txt

# Julia 1.10+ with Wflow.jl
curl -fsSL https://install.julialang.org | sh      # juliaup
julia --project=pipeline/julia -e 'using Pkg; Pkg.instantiate()'
```

Credentials:

| Service | Used for | Where |
|---|---|---|
| [Copernicus CDS](https://cds.climate.copernicus.eu/) | ERA5 (historical only) | `~/.cdsapirc` |

CHIRPS, ECMWF open data, FABDEM, SoilGrids, WorldCover and HydroLAKES need no account.

## Step 1 – model build

```bash
python pipeline/static/fetch_static.py        # FABDEM + flow network, SoilGrids, WorldCover, HydroLAKES (~1 GB)
python pipeline/build/forecast_points.py      # one point per reach, 5 km upstream of its outlet
python pipeline/build/build_model.py          # hydromt build wflow_sbm
```

## Step 2 – historical run and thresholds

```bash
python pipeline/historical.py                 # CHIRPS final + ERA5, 2001–2025
```

Downloads are resumable. The first year is spin-up and excluded from the annual maxima.
Thresholds are a Gumbel fit (L-moments) to the 24 complete years 2002–2025, so the 50-year
value is an extrapolation and should be read as indicative. The daily job catches up from
January 2026 on its first run.

## Steps 3–4 – daily run

```bash
python pipeline/daily.py --out web/public/data/latest
```

To run it on GitHub Actions (`.github/workflows/daily-forecast.yml`), publish the model and the
seed state once (no secrets needed):

```bash
tar -czf model.tar.gz -C .cache/data model
tar -czf state.tar.gz -C .cache/data state
gh release create model model.tar.gz --title "Wflow model" --notes "Built with pipeline/build"
gh release create state state.tar.gz --title "Model state" --notes "Updated daily"
```

## Design choices

- **Daily time step** throughout: CHIRPS and the ENS are used as daily totals, and the
  thresholds come from daily maxima, so forecasts and thresholds are comparable.
- **CHIRPS for observed rainfall.** It blends satellite estimates with station data and does
  well over East Africa. The thresholds use CHIRPS final and the warm state CHIRPS final or
  prelim, so both come from the same product; prelim has fewer stations, so a small bias is
  possible.
- **Temperature and PET from ERA5 monthly means**, interpolated to days between mid-month
  values (De Bruin PET). All years come in one CDS request; daily statistics would need a
  request per variable-year, each queueing for minutes to hours. The daily runs use the
  day-of-year climatology of the same data, since ERA5 arrives about 5 days late. PET varies
  mostly with the season here, and temperature only drives snow, which the model leaves out.
- **CHIRPS access.** Long periods come from the IRI/LDEO Data Library, which cuts out the
  region server-side (one request per year); the newest days come from the CHC server one
  file at a time, because reading hundreds of files from CHC in a burst gets the client blocked.
- **Provisional last days.** CHIRPS prelim lags about 6 days, so those days use the ECMWF HRES
  day-1 forecast (00–24 h total), read from ECMWF's cloud archive. They are re-run with CHIRPS
  once it is published; only CHIRPS-based states are kept.
- **No calibration yet.** Default HydroMT-Wflow parameters. Because thresholds come from the same
  model, the alert levels are much less sensitive to model bias than the raw discharge values.
- **Hydrography from FABDEM.** FABDEM (Copernicus DEM with forests and buildings removed) is
  averaged from 30 m to 3 arcsec, the mapped rivers are burned in 10 m, and flow directions,
  upstream area, basins, stream order and slope are derived with pyflwdir. River width has no
  measured source and follows a power law on upstream area (about 70 m at the Wami mouth).
- **Lakes and reservoirs** from HydroLAKES, run without control rules (Mindu dam is small
  compared with flood volumes).
