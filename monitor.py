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
    
    # Current day is index 30
    rain_today = data["daily"]["precipitation_sum"][30]
    evap_today = data["daily"]["et0_fao_evapotranspiration"][30]
    
    # Future 7 days
    rain_future = sum(data["daily"]["precipitation_sum"][31:38])
    evap_future = sum(data["daily"]["et0_fao_evapotranspiration"][31:38])
    
    return rain_today, evap_today, rain_future, evap_future

os.makedirs("data", exist_ok=True)
history = "data/history.csv"

# Load existing data to get the last storage value
previous = {}
if os.path.exists(history):
    try:
        df_old = pd.read_csv(history)
        for loc in locations.keys():
            # Get the last storage value for this location
            loc_data = df_old[df_old['location'] == loc]
            if not loc_data.empty:
                previous[loc] = loc_data.iloc[-1]["storage"]
    except Exception as e:
        print(f"Error reading history: {e}")

rows = []
for name, info in locations.items():
    rain, evap, rain_f, evap_f = weather(info["lat"], info["lon"])
    capacity = info["capacity"]
    
    # Use previous storage or default to 80%
    storage = previous.get(name, capacity * 0.8)
    storage = max(0, min(storage + rain - evap, capacity))
    
    future_storage = max(0, min(storage + rain_f - evap_f, capacity))
    
    target = capacity * 0.6
    irrigation = max(0, round(target - storage, 1))
    
    risk = "SAFE"
    if storage < capacity * 0.25:
        risk = "NOW"
    elif future_storage < capacity * 0.25:
        risk = "SOON"

    # We define the columns strictly here
    rows.append({
        "date": today,
        "location": name,
        "storage": round(storage, 2),
        "future_storage": round(future_storage, 2),
        "irrigation": irrigation,
        "risk": risk
    })

df_new = pd.DataFrame(rows)

# Combine and Clean
if os.path.exists(history):
    old = pd.read_csv(history)
    # Ensure columns match for the merge
    combined = pd.concat([old, df_new], ignore_index=True)
else:
    combined = df_new

# Drop duplicates so we don't have multiple entries for the same day
combined = combined.drop_duplicates(subset=["date", "location"], keep='last')

# Save with specific column order to keep the CSV clean
column_order = ["date", "location", "storage", "future_storage", "irrigation", "risk"]
combined[column_order].to_csv(history, index=False)

print(f"Update complete for {today}")
