"""ESPN unofficial API fetcher for current PGA Tour event/field data and player stats.

No API key required. Endpoints are undocumented and may change.
All functions return empty/default data on failure — they never raise.
"""
import re
import unicodedata
from datetime import date, timedelta
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


# ── Name normalisation (mirrors model._norm_name) ────────────────────────────

def _norm_name(name: str) -> str:
    if not name:
        return ""
    nfd = unicodedata.normalize("NFD", name)
    ascii_name = nfd.encode("ascii", "ignore").decode("ascii")
    lower = ascii_name.lower()
    clean = re.sub(r"[^a-z\s]", "", lower).strip()
    return re.sub(r"\s+", " ", clean)


# ── Recent event scoring (last N completed events) ───────────────────────────

def get_recent_event_scoring(num_events: int = 3) -> dict:
    """Return per-player scoring averages from the last N completed PGA events.

    Steps back in 7-day increments from last week, collecting completed events.
    Returns:
        {
          "rory mcilroy": 69.0,   # avg strokes/round across last N events
          ...
        }
    Returns empty dict on total failure. Never raises.
    """
    try:
        seen_event_ids: set = set()
        # {norm_name: [round_stroke_values]}
        strokes_by_player: dict[str, list[float]] = {}

        start_date = date.today() - timedelta(days=7)  # start from last week

        for week_offset in range(10):  # max 10 weeks back to avoid infinite loop
            if len(seen_event_ids) >= num_events:
                break

            check_date = start_date - timedelta(weeks=week_offset)
            date_str = check_date.strftime("%Y%m%d")

            try:
                resp = requests.get(
                    _SCOREBOARD_URL,
                    params={"dates": date_str},
                    timeout=_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"[espn] get_recent_event_scoring: fetch failed for {date_str}: {exc}")
                continue

            events = data.get("events") or []
            for event in events:
                event_id = str(event.get("id") or "")
                if not event_id or event_id in seen_event_ids:
                    continue

                # Only process completed events
                status_name = (
                    event.get("status", {}).get("type", {}).get("name", "")
                )
                if status_name != "STATUS_FINAL":
                    continue

                # Only PGA Tour events (not opposite-field or Korn Ferry)
                tour = event.get("tour", {})
                if isinstance(tour, dict):
                    tour_slug = tour.get("slug", "") or ""
                    if tour_slug and "pga" not in tour_slug.lower():
                        continue

                seen_event_ids.add(event_id)
                if len(seen_event_ids) > num_events:
                    break

                competitors = (
                    event.get("competitions") or [{}]
                )[0].get("competitors") or []

                for c in competitors:
                    athlete = c.get("athlete") or {}
                    player_name = (
                        athlete.get("displayName")
                        or athlete.get("fullName")
                        or ""
                    )
                    if not player_name:
                        continue

                    norm = _norm_name(player_name)

                    # Sum per-round strokes from linescores
                    # Filter: period 1-4 (not playoff) and value > 50 (valid round)
                    round_strokes = [
                        ls["value"]
                        for ls in (c.get("linescores") or [])
                        if ls.get("period", 0) in (1, 2, 3, 4)
                        and ls.get("value", 0) > 50
                    ]
                    if not round_strokes:
                        continue

                    strokes_by_player.setdefault(norm, []).extend(round_strokes)

        # Convert accumulated strokes to per-round averages
        result: dict[str, float] = {}
        for norm, strokes in strokes_by_player.items():
            if strokes:
                result[norm] = sum(strokes) / len(strokes)

        print(f"[espn] get_recent_event_scoring: {len(seen_event_ids)} events, {len(result)} players")
        return result

    except Exception as exc:
        print(f"[espn] get_recent_event_scoring: unexpected error: {exc}")
        return {}


# ── Last year's top finishers at the same tournament ─────────────────────────

def get_last_year_top_finishers(event_name: str, start_date_str: str, top_n: int = 10) -> list:
    """Find the same tournament from ~1 year ago and return its top N finishers.

    Searches ±7 days of (start_date - 364 days) for an event whose name
    fuzzy-matches the current tournament name.

    Returns:
        [
          {"player_name": "Rory McIlroy", "finish_position": 1},
          ...
        ]
    Returns empty list if the event can't be found or matched. Never raises.
    """
    try:
        if not start_date_str:
            print("[espn] get_last_year_top_finishers: no start_date provided")
            return []

        # Parse start date
        try:
            from datetime import datetime
            start_dt = datetime.strptime(start_date_str[:10], "%Y-%m-%d").date()
        except Exception:
            print(f"[espn] get_last_year_top_finishers: bad start_date: {start_date_str}")
            return []

        target_date = start_dt - timedelta(days=364)

        # Normalise event name for fuzzy matching: keep significant words only
        def _sig_words(name: str) -> set:
            stop = {"the", "a", "an", "in", "at", "by", "pres", "presented", "presented by"}
            return {
                w.lower()
                for w in re.findall(r"[a-zA-Z]+", name)
                if w.lower() not in stop and len(w) > 2
            }

        current_words = _sig_words(event_name)
        if not current_words:
            print("[espn] get_last_year_top_finishers: no significant words in event name")
            return []

        # Search ±7 days around target date
        best_event = None
        best_overlap = 0

        for day_offset in [0, -7, 7, -14, 14]:
            check_date = target_date + timedelta(days=day_offset)
            date_str = check_date.strftime("%Y%m%d")

            try:
                resp = requests.get(
                    _SCOREBOARD_URL,
                    params={"dates": date_str},
                    timeout=_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"[espn] get_last_year_top_finishers: fetch failed for {date_str}: {exc}")
                continue

            for event in data.get("events") or []:
                status_name = (
                    event.get("status", {}).get("type", {}).get("name", "")
                )
                if status_name != "STATUS_FINAL":
                    continue

                candidate_name = event.get("name") or ""
                overlap = len(current_words & _sig_words(candidate_name))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_event = event

            if best_overlap >= max(2, len(current_words) // 2):
                break  # good enough match found

        if best_event is None or best_overlap < 2:
            print(f"[espn] get_last_year_top_finishers: no match found for '{event_name}' (best overlap={best_overlap})")
            return []

        print(f"[espn] get_last_year_top_finishers: matched '{best_event.get('name')}' (overlap={best_overlap})")

        competitors = (
            best_event.get("competitions") or [{}]
        )[0].get("competitors") or []

        # Sort by finish order (1 = winner) and return top N
        sorted_comps = sorted(competitors, key=lambda c: c.get("order", 9999))
        result = []
        for c in sorted_comps[:top_n]:
            athlete = c.get("athlete") or {}
            player_name = (
                athlete.get("displayName")
                or athlete.get("fullName")
                or ""
            )
            if not player_name:
                continue
            result.append({
                "player_name": player_name,
                "finish_position": c.get("order", len(result) + 1),
            })

        print(f"[espn] get_last_year_top_finishers: {len(result)} finishers found")
        return result

    except Exception as exc:
        print(f"[espn] get_last_year_top_finishers: unexpected error: {exc}")
        return []


# ── Finish positions for a completed past event ───────────────────────────────

def get_event_results(espn_event_id: str, week_label_str: str) -> dict:
    """Fetch finish positions for a completed past ESPN event.

    Args:
        espn_event_id: Raw ESPN event ID (e.g. "401811935"), WITHOUT the "espn_" prefix.
        week_label_str: The week's start date (YYYY-MM-DD) stored in weekly_results.

    Returns:
        {norm_player_name: finish_position (int)} for all competitors found.
        Returns {} on any failure. Never raises.
    """
    try:
        from datetime import datetime

        # Convert week_label to YYYYMMDD for the ESPN dates param
        try:
            dt = datetime.strptime(week_label_str[:10], "%Y-%m-%d")
            date_str = dt.strftime("%Y%m%d")
        except Exception:
            date_str = None

        # Try the exact week date first, then ±7 days as fallback
        offsets_to_try = [0, 7, -7, 14, -14] if date_str else []
        found_event = None

        for offset in offsets_to_try:
            check_date = datetime.strptime(date_str, "%Y%m%d") + timedelta(days=offset)
            fetch_date = check_date.strftime("%Y%m%d")

            try:
                resp = requests.get(
                    _SCOREBOARD_URL,
                    params={"dates": fetch_date},
                    timeout=_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"[espn] get_event_results: fetch failed for {fetch_date}: {exc}")
                continue

            for event in data.get("events") or []:
                if str(event.get("id") or "") == espn_event_id:
                    found_event = event
                    break

            if found_event:
                break

        if not found_event:
            print(f"[espn] get_event_results: event {espn_event_id} not found near {week_label_str}")
            return {}

        # Extract competitors and their finish positions
        competitors = (
            found_event.get("competitions") or [{}]
        )[0].get("competitors") or []

        results: dict[str, int] = {}
        for c in competitors:
            athlete = c.get("athlete") or {}
            player_name = (
                athlete.get("displayName")
                or athlete.get("fullName")
                or ""
            )
            if not player_name:
                continue

            finish = c.get("order")
            if finish is None:
                continue

            try:
                finish_int = int(finish)
            except (TypeError, ValueError):
                continue

            norm = _norm_name(player_name)
            results[norm] = finish_int

        print(f"[espn] get_event_results: event {espn_event_id}: {len(results)} player results")
        return results

    except Exception as exc:
        print(f"[espn] get_event_results: unexpected error: {exc}")
        return {}
