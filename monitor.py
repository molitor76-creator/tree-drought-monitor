
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Use the local date in Germany, not the GitHub runner's UTC date.
today = datetime.now(ZoneInfo("Europe/Berlin")).date()
today_str = today.isoformat()

# These capacities are provisional assumptions, not measured soil values.
locations = {
    "Gauting": {
        "lat": 48.067,
        "lon": 11.377,
        "capacity": 100
    },
    "Waging am See": {
        "lat": 47.933,
        "lon": 12.733,
        "capacity": 70
    },
    "Dettenhausen": {
        "lat": 48.605,
        "lon": 9.106,
        "capacity": 180
    }
}

HISTORY_FILE = "data/history.csv"
TARGET_FRACTION = 0.60
CRITICAL_FRACTION = 0.25
LOW_FRACTION = 0.50

def get_weather(lat, lon):
    """
    Retrieve 30 days of historical daily weather and 7 forecast days.
    Values are indexed by calendar date to avoid relying on array positions.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&daily=precipitation_sum,et0_fao_evapotranspiration"
        "&past_days=30"
        "&forecast_days=7"
        "&timezone=Europe%2FBerlin"
    )

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            daily = data["daily"]
            dates = daily["time"]
            rain_values = daily["precipitation_sum"]
            et0_values = daily["et0_fao_evapotranspiration"]

            weather_by_date = {}

            for i, date_string in enumerate(dates):
                rain = rain_values[i]
                et0 = et0_values[i]

                if rain is None or et0 is None:
                    raise ValueError(
                        f"Missing weather value for {date_string}"
                    )

                weather_by_date[date_string] = {
                    "rain": float(rain),
                    "et0": float(et0)
                }

            if today_str not in weather_by_date:
                raise ValueError("Today's weather data is missing")

            return weather_by_date

        except Exception as error:
            print(
                f"Weather request attempt {attempt + 1} failed "
                f"for {lat}, {lon}: {error}"
            )
            time.sleep(2)

    raise RuntimeError(
        f"Could not retrieve weather data for {lat}, {lon}"
    )


def classify_severity(storage, capacity, stress_days):
    """
    Severity is a model indicator based on storage and duration below
    the critical storage threshold. It is not a measured tree-stress value.
    """
    ratio = storage / capacity

    if ratio < CRITICAL_FRACTION and stress_days >= 7:
        return "SEVERE"
    elif ratio < CRITICAL_FRACTION:
        return "HIGH"
    elif ratio < LOW_FRACTION:
        return "MODERATE"
    else:
        return "LOW"


def advance_storage(storage, rain, et0, capacity):
    """
    Simple soil-water reservoir:
    rainfall adds water; reference evapotranspiration removes water.
    Storage is limited to the assumed available-water capacity.
    """
    return max(0.0, min(storage + rain - et0, capacity))


def process_location(name, info, old_data, weather_data):
    capacity = info["capacity"]
    target = capacity * TARGET_FRACTION
    critical_level = capacity * CRITICAL_FRACTION

    # Find the most recent valid historical record for this location.
    previous_date = None
    storage = None
    stress_days = 0

    if not old_data.empty:
        old_data = old_data.copy()
        old_data["date"] = pd.to_datetime(
            old_data["date"], errors="coerce"
        ).dt.date
        old_data = old_data.dropna(subset=["date"])
        old_data = old_data.sort_values("date")

        if not old_data.empty:
            last = old_data.iloc[-1]
            previous_date = last["date"]
            storage = float(last["storage"])

            if "stress_days" in old_data.columns:
                try:
                    stress_days = int(last["stress_days"])
                except (TypeError, ValueError):
                    stress_days = 0

    weather_dates = sorted(
        datetime.strptime(d, "%Y-%m-%d").date()
        for d in weather_data.keys()
    )

    first_weather_date = weather_dates[0]

    # If there is no usable history, initialise at 80% capacity
    # at the beginning of the available weather period.
    if (
        previous_date is None
        or previous_date < first_weather_date
        or previous_date > today
    ):
        storage = capacity * 0.80
        stress_days = 0
        dates_to_process = [
            d for d in weather_dates if d <= today
        ]
    else:
        dates_to_process = [
            d for d in weather_dates
            if previous_date < d <= today
        ]

    # Process every day since the last saved record.
    for current_date in dates_to_process:
        day = weather_data[current_date.isoformat()]

        storage = advance_storage(
            storage,
            day["rain"],
            day["et0"],
            capacity
        )

        if storage < critical_level:
            stress_days += 1
        else:
            stress_days = 0

    # If this is a repeat run on the same day, storage is not
    # recalculated from today's weather a second time.
    storage = round(storage, 2)

    # Calculate the next seven days using the forecast.
    forecast_dates = [
        d for d in weather_dates if d > today
    ][:7]

    future_storage = storage

    for forecast_date in forecast_dates:
        day = weather_data[forecast_date.isoformat()]
        future_storage = advance_storage(
            future_storage,
            day["rain"],
            day["et0"],
            capacity
        )

    future_storage = round(future_storage, 2)

    # 1 mm of water = 1 litre per square metre.
    irrigation = max(0.0, round(target - storage, 1))

    # Preserve the existing risk categories for the dashboard map.
    if storage < critical_level:
        risk = "NOW"
    elif future_storage < critical_level:
        risk = "SOON"
    else:
        risk = "SAFE"

    severity = classify_severity(
        storage,
        capacity,
        stress_days
    )

    return {
        "date": today_str,
        "location": name,
        "storage": storage,
        "future_storage": future_storage,
        "irrigation": irrigation,
        "risk": risk,
        "severity": severity,
        "stress_days": stress_days
    }


def main():
    os.makedirs("data", exist_ok=True)

    # Read existing history.
    if os.path.exists(HISTORY_FILE):
        try:
            old = pd.read_csv(HISTORY_FILE)
        except Exception as error:
            raise RuntimeError(
                f"Could not read {HISTORY_FILE}: {error}"
            )
    else:
        old = pd.DataFrame()

    required_columns = [
        "date", "location", "storage"
    ]

    if not old.empty:
        missing = [
            column for column in required_columns
            if column not in old.columns
        ]
        if missing:
            raise RuntimeError(
                "Existing history.csv is missing columns: "
                + ", ".join(missing)
            )

    new_rows = []

    for name, info in locations.items():
        print(f"Processing {name}...")

        weather_data = get_weather(
            info["lat"],
            info["lon"]
        )

        if not old.empty:
            location_history = old[
                old["location"] == name
            ].copy()
        else:
            location_history = pd.DataFrame()

        result = process_location(
            name,
            info,
            location_history,
            weather_data
        )

        new_rows.append(result)

        print(
            f"{name}: storage={result['storage']} mm, "
            f"irrigation={result['irrigation']} L/m², "
            f"risk={result['risk']}, "
            f"severity={result['severity']}"
        )

    new_data = pd.DataFrame(new_rows)

    if old.empty:
        combined = new_data
    else:
        combined = pd.concat(
            [old, new_data],
            ignore_index=True
        )

    # Keep one record per date and location.
    combined["date"] = pd.to_datetime(
        combined["date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    combined = combined.dropna(
        subset=["date", "location"]
    )

    combined = combined.drop_duplicates(
        subset=["date", "location"],
        keep="last"
    )

    columns = [
        "date",
        "location",
        "storage",
        "future_storage",
        "irrigation",
        "risk",
        "severity",
        "stress_days"
    ]

    combined = combined.reindex(columns=columns)
    combined = combined.sort_values(
        ["date", "location"]
    )

    combined.to_csv(HISTORY_FILE, index=False)

    print(
        f"Monitor update successful for {today_str}"
    )


if __name__ == "__main__":
    main()
