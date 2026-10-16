# **Climate Data Cube Workshop**

Part of the [IEEE GRSS Autumn School 2026](https://it-u.at/en/events/earth-observation-and-geoai-for-climate-resilient-urban-systems-grss-school/) training. Participants learn how to access climate data from the EUMETSAT LSA SAF data service and turn raw NetCDF files into a compressed, chunked **Zarr v3 cube** — covering cloud-native principles (chunking, sharding, compression, lazy access) and how to move from raw files to analysis-ready products for maps, time series and regional indicators.

> **Note:** This is a demonstration pipeline, not a production climate service — but it could become one with further validation and optimisation.

| | |
|---|---|
| 📖 Tutorial (step by step) | <https://khizerzakir.github.io/tutorial-repo/> |
| 🧰 Command builder | <https://khizerzakir.github.io/tutorial-repo/tutorial/reference.html> |
| 🎤 Slides | <https://khizerzakir.github.io/tutorial-repo/slides/presentation.html> |
| 💻 Code | [`code/`](code/) |

## **Quick start**

On **Windows**, everything below runs inside **WSL2 (Ubuntu)**: Start menu → *Ubuntu* (first time: `wsl --install -d Ubuntu` in an admin PowerShell). On macOS/Linux use your terminal. Full instructions: [tutorial A · Setup](https://khizerzakir.github.io/tutorial-repo/tutorial/01-setup.html).

```bash
# 1. tools (Ubuntu/WSL; macOS: brew install git wget cdo)
sudo apt update && sudo apt install -y git wget curl cdo
curl -LsSf https://astral.sh/uv/install.sh | sh && source "$HOME/.local/bin/env"

# 2. repository + Python environment (keep it under ~/, not /mnt/c on WSL)
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/khizerzakir/tutorial-repo.git && cd tutorial-repo
uv sync --locked --extra notebook

# 3. credentials (never commit this file)
cp code/.env.example code/.env && nano code/.env

# 4. pipeline: download → crop/remap → cube
bash code/01_download_sample.sh 2015 06 METREF
MAIN_VARIABLE=METREF uv run bash code/02_preprocess_cdo.sh 0.05 data/raw/METREF data/interim/METREF
uv run python code/03_build_zarr_cube.py --input data/interim/METREF

# 5. explore
uv run --extra notebook jupyter lab code/notebooks
```

Run all commands from the **repository root**. Start the preprocessing script through `uv run` (or after `source .venv/bin/activate`) so its internal `python3` calls use the project environment.

## **Objective and scope**

A small, reproducible processing chain prepares selected LSA SAF products for regional mapping and time-series analysis. The sample configuration uses **METREF** (reference evapotranspiration) and **FVC/MDFVC** (fractional vegetation cover). Before analysis, check each product's availability, variable names, units, time coverage, quality flags and access terms in the [LSA SAF Data Service](https://datalsasaf.lsasvcs.ipma.pt/).

Start with a short period and a small, representative area; validate that result before processing a larger region or time span.

## **Workflow**

| Step | Command | Output |
|---|---|---|
| 1 · Download | `bash code/01_download_sample.sh [YYYY] [MM] [PRODUCT] [URL]` | `data/raw/<PRODUCT>/YYYY/MM/*.nc` |
| 2 · Inspect | `cdo -s showname / sinfo / infon <file>` | variable names, grid, value ranges |
| 3 · Crop & remap | `MAIN_VARIABLE=… [QA_VARIABLES=…] uv run bash code/02_preprocess_cdo.sh [RES] [IN] [OUT] [AOI_FILE]` | `data/interim/<PRODUCT>/YYYY/MM/*_processed.nc`, `cdo.log` |
| 4 · Build cube | `uv run python code/03_build_zarr_cube.py --input data/interim/<PRODUCT> [--profile …]` | `data/zarr/<variable>_cube.zarr` |
| 5 · Explore | `code/notebooks/1_…`, `2_…`, `3_…` + `code/plot_utils/` | validation tables, maps, time series |

Key behaviour:

- **Download** reads credentials and defaults from `code/.env`; positional arguments override them.
- **Preprocessing** snaps the region (YAML `domain:` or a vector AOI file) outward to whole raw-grid cells, writes `code/preprocess_utils/grid.txt` and **updates `config_resolution.yaml` in place**. Continuous variables use the YAML `remap_method` (bilinear by default); QA variables always use nearest neighbour. Parallelism is set with `processing.parallel` in the YAML. Only validated outputs are renamed into place; re-runs resume.
- **Cube builder** concatenates the interim files along time, rounds shards to whole inner chunks, writes to `<output>.tmp`, validates the first/last time steps against the sources and only then replaces the previous cube. Useful flags: `--dry-run`, `--profile map|balanced|timeseries`, `--append`, `--variables`, `--float32`, `--workers`, `--chunks/--shards`, `--clevel`. See `--help`.

> **Important:** choose AOI size, `JOBS`, `processing.parallel` and `--workers` to fit your machine's RAM, disk and network.

## **Repository structure**

```text
.
├── README.md                    # Purpose, quick start, workflow
├── index.qmd                    # Tutorial website landing page
├── _quarto.yml                  # Website navigation and theme
├── tutorial/
│   ├── 01-setup.qmd             # A · WSL/terminal, tools, uv, credentials
│   ├── 02-run-code.qmd          # B · download, inspect, crop and remap
│   ├── 03-zarr-cubes.qmd        # C · build, chunk explorer, open the cube
│   ├── 04-explore.qmd           # D · notebooks and plot_utils
│   ├── reference.qmd            # Command builder + all script options
│   ├── _chunk-explorer.qmd      # Interactive widget (also used in the slides)
│   ├── _command-builder.qmd     # Interactive widget
│   ├── tutorial.scss            # Site styles
│   └── imgs/                    # Portal screenshots
├── slides/
│   ├── presentation.qmd         # Reveal.js slides (animated, interactive)
│   ├── theme.scss               # Slide theme and components
│   └── img/                     # Slide figures and logos
├── code/
│   ├── .env.example             # Credential/settings template (copy to code/.env)
│   ├── 01_download_sample.sh    # Authenticated LSA SAF download
│   ├── 02_preprocess_cdo.sh     # Clip, remap, validate and write interim NetCDF
│   ├── 03_build_zarr_cube.py    # Chunked, sharded, compressed Zarr v3 cube
│   ├── preprocess_utils/        # Region/grid settings and AOI snapping helper
│   ├── plot_utils/              # Reusable map/time-series/mobility plotting
│   └── notebooks/               # 1 validate · 2 plot · 3 application
├── data/aoi/                    # Spatial units and mobility table for the application notebook
├── pyproject.toml / uv.lock     # Python dependencies (locked)
└── requirements.txt             # pip export of uv.lock
```

Generated data stay outside version control:

```text
data/raw/<PRODUCT>/YYYY/MM/        downloaded source NetCDF
data/interim/<PRODUCT>/YYYY/MM/    clipped and remapped NetCDF (+ cdo.log)
data/zarr/<variable>_cube.zarr/    analysis-ready cube
```

## **Build the website and slides locally**

Install [Quarto](https://quarto.org/docs/get-started/) and run `quarto preview` (live) or `quarto render` (to `docs/`) from the repository root. The site is published to GitHub Pages by `.github/workflows/publish.yml` on every push to `main`. The interactive widgets are plain JavaScript and work offline.

## **Applications and next steps**

After product-specific validation, a regional cube supports seasonal maps, regional statistics, time-series comparisons, vegetation/evapotranspiration monitoring and climate-impact indicators — see `code/notebooks/3_application.ipynb` for a climate–mobility example. Possible improvements: quality-aware masks, coverage thresholds, unit/metadata checks, tests on representative files, multi-product harmonisation, provenance/STAC cataloguing, object-storage output and workload-based chunk benchmarking.

## **Security and citation**

- Never commit `code/.env` (it is in `.gitignore`); don't pass passwords on the command line or show them in screenshots.
- LSA SAF data are CC BY 4.0 — follow the LSA SAF attribution guidance when publishing.
- I would like to acknowledge [OpenAI](https://chatgpt.com/) & [Claude](https://claude.ai/) that helped me refine my code and build effects in the repository. 
- To cite this repository, see [`CITATION.cff`](CITATION.cff).
