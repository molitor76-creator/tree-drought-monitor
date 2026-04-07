import requests
import os
import pandas as pd
from datetime import date
import time

today = str(date.today())

locations = {
    "Gauting": {"lat": 48.067, "lon": 11.377, "capacity": 100},
    "Waging am See": {"lat": 47.933, "lon": 12.733, "capacity": 70},
    "Dettenhausen": {"lat": 48.605, "lon": 9.106, "capacity": 180}
}

def weather(lat, lon):
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,et0_fao_evapotranspiration&past_days=30&forecast_days=7&timezone=Europe%2FBerlin"
    
    # Try the request up to 3 times in case the API is busy
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                # Extract values with fallback to 0 if index is missing
                rain_today = data["daily"]["precipitation_sum"][30]
                evap_today = data["daily"]["et0_fao_evapotranspiration"][30]
                rain_future = sum(data["daily"]["precipitation_sum"][31:38])
                evap_future = sum(data["daily"]["et0_fao_evapotranspiration"][31:38])
                
                return rain_today, evap_today, rain_future, evap_future
            else:
                print(f"API returned status {response.status_code}. Retrying...")
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
        
        time.sleep(2) # Wait 2 seconds before retrying
    
    print(f"Failed to fetch weather for {lat}, {lon}. Using 0 for today.")
    return 0, 0, 0, 0

os.makedirs("data", exist_ok=True)
history = "data/history.csv"
previous = {}

# Load existing storage values
if os.path.exists(history):
    try:
        df_old = pd.read_csv(history)
        for loc in locations.keys():
            loc_data = df_old[df_old['location'] == loc]
            if not loc_data.empty:
                previous[loc] = loc_data.iloc[-1]["storage"]
    except:
        pass

rows = []
for name, info in locations.items():
    rain, evap, rain_f, evap_f = weather(info["lat"], info["lon"])
    capacity = info["capacity"]
    
    # Logic-first validation: Default to 80% if brand new
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

    rows.append({
        "date": today,
        "location": name,
        "storage": round(storage, 2),
        "future_storage": round(future_storage, 2),
        "irrigation": irrigation,
        "risk": risk
    })

# Standardize and Save
df_new = pd.DataFrame(rows)
if os.path.exists(history):
    try:
        old = pd.read_csv(history)
        combined = pd.concat([old, df_new], ignore_index=True)
    except:
        combined = df_new
else:
    combined = df_new

if not combined.empty:
    # Ensure correct columns and remove duplicates
    combined = combined.drop_duplicates(subset=["date", "location"], keep='last')
    cols = ["date", "location", "storage", "future_storage", "irrigation", "risk"]
    combined[cols].to_csv(history, index=False)

print(f"Monitor update successful for {today}")
