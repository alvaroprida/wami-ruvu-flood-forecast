# Impact-based forecast (IbF)

Prototype for the **IbF** tab: turn the hazard forecast into people and buildings affected.
First domain: the **lower Ruvu floodplain** (config `ibf.domains.ruvu_lower`), fed by the
`ruvu_middle` and `ngerengere` forecast reaches. Chosen because it is a flat floodplain next to the
Kibaha–Bagamoyo–Dar es Salaam corridor, so it has the most exposure of the ten reaches.

```
forecast.json ──▶ trigger.py ──▶ sfincs_model.py ──▶ depth maps ──▶ impact.py ──▶ impact.json
 (alert levels)   which domains    SFINCS per        (hmax, per     × WorldPop
                  to run           scenario          scenario)      × Overture buildings
```

| Step | Script | Status |
|---|---|---|
| Trigger: domains whose inflow reaches are alerted | `trigger.py` | works on the current forecast |
| Hydraulic model build + run, per scenario (`p50`, `p95` hydrograph) | `sfincs_model.py` | **written, not executed** (no SFINCS executable was available) |
| 30 m DEM | `fetch_dem.py` | tested (real FABDEM tiles for the domain) |
| Depth × exposure → impact, Englhardt curves | `impact.py`, `vulnerability.py` (`test_impact.py`) | core logic tested on synthetic data; raster/vector alignment helpers not yet run |
| Site JSON + IbF tab | — | not started: the tab shows the chain and the triggered reaches only |

## Setup

Use a separate environment: hydromt-sfincs 2.x needs hydromt ≥ 1.4, which may conflict with the
Wflow pins.

```bash
pip install -r pipeline/ibf/requirements.txt
```

SFINCS itself is not a pip package. On Linux/GitHub Actions run it with Docker
(`deltares/sfincs-cpu`, `--vm docker`); on Windows download the executable from Deltares and pass `--exe`.

## Exposure data (once)

```bash
# Population: WorldPop R2025A, 2025, 100 m constrained (URL in config.yml)
curl -O https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/TZA/v1/100m/constrained/tza_pop_2025_CN_100m_R2025A_v1.tif

# Buildings: Overture Maps footprints for the domain bbox
overturemaps download --bbox=38.45,-7.08,39.00,-6.30 -f geoparquet --type=building -o buildings_ruvu_lower.parquet
```

Overture coverage in rural Tanzania is patchy (largely derived from OSM and Google/Microsoft ML footprints),
so building counts are lower bounds in places; population is the more complete measure.

## Known gaps and decisions

- **Elevation.** 30 m FABDEM, mosaicked for the domain by `fetch_dem.py` (tested: 2808 x 1980 cells for the lower Ruvu).
  FABDEM has forests and buildings removed but is still a surface model of limited vertical accuracy on flat floodplains.
- **Wflow bias.** Wflow is uncalibrated and its discharge is too high; SFINCS needs absolute discharge,
  so flood extents will be overestimated until Wflow is bias-corrected (or hydrographs are quantile-mapped).
- **Boundaries.** Inflow at the two reach outlets, sea level fixed at 0 m (no tide or surge), no rainfall
  on the domain and no river bathymetry beyond what FABDEM carries.
- **Scenarios.** Two runs per domain (median and 95th-percentile hydrograph) instead of the full ensemble.
- **Vulnerability.** Stage-damage curves of Englhardt et al. (2019), class I (non-engineered/informal buildings) by
  default, class II (wooden) selectable in `config.yml`. The paper only publishes the curves as a figure, so the points
  in `vulnerability.py` were digitised from Fig. 2 (about ±0.03). Every building is assumed to be class I: Overture has
  no construction material, so this is a deliberately pessimistic choice for rural/informal stock and overstates damage
  in engineered city buildings. Damage is reported as a mean damage factor and as building-loss equivalents.
- **Hosting.** Flood-extent products for the site should be simplified polygons (GeoJSON), not rasters.
