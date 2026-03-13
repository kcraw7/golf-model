import sqlite3
import json
from datetime import datetime
from typing import Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row) -> dict:
    if row is None:
        return None
    return dict(row)


def _rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ── Read queries ────────────────────────────────────────────────────────────

def get_current_tournament(conn: sqlite3.Connection) -> Optional[dict]:
    cur = conn.execute(
        "SELECT * FROM tournament_info ORDER BY fetched_at DESC LIMIT 1"
    )
    return _row_to_dict(cur.fetchone())


def get_current_players(conn: sqlite3.Connection) -> list:
    """Return players sorted by edge_top10 DESC, nulls last."""
    cur = conn.execute("""
        SELECT * FROM player_field
        WHERE event_id = (
            SELECT event_id FROM tournament_info ORDER BY fetched_at DESC LIMIT 1
        )
        ORDER BY
            CASE WHEN edge_top10 IS NULL THEN 1 ELSE 0 END,
            edge_top10 DESC
    """)
    return _rows_to_list(cur.fetchall())


def get_weather(conn: sqlite3.Connection, event_id: str) -> list:
    cur = conn.execute(
        "SELECT * FROM weather_forecast WHERE event_id = ? ORDER BY forecast_date",
        (event_id,)
    )
    return _rows_to_list(cur.fetchall())


def get_last_refresh(conn: sqlite3.Connection) -> Optional[dict]:
    cur = conn.execute(
        "SELECT * FROM refresh_log ORDER BY id DESC LIMIT 1"
    )
    return _row_to_dict(cur.fetchone())


def get_weekly_history(conn: sqlite3.Connection) -> list:
    cur = conn.execute("""
        SELECT * FROM weekly_results
        ORDER BY recorded_at DESC
    """)
    return _rows_to_list(cur.fetchall())


def get_pending_outcomes(conn: sqlite3.Connection) -> list:
    """Return weekly_results rows where outcome_hit is still NULL, ordered by event_id."""
    cur = conn.execute("""
        SELECT * FROM weekly_results
        WHERE outcome_hit IS NULL
        ORDER BY event_id, id
    """)
    return _rows_to_list(cur.fetchall())


def update_player_outcome(
    conn: sqlite3.Connection,
    row_id: int,
    finish_position: int,
    outcome_hit: int,
) -> None:
    """Update finish_position and outcome_hit for one weekly_results row."""
    conn.execute("""
        UPDATE weekly_results
        SET finish_position = ?, outcome_hit = ?
        WHERE id = ?
    """, (finish_position, outcome_hit, row_id))


# ── tournament_results queries ────────────────────────────────────────────────

def get_tournament_result_event_ids(conn: sqlite3.Connection) -> set:
    """Return set of event_ids already in tournament_results."""
    cur = conn.execute("SELECT DISTINCT event_id FROM tournament_results")
    return {r[0] for r in cur.fetchall()}


def save_tournament_results(conn: sqlite3.Connection, rows: list) -> None:
    """INSERT OR IGNORE full-field rows into tournament_results."""
    for row in rows:
        conn.execute("""
            INSERT OR IGNORE INTO tournament_results
                (event_id, event_name, week_label, player_name, dg_id,
                 model_win_prob, model_rank, finish_position, is_pick, recorded_at)
            VALUES
                (:event_id, :event_name, :week_label, :player_name, :dg_id,
                 :model_win_prob, :model_rank, :finish_position, :is_pick, :recorded_at)
        """, row)


def snapshot_retro_picks(
    conn: sqlite3.Connection,
    event_id: str,
    event_name: str,
    week_label: str,
    picks: list,
    recorded_at: str,
) -> None:
    """Insert retroactive top-20 picks into weekly_results with recommendation='Model Pick'.
    Skips duplicates by (event_id, dg_id).
    picks: list of dicts with player_name, dg_id, model_win_prob
    """
    existing = conn.execute(
        "SELECT dg_id FROM weekly_results WHERE event_id = ?", (event_id,)
    ).fetchall()
    existing_ids = {r["dg_id"] for r in existing}

    for p in picks:
        if p.get("dg_id") in existing_ids:
            continue
        conn.execute("""
            INSERT INTO weekly_results
                (event_id, event_name, week_label, dg_id, player_name,
                 finish_position, recommendation, model_prob, market_prob,
                 edge, outcome_hit, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Model Pick', ?, NULL, NULL, ?, ?)
        """, (
            event_id,
            event_name,
            week_label,
            p.get("dg_id"),
            p.get("player_name"),
            p.get("finish_position"),
            p.get("model_win_prob"),
            1 if (p.get("finish_position") or 999) <= 10 else 0,
            recorded_at,
        ))


def get_tournament_detail(conn: sqlite3.Connection, event_id: str) -> list:
    """Return all rows for one event from tournament_results, ordered by model_rank ASC."""
    cur = conn.execute("""
        SELECT * FROM tournament_results
        WHERE event_id = ?
        ORDER BY model_rank ASC
    """, (event_id,))
    return _rows_to_list(cur.fetchall())


def get_player_leaderboard(conn: sqlite3.Connection) -> list:
    """Aggregate per player across tournament_results.
    Returns: player_name, tournaments, picks, hits, hit_rate,
             avg_model_rank, avg_finish_rank, rank_delta
    """
    cur = conn.execute("""
        SELECT
            player_name,
            COUNT(DISTINCT event_id)                                AS tournaments,
            SUM(CASE WHEN is_pick = 1 THEN 1 ELSE 0 END)           AS picks,
            SUM(CASE WHEN is_pick = 1 AND finish_position <= 10
                     THEN 1 ELSE 0 END)                             AS hits,
            CASE WHEN SUM(is_pick) > 0
                 THEN ROUND(
                     100.0 * SUM(CASE WHEN is_pick = 1 AND finish_position <= 10
                                      THEN 1 ELSE 0 END)
                     / SUM(is_pick), 1)
                 ELSE NULL END                                       AS hit_rate,
            ROUND(AVG(CAST(model_rank AS REAL)), 1)                 AS avg_model_rank,
            ROUND(AVG(CAST(finish_position AS REAL)), 1)            AS avg_finish_rank,
            ROUND(AVG(CAST(model_rank AS REAL))
                - AVG(CAST(finish_position AS REAL)), 1)            AS rank_delta
        FROM tournament_results
        WHERE finish_position IS NOT NULL
        GROUP BY player_name
        HAVING tournaments >= 1
        ORDER BY picks DESC, hit_rate DESC
    """)
    return _rows_to_list(cur.fetchall())


# ── Write queries ────────────────────────────────────────────────────────────

def replace_tournament(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute("DELETE FROM tournament_info")
    conn.execute("""
        INSERT INTO tournament_info
            (event_id, event_name, course_name, location, tour, start_date, end_date, fetched_at)
        VALUES
            (:event_id, :event_name, :course_name, :location, :tour, :start_date, :end_date, :fetched_at)
    """, data)


def replace_players(
    conn: sqlite3.Connection,
    players: list,
    event_id: str,
    fetched_at: str,
) -> None:
    conn.execute("DELETE FROM player_field WHERE event_id = ?", (event_id,))
    for p in players:
        p_copy = dict(p)
        p_copy["event_id"] = event_id
        p_copy["fetched_at"] = fetched_at
        conn.execute("""
            INSERT INTO player_field (
                dg_id, player_name, country,
                dg_win_prob, dg_top5_prob, dg_top10_prob, dg_top20_prob,
                mkt_win_prob, mkt_top10_prob,
                odds_win_american, odds_top10_american,
                sg_total, sg_ott, sg_app, sg_atg, sg_putt,
                course_history_sg, course_history_rounds, recent_form_sg,
                edge_win, edge_top10,
                recommendation, blurb,
                current_position,
                event_id, fetched_at
            ) VALUES (
                :dg_id, :player_name, :country,
                :dg_win_prob, :dg_top5_prob, :dg_top10_prob, :dg_top20_prob,
                :mkt_win_prob, :mkt_top10_prob,
                :odds_win_american, :odds_top10_american,
                :sg_total, :sg_ott, :sg_app, :sg_atg, :sg_putt,
                :course_history_sg, :course_history_rounds, :recent_form_sg,
                :edge_win, :edge_top10,
                :recommendation, :blurb,
                :current_position,
                :event_id, :fetched_at
            )
        """, p_copy)


def replace_weather(
    conn: sqlite3.Connection,
    forecasts: list,
    event_id: str,
    fetched_at: str,
) -> None:
    conn.execute("DELETE FROM weather_forecast WHERE event_id = ?", (event_id,))
    for f in forecasts:
        f_copy = dict(f)
        f_copy["event_id"] = event_id
        f_copy["fetched_at"] = fetched_at
        conn.execute("""
            INSERT INTO weather_forecast
                (event_id, forecast_date, avg_temp_f, high_f, low_f, wind_mph,
                 precip_chance, description, fetched_at)
            VALUES
                (:event_id, :forecast_date, :avg_temp_f, :high_f, :low_f, :wind_mph,
                 :precip_chance, :description, :fetched_at)
        """, f_copy)


def log_refresh(
    conn: sqlite3.Connection,
    status: str,
    warnings: list,
    odds_credits: Optional[int],
) -> None:
    conn.execute("""
        INSERT INTO refresh_log (refreshed_at, status, warnings, odds_credits_remaining)
        VALUES (?, ?, ?, ?)
    """, (
        datetime.utcnow().isoformat(),
        status,
        json.dumps(warnings),
        odds_credits,
    ))


def snapshot_weekly_picks(
    conn: sqlite3.Connection,
    players: list,
    tournament: dict,
) -> None:
    """Insert Strong Value and Value picks into weekly_results for tracking."""
    event_id = tournament.get("event_id", "")
    event_name = tournament.get("event_name", "")
    week_label = tournament.get("start_date", datetime.utcnow().strftime("%Y-%m-%d"))
    recorded_at = datetime.utcnow().isoformat()

    # Only snapshot picks not already recorded for this event
    existing = conn.execute(
        "SELECT dg_id FROM weekly_results WHERE event_id = ?", (event_id,)
    ).fetchall()
    existing_ids = {r["dg_id"] for r in existing}

    for p in players:
        rec = p.get("recommendation", "")
        if rec not in ("Strong Value", "Value"):
            continue
        if p.get("dg_id") in existing_ids:
            continue

        conn.execute("""
            INSERT INTO weekly_results
                (event_id, event_name, week_label, dg_id, player_name,
                 finish_position, recommendation, model_prob, market_prob,
                 edge, outcome_hit, recorded_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, NULL, ?)
        """, (
            event_id,
            event_name,
            week_label,
            p.get("dg_id"),
            p.get("player_name"),
            rec,
            p.get("dg_top10_prob"),
            p.get("mkt_top10_prob"),
            p.get("edge_top10"),
            recorded_at,
        ))
