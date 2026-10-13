"""Small plotting helpers for time slices from xarray gridded datasets.

The module accepts an already-open ``xarray.Dataset``. It does not open files,
modify the dataset, or require Cartopy. For comparable maps, pass the same
``vmin`` and ``vmax`` to every call (or use the same limits for all panels).

Examples
--------
    import xarray as xr
    from adaptive_cube_plot import plot_time_slices

    ds = xr.open_zarr("climate_cube.zarr")  # or xr.open_dataset(...)
    fig, axes = plot_time_slices(
        ds, var="NDVI", time_index=[0, 6, 12], vmin=0, vmax=1,
        extent=(-18, 40, 10, 20),
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
        Crop in coordinate units. For geographic coordinates, use degrees.
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
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False, constrained_layout=True)
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
        )
        ax.set_title(f"{var_name} — {label}")
        ax.set_xlabel(x_name)
        ax.set_ylabel(y_name)
        ax.set_aspect("auto")
        if extent is not None:
            xmin, xmax, ymin, ymax = extent
            ax.set_xlim(xmin, xmax)
            ax.set_ylim(ymin, ymax)
        ax.grid(True, linestyle=":", linewidth=0.5, alpha=0.45)

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


__all__ = ["VAR_CMAP", "plot_time_slices", "plot_spatial_timeseries"]
