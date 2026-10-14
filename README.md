# **Climate Data Cube Workshop**

This is part of the [IEEE Autumn School 2026](https://it-u.at/en/events/earth-observation-and-geoai-for-climate-resilient-urban-systems-grss-school/) Training. In this workshop participants will mainly learn how to access climate data from EUMETSAT data portal and create Zarr cubes. We will explore the principles of cloud-native geospatial data, including chunking, compression, and scalable data access, and demonstrate how to change raw climate data files to efficient, analysis-ready products. The concepts and workflows presented can be applied to a wide range of Earth observation datasets, including time series analysis, regional subsets, and climate resilience indicators.
> **!Note:** It is a demonstration pipeline, not a production climate service - but could become a service with optimization.

## **Objective and scope**

The hands-on workshop shows how a small, reproducible processing chain can prepare selected LSA SAF products for regional mapping and time-series analysis. The checked-in sample configuration uses **METREF** (reference evapotranspiration) and **FVC** (fractional vegetation cover) as example products. Before analysis, check each product's current availability, variable names, units, time coverage, quality flags, and access terms in the [LSA SAF Data Service](https://datalsasaf.lsasvcs.ipma.pt/).

The initial run should use a short period and a small, representative area. Validate that result before processing a larger region or time span. The objective is to get an understanding of how we can get the targetted data and then quickly make it available for your analysis. 

## **Repository structure**

```text
.
├── README.md                 # Purpose, workflow, setup and limitations
├── index.qmd                 # Tutorial website landing page
├── _quarto.yml               # Website navigation and HTML theme
├── tutorial/
│   ├── imgs/                 # Portal/setup illustrations
│   ├── 01-setup.qmd          # Environment and credentials
│   ├── 02-run-code.qmd       # Download and preprocess a sample
│   └── 03-zarr-cubes.qmd     # Build and inspect the Zarr cube
├── slides/
│   ├── presentation.qmd      # Reveal.js workshop slides
│   ├── theme.scss            # Existing presentation theme
│   └── img/                  # Slide figures
├── code/
│   ├── .env.example          # Credential/settings template (copy to code/.env)
│   ├── 01_download_sample.sh # Authenticated LSA SAF download
│   ├── 02_preprocess_cdo.sh  # Clip, remap, validate and write interim NetCDF
│   ├── 03_build_zarr_cube.py    # Compressed/sharded Zarr v3 output
│   ├── preprocess_utils/     # Region/grid settings and grid generator
│   ├── plot_utils/           # Reusable cube plotting functions
│   └── notebooks/            # Data inspection notebooks
├── pyproject.toml            # Python dependencies
├── requirements.txt          # pip dependency export
└── uv.lock                   # Locked uv environment
```

Generated data stay outside version control:

```text
data/raw/<product>/YYYY/MM/  downloaded source NetCDF
data/interim/YYYY/MM/        clipped and remapped NetCDF
data/zarr/*.zarr/             analysis-ready cube
```
## **Workflow**

1. **Configure and download.** Register for LSA SAF access, store credentials in the ignored local `code/.env`, choose a product URL and sample month, and run `code/01_download_sample.sh`. 
2. **Inspect the source.** Check coordinates, time, variable names, units, fill values, quality flags, and valid-value counts before remapping.
3. **Clip and remap.** `code/02_preprocess_cdo.sh` clip and remap continuous fields to a grid created from bounds in `code/preprocess_utils/config_resolution.yaml`.
4. **Validate interim outputs.** The preprocessing script included here writes through temporary files, checks that CDO can read the result and that at least one valid cell remains, then renames only a successful output into place.
5. **Build the cube.** `code/build_zarr_cube.py` opens interim NetCDF with xarray/Dask and writes a compressed, chunked and sharded Zarr v3 store.
6. **Explore.** Use the `code/notebooks` and `code/plot_utils/` to inspect and plot the data.

From the repository root, the main commands are:

```bash
cp code/.env.example code/.env   # Add LSA SAF credentials to code/.env
bash code/01_download_sample.sh
bash code/02_preprocess_cdo.sh
uv run python code/03_build_zarr_cube.py
```

Run from the repository root because the download script's default credential path is `code/.env`. Install CDO separately from the Python packages. For a local website build, install Quarto and run `quarto render` from the root.

> **Important:** Select AOIs and workers based on the limitation of your system


## **Applications and possible updates/next steps**

**What you can do afterwards**

After product-specific validation, a regional cube can support seasonal maps, regional statistics, time-series comparisons, vegetation/evapotranspiration monitoring and climate-impact indicators. Possible improvements include quality-aware masks, automated coverage thresholds, unit/metadata checks, tests on representative files, multi-product harmonization, provenance/STAC cataloguing, cloud/object-storage support, and workload-based chunk/shard benchmarking.


## **Links**

| | |
|---|---|
| 📖 Tutorial site | [Tutorial site](https://khizerzakir.github.io/tutorial-repo/) |
| 🎤 Slides | [Open the slides](https://khizerzakir.github.io/tutorial-repo/slides/presentation.html) |
| 💻 Code | [`code/`](code/) |

## **Security and Citation**

Keep credentials out of Git and follow the data provider's current attribution and licensing guidance. 

- Never commit `.env` (it is in `.gitignore`).
- Don't pass passwords on the command line.

LSA SAF data are CC BY 4.0. Follow the LSA SAF attribution guidance when publishing. To cite this repository, see [`CITATION.cff`](CITATION.cff).



