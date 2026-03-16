import requests
import os
import pandas as pd
from datetime import date

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
        advice="No watering needed"
    elif score>10:
        level="MODERATE"
        advice="Monitor soil moisture"
    elif score>-10:
        level="HIGH"
        advice="Water trees if soil dry"
    else:
        level="SEVERE"
        advice="Water trees deeply"

    return storage,forecast,level,advice


data=[]

for name,coords in locations.items():

    rh,eh,rf,ef=weather_data(coords["lat"],coords["lon"])

    storage,forecast,level,advice=tree_stress(rh,eh,rf,ef)

    data.append({
        "location":name,
        "storage":storage,
        "forecast":forecast,
        "stress":level
    })

report=f"Weekly Tree Drought Monitor\nDate: {date.today()}\n\n"

for d in data:

    report+=f"""
{d['location']}

Water storage estimate: {d['storage']:.1f}
Forecast balance: {d['forecast']:.1f}

Stress level: {d['stress']}
"""


os.makedirs("reports",exist_ok=True)

filename=f"reports/{date.today()}-report.md"

with open(filename,"w") as f:
    f.write(report)

df=pd.DataFrame(data)

os.makedirs("data",exist_ok=True)

csv_file="data/history.csv"

if os.path.exists(csv_file):

    old=pd.read_csv(csv_file)
    df=pd.concat([old,df])

df.to_csv(csv_file,index=False)

print(report)
