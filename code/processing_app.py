from pandas import api
import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium", app_title="Climate cube builder")


@app.cell
def _():
    import datetime as dt
    import json
    import math
    import os
    import re
    import shlex
    import subprocess
    import tempfile
    import time
    from pathlib import Path

    import marimo as mo
    import yaml

    REPO = Path(__file__).resolve().parents[1]
    print(f"Repository root: {REPO}")
    CODE = REPO / "code"
    DATA = REPO / "data"
    DEFAULT_CFG = CODE / "preprocess_utils" / "config_resolution.yaml"
    BASE_URL = os.environ.get("LSASAF_BASE_URL", "https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG")
    # product folder on the LSA SAF server → (main variable, description); "Other…" lets you type any product
    PRODUCTS = {
        "METREF": ("METREF", "Reference evapotranspiration, daily (mm/day)"),
        "MDFVC": ("FVC", "Fractional vegetation cover, daily"),
        "Other…": ("", "type the product folder and variable name"),
    }
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return (BASE_URL, CODE, DATA, DEFAULT_CFG, MONTHS, PRODUCTS, Path, REPO, dt, json, math, mo, os, re,
            shlex, subprocess, tempfile, time, yaml)


@app.cell
def _(mo):
    mo.md(
        r"""
        # Climate cube builder
        Download LSA SAF products, **clip them on the fly** to your study area (only the clipped files are kept),
        optionally **remap** them to a chosen resolution, and build a **Zarr cube**.
        Choose the settings below; the panel at the bottom shows the equivalent command line before you start.
        """
    )
    return


@app.cell
def _(CODE, mo):
    _env = CODE / ".env"
    use_env = mo.ui.checkbox(value=_env.exists(), label=f"use credentials from code/.env ({'found' if _env.exists() else 'not found'})")
    user = mo.ui.text(label="LSA SAF username", placeholder="username")
    password = mo.ui.text(label="password", kind="password")
    mo.vstack([mo.md("### 1 · Account"), use_env, mo.hstack([user, password], justify="start")])
    return password, use_env, user


@app.cell
def _(PRODUCTS, mo):
    product = mo.ui.dropdown(options=list(PRODUCTS), value="METREF", label="Product")
    custom_product = mo.ui.text(label="product folder (Other…)", placeholder="e.g. MDLST")
    return custom_product, product


@app.cell
def _(PRODUCTS, custom_product, mo, product):
    prod_name = custom_product.value.strip() if product.value == "Other…" else product.value
    main_var = mo.ui.text(value=PRODUCTS[product.value][0] or prod_name, label="main variable")
    qa_vars = mo.ui.text(value="quality_flag", label="QA variables (comma-separated, nearest neighbour)")
    inspect_btn = mo.ui.run_button(label="Inspect first file of the start month")
    mo.vstack([
        mo.md("### 2 · Product and variables"),
        mo.hstack([product, custom_product], justify="start"),
        mo.md(f"*{PRODUCTS[product.value][1]}*"),
        mo.hstack([main_var, qa_vars], justify="start"),
        inspect_btn,
    ])
    return inspect_btn, main_var, prod_name, qa_vars


@app.cell
def _(MONTHS, dt, mo):
    _this = dt.date.today().year
    _yrs = [str(y) for y in range(2004, _this + 1)]
    year_from = mo.ui.dropdown(options=_yrs, value="2015", label="from year")
    year_to = mo.ui.dropdown(options=_yrs, value="2015", label="to year")
    months = mo.ui.multiselect(options=MONTHS, value=["Jun"], label="Months")
    mo.vstack([mo.md("### 3 · Period"), mo.hstack([year_from, year_to, months], justify="start")])
    return months, year_from, year_to


@app.cell
def _(DEFAULT_CFG, mo, yaml):
    _d = (yaml.safe_load(DEFAULT_CFG.read_text()) or {}).get("domain", {})
    region_mode = mo.ui.radio(options=["Bounding box", "AOI file"], value="Bounding box", inline=True, label="Region")
    lon_min = mo.ui.number(value=float(_d.get("lon_min", -17.3)), step=0.05, label="lon min")
    lon_max = mo.ui.number(value=float(_d.get("lon_max", -11.2)), step=0.05, label="lon max")
    lat_min = mo.ui.number(value=float(_d.get("lat_min", 12.2)), step=0.05, label="lat min")
    lat_max = mo.ui.number(value=float(_d.get("lat_max", 16.8)), step=0.05, label="lat max")
    aoi_upload = mo.ui.file(filetypes=[".gpkg", ".geojson", ".json", ".parquet", ".zip"], label="AOI (GeoPackage, GeoJSON, GeoParquet or zipped Shapefile)")
    return aoi_upload, lat_max, lat_min, lon_max, lon_min, region_mode


@app.cell
def _(aoi_upload, lat_max, lat_min, lon_max, lon_min, mo, region_mode):
    mo.vstack([
        mo.md("### 4 · Region"),
        region_mode,
        mo.hstack([lon_min, lon_max, lat_min, lat_max], justify="start") if region_mode.value == "Bounding box" else aoi_upload,
        mo.md("The region is snapped outward to whole cells of the product's grid."),
    ])
    return


@app.cell
def _(mo):
    mode = mo.ui.radio(
        options={"Clip only — keep the original cells and values (REMAP=0)": "clip",
                 "Clip and remap to a target grid": "remap"},
        value="Clip only — keep the original cells and values (REMAP=0)", label="Processing")
    res_native = mo.ui.checkbox(value=True, label="native resolution of the product")
    res_value = mo.ui.number(value=0.1, start=0.005, stop=5, step=0.005, label="target resolution (°)")
    method = mo.ui.dropdown(options={"bilinear (smooth fields, same or finer grid)": "bilinear",
                                     "conservative (area average, coarser grid)": "conservative",
                                     "nearest neighbour (categories)": "nearest"},
                            value="bilinear (smooth fields, same or finer grid)", label="remap method")
    buffer_val = mo.ui.number(value=2, start=0, stop=500, step=0.5, label="buffer")
    buffer_unit = mo.ui.dropdown(options=["grid cells", "km", "degrees"], value="grid cells", label="unit")
    jobs = mo.ui.slider(1, 8, value=4, label="files in parallel", show_value=True)
    return buffer_unit, buffer_val, jobs, method, mode, res_native, res_value


@app.cell
def _(buffer_unit, buffer_val, jobs, method, mo, mode, res_native, res_value):
    _remap = mode.value == "remap"
    mo.vstack([
        mo.md("### 5 · Grid and processing"),
        mode,
        mo.hstack([res_native, res_value, method], justify="start") if _remap else mo.md(
            "*Clip only:* cells and values exactly as delivered, no interpolation, no buffer needed. "
            "Smallest and fastest — recommended unless you need a different resolution."),
        mo.hstack([buffer_val, buffer_unit], justify="start") if _remap else mo.md(""),
        mo.md("*The buffer is cut around the region before remapping, so edge cells have neighbours to interpolate from.*") if _remap else mo.md(""),
        jobs,
    ])
    return


@app.cell
def _(mo, prod_name):
    out_dir = mo.ui.text(value=f"data/interim/{prod_name or 'PRODUCT'}", label="output folder (inside the repository)", full_width=True)
    build_cube = mo.ui.checkbox(value=True, label="build a Zarr cube when processing is done")
    profile = mo.ui.dropdown(options=["balanced", "map", "timeseries"], value="balanced", label="chunk profile")
    mo.vstack([mo.md("### 6 · Output"), out_dir, mo.hstack([build_cube, profile], justify="start")])
    return build_cube, out_dir, profile


@app.cell
def _(mo, out_dir):
    cube_path = mo.ui.text(value=f"data/zarr/{out_dir.value.strip().rstrip('/').split('/')[-1].lower()}_cube.zarr",
                           label="Zarr cube path", full_width=True)
    cube_path
    return (cube_path,)


@app.cell
def _(DATA, aoi_upload, region_mode):
    # save an uploaded AOI next to the data (zipped shapefiles are unpacked)
    aoi_path = None
    if region_mode.value == "AOI file" and aoi_upload.value:
        import zipfile, io
        _f = aoi_upload.value[0]
        _dir = DATA / "aoi" / "uploads"; _dir.mkdir(parents=True, exist_ok=True)
        if _f.name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(_f.contents)) as _z:
                _z.extractall(_dir / _f.name[:-4])
            _shp = sorted((_dir / _f.name[:-4]).rglob("*.shp"))
            aoi_path = _shp[0] if _shp else None
        else:
            aoi_path = _dir / _f.name
            aoi_path.write_bytes(_f.contents)
    return (aoi_path,)


@app.cell
def _(BASE_URL, MONTHS, aoi_path, buffer_unit, buffer_val, jobs, lat_max, lat_min, lon_max, lon_min, main_var, math,
      method, mode, months, out_dir, prod_name, qa_vars, region_mode, res_native, res_value, shlex, year_from, year_to):
    # one settings object used by the summary, the command preview and the run
    _remap = mode.value == "remap"
    _target = None if (not _remap or res_native.value) else float(res_value.value)
    _cell = _target or 0.05
    _lat = (lat_min.value + lat_max.value) / 2
    _buf = {"degrees": buffer_val.value,
            "km": buffer_val.value / (111.32 * max(0.2, math.cos(math.radians(_lat)))),
            "grid cells": buffer_val.value * _cell}[buffer_unit.value] if _remap else 0.0
    settings = dict(
        product=prod_name, url=f"{BASE_URL}/{prod_name}/NETCDF", main=main_var.value.strip(),
        qa=",".join(v.strip() for v in qa_vars.value.split(",") if v.strip()),
        years=list(range(int(year_from.value), max(int(year_from.value), int(year_to.value)) + 1)),
        months=[MONTHS.index(m) + 1 for m in months.value],
        bbox=None if region_mode.value == "AOI file" else
             dict(lon_min=lon_min.value, lon_max=lon_max.value, lat_min=lat_min.value, lat_max=lat_max.value),
        aoi=str(aoi_path) if aoi_path else None,
        remap=_remap, target_res=_target, method=method.value, buffer_deg=round(float(_buf), 4),
        jobs=int(jobs.value), out=out_dir.value.strip())
    _env = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in [
        ("MAIN_VARIABLE", settings["main"]), ("QA_VARIABLES", settings["qa"]), ("REMAP", int(_remap)),
        ("TARGET_RES", _target or ""), ("JOBS", settings["jobs"]), ("OUT_DIR", settings["out"]),
        ("CONFIG_FILE", "<run config>")] if v != "")
    command = (f"for y in {' '.join(map(str, settings['years']))}; do for m in {' '.join(f'{m:02d}' for m in settings['months'])}; do\n"
               f"  {_env} uv run bash code/01b_download_and_clip.sh $y $m {settings['product']} {settings['url']}"
               f"{' ' + shlex.quote(settings['aoi']) if settings['aoi'] else ''}\ndone; done")
    return command, settings


@app.cell
def _(build_cube, command, cube_path, mo, profile, settings):
    _n = len(settings["years"]) * len(settings["months"])
    _problems = []
    if not settings["product"]: _problems.append("choose or type a product")
    if not settings["main"]: _problems.append("set the main variable")
    if not settings["months"]: _problems.append("select at least one month")
    if settings["bbox"] is None and not settings["aoi"]: _problems.append("upload an AOI file")
    if settings["bbox"] and (settings["bbox"]["lon_min"] >= settings["bbox"]["lon_max"] or settings["bbox"]["lat_min"] >= settings["bbox"]["lat_max"]):
        _problems.append("min must be smaller than max in the bounding box")
    ready = not _problems
    run_btn = mo.ui.run_button(label=f"▶ Run {_n} month(s)", disabled=not ready)
    _grid = ("original cells (no remapping)" if not settings["remap"] else
             f"remap ({settings['method']}) to {'native' if settings['target_res'] is None else str(settings['target_res']) + '°'} grid, buffer {settings['buffer_deg']}°")
    mo.vstack([
        mo.md("### 7 · Summary"),
        mo.md(f"**{settings['product']} / {settings['main']}** · {_n} month(s) ≈ {_n * 30} daily files · {_grid} · "
              f"{settings['jobs']} in parallel → `{settings['out']}`"
              + (f" · then Zarr cube `{cube_path.value}` ({profile.value})" if build_cube.value else "")),
        mo.callout(mo.md("; ".join(_problems)), kind="warn") if _problems else mo.md(""),
        mo.accordion({"Equivalent command line": mo.md(f"```bash\n{command}\n```")}),
        run_btn,
    ])
    return ready, run_btn


@app.cell
def _(CODE, Path, os, password, tempfile, use_env, user):
    def credentials_env():
        """Environment for child processes: credentials via a private temporary .env file (never on the command line)."""
        import sys
        env = dict(os.environ)
        env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"   # scripts use the app's Python
        if use_env.value and (CODE / ".env").exists():
            env["ENV_FILE"] = str(CODE / ".env")
            return env, None
        fd, path = tempfile.mkstemp(prefix="lsasaf_", suffix=".env"); os.close(fd)
        Path(path).write_text(f'LSASAF_USERNAME="{user.value}"\nLSASAF_PASSWORD="{password.value}"\n')
        os.chmod(path, 0o600)
        env["ENV_FILE"] = path
        return env, path
    return (credentials_env,)


@app.cell
def _(DATA, DEFAULT_CFG, Path, REPO, dt, json, settings, yaml):
    def write_run_config():
        """Run-specific YAML + grid file, so the repository defaults stay untouched."""
        run = DATA / "runs" / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{settings['product']}"
        run.mkdir(parents=True, exist_ok=True)
        cfg = yaml.safe_load(DEFAULT_CFG.read_text()) or {}
        if settings["bbox"]:
            cfg["domain"] = dict(settings["bbox"])
        cfg.setdefault("processing", {})
        cfg["processing"].update(remap_method=settings["method"], buffer=settings["buffer_deg"], parallel=1)
        cfg.setdefault("paths", {})["grid"] = str(run / "grid.txt")
        (run / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
        (run / "settings.json").write_text(json.dumps(settings, indent=2, default=str))
        return run
    return (write_run_config,)


@app.cell
def _(CODE, REPO, credentials_env, inspect_btn, mo, os, settings, subprocess, tempfile, Path):
    # Inspect: download the first file of the first selected month and list its variables
    mo.stop(not inspect_btn.value)
    _env, _tmpenv = credentials_env()
    _y, _m = settings["years"][0], (settings["months"] or [1])[0]
    _script = f'''
set -euo pipefail; set -a; . "$ENV_FILE"; set +a
W="$(mktemp)"; printf 'http_user=%s\\nhttp_password=%s\\n' "$LSASAF_USERNAME" "$LSASAF_PASSWORD" > "$W"; export WGETRC="$W"
SRC="{settings['url']}"; HOST="${{SRC%%/PRODUCTS*}}"
for d in $(seq -w 1 31); do u=$(wget -q -O- "$SRC/{_y}/{_m:02d}/$d/" | tr '"' '\\n' | grep -E '\\.nc$' | head -1 || true); [ -n "$u" ] && break; done
[ -n "${{u:-}}" ] || {{ echo "no files found for {_y}-{_m:02d}"; exit 1; }}
T="$(mktemp -d)"; wget -q -O "$T/f.nc" "$HOST$u"; echo "file: ${{u##*/}}"; echo "variables: $(cdo -s showname "$T/f.nc")"
cdo -s griddes "$T/f.nc" | grep -E "xsize|ysize|xinc|yinc|xfirst|yfirst" | tr -s " "
rm -rf "$T" "$W"
'''
    with mo.status.spinner("Inspecting the first file …"):
        _r = subprocess.run(["bash", "-c", _script], env=_env, capture_output=True, text=True, cwd=REPO)
    if _tmpenv: os.remove(_tmpenv)
    mo.callout(mo.md(f"```\n{(_r.stdout + _r.stderr).strip()[-3000:]}\n```"), kind="success" if _r.returncode == 0 else "danger")
    return


@app.cell
def _(CODE, REPO, build_cube, credentials_env, cube_path, mo, os, profile, results_view, run_btn, settings, subprocess, time, write_run_config):
    # Run: one call of 01b_download_and_clip.sh per month, live log, then the cube builder
    import sys
    mo.stop(not run_btn.value, mo.md("*Press ▶ Run to start. Progress and the log appear here.*"))
    run_dir = write_run_config()
    _env, _tmpenv = credentials_env()
    _env.update(MAIN_VARIABLE=settings["main"], QA_VARIABLES=settings["qa"], REMAP=str(int(settings["remap"])),
                TARGET_RES=str(settings["target_res"] or ""), JOBS=str(settings["jobs"]),
                OUT_DIR=str(REPO / settings["out"]), CONFIG_FILE=str(run_dir / "config.yaml"),
                TMP_DIR=str(REPO / "data" / "tmp"))
    _todo = [(y, m) for y in settings["years"] for m in settings["months"]]
    _log, _failed, _t0 = [], [], time.time()
    _logfile = open(run_dir / "run.log", "w")
    try:
        for _k, (_y, _m) in enumerate(_todo, 1):
            _cmd = ["bash", str("code/01b_download_and_clip.sh"), str(_y), f"{_m:02d}", settings["product"], settings["url"]]
            if settings["aoi"]:
                _cmd.append(settings["aoi"])
            _p = subprocess.Popen(_cmd, cwd=REPO, env=_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for _line in _p.stdout:
                if _line.startswith("cdo ") and "weights" in _line:
                    continue                                    # CDO prints one line per remapped file
                _log.append(f"[{_y}-{_m:02d}] {_line.rstrip()}"); _logfile.write(_log[-1] + "\n"); _logfile.flush()
                mo.output.replace(mo.vstack([
                    mo.md(f"**Month {_k}/{len(_todo)}** ({_y}-{_m:02d}) · {time.time() - _t0:.0f}s elapsed"),
                    mo.md(f"```\n" + "\n".join(_log[-18:]) + "\n```"),
                ]))
            if _p.wait() != 0:
                _failed.append(f"{_y}-{_m:02d}")
        if build_cube.value and not _failed:
            _log.append("Building the Zarr cube …")
            mo.output.replace(mo.md("```\n" + "\n".join(_log[-18:]) + "\n```"))
            _c = subprocess.run([sys.executable, str(CODE / "03_build_zarr_cube.py"), "--input", str(REPO / settings["out"]),
                                 "--profile", profile.value, "--output", str(REPO / cube_path.value.strip())], cwd=REPO, env=_env, capture_output=True, text=True)
            _log += (_c.stdout + _c.stderr).strip().splitlines()[-8:]
            if _c.returncode != 0:
                _failed.append("cube")
    finally:
        _logfile.close()
        if _tmpenv: os.remove(_tmpenv)
    _secs = round(time.time() - _t0)
    mo.output.replace(mo.vstack([
        mo.callout(mo.md(f"**{'Finished' if not _failed else 'Finished with errors: ' + ', '.join(_failed)}** in "
                         f"{_secs} s. Settings, grid and full log: `{run_dir.relative_to(REPO)}`. "
                         + ("Re-run to retry; finished files are skipped." if _failed else "")),
                   kind="success" if not _failed else "warn"),
        mo.md("```\n" + "\n".join(_log[-25:]) + "\n```"),
        results_view(settings["out"], settings["main"]),
    ]))
    return


@app.cell
def _(REPO, mo):
    def results_view(out_rel, main):
        """Summary of what is kept in an output folder, with a map of the last file."""
        import xarray as xr
        import matplotlib.pyplot as plt
        out = REPO / out_rel
        files = sorted(out.rglob("*_processed.nc")) if out.exists() else []
        if not files:
            return mo.md(f"No processed files in `{out_rel}` yet.")
        size = sum(f.stat().st_size for f in files) / 1e6
        tmp = REPO / "data" / "tmp"
        raw_left = sum(1 for _ in tmp.rglob("*.nc")) if tmp.exists() else 0
        with xr.open_dataset(files[-1]) as ds:
            v = main if main in ds else list(ds.data_vars)[0]
            da = ds[v].isel(time=0) if "time" in ds[v].dims else ds[v]
            fig, ax = plt.subplots(figsize=(6.5, 4.2))
            da.plot(ax=ax, cmap="viridis")
            ax.set_title(f"{files[-1].name}\n{v} · {ds.sizes.get('lon', '?')} × {ds.sizes.get('lat', '?')} cells", fontsize=8)
            fig.tight_layout()
        zdir = REPO / "data" / "zarr"
        cubes = sorted(zdir.glob("*.zarr")) if zdir.exists() else []
        return mo.vstack([
            mo.hstack([mo.stat(value=str(len(files)), label="clipped files kept"),
                       mo.stat(value=f"{size:.1f} MB", label="on disk"),
                       mo.stat(value=str(raw_left), label="raw files left")], justify="start"),
            fig,
            mo.md("Cubes: " + (", ".join(f"`{c.relative_to(REPO)}`" for c in cubes) or "none yet")),
        ])
    return (results_view,)


@app.cell
def _(mo):
    refresh = mo.ui.button(label="↻ refresh", value=0, on_click=lambda v: v + 1)
    return (refresh,)


@app.cell
def _(mo, refresh, results_view, settings):
    refresh.value
    mo.vstack([mo.md("### 8 · Output folder contents (press refresh after a run)"), refresh,
               results_view(settings["out"], settings["main"])])
    return


if __name__ == "__main__":
    app.run()
