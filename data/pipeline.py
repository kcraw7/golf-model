"""Orchestration: refresh pipeline and dashboard data assembly."""
from datetime import datetime, timezone
from typing import Optional

from data.fetchers.espn import get_field, get_stats, get_recent_event_scoring, get_last_year_top_finishers, get_event_results, get_season_events
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

    # ── Step 4: Form (last 3 events vs season avg) ───────────────────────────
    try:
        recent_scoring = get_recent_event_scoring(num_events=3)
    except Exception as exc:
        warnings.append(f"Recent form fetch failed: {exc}")
        recent_scoring = {}

    # ── Step 5: Course fit (last year's top finishers at this tournament) ────
    winner_profile: dict = {}
    try:
        event_name = field.get("event_name") or ""
        start_date = field.get("start_date") or ""
        if event_name and start_date:
            top_finishers = get_last_year_top_finishers(event_name, start_date)
            if top_finishers:
                winner_profile = model.build_winner_profile(top_finishers, skills)
    except Exception as exc:
        warnings.append(f"Course fit fetch failed: {exc}")

    # ── Step 6: Score ───────────────────────────────────────────────────────
    scored_players = model.merge_and_score(
        field, preds, skills, decomps, odds_data,
        recent_scoring=recent_scoring,
        winner_profile=winner_profile,
    )

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

            # ── Step 7: Snapshot picks ──────────────────────────────────────
            queries.snapshot_weekly_picks(conn, scored_players, field)

            # ── Step 8: Log ─────────────────────────────────────────────────
            queries.log_refresh(conn, status, warnings, odds_fetcher.CREDITS_REMAINING)

            conn.commit()
        except Exception as exc:
            warnings.append(f"Database write failed: {exc}")
            status = "error"

    # ── Step 9: Backfill past outcomes ───────────────────────────────────────
    try:
        backfill_outcomes(db_path, current_event_id=event_id)
    except Exception as exc:
        print(f"[pipeline] backfill_outcomes failed (non-fatal): {exc}")

    # ── Step 10: Season backfill (retroactive model runs) ────────────────────
    try:
        backfill_season(db_path, current_event_id=event_id)
    except Exception as exc:
        print(f"[pipeline] backfill_season failed (non-fatal): {exc}")

    return {
        "status": status,
        "warnings": warnings,
        "refreshed_at": now_iso,
    }


def backfill_outcomes(db_path: str, current_event_id: str = "") -> None:
    """Backfill finish positions and hit/miss outcomes for all past pending picks.

    Skips the current in-progress event (can't score an event still being played).
    Called automatically at the end of run_refresh(); catches all exceptions internally.
    """
    from itertools import groupby

    with queries.get_connection(db_path) as conn:
        pending_rows = queries.get_pending_outcomes(conn)

    if not pending_rows:
        print("[pipeline] backfill_outcomes: no pending rows to fill")
        return

    # Group by event_id
    pending_rows.sort(key=lambda r: r["event_id"])
    grouped = {
        eid: list(rows)
        for eid, rows in groupby(pending_rows, key=lambda r: r["event_id"])
    }

    total_updated = 0

    for event_id, rows in grouped.items():
        # Skip the currently-active event — it's still in progress
        if event_id == current_event_id:
            print(f"[pipeline] backfill_outcomes: skipping current event {event_id}")
            continue

        # Strip the "espn_" prefix to get the raw ESPN ID
        raw_espn_id = event_id.replace("espn_", "") if event_id.startswith("espn_") else event_id

        # Use week_label from the first row for the date lookup
        week_label = rows[0].get("week_label", "")

        results_map = get_event_results(raw_espn_id, week_label)
        if not results_map:
            print(f"[pipeline] backfill_outcomes: no results for event {event_id} ({week_label})")
            continue

        updated_count = 0
        with queries.get_connection(db_path) as conn:
            for row in rows:
                player_name = row.get("player_name", "")
                # Normalise name same way espn.py does
                import unicodedata
                import re as _re

                def _norm(name):
                    if not name:
                        return ""
                    nfd = unicodedata.normalize("NFD", name)
                    a = nfd.encode("ascii", "ignore").decode("ascii")
                    c = _re.sub(r"[^a-z\s]", "", a.lower()).strip()
                    return _re.sub(r"\s+", " ", c)

                norm = _norm(player_name)
                finish = results_map.get(norm)

                if finish is None:
                    continue  # player not found in results (DNS, WD, etc.)

                outcome_hit = 1 if finish <= 10 else 0
                queries.update_player_outcome(conn, row["id"], finish, outcome_hit)
                updated_count += 1

            conn.commit()

        total_updated += updated_count
        print(f"[pipeline] backfill_outcomes: event {event_id}: updated {updated_count}/{len(rows)} rows")

    print(f"[pipeline] backfill_outcomes: total {total_updated} rows updated across {len(grouped)} events")


def backfill_season(db_path: str, current_event_id: str = "") -> None:
    """Retroactively score all completed PGA Tour events this season.

    For each past event not already in tournament_results:
    - Matches field players to current season stats
    - Runs sg_to_win_probs() to rank players by model win probability
    - Saves full field to tournament_results
    - Saves top-20 picks to weekly_results with recommendation='Model Pick'

    Called automatically at end of run_refresh(); never raises.
    """
    import unicodedata as _ud
    import re as _re
    from datetime import datetime as _dt

    def _norm(name):
        if not name:
            return ""
        nfd = _ud.normalize("NFD", name)
        a = nfd.encode("ascii", "ignore").decode("ascii")
        c = _re.sub(r"[^a-z\s]", "", a.lower()).strip()
        return _re.sub(r"\s+", " ", c)

    # Discover all completed events this season
    season_events = get_season_events(since_date_str="2025-10-01")
    if not season_events:
        print("[pipeline] backfill_season: no season events found")
        return

    # Which events are already done?
    with queries.get_connection(db_path) as conn:
        done_ids = queries.get_tournament_result_event_ids(conn)

    # Get current season stats once — build a norm-name lookup
    try:
        stats_list = get_stats()
    except Exception as exc:
        print(f"[pipeline] backfill_season: stats fetch failed: {exc}")
        stats_list = []

    stats_lookup: dict = {}
    for s in stats_list:
        norm = _norm(s.get("player_name", ""))
        if norm:
            stats_lookup[norm] = s

    now_iso = _dt.utcnow().isoformat()
    events_processed = 0

    for event in season_events:
        event_id = event["event_id"]

        # Skip current in-progress event and already-done events
        if event_id == current_event_id or event_id in done_ids:
            continue

        competitors = event.get("competitors") or []
        if not competitors:
            continue

        # Build player dicts for model scoring
        players = []
        for c in competitors:
            player_name = c.get("player_name", "")
            norm = _norm(player_name)
            stat = stats_lookup.get(norm, {})

            players.append({
                "dg_id": c.get("dg_id"),
                "player_name": player_name,
                # ESPN stats — may be None if player not in current stats
                "scoring_avg": stat.get("scoring_avg"),
                "gir_pct": stat.get("gir_pct"),
                "birdies_per_round": stat.get("birdies_per_round"),
                "putts_per_hole": stat.get("putts_per_hole"),
                "driving_dist": stat.get("driving_dist"),
                # No form/fit for retroactive — set to None
                "recent_form_sg": None,
                "course_history_sg": None,
                "finish_position": c.get("finish_position"),
            })

        if not players:
            continue

        # Run model scoring
        try:
            scored = model.sg_to_win_probs(players)
        except Exception as exc:
            print(f"[pipeline] backfill_season: scoring failed for {event_id}: {exc}")
            continue

        # Sort by win prob descending and assign model_rank
        scored.sort(key=lambda p: p.get("dg_win_prob") or 0.0, reverse=True)
        for rank, p in enumerate(scored, start=1):
            p["model_rank"] = rank
            p["is_pick"] = 1 if rank <= 20 else 0

        # Build rows for tournament_results
        tr_rows = []
        for p in scored:
            tr_rows.append({
                "event_id": event_id,
                "event_name": event["event_name"],
                "week_label": event.get("start_date", ""),
                "player_name": p.get("player_name"),
                "dg_id": p.get("dg_id"),
                "model_win_prob": p.get("dg_win_prob"),
                "model_rank": p.get("model_rank"),
                "finish_position": p.get("finish_position"),
                "is_pick": p.get("is_pick", 0),
                "recorded_at": now_iso,
            })

        # Top-20 picks for weekly_results
        retro_picks = [p for p in scored if p.get("is_pick")]

        with queries.get_connection(db_path) as conn:
            queries.save_tournament_results(conn, tr_rows)
            queries.snapshot_retro_picks(
                conn,
                event_id=event_id,
                event_name=event["event_name"],
                week_label=event.get("start_date", ""),
                picks=[{
                    "player_name": p.get("player_name"),
                    "dg_id": p.get("dg_id"),
                    "model_win_prob": p.get("dg_win_prob"),
                    "finish_position": p.get("finish_position"),
                } for p in retro_picks],
                recorded_at=now_iso,
            )
            conn.commit()

        events_processed += 1
        print(f"[pipeline] backfill_season: processed {event['event_name']} ({event_id}): "
              f"{len(tr_rows)} players, {len(retro_picks)} picks")

    print(f"[pipeline] backfill_season: done — {events_processed} new events processed")


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
