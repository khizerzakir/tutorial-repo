# Climate cube builder (point-and-click app)

A small browser app for the tutorial pipeline. You choose the product, variables, years, region, resolution and
buffer in a form; the app downloads each daily LSA SAF file, **clips it to your study area, deletes the raw file**
and, at the end, builds a **Zarr cube**. Only the clipped files are kept.

It is a front end for the scripts in `code/`: every run calls `code/01b_download_and_clip.sh` (month by month) and
`code/03_build_zarr_cube.py`, so the results are identical to running them by hand. The app shows the equivalent
command line before you start.

| File | What it is |
|---|---|
| `processing_app.py` | the app ([marimo](https://marimo.io) notebook, runs as a web page) |
| `Dockerfile` | image with Python 3.12, CDO, wget and the locked Python environment |
| `docker-compose.yml` | starts the app on <http://localhost:2718> and mounts the repository's `data/` folder |

## Start

### With Docker (nothing else to install)

From the **repository root**:

```bash
docker compose -f code/app/docker-compose.yml up --build
```

Open <http://localhost:2718>. Stop with `Ctrl+C` (or `docker compose -f code/app/docker-compose.yml down`).
The first build takes a few minutes; later starts take seconds.

- Downloads, runs and cubes are written to the repository's `data/` folder on your computer, not inside the container.
- The app listens on `127.0.0.1` only, so it is not reachable from other computers.
- To reuse saved credentials instead of typing them, create `code/.env` (see `code/.env.example`) and uncomment the
  `../.env:/app/code/.env:ro` line in `docker-compose.yml`.
- On Windows, run the command in WSL2 (Ubuntu) with Docker Desktop's WSL integration switched on.

### Without Docker

Needs the tutorial setup (`cdo`, `wget`, `uv`; see the main README):

```bash
uv sync --locked --extra dashboard
uv run --extra dashboard marimo run code/app/processing_app.py
```

To edit the app itself: `uv run --extra dashboard marimo edit code/app/processing_app.py`.

## Using the app

The page is a form with eight sections, filled from top to bottom.

| Section | What you set | Notes |
|---|---|---|
| 1 · Account | LSA SAF username and password, or *use credentials from code/.env* | The password is written to a private temporary file (`chmod 600`) for the run and deleted afterwards; it never appears on a command line or in the logs. |
| 2 · Product and variables | product (`METREF`, `MDFVC`, or *Other…* to type any product folder), main variable, QA variables | **Inspect first file** downloads one file of the start month and lists its variables and grid, so you can check the names before a long run. |
| 3 · Period | from year, to year, months | Every selected month of every year is processed. |
| 4 · Region | bounding box (lon/lat), or an AOI file (GeoPackage, GeoJSON, GeoParquet or zipped Shapefile) | The region is snapped outward to whole cells of the product's grid. Uploaded AOIs are saved in `data/aoi/uploads/`. |
| 5 · Grid and processing | clip only or clip and remap; target resolution; remap method; buffer and unit; files in parallel | See [Clip only or remap?](#clip-only-or-remap) below. |
| 6 · Output | output folder, Zarr cube on/off, chunk profile, cube path | Use a new output folder per setting (e.g. `data/interim/METREF_0p1`) so native and remapped files don't mix. |
| 7 · Summary | — | Number of months and files, grid, output, any missing setting, the **equivalent command line**, and the **▶ Run** button. |
| 8 · Output folder contents | — | Files kept, disk use, raw files left, a map of the last file, existing cubes. Press **↻ refresh** after a run. |

While a run is going, the log streams under the Run button. When it finishes you see a summary, the cube builder's
validation report and a map.

**Re-running is safe:** files whose clipped version already exists are skipped, so after an interruption or an
error just press ▶ Run again.

## Clip only or remap?

| | Clip only (`REMAP=0`) | Clip and remap (`REMAP=1`) |
|---|---|---|
| What happens | the study area is cut out of the full-disk file | a slightly larger area (study area + buffer) is cut out and interpolated onto a new grid |
| Cells and values | exactly as delivered by LSA SAF | interpolated |
| Resolution | the product's own (0.05° for METREF) | native or any target, e.g. `0.1` |
| Buffer | not needed | needed, so the edge cells have neighbours to interpolate from |
| When to use | **default choice**: smallest, fastest, faithful | when you need a different resolution, e.g. to match another dataset |

At the product's own resolution both modes give the same cells, so remapping only makes sense with a different target
resolution. Pick the method by what you are doing:

| Method | Use for |
|---|---|
| `bilinear` | smooth fields on a grid at the same or finer resolution |
| `conservative` | a **coarser** grid: each new cell is the area average of the cells it covers |
| `nearest` | categories and flags (QA variables always use nearest neighbour) |

**Buffer units.** The buffer is converted to degrees before it is used: *grid cells* × the target resolution
(native: 0.05°); *km* ÷ (111.32 × cos(latitude)) at the middle of your region; *degrees* as entered. The default,
2 grid cells, is enough for all three methods.

## What a run leaves behind

```text
data/
├── interim/<output folder>/YYYY/MM/*_processed.nc   clipped (and remapped) daily files
├── interim/<output folder>/cdo.log                  processed / failed per file
├── zarr/<name>_cube.zarr                            the cube, if selected
└── runs/<YYYYMMDD_HHMMSS>_<PRODUCT>/
    ├── settings.json                                everything you chose in the form
    ├── config.yaml                                  the settings file passed to the scripts
    ├── grid.txt                                     the CDO target grid
    └── run.log                                      full log
```

The repository's own `code/preprocess_utils/config_resolution.yaml` is only read, never changed: each run gets its
own copy in `data/runs/`. To repeat a run by hand, use the command from the summary with
`CONFIG_FILE=data/runs/<run>/config.yaml`.

`data/runs/` and `data/aoi/uploads/` are in `.gitignore`. Raw files exist only briefly in `data/tmp/` while a
file is being processed; at most *files in parallel* of them at once.

## Settings for other servers

| Environment variable | Purpose | Default |
|---|---|---|
| `LSASAF_BASE_URL` | server root that holds the product folders | `https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG` |

The app expects the LSA SAF layout `<base>/<PRODUCT>/NETCDF/YYYY/MM/DD/*.nc`. With Docker, set the variable under
`environment:` in `docker-compose.yml`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| **Inspect** says "no files found" | wrong product name, wrong credentials, or no data for that month. Check the product folder on the LSA SAF server. |
| `Error creating grid/YAML` with a Python traceback | the scripts are using a different Python. Start the app through `uv run` (or Docker), not with a system `marimo`. |
| "Finished with errors: YYYY-MM" | look at `data/runs/<run>/run.log` and `data/interim/<folder>/cdo.log`; then press ▶ Run again: finished files are skipped. |
| Main variable not found | names differ between products. Use **Inspect** and copy the exact name. |
| Port 2718 already in use | change the left side of `127.0.0.1:2718:2718` in `docker-compose.yml`, e.g. `127.0.0.1:8080:2718`. |
| `docker compose` cannot pull `python:3.12-slim` | no access to Docker Hub (proxy or firewall). Use the *Without Docker* route. |

## Security

- Never commit `code/.env`; it is in `.gitignore` and `.dockerignore`, so it is never copied into the image.
- Credentials typed in the form exist only in a temporary file during the run.
- The container port is bound to `127.0.0.1`. Do not change this to `0.0.0.0` on a shared or public machine: the app
  has no login of its own (`--no-token`).
