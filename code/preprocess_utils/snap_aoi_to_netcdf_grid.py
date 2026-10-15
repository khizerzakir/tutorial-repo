"""Create one raw-grid-aligned CDO grid from an AOI or YAML bounds.

Pass ``--aoi`` to use vector bounds; omit it to use the YAML ``domain``.
Both modes update one YAML and write one grid.txt. Example:
    python snap_aoi_to_netcdf_grid.py --netcdf raw.nc --config config.yaml \\
        --aoi study.shp --grid grid.txt

All values are derived from the raw NetCDF grid (resolution, cell edges and
centres) and cleaned of floating-point noise, e.g. -17.23 instead of
-17.229999999999997.

Requires: xarray, numpy, PyYAML, and relevant NetCDF drivers. AOI input also
requires geopandas (GeoParquet additionally pyarrow).
"""
from pathlib import Path
import argparse
import math

import numpy as np
import yaml


# ---- Default paths (command-line options override these) ----
AOI_FILE = None
NETCDF_FILE = Path("data/raw/METREF/example.nc")
CONFIG_FILE = Path("code/preprocess_utils/config_resolution.yaml")
GRID_FILE = Path("code/preprocess_utils/grid.txt")


def get_axis(ds, candidates):
    for name in candidates:
        if name in ds.variables:
            values = np.asarray(ds[name].values).squeeze()
            if values.ndim == 1:
                return values
    raise ValueError(f"Could not find a 1-D coordinate among {candidates}")


def axis_spacing(values, name):
    axis = np.unique(np.asarray(values, dtype=float)[np.isfinite(values)])
    axis.sort()
    diffs = np.diff(axis)
    if len(axis) < 2 or np.any(diffs <= 0):
        raise ValueError(f"Invalid {name} coordinate axis")

    # Endpoints give an accurate spacing for regular float32 axes, even when
    # individual differences vary slightly due to coordinate rounding.
    step = float((axis[-1] - axis[0]) / (len(axis) - 1))
    if not np.allclose(diffs, step, rtol=1e-3, atol=step * 1e-3):
        raise ValueError(f"The NetCDF {name} axis is not regularly spaced")
    return float(axis[0]), float(axis[-1]), step


def decimals_for(step):
    """Decimals that keep real grid values (step/100 precision) but drop float noise."""
    return max(int(math.ceil(-math.log10(step))) + 2, 2)


POS_TOL = 2e-5  # degrees: above float32 coordinate noise, far below a grid cell


def tidy(value, ndec, tol):
    """Round away float noise; keep the value (to 8 decimals) if it is not on a clean decimal."""
    rounded = round(float(value), ndec)
    return rounded if abs(rounded - value) <= tol else round(float(value), 8)


def snap_outward(value, grid_edge, step, direction):
    index = (value - grid_edge) / step
    if direction == "down":
        return grid_edge + np.floor(index + 1e-9) * step
    return grid_edge + np.ceil(index - 1e-9) * step


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aoi", type=Path, default=AOI_FILE,
                        help="Input AOI vector file (.shp, .gpkg, .geojson, .parquet, .geoparquet, etc.)")
    parser.add_argument("--aoi-crs", help="Actual source CRS if the AOI has no CRS metadata")
    parser.add_argument("--netcdf", type=Path, default=NETCDF_FILE, help="Raw NetCDF used to read grid coordinates")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help="Input YAML configuration")
    parser.add_argument("--output-yaml", type=Path, help="YAML output; defaults to updating --config in place")
    parser.add_argument("--grid", type=Path, default=GRID_FILE, help="Output CDO grid description")
    args = parser.parse_args()

    try:
        import xarray as xr
    except ImportError as exc:
        raise SystemExit("Reading raw NetCDF coordinates requires xarray.") from exc

    config = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    if args.aoi:
        try:
            import geopandas as gpd
        except ImportError as exc:
            raise SystemExit("AOI input requires geopandas; GeoParquet also requires pyarrow.") from exc
        if args.aoi.suffix.lower() in {".parquet", ".geoparquet"}:
            aoi = gpd.read_parquet(args.aoi)
        else:
            aoi = gpd.read_file(args.aoi)
        if aoi.empty:
            raise ValueError("AOI file contains no features")
        if aoi.crs is None:
            if args.aoi_crs:
                aoi = aoi.set_crs(args.aoi_crs)
            else:
                raise ValueError("AOI has no CRS; supply --aoi-crs with its actual CRS.")
        west, south, east, north = map(float, aoi.to_crs("EPSG:4326").total_bounds)
    else:
        domain = config.get("domain", {})
        west, south, east, north = (float(domain[k]) for k in
                                    ("lon_min", "lat_min", "lon_max", "lat_max"))

    with xr.open_dataset(args.netcdf, decode_cf=False) as ds:
        lon = get_axis(ds, ("lon", "longitude"))
        lat = get_axis(ds, ("lat", "latitude"))
    lon_min, lon_max, dx = axis_spacing(lon, "longitude")
    lat_min, lat_max, dy = axis_spacing(lat, "latitude")

    # Clean resolution and precision per axis, derived from the raw grid.
    ndx, ndy = decimals_for(dx), decimals_for(dy)
    # Strict tolerance for the step: rounding it loosely would drift over many cells
    # (so 1/24 degree stays 0.0416666667 instead of becoming 0.0417).
    dx, dy = tidy(dx, ndx, 1e-4 * dx), tidy(dy, ndy, 1e-4 * dy)

    # Grid-cell edges are half a cell beyond the first/last coordinate centres.
    west_edge, east_edge = tidy(lon_min - dx / 2, ndx, POS_TOL), tidy(lon_max + dx / 2, ndx, POS_TOL)
    south_edge, north_edge = tidy(lat_min - dy / 2, ndy, POS_TOL), tidy(lat_max + dy / 2, ndy, POS_TOL)
    if west_edge >= east_edge or south_edge >= north_edge:
        raise ValueError("NetCDF grid has invalid bounds")

    # Snap the requested bounds outward to whole raw cells, then clean them.
    west = tidy(snap_outward(west, west_edge, dx, "down"), ndx, POS_TOL)
    south = tidy(snap_outward(south, south_edge, dy, "down"), ndy, POS_TOL)
    east = tidy(snap_outward(east, west_edge, dx, "up"), ndx, POS_TOL)
    north = tidy(snap_outward(north, south_edge, dy, "up"), ndy, POS_TOL)
    eps = 1e-6
    if (west < west_edge - eps or east > east_edge + eps
            or south < south_edge - eps or north > north_edge + eps):
        raise ValueError("AOI extends beyond the NetCDF grid coverage")

    # Grid description uses cell-centre coordinates, while YAML domain bounds
    # describe the snapped outer cell edges.
    xsize = int(round((east - west) / dx))
    ysize = int(round((north - south) / dy))
    xfirst = tidy(west + dx / 2, ndx + 1, POS_TOL)
    yfirst = tidy(north - dy / 2, ndy + 1, POS_TOL)
    args.grid.parent.mkdir(parents=True, exist_ok=True)
    args.grid.write_text(
        "\n".join(("gridtype = lonlat", f"xsize = {xsize}", f"ysize = {ysize}",
                   f"xfirst = {xfirst:.12g}", f"yfirst = {yfirst:.12g}",
                   f"xinc = {dx:.12g}", f"yinc = {-dy:.12g}", "")),
        encoding="utf-8",
    )

    config["domain"] = {"lon_min": west, "lon_max": east, "lat_min": south, "lat_max": north}
    config["grid"] = {"xfirst": xfirst, "yfirst": yfirst, "xinc": dx, "yinc": -dy,
                      "xsize": xsize, "ysize": ysize,
                      "alignment": "raw NetCDF cell edges and centres"}
    output_yaml = args.output_yaml or args.config
    output_yaml.parent.mkdir(parents=True, exist_ok=True)
    output_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    print(f"Raw resolution: dx={dx:g}°, dy={dy:g}°  ({xsize} x {ysize} cells)")
    print(f"Aligned bounds: lon {west:g} to {east:g}, lat {south:g} to {north:g}")
    print(f"Saved updated YAML: {output_yaml}")
    print(f"Saved CDO target grid: {args.grid}")


if __name__ == "__main__":
    main()