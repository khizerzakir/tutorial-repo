## Plotting Utils


```python
from pathlib import Path
import sys

repo_root = next(
    parent for parent in [Path.cwd().resolve(), *Path.cwd().resolve().parents]
    if (parent / "pyproject.toml").exists()
)
module_dir = repo_root / "code" / "plot_utils"
sys.path.insert(0, str(module_dir))

from adaptive_cube_plot import plot_time_slices, plot_spatial_timeseries

ds = xr.open_zarr("data/zarr/metref_sample_1month.zarr", chunks="auto")
```

If your notebook is running outside the repository root, replace `Path.cwd()` with the full path to your project folder.

## Plot maps by time index

```python
fig, axes = plot_time_slices(
    ds,
    var="NDVI",
    time_index=[0, 5, 10],
    ncols=3,
    vmin=0,
    vmax=1,
)
```

## Plot maps by date

The dates must match timestamps in the dataset.

```python
fig, axes = plot_time_slices(
    ds,
    var="NDVI",
    times=["2013-01-01", "2013-06-01"],
    ncols=2,
    vmin=0,
    vmax=1,
)
```

You can crop the maps by extent. The order is **xmin, xmax, ymin, ymax**:

```python
fig, axes = plot_time_slices(
    ds,
    var="NDVI",
    time_index=[0, 5, 10],
    extent=(-18, -11, 12, 17),
    ncols=2,
    vmin=0,
    vmax=1,
)
```

## Plot time series for selected points and areas

Points use **(longitude, latitude)** and select the nearest grid cell. Areas use a bounding box in the order **(xmin, xmax, ymin, ymax)** and are summarized at every timestep.

```python
fig, ax = plot_spatial_timeseries(
    ds,
    var="NDVI",
    points={
        "Niakhar": (-16.4, 14.5),
        "Dakar": (-17.45, 14.7),
    },
    areas={
        "Study area": (-17, -16, 13, 14),
    },
    area_stat="mean",          # or "median"
    show_area_spread=True,     # area mean ± spatial standard deviation
    time_range=("2013-01-01", "2015-12-31"),
)
```

The module currently provides two plotting functions: `plot_time_slices` for map panels and `plot_spatial_timeseries` for point and area time series. Use the same `vmin` and `vmax` when comparing maps across dates; otherwise each call may use its own data range.