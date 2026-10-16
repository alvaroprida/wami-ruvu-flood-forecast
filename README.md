# Wami–Ruvu Flood Forecast

**[▶ Open the live dashboard](https://alvaroprida.github.io/wami-ruvu-flood-forecast/)**

[![Deploy](https://github.com/alvaroprida/wami-ruvu-flood-forecast/actions/workflows/deploy-pages.yml/badge.svg)](https://github.com/alvaroprida/wami-ruvu-flood-forecast/actions/workflows/deploy-pages.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Experimental ensemble river-flow forecasting for the **Wami** and **Ruvu** basins in eastern Tanzania.
A distributed hydrological model (Wflow) is driven by the 51-member ECMWF ensemble rainfall forecast;
forecast peaks are compared against model-consistent return-period flows to flag reaches at risk of flooding
up to 15 days ahead.

![Screenshot of the forecast dashboard](docs/screenshot.png)

> **Status: prototype.** The web app currently runs on synthetic forecast data (see
> [`pipeline/mock`](pipeline/mock)) while the model pipeline is being built. This is a research project,
> not an official warning service — official flood and weather warnings for Tanzania are issued by the
> Tanzania Meteorological Authority.

## How it works

```
        observed rainfall (IMERG)                  ECMWF ENS, 51 members, 15 days
                  │                                             │
                  ▼                                             ▼
   ┌──────────────────────────────┐   daily state   ┌──────────────────────────────┐
   │ Wflow warm-state run         │ ──────────────▶ │ Wflow ensemble forecast      │
   └──────────────────────────────┘                 └──────────────────────────────┘
                                                                │ discharge per reach
   ┌──────────────────────────────┐                             ▼
   │ 40-year Wflow simulation     │  2/5/20/50-yr   ┌──────────────────────────────┐
   │ → annual maxima → Gumbel/GEV │ ──────────────▶ │ Exceedance probabilities     │
   └──────────────────────────────┘   thresholds    │ → alert level per reach      │
                                                    └──────────────────────────────┘
                                                                │ static JSON
                                                                ▼
                                                    React + MapLibre + ECharts site
```

1. **Warm state.** Wflow runs continuously on near-real-time satellite rainfall, saving its state daily.
2. **Ensemble forecast.** Each day the model restarts from that state, once per ensemble member.
3. **Thresholds.** Return-period flows come from a long simulation with the *same* model, so systematic
   model bias largely cancels out (the approach used by GloFAS).
4. **Alerts.** A reach is flagged when enough members exceed a return-period flow at any lead time:

   | Level | Rule |
   |---|---|
   | 20-year flow likely | ≥ 30% of members above the 20-year flow |
   | 5-year flow likely | ≥ 30% of members above the 5-year flow |
   | 2-year flow likely | ≥ 50% of members above the 2-year flow |

The site is fully static: the pipeline writes JSON files, the front-end reads them. No server, no database.

## Repository layout

```
model/          Wflow model build (HydroMT-Wflow config, Wflow TOML)        — planned
pipeline/       Data ingestion, forecast runs, thresholds, alert logic
  basins/       Basin delineation from HydroBASINS + overview map (docs/basins.png)
  mock/         Synthetic network + forecast generator used by the prototype site
web/            React front-end (Vite, TypeScript, MapLibre GL, ECharts, Tailwind)
docs/           Screenshots and notes
```

## Data contract

Everything the front-end needs lives under `web/public/data/`:

| File | Content |
|---|---|
| `network.geojson` | Forecast reaches: geometry, basin, upstream area, outlet point |
| `latest/forecast.json` | Issue time, alert rule, per-reach summary (level, exceedance probabilities, peak) |
| `latest/reaches/<id>.json` | Simulated past flow, ensemble quantiles and members, thresholds, catchment rainfall |

Time series use `locationId`-style reach ids and UTC timestamps so they map directly onto the
Delft-FEWS Published Interface; the operational outputs will also be written as CF-NetCDF for FEWS import.

## Run locally

```bash
# regenerate the mock data (Python 3.10+, standard library only)
python pipeline/mock/build_network.py        # fetches river geometry from OpenStreetMap
python pipeline/mock/generate_forecast.py

# basin outlines and overview map (needs geopandas, matplotlib, contextily)
python pipeline/basins/extract_basins.py

# run the site
cd web
npm install
npm run dev
```

## Roadmap

- [x] Front-end prototype on synthetic data
- [ ] Wflow model build for both basins (HydroMT-Wflow, MERIT Hydro, reservoirs)
- [ ] Historical simulation and return-period thresholds
- [ ] Daily warm-state run on IMERG + ERA5
- [ ] ECMWF ENS ingestion and ensemble forecast runs
- [ ] Hindcast verification against past flood events; comparison with GloFAS and Google Flood Hub
- [ ] Scheduled daily run and automatic deployment

## Data & credits

- [Wflow.jl](https://github.com/Deltares/Wflow.jl) and [HydroMT-Wflow](https://github.com/Deltares/hydromt_wflow), Deltares
- Forecast rainfall: [ECMWF open data](https://www.ecmwf.int/en/forecasts/datasets/open-data), CC BY 4.0
- Observed rainfall: NASA GPM IMERG
- Hydrography: MERIT Hydro
- Basin boundaries: [HydroSHEDS HydroBASINS](https://www.hydrosheds.org/products/hydrobasins) v1c
- River geometry: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL); basemap: [OpenFreeMap](https://openfreemap.org)

## License

Code is released under the [MIT License](LICENSE). Third-party data keeps its own licence (see above).
