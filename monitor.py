import requests
import os
import pandas as pd
from datetime import date

today=str(date.today())

locations = {
"Gauting":{"lat":48.067,"lon":11.377,"capacity":160},
"Waging am See":{"lat":47.933,"lon":12.733,"capacity":180},
"Dettenhausen":{"lat":48.605,"lon":9.106,"capacity":140}
}

def weather_data(lat,lon):

    url=f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,et0_fao_evapotranspiration&past_days=30&timezone=Europe%2FBerlin"

    data=requests.get(url).json()

    rain=sum(data["daily"]["precipitation_sum"][:30])
    evap=sum(data["daily"]["et0_fao_evapotranspiration"][:30])

    forecast_rain=sum(data["daily"]["precipitation_sum"][30:37])
    forecast_evap=sum(data["daily"]["et0_fao_evapotranspiration"][30:37])

    return rain,evap,forecast_rain,forecast_evap


def classify(storage,capacity):

    ratio=storage/capacity

    if ratio>0.7:
        return "LOW"
    elif ratio>0.4:
        return "MODERATE"
    elif ratio>0.2:
        return "HIGH"
    else:
        return "SEVERE"


rows=[]
alerts=[]

for name,info in locations.items():

    lat=info["lat"]
    lon=info["lon"]
    capacity=info["capacity"]

    rain,evap,forecast_rain,forecast_evap=weather_data(lat,lon)

    storage=rain-evap

    storage=max(0,min(storage,capacity))

    stress=classify(storage,capacity)

    if stress=="SEVERE":
        alerts.append(name)

    rows.append({
    "date":today,
    "location":name,
    "storage":round(storage,2),
    "forecast":round(forecast_rain-forecast_evap,2),
    "stress":stress
    })


df=pd.DataFrame(rows)

os.makedirs("data",exist_ok=True)

history_file="data/history.csv"

if os.path.exists(history_file):

    old=pd.read_csv(history_file)
    df=pd.concat([old,df])

df=df.drop_duplicates(subset=["date","location"])

df.to_csv(history_file,index=False)


report="Weekly Tree Drought Monitor\n"
report+="Date: "+today+"\n\n"

for r in rows:

    report+=f"""
{r['location']}

Estimated soil water: {r['storage']} mm
Forecast balance: {r['forecast']} mm

Stress level: {r['stress']}
"""

os.makedirs("reports",exist_ok=True)

with open(f"reports/{today}-report.md","w") as f:
    f.write(report)

if alerts:

    with open("alert.txt","w") as f:
        f.write(",".join(alerts))

print(report)
