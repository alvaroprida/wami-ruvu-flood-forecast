# Impact-based forecast (IbF)

Turns discharge hydrographs into people and buildings affected, for the **IbF** tab of the site.
First domain: the **lower Ruvu floodplain** (`ibf.domains.ruvu_lower` in `config.yml`), fed by the
`ruvu_middle` and `ngerengere` reaches. Chosen because it is a flat floodplain next to the
Kibaha–Bagamoyo–Dar es Salaam corridor, so it has the most exposure of the ten reaches.

```
hydrographs ──▶ sfincs_model.py ──▶ max depth, 30 m ──▶ products.py ──▶ web/public/data/ibf/<mode>/
 demo: Wflow + CHIRPS   build + run      (downscaled      × WorldPop        manifest.json, summary.json,
 live: ENS p50 / p95    SFINCS 100 m      to FABDEM)      × Overture        depth.png, population.png,
                                                          × Englhardt       buildings.geojson
```

| Script | Purpose |
|---|---|
| `trigger.py` | Which domains to run: any inflow reach at alert level ≥ `min_alert_level` in `forecast.json` |
| `fetch_dem.py` | 30 m FABDEM mosaic for the domain |
| `admin.py` | Ward (ADM3) and district (ADM2) polygons from geoBoundaries, used to aggregate impact |
| `exposure.py` | Overture buildings + WorldPop window; people allocated to buildings by footprint area |
| `event_hydrograph.py` | Wflow run for a past period (CHIRPS final, cold start with spin-up) → daily discharge |
| `sfincs_model.py` | Build (hydromt-sfincs), run (WSL distro or native `sfincs`), downscale depth to 30 m |
| `vulnerability.py`, `impact.py` | Englhardt et al. (2019) stage-damage curves; depth × exposure → impact |
| `products.py` | Impact summary + the map overlays and affected buildings for the site |
| `run_ibf.py` | `demo` and `live` entry points that chain everything and write the manifest |

## Demo event (local)

```bash
python pipeline/ibf/fetch_dem.py ruvu_lower
python pipeline/ibf/exposure.py ruvu_lower
# Wflow over the event period (needs Julia >= 1.10 + pipeline/julia, the model release, JULIA=<path to julia>)
python pipeline/ibf/event_hydrograph.py <name> --start 2023-10-01 --end 2024-05-31
python pipeline/ibf/run_ibf.py demo --hydro <data_root>/ibf/<name>/wflow_q.csv --title "..." \
    --search-from 2023-11-01 --search-to 2024-05-31 --peak-days 12
```

The event window is ±`peak-days` around the largest summed inflow in the search window. The demo
products are committed under `web/public/data/ibf/demo/`.

## Demo forecast (lead times)

The site's first IbF view replays a real forecast: the ECMWF ENS run issued on **3 January 2024**, just
before the January 2024 flood rose (archived open data, 0.4°, 50 members), through Wflow, then the median and
95th-percentile inflows through SFINCS with 3-hourly maps. SFINCS is spun up on the observed-rainfall discharge
of the 7 days before the issue date, so the floodplain is not pre-filled at the forecast's first value. The
95th percentile catches the 7–8 January peak about 5 days ahead; the median underestimates it. Each lead day's maximum water level becomes a 30 m depth map, and impacts are
computed per building, ward and day, so the slider shows how the forecast impact develops.

```bash
# main environment (Wflow): warm state on CHIRPS up to 14 Jan, then the 50 members
python pipeline/ibf/hindcast_forecast.py 2024-01-03
# hydromt-sfincs environment: SFINCS per scenario (Docker on macOS) + per-day products
python pipeline/ibf/run_forecast_demo.py 2024-01-03
```

Products in `web/public/data/ibf/forecast/`: per-day depth and affected-population overlays per scenario,
a dimmed all-population layer, ward tables per day (`wards.json`), and **all building footprints** in one
PMTiles file (`buildings.pmtiles`, made with tippecanoe) whose properties hold the depth of every
scenario and day, so the map restyles them in the browser without reloading. `gauges.json` holds the forecast
discharge of every river gauge (10 forecast points + 40 virtual gauges) with its return-period thresholds, for
the gauge layer and the gauge timeline.

## Live (CI)

`.github/workflows/ibf-live.yml` runs after the daily forecast. If no inflow reach is alerted it only
publishes a "not triggered" manifest. Otherwise it runs SFINCS (Docker image `deltares/sfincs-cpu`) for
the median and 95th-percentile hydrographs and publishes the products as the `ibf-latest` release asset;
`deploy-pages.yml` unpacks it into `web/public/data/ibf/live/`. Static inputs (DEM, exposure) are cached.
**The triggered path has not run on CI yet**: today's forecast has no alert, so only the "not triggered"
path can be exercised there.

## Environment

hydromt-sfincs 1.2 needs hydromt 0.10, the Wflow build uses hydromt 1.x, so keep a separate environment:
`pip install -r pipeline/ibf/requirements-sfincs.txt` (Python 3.10–3.11). On Windows, SFINCS runs in a WSL
distro that has `sfincs` on its PATH (`SFINCS_WSL_DISTRO`, default `sfincs`). `_env.py` points PROJ at the
active environment (other installs, e.g. PostgreSQL, set `PROJ_LIB` globally and break rasterio/pyproj).

## Method and known limits

- **Wflow bias.** Wflow is uncalibrated and its discharge is far too high (the model's own 2-year flow at
  `ruvu_middle` is about 2,000 m³/s). SFINCS needs absolute discharge, so flood extent and impact are
  **overestimates** until Wflow is calibrated or bias-corrected. This is the main caveat of every number here.
- **Hydraulic model.** 150 m grid, 6 × 6 subgrid pixels (25 m) from the 30 m FABDEM, Manning 0.05 on land, inflow at
  the two reach outlets (snapped to the lowest cell within 600 m), coast as a fixed 0 m water level (no tide or
  surge), no rainfall on the domain, no infiltration, no river bathymetry beyond FABDEM. Max depth is
  downscaled to 30 m. Sea cells (DEM ≤ 0.05 m) are removed; permanent river water stays in the depth map.
- **Exposure.** WorldPop R2025A 2025, 100 m constrained (people per flooded cell, total conserved). Overture
  buildings (centroids, ≥ 15 m²); coverage in rural Tanzania is partial, so building counts are lower bounds.
  The people allocated to buildings add up to less than the WorldPop total because some cells have people but
  no mapped building.
- **Vulnerability.** Stage-damage curves of Englhardt et al. (2019), class I (non-engineered / informal) by
  default, class II (wooden) selectable in `config.yml`. The paper publishes the curves only as a figure, so the
  points in `vulnerability.py` were digitised from Fig. 2 (about ±0.03). Every building gets the class I curve:
  Overture has no construction material, so this is pessimistic for engineered city buildings.
- **Scenarios.** Live runs the median and 95th-percentile hydrographs, not the full ensemble.
