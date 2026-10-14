# Adaptive cube plotting

`adaptive_cube_plot.py` provides importable plotting functions for xarray cubes:

- `plot_time_slices`: time-index/date panel maps with shared colour scale, Cartopy projection, inferred data extent, coastlines/borders and optional GeoDataFrame boundaries.
- `plot_spatial_timeseries`: time series at selected points and area summaries.
- `plot_climate_mobility_period`: side-by-side climate and aggregated origin/destination mobility maps for a selected half-month.

## Install

Install the project dependencies plus optional geospatial packages:

```bash
pip install matplotlib numpy pandas xarray cartopy geopandas pyarrow pyproj
```

Cartopy may need system libraries depending on the platform. Importing the module and using time-series plotting does not require Cartopy; map functions do.

## Import

From the repository root:

```python
from code.plot_utils.adaptive_cube_plot import (
    plot_time_slices,
    plot_spatial_timeseries,
    plot_climate_mobility_period,
)
```

If `code` is not a Python package in the local checkout, add its parent directory to `sys.path`, or add `code/plot_utils` directly:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "code" / "plot_utils"))
from adaptive_cube_plot import plot_time_slices
```

## Panel maps

```python
import xarray as xr
from adaptive_cube_plot import plot_time_slices

ds = xr.open_zarr("data/zarr/metref_sample_1month.zarr")
fig, axes = plot_time_slices(
    ds,
    var="METREF",
    time_index=[0, 5, 10],
    data_crs="EPSG:4326",
    ncols=3,
    show=False,
)
```

The map extent is calculated from the selected coordinates. Set `extent=(xmin, xmax, ymin, ymax)` to crop all panels to a common area. `data_crs` describes the existing coordinate values; it does **not** reproject the data. Longitude/latitude coordinate names imply EPSG:4326. For projected `x/y`, pass the actual CRS (for example, `data_crs="EPSG:32628"`). The default display projection is Plate Carrée; supply a Cartopy CRS as `map_crs` for another projection.

Overlay an AOI or administrative boundary:

```python
import geopandas as gpd
boundaries = gpd.read_file("data/aoi.geojson")
fig, axes = plot_time_slices(
    ds, var="METREF", time_index=[0, 5], data_crs="EPSG:4326",
    boundaries=boundaries, ncols=2, show=False,
)
```

If a boundary file has no embedded CRS, provide `boundary_crs`. This assigns the source CRS metadata. Confirm the source CRS before assigning it.

## Climate and mobility comparison

The mobility table is expected to contain an origin or destination ID, a date/period column, and a numeric metric. Defaults match the normalized OD schema (`norm_spatial_id_origin`, `norm_spatial_id_destination`, `date`, `N_depart`). Spatial units must have a matching ID column and geometry.

```python
import geopandas as gpd
from adaptive_cube_plot import plot_climate_mobility_period

units = gpd.read_parquet("data/spatial/units.parquet")
fig, axes = plot_climate_mobility_period(
    ds,
    mobility="data/mobility/flows.parquet",
    spatial_units=units,
    var="METREF",
    period="2020-06-01",            # dates are grouped into days 1–15 / 16–month-end
    mobility_metric="N_depart_adj", # or N_depart / N_migrants_adj
    flow_direction="origin",        # alternatively: destination
    spatial_id_col="norm_spatial_id",
    data_crs="EPSG:4326",
    subset_type="your_subset",      # optional filter, if this column exists
    days_span=15,                    # optional filter, if this column exists
    show=False,
)
```

For `HalfMonthIndex` tables, set `period_col="HalfMonthIndex"` and pass the exact key as `mobility_period`; keep `period` as the climate date used for climate aggregation. Set `origin_col`/`destination_col` if your table uses other ID names. The comparison aggregates counts by origin or destination polygon; it does not draw OD flow lines. The juxtaposition is descriptive and does not establish a climate–mobility relationship. Exact temporal interpretation depends on the product timestamp semantics and the mobility period definition.

## Existing point and area time series

```python
fig, ax = plot_spatial_timeseries(
    ds, var="METREF",
    points={"Site A": (-16.4, 14.5)},
    areas={"AOI": (-17.0, -16.0, 13.0, 14.0)},
    show_area_spread=True,
    show=False,
)
```

Point coordinates and area bounds must use the cube coordinate system. For projected data, provide projected point/bounds values; the time-series function samples the nearest grid cell and does not transform coordinates.

## Known limits

- Automatic extent assumes rectilinear 1-D x/y coordinates; curvilinear grids need preprocessing or a dedicated plotting path.
- Coastline/border detail is cartographic context, not a replacement for authoritative local boundaries.
- Plate Carrée is a practical default, but can distort area and shape at high latitudes or across wide extents.
- Mobility IDs must match the spatial-unit IDs and be consistently typed. Unmatched units appear without a mobility value.
- Mobility aggregates depend on filters, adjustment factors and period semantics; inspect those before interpreting the maps.
