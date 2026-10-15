"""CRS-aware plots for xarray climate cubes and aggregated mobility data.

Cartopy is required for map functions. Lon/lat coordinates default to
EPSG:4326; projected x/y coordinates require an explicit ``data_crs`` unless
the CRS is stored in the DataArray metadata. Plotting never mutates the cube.

Examples
--------
    import xarray as xr
    from adaptive_cube_plot import plot_time_slices

    ds = xr.open_zarr("climate_cube.zarr")  # or xr.open_dataset(...)
    fig, axes = plot_time_slices(
        ds, var="NDVI", time_index=[0, 6, 12], vmin=0, vmax=1,
        data_crs="EPSG:4326",  # bounds infer from the selected data by default
    )

    fig, ax = plot_spatial_timeseries(
        ds, var="NDVI", points={"Niakhar": (-16.4, 14.5)},
        areas={"Study area": (-17, -16, 13, 14)},
    )
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence
import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable


# User-provided fixed colour ramp. Positions are normalized from 0 to 1.
_COLORS = [
    (0.00, "#f1f1f1"),
    (0.08, "#556691"),
    (0.12, "#112182"),
    (0.22, "#135aba"),
    (0.32, "#449bf3"),
    (0.42, "#c5eefd"),
    (0.50, "#ffd55c"),
    (0.60, "#ff8800"),
    (0.70, "#f11c00"),
    (0.80, "#ae2716"),
    (0.90, "#7e0007"),
    (1.00, "#510056"),
]
VAR_CMAP = LinearSegmentedColormap.from_list("Var", _COLORS, N=256)


def _find_coord(data: xr.DataArray, requested: str | None, candidates: Sequence[str], label: str) -> str:
    """Resolve a coordinate name from an explicit name or common aliases."""
    if requested is not None:
        if requested not in data.coords and requested not in data.dims:
            raise ValueError(f"{label} coordinate {requested!r} not found. Available: {list(data.coords)}")
        return requested
    for name in candidates:
        if name in data.coords or name in data.dims:
            return name
    raise ValueError(f"Could not identify {label} coordinate. Pass {label}_coord explicitly.")


def _indices_for_selection(
    data: xr.DataArray,
    time_coord: str,
    time_index: int | Sequence[int] | None,
    times: object | Sequence[object] | None,
) -> list[int]:
    """Convert index/date arguments to validated positional indices."""
    n = data.sizes[time_coord]
    if time_index is not None and times is not None:
        raise ValueError("Use either time_index or times, not both.")
    if times is not None:
        values = [times] if isinstance(times, (str, date, datetime, np.datetime64, pd.Timestamp)) else list(times)
        coord_values = pd.to_datetime(data[time_coord].values)
        out = []
        for value in values:
            target = pd.Timestamp(value)
            matches = np.flatnonzero(coord_values == target)
            if len(matches) == 0:
                raise KeyError(f"Requested time {value!r} is not an exact coordinate value. Use a valid dataset timestamp.")
            out.append(int(matches[0]))
        return out
    if time_index is None:
        return [0]
    raw = [time_index] if isinstance(time_index, (int, np.integer)) else list(time_index)
    out = []
    for value in raw:
        if not isinstance(value, (int, np.integer)):
            raise TypeError("time_index must contain integers. Use times=... for date selection.")
        idx = int(value)
        if idx < 0 or idx >= n:
            raise IndexError(f"Time index {idx} outside valid range 0 to {n - 1}.")
        out.append(idx)
    if not out:
        raise ValueError("Select at least one time index or date.")
    return out


def _crop(data: xr.DataArray, x_name: str, y_name: str, extent: tuple[float, float, float, float] | None) -> xr.DataArray:
    """Crop rectilinear coordinates to (xmin, xmax, ymin, ymax), either axis order."""
    if extent is None:
        return data
    xmin, xmax, ymin, ymax = extent
    x = data[x_name]
    y = data[y_name]
    if x.ndim != 1 or y.ndim != 1:
        raise ValueError("extent cropping currently expects 1-D longitude/x and latitude/y coordinates.")
    xmask = (x >= xmin) & (x <= xmax)
    ymask = (y >= ymin) & (y <= ymax)
    if not bool(xmask.any()) or not bool(ymask.any()):
        raise ValueError("The requested extent does not overlap the dataset coordinates.")
    return data.where(xmask & ymask, drop=True)


def _map_dependencies():
    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
    except ImportError as exc:
        raise ImportError("Map plotting requires Cartopy. Install it with `pip install cartopy`.") from exc
    return ccrs, cfeature


def _data_crs(data: xr.DataArray, x_name: str, y_name: str, requested):
    """Resolve coordinate CRS; lon/lat names are the only safe implicit case."""
    if requested is not None:
        return requested
    for key in ("crs", "spatial_ref", "crs_wkt"):
        if key in data.attrs:
            return data.attrs[key]
    for coord in (data[x_name], data[y_name]):
        for key in ("crs", "spatial_ref", "crs_wkt"):
            if key in coord.attrs:
                return coord.attrs[key]
    if x_name.lower() in {"lon", "longitude"} and y_name.lower() in {"lat", "latitude"}:
        return "EPSG:4326"
    raise ValueError("Could not infer the data CRS. Pass data_crs, e.g. 'EPSG:4326' or 'EPSG:32628'.")


def _cartopy_crs(value, ccrs):
    if hasattr(value, "transform_points"):
        return value
    from pyproj import CRS
    parsed = CRS.from_user_input(value)
    if parsed.is_geographic:
        return ccrs.PlateCarree()
    epsg = parsed.to_epsg()
    if epsg is None:
        raise ValueError("Cartopy needs an EPSG code for this projected CRS; pass a Cartopy CRS as data_crs.")
    return ccrs.epsg(epsg)


def _default_map_crs(value, extent, source_crs, ccrs):
    """Choose a local conformal projection for geographic regional maps."""
    try:
        from pyproj import CRS
        geographic = CRS.from_user_input(value).is_geographic
    except Exception:
        geographic = False
    xmin, xmax, ymin, ymax = extent
    if geographic and xmax - xmin < 100 and ymax - ymin < 80 and max(abs(ymin), abs(ymax)) < 80:
        mid_lat = (ymin + ymax) / 2
        span = max(ymax - ymin, 2.0)
        parallels = (mid_lat - span / 4, mid_lat + span / 4)
        return ccrs.LambertConformal(
            central_longitude=(xmin + xmax) / 2,
            central_latitude=mid_lat,
            standard_parallels=parallels,
        )
    return source_crs


def _coord_extent(data: xr.DataArray, x_name: str, y_name: str):
    """Outer cell bounds from 1-D coordinate centers."""
    x, y = np.asarray(data[x_name]), np.asarray(data[y_name])
    if x.ndim != 1 or y.ndim != 1 or not x.size or not y.size:
        raise ValueError("Automatic map framing requires non-empty 1-D x/y coordinates.")
    def bounds(v):
        step = float(np.nanmedian(np.abs(np.diff(v)))) if v.size > 1 else 0.0
        return float(np.nanmin(v) - step / 2), float(np.nanmax(v) + step / 2)
    xmin, xmax = bounds(x); ymin, ymax = bounds(y)
    return xmin, xmax, ymin, ymax


def _add_map_context(ax, cfeature, *, add_coastlines, add_borders, resolution):
    if add_coastlines:
        ax.coastlines(resolution=resolution, linewidth=0.65, color="#35445b", zorder=4)
    if add_borders:
        ax.add_feature(cfeature.BORDERS.with_scale(resolution), linewidth=0.45,
                       edgecolor="#46556a", facecolor="none", zorder=4)


def plot_time_slices(
    ds: xr.Dataset | xr.DataArray,
    var: str | None = None,
    *,
    time_index: int | Sequence[int] | None = None,
    times: object | Sequence[object] | None = None,
    x_coord: str | None = None,
    y_coord: str | None = None,
    time_coord: str = "time",
    extent: tuple[float, float, float, float] | None = None,
    data_crs: str | object | None = None,
    map_crs: object | None = None,
    boundaries=None,
    boundary_crs: str | None = None,
    add_coastlines: bool = True,
    add_borders: bool = True,
    coastline_resolution: str = "50m",
    vmin: float | None = None,
    vmax: float | None = None,
    robust: bool = False,
    downsample: int = 1,
    ncols: int = 3,
    figsize: tuple[float, float] | None = None,
    cmap=VAR_CMAP,
    title: str | None = None,
    colorbar_label: str | None = None,
    output_path: str | Path | None = None,
    dpi: int = 180,
    show: bool = True,
):
    """Plot one or more spatial time slices as a panel.

    Parameters
    ----------
    ds : xarray.Dataset or xarray.DataArray
        Already-open data. For a Dataset, ``var`` is required.
    var : str, optional
        Dataset variable to plot.
    time_index : int or sequence of int, default 0
        Positional time index or indices, e.g. ``[0, 5, 10]``. Set to None
        when using ``times`` or for a variable without a time dimension.
    times : date-like or sequence of date-like, optional
        Exact timestamps present in the time coordinate, e.g.
        ``["2020-01-01", "2020-02-01"]``.
    x_coord, y_coord : str, optional
        Coordinate names. Common aliases (lon/longitude/x and lat/latitude/y)
        are detected automatically.
    extent : (xmin, xmax, ymin, ymax), optional
        Crop in coordinate units. Defaults to the selected data footprint.
    data_crs : str or Cartopy CRS, optional
        CRS of x/y coordinate values. Lon/lat names imply EPSG:4326; projected
        coordinates require an explicit CRS. This labels coordinates; it does
        not reproject the data.
    map_crs : Cartopy CRS, optional
        Display projection. Defaults to a local Lambert Conformal projection
        for regional lon/lat maps, avoiding the x-axis stretch of raw degrees.
    boundaries : GeoDataFrame, optional
        Optional study-area/admin boundaries to overlay. They must have a CRS,
        or provide boundary_crs if their CRS is missing.
    vmin, vmax : float, optional
        Data values mapped to the ends of the colour ramp. Set explicit limits
        when comparing maps or dates. If omitted, limits use the selected data.
    robust : bool, default False
        If limits are omitted, use the 2nd and 98th percentiles instead of
        min/max. This is useful for outliers, but can hide extremes.
    downsample : int, default 1
        Spatial stride for display only. It does not alter the source dataset.
    ncols : int, default 3
        Number of panel columns.
    output_path : path, optional
        Save the figure if supplied. The function does not create an implicit
        output directory.
    show : bool, default True
        Call ``plt.show()`` before returning.

    Returns
    -------
    fig, axes
        Figure and 2-D array of axes (unused axes are hidden).
    """
    if isinstance(ds, xr.DataArray):
        data = ds
        var_name = var or data.name or "variable"
    else:
        if var is None:
            raise ValueError("Pass var='variable_name' when ds is an xarray.Dataset.")
        if var not in ds:
            raise KeyError(f"Variable {var!r} not found. Available: {list(ds.data_vars)}")
        data = ds[var]
        var_name = var

    x_name = _find_coord(data, x_coord, ("lon", "longitude", "x"), "x")
    y_name = _find_coord(data, y_coord, ("lat", "latitude", "y"), "y")
    has_time = time_coord in data.dims
    if times is not None and not has_time:
        raise ValueError(f"{var_name!r} has no {time_coord!r} dimension; date selection is unavailable.")
    if has_time:
        indices = _indices_for_selection(data, time_coord, time_index, times)
    else:
        indices = [None]

    if ncols < 1:
        raise ValueError("ncols must be at least 1.")
    if downsample < 1:
        raise ValueError("downsample must be a positive integer.")

    selected = _crop(data, x_name, y_name, extent)
    slices: list[xr.DataArray] = []
    labels: list[str] = []
    for idx in indices:
        one = selected.isel({time_coord: idx}) if idx is not None else selected
        # A spatial map must be 2-D after selecting time. Require the user to
        # select any remaining level/band dimensions explicitly first.
        extras = [dim for dim in one.dims if dim not in (x_name, y_name)]
        if extras:
            raise ValueError(f"After time selection, {var_name!r} still has dimensions {extras}. Select them first, e.g. ds[{var_name!r}].isel({extras[0]}=0).")
        one = one.transpose(y_name, x_name)
        if downsample > 1:
            one = one.isel({y_name: slice(None, None, downsample), x_name: slice(None, None, downsample)})
        slices.append(one)
        if idx is None:
            labels.append("Spatial field")
        else:
            value = data[time_coord].values[idx]
            try:
                labels.append(pd.Timestamp(value).strftime("%d %b %Y"))
            except Exception:
                labels.append(str(value))

    # Determine one shared scale for every panel.
    if vmin is None or vmax is None:
        finite_parts = []
        for one in slices:
            arr = np.asarray(one.values).ravel()
            arr = arr[np.isfinite(arr)]
            if arr.size:
                finite_parts.append(arr)
        if not finite_parts:
            raise ValueError("Selected data contain no finite values to plot.")
        values = np.concatenate(finite_parts)
        if robust:
            auto_min, auto_max = np.nanpercentile(values, [2, 98])
        else:
            auto_min, auto_max = np.nanmin(values), np.nanmax(values)
        vmin = float(auto_min) if vmin is None else float(vmin)
        vmax = float(auto_max) if vmax is None else float(vmax)
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        raise ValueError(f"Colour limits must be finite and vmax > vmin; received vmin={vmin}, vmax={vmax}.")

    n_panels = len(slices)
    nrows = math.ceil(n_panels / ncols)
    if figsize is None:
        figsize = (5.6 * ncols, 4.6 * nrows)
    ccrs, cfeature = _map_dependencies()
    source_crs_value = _data_crs(data, x_name, y_name, data_crs)
    source_crs = _cartopy_crs(source_crs_value, ccrs)
    map_extent = extent or _coord_extent(selected, x_name, y_name)
    display_crs = map_crs if map_crs is not None else _default_map_crs(
        source_crs_value, map_extent, source_crs, ccrs
    )
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False,
                             subplot_kw={"projection": display_crs}, constrained_layout=True)
    norm = Normalize(vmin=vmin, vmax=vmax, clip=False)
    mesh = None
    for i, (one, label) in enumerate(zip(slices, labels)):
        ax = axes.flat[i]
        mesh = ax.pcolormesh(
            one[x_name].values,
            one[y_name].values,
            one.values,
            cmap=cmap,
            norm=norm,
            shading="auto",
            rasterized=True,
            transform=source_crs,
        )
        ax.set_title(f"{var_name} — {label}")
        ax.set_extent(map_extent, crs=source_crs)
        _add_map_context(ax, cfeature, add_coastlines=add_coastlines,
                         add_borders=add_borders, resolution=coastline_resolution)
        if boundaries is not None:
            if not hasattr(boundaries, "to_crs"):
                raise TypeError("boundaries must be a GeoDataFrame or GeoSeries.")
            layer = boundaries
            if layer.crs is None:
                if boundary_crs is None:
                    raise ValueError("Boundary layer has no CRS; pass boundary_crs explicitly.")
                layer = layer.set_crs(boundary_crs)
            layer = layer.to_crs(source_crs_value)
            ax.add_geometries(layer.geometry, crs=source_crs, facecolor="none",
                              edgecolor="#17283d", linewidth=0.9, zorder=5)
        ax.gridlines(draw_labels=False, linestyle=":", linewidth=0.45, alpha=0.5)

    for ax in axes.flat[n_panels:]:
        ax.set_visible(False)

    cbar = fig.colorbar(
        mesh, ax=list(axes.flat[:n_panels]), orientation="horizontal",
        location="bottom", shrink=0.88, pad=0.08, fraction=0.06,
    )
    cbar.set_label(colorbar_label or data.attrs.get("units", var_name))
    fig.suptitle(title or f"{var_name} time slices", fontsize=14)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    return fig, axes


def plot_spatial_timeseries(
    ds: xr.Dataset | xr.DataArray,
    var: str | None = None,
    *,
    points: dict[str, tuple[float, float]] | None = None,
    areas: dict[str, tuple[float, float, float, float]] | None = None,
    x_coord: str | None = None,
    y_coord: str | None = None,
    time_coord: str = "time",
    area_stat: str = "mean",
    show_area_spread: bool = False,
    time_range: tuple[object, object] | None = None,
    title: str | None = None,
    y_label: str | None = None,
    output_path: str | Path | None = None,
    dpi: int = 180,
    show: bool = True,
):
    """Plot temporal series for named points and rectangular spatial areas.

    ``points`` maps labels to (x, y); the nearest grid cell is sampled.
    ``areas`` maps labels to (xmin, xmax, ymin, ymax); each area is reduced
    per time step using mean or median. Optional shading shows mean +/- one
    spatial standard deviation. Series share a single legend.
    """
    if isinstance(ds, xr.DataArray):
        data = ds
        var_name = var or data.name or "variable"
    else:
        if var is None:
            raise ValueError("Pass var='variable_name' when ds is an xarray.Dataset.")
        if var not in ds:
            raise KeyError(f"Variable {var!r} not found. Available: {list(ds.data_vars)}")
        data, var_name = ds[var], var

    if time_coord not in data.dims:
        raise ValueError(f"{var_name!r} has no {time_coord!r} dimension.")
    if not points and not areas:
        raise ValueError("Pass at least one named point or area.")
    if area_stat not in {"mean", "median"}:
        raise ValueError("area_stat must be 'mean' or 'median'.")
    x_name = _find_coord(data, x_coord, ("lon", "longitude", "x"), "x")
    y_name = _find_coord(data, y_coord, ("lat", "latitude", "y"), "y")
    if x_name not in data.dims or y_name not in data.dims:
        raise ValueError("The x and y coordinates must be dimensions of the variable.")
    if time_range is not None:
        data = data.sel({time_coord: slice(*time_range)})
        if data.sizes.get(time_coord, 0) == 0:
            raise ValueError("time_range selects no time steps.")

    series, spreads = {}, {}
    for label, (x, y) in (points or {}).items():
        sampled = data.sel({x_name: x, y_name: y}, method="nearest")
        extra = [d for d in sampled.dims if d != time_coord]
        if extra:
            raise ValueError(f"Select remaining dimensions {extra} before plotting.")
        series[label] = sampled.transpose(time_coord).compute()

    for label, (xmin, xmax, ymin, ymax) in (areas or {}).items():
        area = data.where(
            (data[x_name] >= xmin) & (data[x_name] <= xmax)
            & (data[y_name] >= ymin) & (data[y_name] <= ymax),
            drop=True,
        )
        if not area.sizes.get(x_name, 0) or not area.sizes.get(y_name, 0):
            raise ValueError(f"Area {label!r} does not overlap the dataset.")
        reduce = area.mean if area_stat == "mean" else area.median
        summary = reduce(dim=(y_name, x_name), skipna=True)
        extra = [d for d in summary.dims if d != time_coord]
        if extra:
            raise ValueError(f"Select remaining dimensions {extra} before plotting.")
        series[label] = summary.transpose(time_coord).compute()
        if show_area_spread:
            if area_stat != "mean":
                raise ValueError("Spread shading is available with area_stat='mean'.")
            spreads[label] = area.std(dim=(y_name, x_name), skipna=True).transpose(time_coord).compute()

    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)
    time_values = data[time_coord].values
    for label, values in series.items():
        line, = ax.plot(time_values, values.values, linewidth=1.8, label=label)
        if label in spreads:
            sd = spreads[label].values
            ax.fill_between(time_values, values.values - sd, values.values + sd,
                            color=line.get_color(), alpha=0.18, linewidth=0)
    ax.set_title(title or f"{var_name} over time", pad=12)
    ax.set_xlabel("Time")
    ax.set_ylabel(y_label or data.attrs.get("units", var_name))
    ax.grid(True, linestyle=":", linewidth=0.7, alpha=0.55)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18),
              ncol=min(4, len(series)), frameon=False,
              title="Selected points / areas")
    fig.autofmt_xdate(rotation=0)
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    return fig, ax


def plot_climate_mobility_period(
    ds: xr.Dataset | xr.DataArray,
    mobility: pd.DataFrame | str | Path,
    spatial_units,
    *,
    var: str | None = None,
    period: object,
    mobility_metric: str = "N_depart",
    flow_direction: str = "origin",
    spatial_id_col: str = "norm_spatial_id",
    period_col: str = "date",
    mobility_period: object | None = None,
    origin_col: str = "norm_spatial_id_origin",
    destination_col: str = "norm_spatial_id_destination",
    time_coord: str = "time",
    x_coord: str | None = None,
    y_coord: str | None = None,
    data_crs: str | object | None = None,
    spatial_units_crs: str | None = None,
    subset_type: str | None = None,
    days_span: int | None = None,
    climate_stat: str = "mean",
    ncols: int = 2,
    figsize: tuple[float, float] = (12, 5.5),
    title: str | None = None,
    output_path: str | Path | None = None,
    dpi: int = 180,
    show: bool = True,
):
    """Compare a climate period map with mobility totals by origin/destination.

    Mobility may be a DataFrame or Parquet path. ``period`` is a climate
    timestamp/date. Date columns group mobility into the matching half-month
    (days 1–15 or 16–month-end). For ``HalfMonthIndex``, pass the exact key as
    ``mobility_period``. Requires optional GeoPandas and Cartopy.

    This is a side-by-side visual comparison, not a statistical association
    or a directed OD flow map. Mobility counts are summed by the selected
    origin/destination polygon; climate is averaged over the same dates.
    """
    try:
        import geopandas as gpd
    except ImportError as exc:
        raise ImportError("Mobility map requires GeoPandas. Install with `pip install geopandas pyarrow`.") from exc
    ccrs, cfeature = _map_dependencies()
    if flow_direction not in {"origin", "destination"}:
        raise ValueError("flow_direction must be 'origin' or 'destination'.")
    if climate_stat not in {"mean", "max"}:
        raise ValueError("climate_stat must be 'mean' or 'max'.")
    data = ds if isinstance(ds, xr.DataArray) else ds[var] if var in ds else None
    if data is None:
        raise ValueError("For a Dataset, pass var naming an existing data variable.")
    var_name = var or data.name or "climate"
    x_name = _find_coord(data, x_coord, ("lon", "longitude", "x"), "x")
    y_name = _find_coord(data, y_coord, ("lat", "latitude", "y"), "y")
    source_value = _data_crs(data, x_name, y_name, data_crs)
    source_crs = _cartopy_crs(source_value, ccrs)

    if isinstance(mobility, (str, Path)):
        mobility = pd.read_parquet(mobility)
    units = gpd.read_file(spatial_units) if isinstance(spatial_units, (str, Path)) else spatial_units.copy()
    if not isinstance(units, (gpd.GeoDataFrame, gpd.GeoSeries)):
        raise TypeError("spatial_units must be a GeoDataFrame/GeoSeries or readable vector file.")
    if units.crs is None:
        if spatial_units_crs is None:
            raise ValueError("Spatial units have no CRS; pass spatial_units_crs explicitly.")
        units = units.set_crs(spatial_units_crs)
    if spatial_id_col not in units:
        raise KeyError(f"{spatial_id_col!r} not found in spatial_units columns {list(units.columns)}")
    selected_id_col = origin_col if flow_direction == "origin" else destination_col
    if selected_id_col not in mobility:
        candidates = ["origin", "origin_spatial_id"] if flow_direction == "origin" else ["destination", "destination_spatial_id"]
        selected_id_col = next((col for col in candidates if col in mobility), selected_id_col)
    if selected_id_col not in mobility or mobility_metric not in mobility:
        raise KeyError(f"Expected mobility columns {selected_id_col!r} and {mobility_metric!r}; found {list(mobility.columns)}")

    frame = mobility.copy()
    if subset_type is not None:
        if "subset_type" not in frame:
            raise KeyError("subset_type filter requested but column is absent.")
        frame = frame[frame["subset_type"] == subset_type]
    if days_span is not None:
        if "days_span" not in frame:
            raise KeyError("days_span filter requested but column is absent.")
        frame = frame[frame["days_span"] == days_span]
    target = pd.Timestamp(period)
    if period_col not in frame:
        raise KeyError(f"Period column {period_col!r} not found.")
    if period_col == "HalfMonthIndex":
        if mobility_period is None:
            raise ValueError("Pass the exact HalfMonthIndex key as mobility_period; period remains the climate date.")
        frame = frame[frame[period_col] == mobility_period]
        start = target
        end = target + pd.Timedelta(days=15)
    else:
        datevals = pd.to_datetime(frame[period_col], errors="coerce")
        start = target.normalize().replace(day=1 if target.day <= 15 else 16)
        end = (start + pd.Timedelta(days=15)) if start.day == 1 else (start + pd.offsets.MonthBegin(1))
        frame = frame[(datevals >= start) & (datevals < end)]
    if frame.empty:
        raise ValueError(f"No mobility rows found for the selected period/filter ({start.date()} to {end.date()}).")
    totals = frame.groupby(selected_id_col, dropna=True)[mobility_metric].sum()
    units = units.copy()
    units["_mobility_value"] = units[spatial_id_col].map(totals)
    from pyproj import CRS
    units = units.to_crs(CRS.from_user_input(source_value))

    if time_coord not in data.dims:
        raise ValueError(f"Climate variable has no {time_coord!r} dimension for period aggregation.")
    timevals = pd.to_datetime(data[time_coord].values)
    climate = data.isel({time_coord: np.flatnonzero((timevals >= start) & (timevals < end))})
    if climate.sizes.get(time_coord, 0) == 0:
        raise ValueError(f"No climate timestamps overlap {start.date()} to {end.date()}.")
    climate = getattr(climate, climate_stat)(dim=time_coord, skipna=True).transpose(y_name, x_name)
    climate_extent = _coord_extent(climate, x_name, y_name)
    bx0, by0, bx1, by1 = units.total_bounds
    extent_union = (min(climate_extent[0], bx0), max(climate_extent[1], bx1),
                    min(climate_extent[2], by0), max(climate_extent[3], by1))

    map_crs = _default_map_crs(source_value, extent_union, source_crs, ccrs)
    fig, axes = plt.subplots(1, 2, figsize=figsize, squeeze=False,
                             subplot_kw={"projection": map_crs}, constrained_layout=True)
    ax0, ax1 = axes[0]
    mesh = ax0.pcolormesh(climate[x_name], climate[y_name], climate.values,
                          cmap=VAR_CMAP, shading="auto", transform=source_crs, rasterized=True)
    ax0.set_title(f"{var_name} · {climate_stat}")
    ax0.set_extent(extent_union, crs=source_crs)
    _add_map_context(ax0, cfeature, add_coastlines=True, add_borders=True, resolution="50m")
    cb0 = fig.colorbar(mesh, ax=ax0, shrink=0.78, pad=0.03)
    cb0.set_label(data.attrs.get("units", var_name))

    vals = units["_mobility_value"].to_numpy(dtype=float)
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        raise ValueError("No mobility values matched the supplied spatial unit IDs.")
    vmin, vmax = float(np.nanmin(finite)), float(np.nanmax(finite))
    if vmin == vmax:
        vmax = vmin + 1.0
    mobility_norm = Normalize(vmin=vmin, vmax=vmax)
    mobility_cmap = plt.get_cmap("viridis")
    for _, row in units.iterrows():
        value = row["_mobility_value"]
        color = "#d8dde3" if pd.isna(value) else mobility_cmap(mobility_norm(float(value)))
        ax1.add_geometries([row.geometry], crs=source_crs, facecolor=color,
                           edgecolor="#f3f6fa", linewidth=0.35, zorder=3)
    ax1.set_title(f"Mobility {flow_direction} · {mobility_metric}")
    ax1.set_extent(extent_union, crs=source_crs)
    _add_map_context(ax1, cfeature, add_coastlines=True, add_borders=True, resolution="50m")
    sm = ScalarMappable(norm=mobility_norm, cmap=mobility_cmap)
    sm.set_array([])
    cb1 = fig.colorbar(sm, ax=ax1, shrink=0.78, pad=0.03)
    cb1.set_label(mobility_metric)
    fig.suptitle(title or f"Climate and mobility · {start:%Y-%m-%d} to {(end - pd.Timedelta(days=1)):%Y-%m-%d}")
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    if show:
        plt.show()
    return fig, axes


__all__ = ["VAR_CMAP", "plot_time_slices", "plot_spatial_timeseries", "plot_climate_mobility_period"]
