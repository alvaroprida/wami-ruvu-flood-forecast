# Static data

`fetch_static.py` crops every global dataset to the region on the fly and writes a
HydroMT data catalog (`<data_root>/static/data_catalog.yml`) that the model build uses.

| Dataset | Use in the model | Access |
|---|---|---|
| FABDEM V1-2 (30 m → 3 arcsec) | elevation; flow directions, upstream area, river width derived with pyflwdir | open (range requests into the 10° zips) |
| SoilGrids 2020 + 2017 depth to bedrock | soil hydraulic parameters | open |
| ESA WorldCover 2021 | land-use parameters, LAI | open |
| HydroLAKES v1.0 | lakes and reservoirs (e.g. Mindu dam) | open |

## LAI table (assumption)

`lai_mapping_esa_worldcover.csv` gives a monthly leaf area index per ESA WorldCover class.
The usual source, a MODIS LAI climatology, is not openly available in a ready-to-use form,
so these are **approximate values** that follow the bimodal rainfall regime of eastern
Tanzania: green-up in the long rains (Mar–May) and short rains (Nov–Dec), minimum in the
dry season (Jul–Sep). Replacing it with a MODIS-derived table (HydroMT `setup_laimaps`
writes one) is on the roadmap.
