import requests
import os
import pandas as pd
from datetime import date

today=str(date.today())

locations={
"Gauting":{"lat":48.067,"lon":11.377,"capacity":100},
"Waging am See":{"lat":47.933,"lon":12.733,"capacity":70},
"Dettenhausen":{"lat":48.605,"lon":9.106,"capacity":180}
}

def weather(lat,lon):

    url=f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,et0_fao_evapotranspiration&past_days=1&timezone=Europe%2FBerlin"

    data=requests.get(url).json()

    rain=data["daily"]["precipitation_sum"][0]
    evap=data["daily"]["et0_fao_evapotranspiration"][0]

    return rain,evap


def stress(storage,capacity):

    r=storage/capacity

    if r>0.7:
        return "LOW"
    elif r>0.4:
        return "MODERATE"
    elif r>0.25:
        return "HIGH"
    else:
        return "SEVERE"


os.makedirs("data",exist_ok=True)

history="data/history.csv"

previous={}

if os.path.exists(history):

    df=pd.read_csv(history)

    for loc in df["location"].unique():

        previous[loc]=df[df.location==loc].iloc[-1]["storage"]


rows=[]
alerts=[]

for name,info in locations.items():

    rain,evap=weather(info["lat"],info["lon"])

    capacity=info["capacity"]

    storage=previous.get(name,capacity*0.8)

    storage=storage+rain-evap

    storage=max(0,min(storage,capacity))

    level=stress(storage,capacity)

    target=capacity*0.6
    irrigation=max(0,round(target-storage,1))

    if storage<capacity*0.25:

        alerts.append(name)

    rows.append({
    "date":today,
    "location":name,
    "storage":round(storage,2),
    "rain":round(rain,2),
    "evap":round(evap,2),
    "stress":level,
    "irrigation":irrigation
    })


df_new=pd.DataFrame(rows)

if os.path.exists(history):

    old=pd.read_csv(history)
    df_new=pd.concat([old,df_new])

df_new=df_new.drop_duplicates(subset=["date","location"])

df_new.to_csv(history,index=False)


report="Tree Irrigation Monitor\n\n"

for r in rows:

    report+=f"""
{r['location']}

Soil water: {r['storage']} mm
Rain: {r['rain']} mm
Evapotranspiration: {r['evap']} mm

Stress level: {r['stress']}

Recommended irrigation: {r['irrigation']} mm
"""

os.makedirs("reports",exist_ok=True)

with open(f"reports/{today}-report.md","w") as f:

    f.write(report)

if alerts:

    with open("alert.txt","w") as f:

        f.write(",".join(alerts))

print(report)
