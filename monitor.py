import requests
import os
import pandas as pd
from datetime import date

today=str(date.today())

locations = {
    "Gauting": {"lat":48.067,"lon":11.377},
    "Waging am See": {"lat":47.933,"lon":12.733},
    "Dettenhausen": {"lat":48.605,"lon":9.106}
}


def weather_data(lat,lon):

    url=f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,et0_fao_evapotranspiration&past_days=30&timezone=Europe%2FBerlin"

    data=requests.get(url).json()

    rain_history=sum(data["daily"]["precipitation_sum"][:30])
    evap_history=sum(data["daily"]["et0_fao_evapotranspiration"][:30])

    rain_forecast=sum(data["daily"]["precipitation_sum"][30:37])
    evap_forecast=sum(data["daily"]["et0_fao_evapotranspiration"][30:37])

    return rain_history,evap_history,rain_forecast,evap_forecast


def tree_stress(rh,eh,rf,ef):

    storage=rh-eh
    forecast=rf-ef
    score=storage+forecast

    if score>40:
        level="LOW"
    elif score>10:
        level="MODERATE"
    elif score>-10:
        level="HIGH"
    else:
        level="SEVERE"

    return storage,forecast,level


rows=[]
alerts=[]

for name,coords in locations.items():

    rh,eh,rf,ef=weather_data(coords["lat"],coords["lon"])
    storage,forecast,level=tree_stress(rh,eh,rf,ef)

    if level=="SEVERE":
        alerts.append(name)

    rows.append({
        "date":today,
        "location":name,
        "storage":storage,
        "forecast":forecast,
        "stress":level
    })


df=pd.DataFrame(rows)

os.makedirs("data",exist_ok=True)
history_file="data/history.csv"

if os.path.exists(history_file):

    old=pd.read_csv(history_file)
    df=pd.concat([old,df])

df=df.drop_duplicates(subset=["date","location"])

df.to_csv(history_file,index=False)


report=f"Weekly Tree Drought Monitor\nDate: {today}\n\n"

for r in rows:

    report+=f"""
{r['location']}

Storage estimate: {r['storage']:.1f}
Forecast balance: {r['forecast']:.1f}

Stress level: {r['stress']}
"""

os.makedirs("reports",exist_ok=True)

with open(f"reports/{today}-report.md","w") as f:
    f.write(report)


if alerts:

    with open("alert.txt","w") as f:
        f.write(",".join(alerts))


print(report)
