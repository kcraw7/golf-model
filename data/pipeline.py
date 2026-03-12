"""Orchestration: refresh pipeline and dashboard data assembly."""
from datetime import datetime, timezone
from typing import Optional

from data.fetchers.espn import get_field, get_stats
from data.fetchers.pgatour import get_decompositions
from data.fetchers import odds as odds_fetcher, weather as weather_fetcher
from data import model
from db import queries, schema


def run_refresh(db_path: str) -> dict:
    """Run a full data refresh and persist to the database.

    Returns:
        {status, warnings, refreshed_at}
    """
    warnings: list[str] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Ensure tables exist
    schema.init_db(db_path)

    # ── Step 1: Fetch field (ESPN) and SG stats (PGA Tour) ──────────────────
    try:
        field = get_field()
    except Exception as exc:
        warnings.append(f"ESPN field fetch failed: {exc}")
        field = {"event_id": "", "event_name": "", "course_name": "", "location": "",
                 "tour": "pga", "start_date": "", "end_date": "", "players": []}

    # Pre-built DataGolf preds no longer used — model builds probs from SG stats
    preds: list = []

    try:
        skills = get_stats()
    except Exception as exc:
        warnings.append(f"ESPN stats fetch failed: {exc}")
        skills = []

    try:
        decomps = get_decompositions()
    except Exception as exc:
        warnings.append(f"PGA Tour decompositions fetch failed: {exc}")
        decomps = []

    # ── Step 2: Odds ────────────────────────────────────────────────────────
    try:
        odds_data = odds_fetcher.get_golf_odds()
    except Exception as exc:
        warnings.append(f"Odds API fetch failed: {exc}")
        odds_data = {}

    # ── Step 3: Weather ─────────────────────────────────────────────────────
    location = field.get("location") or ""
    try:
        forecast = weather_fetcher.get_forecast(location)
    except Exception as exc:
        warnings.append(f"Weather fetch failed: {exc}")
        forecast = []

    # ── Step 4: Score ───────────────────────────────────────────────────────
    scored_players = model.merge_and_score(field, preds, skills, decomps, odds_data)

    # ── Step 5: Persist ─────────────────────────────────────────────────────
    event_id = field.get("event_id") or "unknown"
    status = "ok" if not warnings else "partial"

    with queries.get_connection(db_path) as conn:
        try:
            tournament_row = {
                "event_id": event_id,
                "event_name": field.get("event_name") or "",
                "course_name": field.get("course_name") or "",
                "location": location,
                "tour": field.get("tour") or "pga",
                "start_date": field.get("start_date") or "",
                "end_date": field.get("end_date") or "",
                "fetched_at": now_iso,
            }
            queries.replace_tournament(conn, tournament_row)
            queries.replace_players(conn, scored_players, event_id, now_iso)
            queries.replace_weather(conn, forecast, event_id, now_iso)

            # ── Step 6: Snapshot picks ──────────────────────────────────────
            queries.snapshot_weekly_picks(conn, scored_players, field)

            # ── Step 7: Log ─────────────────────────────────────────────────
            queries.log_refresh(conn, status, warnings, odds_fetcher.CREDITS_REMAINING)

            conn.commit()
        except Exception as exc:
            warnings.append(f"Database write failed: {exc}")
            status = "error"

    return {
        "status": status,
        "warnings": warnings,
        "refreshed_at": now_iso,
    }


def get_dashboard_data(db_path: str) -> dict:
    """Read current state from DB and return as dashboard payload."""
    schema.init_db(db_path)

    with queries.get_connection(db_path) as conn:
        tournament = queries.get_current_tournament(conn)
        players = queries.get_current_players(conn)
        last_refresh = queries.get_last_refresh(conn)

        event_id = tournament["event_id"] if tournament else ""
        weather = queries.get_weather(conn, event_id) if event_id else []

    # Determine staleness (>6 hours since last refresh)
    is_stale = True
    data_warnings: list[str] = []
    odds_credits_remaining: Optional[int] = None

    if last_refresh:
        try:
            refreshed_dt = datetime.fromisoformat(last_refresh["refreshed_at"])
            if refreshed_dt.tzinfo is None:
                refreshed_dt = refreshed_dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - refreshed_dt).total_seconds() / 3600
            is_stale = age_hours > 6
        except Exception:
            pass

        import json
        try:
            raw_warnings = last_refresh.get("warnings") or "[]"
            data_warnings = json.loads(raw_warnings) if isinstance(raw_warnings, str) else raw_warnings
        except Exception:
            data_warnings = []

        odds_credits_remaining = last_refresh.get("odds_credits_remaining")

    return {
        "tournament": tournament,
        "weather": [dict(w) for w in weather],
        "players": [dict(p) for p in players],
        "last_refreshed": last_refresh["refreshed_at"] if last_refresh else None,
        "is_stale": is_stale,
        "data_warnings": data_warnings,
        "odds_credits_remaining": odds_credits_remaining,
    }
