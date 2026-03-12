"""wttr.in weather fetcher — no API key required."""
import requests
from urllib.parse import quote

_TIMEOUT = 15


def get_forecast(location: str) -> list:
    """Fetch 4-day weather forecast for the given location string.

    Each returned dict:
        {forecast_date, avg_temp_f, high_f, low_f,
         wind_mph, precip_chance, description}
    Returns empty list on any failure.
    """
    if not location or not location.strip():
        print("[weather] No location provided — skipping weather fetch")
        return []

    try:
        encoded = quote(location.strip())
        url = f"https://wttr.in/{encoded}?format=j1"
        resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "golf-model/1.0"})
        resp.raise_for_status()
        data = resp.json()

        weather_days = data.get("weather") or []
        results = []

        for day in weather_days[:4]:
            date_str = day.get("date") or ""
            min_f = _safe_int(day.get("mintempF"))
            max_f = _safe_int(day.get("maxtempF"))
            avg_f = _safe_int(day.get("avgtempF"))

            hourly = day.get("hourly") or []

            # Wind: take max wind speed across hours
            wind_speeds = [_safe_int(h.get("windspeedMiles")) for h in hourly if h.get("windspeedMiles") is not None]
            wind_mph = max(wind_speeds) if wind_speeds else 0

            # Precip: average chance of rain across hours
            precip_values = [_safe_int(h.get("chanceofrain")) for h in hourly if h.get("chanceofrain") is not None]
            precip_chance = int(sum(precip_values) / len(precip_values)) if precip_values else 0

            # Description from first weatherDesc entry
            desc_list = day.get("weatherDesc") or []
            description = desc_list[0].get("value", "") if desc_list else ""

            results.append({
                "forecast_date": date_str,
                "avg_temp_f": avg_f,
                "high_f": max_f,
                "low_f": min_f,
                "wind_mph": wind_mph,
                "precip_chance": precip_chance,
                "description": description,
            })

        return results

    except Exception as exc:
        print(f"[weather] get_forecast failed for '{location}': {exc}")
        return []


def _safe_int(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0
