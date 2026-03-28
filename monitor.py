import requests
import os
import pandas as pd
from datetime import date

today = str(date.today())

locations = {
    "Gauting": {"lat": 48.067, "lon": 11.377, "capacity": 100},
    "Waging am See": {"lat": 47.933, "lon": 12.733, "capacity": 70},
    "Dettenhausen": {"lat": 48.605, "lon": 9.106, "capacity": 180}
}

def weather(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,et0_fao_evapotranspiration&past_days=30&forecast_days=7&timezone=Europe%2FBerlin"
    data = requests.get(url).json()
    
    # Today's weather (Index 30)
    rain_today = data["daily"]["precipitation_sum"][30]
    evap_today = data["daily"]["et0_fao_evapotranspiration"][30]
    
    # Future 7 days (Indices 31 to 37)
    rain_future = sum(data["daily"]["precipitation_sum"][31:38])
    evap_future = sum(data["daily"]["et0_fao_evapotranspiration"][31:38])
    
    return rain_today, evap_today, rain_future, evap_future

os.makedirs("data", exist_ok=True)
history = "data/history.csv"
previous = {}

if os.path.exists(history):
    df = pd.read_csv(history)
    for loc in df["location"].unique():
        previous[loc] = df[df.location == loc].iloc[-1]["storage"]

rows = []
alerts = []

for name, info in locations.items():
    rain, evap, rain_f, evap_f = weather(info["lat"], info["lon"])
    capacity = info["capacity"]
    
    # Determine current soil moisture
    storage = previous.get(name, capacity * 0.8)
    storage = max(0, min(storage + rain - evap, capacity))
    
    # Forecasted soil moisture
    future_storage = max(0, min(storage + rain_f - evap_f, capacity))
    
    # Recommended irrigation to reach 60% capacity
    target = capacity * 0.6
    irrigation = max(0, round(target - storage, 1))
    
    risk = "SAFE"
    if storage < capacity * 0.25:
        risk = "NOW"
        alerts.append(name)
    elif future_storage < capacity * 0.25:
        risk = "SOON"

    rows.append({
        "date": today,
        "location": name,
        "storage": round(storage, 2),
        "future_storage": round(future_storage, 2),
        "irrigation": irrigation,
        "risk": risk
    })

df_new = pd.DataFrame(rows)
if os.path.exists(history):
    old = pd.read_csv(history)
    df_new = pd.concat([old, df_new])

df_new = df_new.drop_duplicates(subset=["date", "location"])
df_new.to_csv(history, index=False)

# MD Report
report = f"# Tree Irrigation Report: {today}\n\n"
for r in rows:
    report += f"### {r['location']}\n* Soil Water: {r['storage']} mm\n* Forecast: {r['future_storage']} mm\n* Risk Level: **{r['risk']}**\n\n"

os.makedirs("reports", exist_ok=True)
with open(f"reports/{today}-report.md", "w") as f:
    f.write(report)

if alerts:
    with open("alert.txt", "w") as f:
        f.write(",".join(alerts))
