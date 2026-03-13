from flask import Flask, jsonify, render_template, request
import config
from db import schema, queries
from data import pipeline
import sqlite3
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


@app.route("/api/backfill_season", methods=["POST"])
def api_backfill_season():
    """Manually trigger season backfill — useful for seeding a fresh Render DB."""
    try:
        pipeline.backfill_season(config.DATABASE_PATH)
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True)
