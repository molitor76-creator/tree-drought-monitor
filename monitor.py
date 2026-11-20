
import os
import re
import json
import time
import requests
import pandas as pd

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
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

# Weather request settings.
MAX_ATTEMPTS = 4
RETRY_DELAYS = [15, 30, 60]
DELAY_BETWEEN_LOCATIONS = 5
REQUEST_TIMEOUT = 45


def cache_filename(name):
    """Create a separate weather cache file for each location."""
    safe_name = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"data/weather_cache_{safe_name}.json"


def parse_retry_after(response):
    """
    Read the Retry-After header if Open-Meteo provides one.
    Supports both seconds and HTTP date formats.
    """
    value = response.headers.get("Retry-After")

    if not value:
        return None

    try:
        return max(0, min(int(value), 180))
    except ValueError:
        pass

    try:
        retry_time = parsedate_to_datetime(value)

        if retry_time.tzinfo is None:
            retry_time = retry_time.replace(tzinfo=timezone.utc)

        seconds = (
            retry_time - datetime.now(timezone.utc)
        ).total_seconds()

        return max(0, min(int(seconds), 180))

    except Exception:
        return None


def convert_weather_response(data):
    """Convert the Open-Meteo response into a date-indexed dictionary."""
    daily = data["daily"]

    dates = daily["time"]
    rain_values = daily["precipitation_sum"]
    et0_values = daily["et0_fao_evapotranspiration"]

    if not (
        len(dates) == len(rain_values) == len(et0_values)
    ):
        raise ValueError("Weather API returned inconsistent daily arrays")

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


def save_weather_cache(cache_file, weather_data):
    """Save a successful weather response without risking a partial file."""
    cache = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "weather": weather_data
    }

    temporary_file = cache_file + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(cache, file)

    os.replace(temporary_file, cache_file)


def load_weather_cache(cache_file, required_start_date):
    """
    Use cached weather only if it covers every date needed to calculate
    storage from the previous history record through today.
    """
    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, "r", encoding="utf-8") as file:
            cache = json.load(file)

        weather_data = cache["weather"]
        fetched_at = cache.get("fetched_at", "unknown")

        if today_str not in weather_data:
            print("Cached weather does not contain today's date.")
            return None

        start_date = required_start_date

        if start_date is None:
            start_date = min(
                datetime.strptime(d, "%Y-%m-%d").date()
                for d in weather_data
            )

        current_date = start_date

        while current_date <= today:
            date_string = current_date.isoformat()

            if date_string not in weather_data:
                print(
                    f"Cached weather is missing {date_string}; "
                    "it cannot safely be used."
                )
                return None

            current_date += timedelta(days=1)

        print(
            "Using cached weather as a temporary fallback. "
            f"Last successful retrieval: {fetched_at}"
        )

        return weather_data

    except Exception as error:
        print(f"Could not read weather cache: {error}")
        return None


def get_weather(name, lat, lon, required_start_date):
    """
    Retrieve daily weather from Open-Meteo.

    Uses progressively longer retries for rate limits and temporary
    connection errors. Falls back to cached data only if the cache
    contains all dates required for the soil-water calculation.
    """
    cache_file = cache_filename(name)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
        "&daily=precipitation_sum,et0_fao_evapotranspiration"
        "&past_days=30"
        "&forecast_days=7"
        "&timezone=Europe%2FBerlin"
    )

    headers = {
        "User-Agent": "TreeIrrigationMonitor/1.0"
    }

    for attempt in range(MAX_ATTEMPTS):
        try:
            print(
                f"Requesting weather for {name} "
                f"(attempt {attempt + 1}/{MAX_ATTEMPTS})..."
            )

            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code == 429:
                retry_after = parse_retry_after(response)

                if retry_after is not None:
                    delay = retry_after
                else:
                    delay = RETRY_DELAYS[
                        min(attempt, len(RETRY_DELAYS) - 1)
                    ]

                print(
                    f"Open-Meteo rate limit reached for {name} "
                    f"(HTTP 429). Waiting {delay} seconds."
                )

                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(delay)

                continue

            response.raise_for_status()

            data = response.json()
            weather_data = convert_weather_response(data)

            save_weather_cache(cache_file, weather_data)

            print(f"Fresh weather data retrieved for {name}.")

            return weather_data

        except requests.exceptions.RequestException as error:
            print(
                f"Weather request attempt {attempt + 1} failed "
                f"for {name}: {error}"
            )

        except (ValueError, KeyError, TypeError) as error:
            print(
                f"Invalid weather response for {name}: {error}"
            )

        if attempt < MAX_ATTEMPTS - 1:
            delay = RETRY_DELAYS[
                min(attempt, len(RETRY_DELAYS) - 1)
            ]

            print(f"Retrying in {delay} seconds...")
            time.sleep(delay)

    print(
        f"Fresh weather retrieval failed for {name}. "
        "Checking the local weather cache."
    )

    cached_data = load_weather_cache(
        cache_file,
        required_start_date
    )

    if cached_data is not None:
        return cached_data

    raise RuntimeError(
        f"No usable fresh or cached weather data for {name}. "
        "Historical data has not been modified."
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

        old_data["storage"] = pd.to_numeric(
            old_data["storage"], errors="coerce"
        )

        old_data = old_data.dropna(
            subset=["date", "storage"]
        )

        old_data = old_data.sort_values("date")

        if not old_data.empty:
            last = old_data.iloc[-1]

            previous_date = last["date"]
            storage = float(last["storage"])

            if "stress_days" in old_data.columns:
                try:
                    value = last["stress_days"]
                    stress_days = (
                        0 if pd.isna(value) else int(value)
                    )
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

    storage = round(storage, 2)

    # Calculate the available forecast days.
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


def get_required_start_date(old_data):
    """
    Determine the earliest date needed from weather data.
    The model uses at most the 30-day historical API window when
    initialising a location without usable recent history.
    """
    earliest_available = today - timedelta(days=30)

    if old_data.empty:
        return earliest_available

    dates = pd.to_datetime(
        old_data["date"], errors="coerce"
    ).dropna()

    if dates.empty:
        return earliest_available

    last_date = dates.max().date()

    if last_date >= today:
        return today

    return max(last_date + timedelta(days=1), earliest_available)


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

    for index, (name, info) in enumerate(locations.items()):
        print(f"Processing {name}...")

        if not old.empty:
            location_history = old[
                old["location"] == name
            ].copy()
        else:
            location_history = pd.DataFrame()

        required_start_date = get_required_start_date(
            location_history
        )

        weather_data = get_weather(
            name,
            info["lat"],
            info["lon"],
            required_start_date
        )

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

        # Avoid sending requests for all three locations too rapidly.
        if index < len(locations) - 1:
            print(
                f"Waiting {DELAY_BETWEEN_LOCATIONS} seconds "
                "before the next location..."
            )
            time.sleep(DELAY_BETWEEN_LOCATIONS)

    # Only update history after all three locations have been processed.
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
