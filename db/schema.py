import sqlite3


def init_db(db_path: str) -> None:
    """Create all tables if they do not already exist."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS tournament_info (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    TEXT NOT NULL,
            event_name  TEXT,
            course_name TEXT,
            location    TEXT,
            tour        TEXT,
            start_date  TEXT,
            end_date    TEXT,
            fetched_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS player_field (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            dg_id                INTEGER,
            player_name          TEXT,
            country              TEXT,
            dg_win_prob          REAL,
            dg_top5_prob         REAL,
            dg_top10_prob        REAL,
            dg_top20_prob        REAL,
            mkt_win_prob         REAL,
            mkt_top10_prob       REAL,
            odds_win_american    INTEGER,
            odds_top10_american  INTEGER,
            sg_total             REAL,
            sg_ott               REAL,
            sg_app               REAL,
            sg_atg               REAL,
            sg_putt              REAL,
            course_history_sg    REAL,
            course_history_rounds INTEGER,
            recent_form_sg       REAL,
            edge_win             REAL,
            edge_top10           REAL,
            recommendation       TEXT,
            blurb                TEXT,
            event_id             TEXT,
            fetched_at           TEXT
        );

        CREATE TABLE IF NOT EXISTS weather_forecast (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        TEXT,
            forecast_date   TEXT,
            avg_temp_f      INTEGER,
            high_f          INTEGER,
            low_f           INTEGER,
            wind_mph        INTEGER,
            precip_chance   INTEGER,
            description     TEXT,
            fetched_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS weekly_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        TEXT,
            event_name      TEXT,
            week_label      TEXT,
            dg_id           INTEGER,
            player_name     TEXT,
            finish_position INTEGER,
            recommendation  TEXT,
            model_prob      REAL,
            market_prob     REAL,
            edge            REAL,
            outcome_hit     INTEGER,
            recorded_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS refresh_log (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            refreshed_at          TEXT,
            status                TEXT,
            warnings              TEXT,
            odds_credits_remaining INTEGER
        );

        CREATE TABLE IF NOT EXISTS tournament_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        TEXT NOT NULL,
            event_name      TEXT,
            week_label      TEXT,
            player_name     TEXT,
            dg_id           INTEGER,
            model_win_prob  REAL,
            model_rank      INTEGER,
            finish_position INTEGER,
            is_pick         INTEGER DEFAULT 0,
            recorded_at     TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS uq_tr_event_player
            ON tournament_results(event_id, player_name);
    """)

    conn.commit()
    conn.close()
