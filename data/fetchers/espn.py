"""ESPN unofficial API fetcher for current PGA Tour event/field data and player stats.

No API key required. Endpoints are undocumented and may change.
All functions return empty/default data on failure — they never raise.
"""
import requests

_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
_STATS_URL = "https://site.web.api.espn.com/apis/common/v3/sports/golf/pga/statistics/byathlete"
_TIMEOUT = 15

_EMPTY_FIELD = {
    "event_id": "",
    "event_name": "",
    "course_name": "",
    "location": "",
    "tour": "pga",
    "start_date": "",
    "end_date": "",
    "players": [],
}


def _safe_date(raw: str) -> str:
    """Extract YYYY-MM-DD from any date-ish string. Returns '' on failure."""
    if not raw:
        return ""
    try:
        return str(raw)[:10]
    except Exception:
        return ""


def _to_float(val) -> float | None:
    """Convert a display value to float. Strips %, commas. Returns None on failure."""
    if val is None:
        return None
    s = str(val).replace("%", "").replace(",", "").strip()
    if not s or s == "--":
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def get_field() -> dict:
    """Fetch current PGA Tour tournament field from ESPN's unofficial scoreboard API.

    Returns:
        {
            "event_id": "espn_12345",
            "event_name": "The Masters",
            "course_name": "Augusta National Golf Club",
            "location": "Augusta, GA",
            "tour": "pga",
            "start_date": "2026-04-09",
            "end_date": "2026-04-12",
            "players": [
                {"dg_id": 12345, "player_name": "Scottie Scheffler", "country": "USA"},
                ...
            ]
        }

    Returns the empty/default dict on any failure. Never raises.
    The player id is taken from competitor["id"] at the top level (NOT competitor["athlete"]["id"]).
    """
    try:
        resp = requests.get(_SCOREBOARD_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[espn] get_field: HTTP request failed: {exc}")
        return dict(_EMPTY_FIELD)

    try:
        events = data.get("events") or []
        if not events:
            print("[espn] get_field: no events in ESPN scoreboard response")
            return dict(_EMPTY_FIELD)

        event = events[0]
        event_name = event.get("name") or event.get("shortName") or ""

        # ESPN event id — prefix with "espn_"
        raw_event_id = str(event.get("id") or "")
        event_id = f"espn_{raw_event_id}" if raw_event_id else ""

        # Competition block
        competitions = event.get("competitions") or []
        comp = competitions[0] if competitions else {}

        # Venue / location
        venue = comp.get("venue") or {}
        course_name = venue.get("fullName") or venue.get("name") or ""
        address = venue.get("address") or {}
        city = address.get("city") or ""
        state = address.get("state") or address.get("country") or ""
        if city and state:
            location = f"{city}, {state}"
        elif city:
            location = city
        else:
            location = ""

        # Dates — prefer event.date / event.endDate per spec
        raw_start = event.get("date") or comp.get("startDate") or ""
        start_date = _safe_date(raw_start)

        raw_end = event.get("endDate") or comp.get("endDate") or ""
        if raw_end:
            end_date = _safe_date(raw_end)
        elif start_date:
            # Default: tournament is 4 days (Thu-Sun), end = start + 3
            try:
                from datetime import datetime, timedelta
                end_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=3)
                end_date = end_dt.strftime("%Y-%m-%d")
            except Exception:
                end_date = ""
        else:
            end_date = ""

        # Players / competitors
        competitors = comp.get("competitors") or []
        if not competitors:
            print("[espn] get_field: competitors list is empty — field not yet posted")

        players = []
        for c in competitors:
            athlete = c.get("athlete") or {}

            # Player id — IMPORTANT: use competitor["id"] at TOP LEVEL, not athlete["id"]
            raw_pid = c.get("id") or ""
            try:
                pid = int(raw_pid)
            except (TypeError, ValueError):
                pid = None

            # Name
            player_name = (
                athlete.get("displayName")
                or athlete.get("fullName")
                or athlete.get("shortName")
                or ""
            )

            if not player_name:
                continue  # skip rows with no usable name

            # Country — nested under athlete.flag.alt
            flag = athlete.get("flag") or {}
            country = (
                flag.get("alt")
                or flag.get("description")
                or athlete.get("country")
                or c.get("country")
                or ""
            )

            players.append({
                "dg_id": pid,
                "player_name": player_name,
                "country": country,
            })

        return {
            "event_id": event_id,
            "event_name": event_name,
            "course_name": course_name,
            "location": location,
            "tour": "pga",
            "start_date": start_date,
            "end_date": end_date,
            "players": players,
        }

    except Exception as exc:
        print(f"[espn] get_field: parse error: {exc}")
        return dict(_EMPTY_FIELD)


def get_stats() -> list[dict]:
    """Fetch player stats from ESPN's byathlete statistics API.

    Returns a list of dicts, one per athlete:
        {
            "athlete_id": 205,          # int (ESPN athlete id)
            "player_name": "Charley Hoffman",
            "scoring_avg": 70.3,        # AVG — lower is better
            "gir_pct": 68.5,            # GIRPCT — greens in regulation %
            "driving_dist": 295.4,      # YDS/DRV — driving distance yards
            "driving_acc": 62.1,        # DRV ACC — driving accuracy %
            "putts_per_hole": 1.72,     # STROKESPERHOLE — putts per hole
            "birdies_per_round": 3.8,   # BIRD/RND — birdies per round
        }

    Returns empty list on any failure. Never raises.
    Stats with displayValue "--" or "" are skipped (stored as None).
    """
    try:
        resp = requests.get(_STATS_URL, params={"limit": "300"}, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[espn] get_stats: HTTP request failed: {exc}")
        return []

    try:
        athletes_raw = data.get("athletes") or []
        if not athletes_raw:
            print("[espn] get_stats: no athletes in ESPN stats response")
            return []

        # Build label→index map from top-level categories definition
        label_to_idx: dict[str, int] = {}
        top_cats = data.get("categories") or []
        for cat_def in top_cats:
            for idx, label in enumerate(cat_def.get("labels") or []):
                label_to_idx[label] = idx

        # Mapping from ESPN label → our field name
        stat_label_map = {
            "AVG": "scoring_avg",
            "GIRPCT": "gir_pct",
            "YDS/DRV": "driving_dist",
            "DRV ACC": "driving_acc",
            "STROKESPERHOLE": "putts_per_hole",
            "BIRD/RND": "birdies_per_round",
        }

        results = []
        for entry in athletes_raw:
            athlete_info = entry.get("athlete") or {}

            # athlete_id comes from athlete["id"] in stats API
            raw_id = athlete_info.get("id") or ""
            try:
                athlete_id = int(raw_id)
            except (TypeError, ValueError):
                athlete_id = None

            player_name = (
                athlete_info.get("displayName")
                or athlete_info.get("fullName")
                or ""
            )

            if not player_name and athlete_id is None:
                continue

            # Parse stats from athlete's category values (indexed by label_to_idx)
            stat_values: dict[str, float | None] = {v: None for v in stat_label_map.values()}

            categories = entry.get("categories") or []
            for cat in categories:
                values = cat.get("values") or []
                for label, field_key in stat_label_map.items():
                    idx = label_to_idx.get(label)
                    if idx is None or idx >= len(values):
                        continue
                    val = values[idx]
                    if val is None or val == 0.0:
                        continue
                    stat_values[field_key] = float(val)

            results.append({
                "athlete_id": athlete_id,
                "player_name": player_name,
                "scoring_avg": stat_values["scoring_avg"],
                "gir_pct": stat_values["gir_pct"],
                "driving_dist": stat_values["driving_dist"],
                "driving_acc": stat_values["driving_acc"],
                "putts_per_hole": stat_values["putts_per_hole"],
                "birdies_per_round": stat_values["birdies_per_round"],
            })

        return results

    except Exception as exc:
        print(f"[espn] get_stats: parse error: {exc}")
        return []
