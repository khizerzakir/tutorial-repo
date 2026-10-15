#!/usr/bin/env python3
"""Build a compressed, chunked and sharded Zarr v3 cube from interim NetCDF files.

Typical use (from the repository root):

    uv run python code/03_build_zarr_cube.py                       # defaults
    uv run python code/03_build_zarr_cube.py --dry-run             # show the plan only
    uv run python code/03_build_zarr_cube.py --input data/interim/METREF --profile balanced
    uv run python code/03_build_zarr_cube.py --input data/interim/METREF --append

Chunk profiles (inner chunk = smallest independently readable block):

    map         time=1,  lat/lon=256   fast single-date maps (default)
    balanced    time=8,  lat/lon=128   maps and time series both acceptable
    timeseries  time=64, lat/lon=32    fast point / small-area time series

Shards group several inner chunks into one storage object. Shard sizes are
rounded to whole multiples of the inner chunk (required by Zarr v3 sharding),
and Dask chunks are aligned to whole shards so no two tasks write to the same
shard.

The store is written to ``<output>.tmp`` and only renamed into place after a
successful write and validation, so a failed run never destroys a previous cube.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr
import zarr
from packaging.version import Version

if Version(zarr.__version__) < Version("3.0"):
    raise SystemExit(
        f"Zarr >= 3.0 is required, but {zarr.__version__} is installed. Run with the "
        "project environment: `uv run python code/03_build_zarr_cube.py`."
    )

import dask
from zarr.codecs import BloscCodec

ROOT = Path(__file__).resolve().parents[1]
DIMS = ("time", "lat", "lon")

# inner chunk shape, shard shape (in elements) per dimension
PROFILES: dict[str, tuple[dict[str, int], dict[str, int]]] = {
    "map": ({"time": 1, "lat": 256, "lon": 256}, {"time": 10, "lat": 512, "lon": 512}),
    "balanced": ({"time": 8, "lat": 128, "lon": 128}, {"time": 32, "lat": 512, "lon": 512}),
    "timeseries": ({"time": 64, "lat": 32, "lon": 32}, {"time": 256, "lat": 256, "lon": 256}),
}
# Names of coordinate variables that CDO / LSA SAF files may use.
RENAME = {"latitude": "lat", "longitude": "lon", "y": "lat", "x": "lon"}
# NetCDF-only encodings that must not leak into the Zarr encoding.
KEEP_ENCODING = {"dtype", "scale_factor", "add_offset", "_FillValue", "units", "calendar"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a sharded Zarr v3 cube from interim NetCDF files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1].split("Shards group", 1)[0],
    )
    p.add_argument("--input", type=Path, default=ROOT / "data" / "interim",
                   help="Folder searched recursively for interim NetCDF (default: data/interim)")
    p.add_argument("--pattern", default="*_processed.nc",
                   help="Filename glob inside --input (default: *_processed.nc)")
    p.add_argument("--output", type=Path, default=None,
                   help="Output .zarr path (default: data/zarr/<first variable>_cube.zarr)")
    p.add_argument("--variables", nargs="+", default=None,
                   help="Data variables to keep, e.g. METREF quality_flag (default: all)")
    p.add_argument("--profile", choices=sorted(PROFILES), default="map",
                   help="Chunk/shard preset tuned for an access pattern (default: map)")
    p.add_argument("--chunks", type=_dims_arg, default=None, metavar="time=1,lat=256,lon=256",
                   help="Override inner chunk sizes")
    p.add_argument("--shards", type=_dims_arg, default=None, metavar="time=10,lat=512,lon=512",
                   help="Override shard sizes (rounded to multiples of the inner chunks)")
    p.add_argument("--clevel", type=int, default=5, choices=range(1, 10), metavar="1-9",
                   help="zstd compression level (default: 5)")
    p.add_argument("--float32", action="store_true",
                   help="Store float64 variables as float32 (halves size; ~7 significant digits)")
    p.add_argument("--workers", type=int, default=None,
                   help="Dask threads for reading/compressing (default: all cores)")
    p.add_argument("--append", action="store_true",
                   help="Append only time steps newer than the existing cube instead of rebuilding")
    p.add_argument("--no-consolidate", action="store_true",
                   help="Do not write consolidated metadata (slower to open, more portable)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the dataset, chunk/shard plan and size estimate, then exit")
    return p.parse_args(argv)


def _dims_arg(text: str) -> dict[str, int]:
    out = {}
    for part in text.split(","):
        key, _, value = part.partition("=")
        if key.strip() not in DIMS or not value.strip().isdigit() or int(value) < 1:
            raise argparse.ArgumentTypeError(f"Expected e.g. time=1,lat=256,lon=256; got {text!r}")
        out[key.strip()] = int(value)
    return out


# opening
def find_files(folder: Path, pattern: str) -> list[Path]:
    files = sorted(folder.rglob(pattern))
    if not files:
        raise SystemExit(f"No files matching {pattern!r} under {folder}. "
                         "Run code/02_preprocess_cdo.sh first or check --input/--pattern.")
    # Sort by the YYYYMMDD[hhmm] stamp in the file name so nested concat is in time order.
    def stamp(path: Path) -> str:
        match = re.search(r"(\d{8})(\d{4})?", path.name)
        return (match.group(0) if match else "") + path.name
    return sorted(files, key=stamp)


def open_interim(files: list[Path], variables: list[str] | None) -> xr.Dataset:
    def preprocess(ds: xr.Dataset) -> xr.Dataset:
        ds = ds.rename({k: v for k, v in RENAME.items() if k in ds.dims or k in ds.coords})
        if variables:
            missing = [v for v in variables if v not in ds.data_vars]
            if missing:
                raise KeyError(f"{missing} not in {ds.encoding.get('source')}; "
                               f"available: {list(ds.data_vars)}")
            ds = ds[variables]
        # Drop CDO helper variables such as time_bnds / lat_bnds.
        return ds.drop_vars([v for v in ds.data_vars if v.endswith(("_bnds", "_bounds"))])

    # All interim files share one target grid, so skip coordinate alignment
    # (join/compat="override") and concatenate along time in file order.
    ds = xr.open_mfdataset(
        files,
        engine="h5netcdf",
        combine="nested",
        concat_dim="time",
        preprocess=preprocess,
        parallel=False,  # opening is metadata-only; HDF5 is not thread-safe
        chunks={},
        data_vars="minimal",
        coords="minimal",
        compat="override",
        join="override",
    )
    missing = [d for d in DIMS if d not in ds.dims]
    if missing:
        raise SystemExit(f"Expected dimensions {DIMS}; missing {missing}. Found {dict(ds.sizes)}.")
    ds = ds.sortby("time")
    if ds.indexes["time"].has_duplicates:
        raise SystemExit("Duplicate timestamps found; check --input/--pattern for overlapping files.")
    return ds


def check_grid(files: list[Path], ds: xr.Dataset) -> None:
    """join='override' trusts the first file's grid, so verify the last one matches."""
    with xr.open_dataset(files[-1], engine="h5netcdf") as last:
        last = last.rename({k: v for k, v in RENAME.items() if k in last.dims or k in last.coords})
        for dim in ("lat", "lon"):
            if last.sizes[dim] != ds.sizes[dim] or not np.allclose(last[dim], ds[dim]):
                raise SystemExit(f"{files[-1].name} has a different {dim} grid than {files[0].name}.")


# chunk plan
def plan_chunks(ds: xr.Dataset, inner_req: dict[str, int], shard_req: dict[str, int]):
    """Clamp inner chunks to the array, round shards to whole inner chunks."""
    inner, shard = {}, {}
    for dim in DIMS:
        size = ds.sizes[dim]
        c = max(1, min(inner_req[dim], size))
        n_inner = math.ceil(size / c)                         # inner chunks needed to cover dim
        k = max(1, min(round(shard_req[dim] / c), n_inner))   # inner chunks per shard
        inner[dim], shard[dim] = c, c * k
    return inner, shard


def build_encoding(ds: xr.Dataset, inner, shard, clevel: int, float32: bool) -> dict:
    compressor = BloscCodec(cname="zstd", clevel=clevel, shuffle="shuffle")
    encoding = {}
    for name, da in ds.data_vars.items():
        old = {k: v for k, v in da.encoding.items() if k in KEEP_ENCODING}
        if float32 and da.dtype == np.float64:
            old["dtype"] = "float32"
        if da.dtype.kind not in "iufb":  # leave strings/objects to xarray defaults
            encoding[name] = old
            continue
        encoding[name] = {
            **old,
            "chunks": tuple(inner[d] for d in da.dims),
            "shards": tuple(shard[d] for d in da.dims),
            "compressors": [compressor],
        }
    for name in ds.coords:  # small 1-D coordinates: one chunk, keep units/calendar
        encoding[name] = {k: v for k, v in ds[name].encoding.items() if k in KEEP_ENCODING}
    return encoding


def human(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def describe_plan(ds, inner, shard, files) -> None:
    n_inner = math.prod(math.ceil(ds.sizes[d] / inner[d]) for d in DIMS)
    n_shard = math.prod(math.ceil(ds.sizes[d] / shard[d]) for d in DIMS)
    itemsize = max(da.dtype.itemsize for da in ds.data_vars.values())
    print(f"Files            : {len(files)}  ({files[0].name} … {files[-1].name})")
    print(f"Variables        : {', '.join(ds.data_vars)}")
    print(f"Dimensions       : {dict(ds.sizes)}")
    print(f"Time range       : {str(ds.time.values[0])[:10]} → {str(ds.time.values[-1])[:10]}")
    print(f"Inner chunk      : {inner}  (~{human(math.prod(inner.values()) * itemsize)} raw each)")
    print(f"Shard            : {shard}")
    print(f"Per variable     : {n_inner} inner chunks in {n_shard} shard object(s)")
    print(f"Uncompressed size: {human(ds.nbytes)}")


# write
def write(ds: xr.Dataset, output: Path, encoding: dict, consolidate: bool, append: bool) -> None:
    with warnings.catch_warnings():
        # xarray stores consolidated metadata in zarr.json; zarr warns it is not yet in the v3 spec.
        warnings.filterwarnings("ignore", message="Consolidated metadata is currently not part")
        if append:
            ds.to_zarr(output, mode="a", append_dim="time", zarr_format=3,
                       consolidated=consolidate, align_chunks=True)
        else:
            ds.to_zarr(output, mode="w", zarr_format=3, encoding=encoding,
                       consolidated=consolidate, align_chunks=True)


def validate(output: Path, files: list[Path], consolidate: bool) -> None:
    """Reopen the store and compare the first and last time step against the sources."""
    cube = xr.open_zarr(output, consolidated=consolidate or None)
    for path in (files[0], files[-1]):
        with xr.open_dataset(path, engine="h5netcdf") as src:
            src = src.rename({k: v for k, v in RENAME.items() if k in src.dims or k in src.coords})
            t = src.time.values[0]
            for name in cube.data_vars:
                if name not in src:
                    continue
                a = cube[name].sel(time=t).values
                b = src[name].isel(time=0).values.astype(a.dtype)
                if not np.allclose(a, b, equal_nan=True, rtol=1e-6):
                    raise SystemExit(f"Validation FAILED: {name} at {str(t)[:10]} differs from {path.name}")
    valid = {n: float(cube[n].notnull().mean().compute()) for n in cube.data_vars}
    print("Validation OK    : first/last time steps match the interim NetCDF")
    print("Valid fraction   : " + ", ".join(f"{n}={v:.1%}" for n, v in valid.items()))
    cube.close()


def store_stats(path: Path) -> tuple[int, int]:
    files = [f for f in path.rglob("*") if f.is_file()]
    return sum(f.stat().st_size for f in files), len(files)


# main
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.workers:
        dask.config.set(scheduler="threads", num_workers=args.workers)
    t0 = time.perf_counter()

    files = find_files(args.input.resolve(), args.pattern)
    ds = open_interim(files, args.variables)
    check_grid(files, ds)

    first_var = next(iter(ds.data_vars))
    output = (args.output or ROOT / "data" / "zarr" / f"{first_var.lower()}_cube.zarr").resolve()
    consolidate = not args.no_consolidate

    inner_req, shard_req = (dict(x) for x in PROFILES[args.profile])
    inner_req.update(args.chunks or {})
    shard_req.update(args.shards or {})
    inner, shard = plan_chunks(ds, inner_req, shard_req)

    print(f"Profile          : {args.profile}")
    describe_plan(ds, inner, shard, files)
    print(f"Output           : {output}")
    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    # One Dask chunk = one whole shard, so writes never touch the same shard twice.
    ds = ds.chunk({d: shard[d] for d in DIMS})
    encoding = build_encoding(ds, inner, shard, args.clevel, args.float32)
    for name in ds.variables:  # stale NetCDF encodings (zlib, chunksizes...) are dropped
        ds[name].encoding = {}
    ds.attrs.update({
        "zarr_cube_created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "zarr_cube_source_files": len(files),
        "zarr_cube_chunks": json.dumps(inner),
        "zarr_cube_shards": json.dumps(shard),
        "zarr_cube_compressor": f"blosc zstd clevel={args.clevel} shuffle",
        "zarr_cube_builder": "code/03_build_zarr_cube.py",
    })

    if args.append:
        if not output.exists():
            raise SystemExit(f"--append needs an existing cube at {output}")
        existing = xr.open_zarr(output, consolidated=consolidate or None)
        last = existing.time.values[-1]
        existing.close()
        ds = ds.sel(time=ds.time > last)
        if ds.sizes["time"] == 0:
            print(f"Nothing to append: cube already ends at {str(last)[:10]}.")
            return 0
        print(f"Appending {ds.sizes['time']} new time step(s) after {str(last)[:10]}")
        ds.attrs.pop("zarr_cube_created")
        write(ds, output, encoding, consolidate, append=True)
        final = output
    else:
        tmp = output.with_name(output.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        write(ds, tmp, encoding, consolidate, append=False)
        validate(tmp, files, consolidate)
        shutil.rmtree(output, ignore_errors=True)
        tmp.rename(output)
        final = output

    if args.append:
        validate(final, files, consolidate)
    size, nfiles = store_stats(final)
    with xr.open_zarr(final, consolidated=consolidate or None) as cube:
        logical = cube.nbytes
    print(f"Stored size      : {human(size)} in {nfiles} files "
          f"(compression ≈ {logical / max(size, 1):.1f}× vs {human(logical)} in memory)")
    print(f"Done in {time.perf_counter() - t0:.1f}s → {final}")
    ds.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
