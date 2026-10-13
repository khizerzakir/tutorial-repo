# **Climate Data Cube Workshop**

This is part of the [IEEE Autumn School 2026](https://it-u.at/en/events/earth-observation-and-geoai-for-climate-resilient-urban-systems-grss-school/) Training. In this workshop participants will mainly learn how to access climate data from EUMETSAT data portal and create Zarr cubes. We will explore the principles of cloud-native geospatial data, including chunking, compression, and scalable data access, and demonstrate how to change raw climate data files to efficient, analysis-ready products. The concepts and workflows presented can be applied to a wide range of Earth observation datasets, including time series analysis, regional subsets, and climate resilience indicators.


## Links

| | |
|---|---|
| 📖 Tutorial site | [khizerzakir.github.io/tutorial-repo](https://khizerzakir.github.io/tutorial-repo/) |
| 🎤 Slides | [Open the slides](https://khizerzakir.github.io/tutorial-repo/slides/presentation.html) |
| 💻 Code | [`code/`](code/) |

## Quick start

1. Register on the [LSA SAF data portal](https://datalsasaf.lsasvcs.ipma.pt/) and activate your account.

   ![Data portal registration](imgs/portal_reg.png)

2. Add your credentials to a `.env` file in `code/`:

```bash
   cp code/.env.example code/.env
```

```
   LSASAF_USERNAME="username"
   LSASAF_PASSWORD="password"
```

3. Choose the products for this tutorial:
   - [METREF: Reference Evapotranspiration](https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG/METREF/)
   - [FVC: Fractional Vegetation Cover](https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG/MDFVC/)

   ![Browse the products](imgs/browse.png)

> 📖 Full step-by-step instructions are in the [tutorial pages](https://khizerzakir.github.io/tutorial-repo/tutorial/01-setup.html).

## Security

- Never commit `.env` (it is in `.gitignore`).
- Don't pass passwords on the command line.

## Citation

LSA SAF data are CC BY 4.0. Follow the LSA SAF attribution guidance when publishing. To cite this repository, see [`CITATION.cff`](CITATION.cff).