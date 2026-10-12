# **Climate Data Cube Workshop**

This is part of the [IEEE Autumn School 2026](https://it-u.at/en/events/earth-observation-and-geoai-for-climate-resilient-urban-systems-grss-school/) Training. In this workshop student will mainly learn how to access climate data from EUMETSAT data portal and create Zarr cubes. 

In this session, participants will work with satellite-derived climate data from EUMETSAT LSA SAF and make analysis-ready data cube using Zarr and Xarray. We will explore the principles of cloud-native geospatial data, including chunking, compression, and scalable data access, and demonstrate how to change raw climate data files to efficient, analysis-ready products. The concepts and workflows presented can be applied to a wide range of Earth observation datasets, including time series analysis, regional subsets, and climate resilience indicators.

> **Important links for this workshop**

- Tutorial Site: https://khizerzakir.github.io/tutorial-repo/
- Slides: https://github.com/khizerzakir/tutorial-repo/slides/presentation.html
- Code: https://github.com/khizerzakir/tutorial-repo/tree/main/code


## **How to get the data?**

- **Portal Registration**

![Data Portal Registration](/imgs/portal_reg.png)

> After you fill out the registration form and activate your account. Please follow the following steps.

- Create a `.env` file in your current folder and write your **"USERNAME"** and **"PASSWORD"** you just created. 
```
USERNAME="username"
PASSWORD="#########"
```
>After saving the file, to secure your credentials, add it to `.gitignore` to avoid pushing it to github. Also, follow the following commands to keep them secure. We will call these credential in our downloading scripts. 


```
## Windows

```

```
## Linux

```
- **Browse Data**

![Browse the products](/imgs/browse.png)

### **Choose Product**

For this tutorial, we are going to choose the following 2 products:

- **[METREF - Reference Evapotranspiration](https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG/METREF/)**
- **[FVC - Fractional Vegetation Cover](https://datalsasaf.lsasvcs.ipma.pt/PRODUCTS/MSG/MDFVC/)**

You can click on the above links to get a basic understand of the data. 
