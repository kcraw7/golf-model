from flask import Flask, jsonify, render_template, request
import config
from db import schema, queries
from data import pipeline
import sqlite3
import threading
from datetime import datetime

app = Flask(__name__)

# Initialize DB on startup
schema.init_db(config.DATABASE_PATH)

# Auto-refresh if DB is empty
with queries.get_connection(config.DATABASE_PATH) as conn:
    if queries.get_current_tournament(conn) is None:
        try:
            print("No data found — running initial refresh...")
            pipeline.run_refresh(config.DATABASE_PATH)
        except Exception as e:
            print(f"Startup refresh failed: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    data = pipeline.get_dashboard_data(config.DATABASE_PATH)
    return jsonify(data)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    result = pipeline.run_refresh(config.DATABASE_PATH)
    return jsonify(result)


@app.route("/api/history")
def api_history():
    with queries.get_connection(config.DATABASE_PATH) as conn:
        history = queries.get_weekly_history(conn)
    return jsonify(history)


@app.route("/api/tournament/<event_id>")
def api_tournament_detail(event_id):
    with queries.get_connection(config.DATABASE_PATH) as conn:
        rows = queries.get_tournament_detail(conn, event_id)
    return jsonify(rows)


@app.route("/api/leaderboard")
def api_leaderboard():
    with queries.get_connection(config.DATABASE_PATH) as conn:
        rows = queries.get_player_leaderboard(conn)
    return jsonify(rows)


_backfill_status = {"running": False, "done": False, "error": None}

@app.route("/api/backfill_season", methods=["POST"])
def api_backfill_season():
    """Manually trigger season backfill in background — returns immediately."""
    global _backfill_status
    if _backfill_status["running"]:
        return jsonify({"status": "already_running"})

    def _run():
        global _backfill_status
        _backfill_status = {"running": True, "done": False, "error": None}
        try:
            pipeline.backfill_season(config.DATABASE_PATH)
            _backfill_status = {"running": False, "done": True, "error": None}
        except Exception as exc:
            _backfill_status = {"running": False, "done": False, "error": str(exc)}

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/api/backfill_status")
def api_backfill_status():
    return jsonify(_backfill_status)


if __name__ == "__main__":
    app.run(debug=True)
