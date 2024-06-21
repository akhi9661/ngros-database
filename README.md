[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/akhi9661/ngros-database/blob/main/database.ipynb)

# NGROS DATABASE MANAGEMENT SYSTEM
*Note*: This repo is a work in progress. No warranty offered for the code modules used. 

---
## HOW TO USE

- Download ```requirements.txt``` and  ```main.py``` (or ```database.ipynb```) files
- Install conda
- Open Anaconda prompt
- Create a new environment: ```conda create -n env_name python=3.10```
- Install required libraries (do install other libraries if required): ```pip install -r /path/to/requirements.txt```
- Open the ipynb file in Jupyter notebook (preferred) or run in console as: ```python main.py```

Alternatively, click on ```Open in Colab``` badge to run it on Google Colab platform.

----
## METEOROLOGICAL DATA

This document provides a brief overview of the parameters used, their sources and links to resources. 

---
### 1. DATA SOURCES

NASA POWER [<https://power.larc.nasa.gov/data-access-viewer/>]

Resources: <https://power.larc.nasa.gov/#resources>

Hourly API Doc: <https://power.larc.nasa.gov/docs/services/api/temporal/hourly/>

---
### 2. MODELS USED
---

| Model Name | Data Type | Additional Information |
| -------- | -------- | -------- |
| MERRA 2 | Meteorology | [Global Modeling and Assimilation Office (GMAO)](http://gmao.gsfc.nasa.gov/) |
| GEOS 5.12.4 | Meteorology | [Global Modeling and Assimilation Office (GMAO)](http://gmao.gsfc.nasa.gov/) |
| GEWEX SRB R4-IP | Solar Radiation | [NASA/GEWEX Surface Radiation Budget (SRB) Project](http://gewex-srb.larc.nasa.gov/) |
| CERES SYN1deg | Solar Radiation | [Clouds and the Earth’s Radiant Energy System (CERES) Project](https://ceres.larc.nasa.gov/) |
| FLASHFlux 4 | Solar Radiation | [CERES Fast Longwave And SHortwave Radiative Fluxes (FLASHFlux)](http://flashflux.larc.nasa.gov/) |

---
### 3. PARAMETERS

---
**Name**: Precipitation Corrected

**Abbreviation**: PRECTOTCORR

**Definition (hourly)**: The bias corrected average of total precipitation at the surface of the earth in water mass (includes water content in snow).

**Unit**: mm/hr

---
**Name**: Temperature at 2 Meters

**Abbreviation**: T2M

**Definition (hourly)**: The average air (dry bulb) temperature at 2 meters above the surface of the earth.

**Unit**: Celsius

---
**Name**: Wind Speed at 2 Meters

**Abbreviation**: WS2M

**Definition (hourly)**: The average of wind speed at 2 meters above the surface of the earth.

**Unit**: m/s

---
**Name**: Relative Humidity at 2 Meters

**Abbreviation**: RH2M

**Definition (hourly)**: The ratio of actual partial pressure of water vapor to the partial pressure at saturation, expressed in percent.

**Unit**: %

---
**Name**: All Sky Surface Shortwave Downward Irradiance

**Abbreviation**: ALLSKY_SFC_SW_DWN

**Definition (hourly)**: The total solar irradiance incident (direct plus diffuse) on a horizontal plane at the surface of the earth under all sky conditions. An alternative term for the total solar irradiance is the "Global Horizontal Irradiance" or GHI.

**Unit**: MJ/m^2/hour

---
### 4. Hourly API Structure

```/api/temporal/hourly/point?parameters=WS10M,WD10M,T2MDEW,T2MWET,T2M,V10M,RH2M,PS,PRECTOT,QV2M,U10M&community=SB&longitude=0&latitude=0&start=20170101&end=20170102&format=CSV```

URL

```https://power.larc.nasa.gov/api/temporal/hourly/point?parameters=WS10M,WD10M,T2MDEW,T2MWET,T2M,V10M,RH2M,PS,PRECTOT,QV2M,U10M&community=SB&longitude=0&latitude=0&start=20170101&end=20170102&format=CSV```
