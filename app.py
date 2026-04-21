from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import uuid
import json
import math
import time
import random
from datetime import datetime
from scipy import stats
import numpy as np

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})
DB_PATH = "ab_test.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS visits (
            id          TEXT PRIMARY KEY,
            variant     TEXT NOT NULL,
            timestamp   INTEGER NOT NULL,
            session_dur INTEGER DEFAULT 0,
            bounce      INTEGER DEFAULT 0,
            converted   INTEGER DEFAULT 0,
            color_pref  TEXT DEFAULT NULL,
            country     TEXT DEFAULT NULL,
            device      TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS color_votes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            variant   TEXT NOT NULL,
            color     TEXT NOT NULL,
            timestamp INTEGER NOT NULL
        );
    """)
    conn.commit()
    conn.close()

def compute_stats(a_visits, a_conv, b_visits, b_conv):
    result = {
        "a_visits": a_visits, "a_conversions": a_conv,
        "b_visits": b_visits, "b_conversions": b_conv,
        "a_rate": 0, "b_rate": 0,
        "lift": 0, "lift_pct": 0,
        "z_score": 0, "p_value": 1,
        "significant": False,
        "ci_lower": 0, "ci_upper": 0,
        "cohens_h": 0,
        "power": 0,
        "recommended_sample": 0,
        "verdict": "Insufficient data"
    }

    if a_visits == 0 or b_visits == 0:
        return result

    p_a = a_conv / a_visits
    p_b = b_conv / b_visits
    result["a_rate"] = round(p_a * 100, 2)
    result["b_rate"] = round(p_b * 100, 2)
    result["lift"] = round((p_b - p_a) * 100, 2)
    result["lift_pct"] = round(((p_b - p_a) / p_a * 100) if p_a > 0 else 0, 1)

    count = np.array([a_conv, b_conv])
    nobs  = np.array([a_visits, b_visits])
    try:
        z, p = stats.proportions_ztest(count, nobs)
        result["z_score"] = round(float(z), 4)
        result["p_value"] = round(float(p), 4)
        result["significant"] = p < 0.05
    except:
        pass

    diff = p_b - p_a
    se   = math.sqrt((p_a*(1-p_a)/a_visits) + (p_b*(1-p_b)/b_visits))
    result["ci_lower"] = round((diff - 1.96 * se) * 100, 2)
    result["ci_upper"] = round((diff + 1.96 * se) * 100, 2)

    h = 2 * math.asin(math.sqrt(p_b)) - 2 * math.asin(math.sqrt(p_a))
    result["cohens_h"] = round(abs(h), 4)

    alpha, z_alpha, z_beta = 0.05, 1.96, 0.842
    if se > 0:
        power_z = (abs(diff) - z_alpha * se) / (se)
        power   = stats.norm.cdf(power_z)
        result["power"] = round(float(power) * 100, 1)

    if abs(h) > 0:
        n_req = int(((z_alpha + z_beta) / h) ** 2)
        result["recommended_sample"] = n_req

    if a_visits + b_visits < 100:
        result["verdict"] = "More data needed"
    elif result["significant"] and p_b > p_a:
        result["verdict"] = "Ship Variant B"
    elif result["significant"] and p_b <= p_a:
        result["verdict"] = "Keep Variant A"
    elif result["power"] < 80:
        result["verdict"] = "Test inconclusive"
    else:
        result["verdict"] = "No significant difference"

    return result

@app.route("/api/visit", methods=["POST"])
def log_visit():
    data    = request.json or {}
    variant = "A" if random.random() < 0.5 else "B"
    vid     = str(uuid.uuid4())
    device  = data.get("device", "unknown")
    country = data.get("country", "unknown")

    conn = get_db()
    conn.execute(
        "INSERT INTO visits (id, variant, timestamp, device, country) VALUES (?, ?, ?, ?, ?)",
        (vid, variant, int(time.time()), device, country)
    )
    conn.commit()
    conn.close()
    return jsonify({"visit_id": vid, "variant": variant})

@app.route("/api/convert", methods=["POST"])
def log_conversion():
    data    = request.json or {}
    vid     = data.get("visit_id")
    dur     = data.get("session_duration", 0)
    color   = data.get("color_pref", None)

    if not vid:
        return jsonify({"error": "visit_id required"}), 400

    conn = get_db()
    conn.execute(
        "UPDATE visits SET converted=1, session_dur=?, color_pref=? WHERE id=?",
        (dur, color, vid)
    )
    conn.commit()

    if color:
        row = conn.execute("SELECT variant FROM visits WHERE id=?", (vid,)).fetchone()
        if row:
            conn.execute(
                "INSERT INTO color_votes (variant, color, timestamp) VALUES (?, ?, ?)",
                (row["variant"], color, int(time.time()))
            )
            conn.commit()

    conn.close()
    return jsonify({"status": "ok", "visit_id": vid})

@app.route("/api/bounce", methods=["POST"])
def log_bounce():
    data = request.json or {}
    vid  = data.get("visit_id")
    dur  = data.get("session_duration", 0)
    if vid:
        conn = get_db()
        conn.execute("UPDATE visits SET bounce=1, session_dur=? WHERE id=?", (dur, vid))
        conn.commit()
        conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/color_vote", methods=["POST"])
def log_color_vote():
    data    = request.json or {}
    variant = data.get("variant")
    color   = data.get("color")
    if not variant or not color:
        return jsonify({"error": "variant and color required"}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO color_votes (variant, color, timestamp) VALUES (?, ?, ?)",
        (variant, color, int(time.time()))
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/results", methods=["GET"])
def get_results():
    conn = get_db()
    rows = conn.execute("SELECT * FROM visits").fetchall()

    a_visits = b_visits = a_conv = b_conv = 0
    a_bounce = b_bounce = 0
    a_dur, b_dur = [], []

    for r in rows:
        if r["variant"] == "A":
            a_visits += 1
            if r["converted"]: a_conv += 1
            if r["bounce"]:    a_bounce += 1
            if r["session_dur"]: a_dur.append(r["session_dur"])
        else:
            b_visits += 1
            if r["converted"]: b_conv += 1
            if r["bounce"]:    b_bounce += 1
            if r["session_dur"]: b_dur.append(r["session_dur"])

    color_rows = conn.execute("SELECT variant, color, COUNT(*) as cnt FROM color_votes GROUP BY variant, color").fetchall()
    color_data = {"A": {}, "B": {}}
    for cr in color_rows:
        color_data[cr["variant"]][cr["color"]] = cr["cnt"]

    conn.close()

    stats_result = compute_stats(a_visits, a_conv, b_visits, b_conv)
    stats_result["a_bounce_rate"] = round(a_bounce / a_visits * 100, 1) if a_visits else 0
    stats_result["b_bounce_rate"] = round(b_bounce / b_visits * 100, 1) if b_visits else 0
    stats_result["a_avg_duration"] = round(sum(a_dur) / len(a_dur), 1) if a_dur else 0
    stats_result["b_avg_duration"] = round(sum(b_dur) / len(b_dur), 1) if b_dur else 0
    stats_result["color_data"] = color_data
    stats_result["total_visitors"] = a_visits + b_visits
    stats_result["timestamp"] = datetime.utcnow().isoformat() + "Z"

    return jsonify(stats_result)

@app.route("/api/seed_demo", methods=["POST"])
def seed_demo():
    conn = get_db()
    COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899"]
    devices = ["desktop", "mobile", "tablet"]
    countries = ["India", "US", "UK", "Germany", "Canada"]
    base_ts = int(time.time()) - 7 * 24 * 3600

    for i in range(500):
        variant = "A" if i < 250 else "B"
        vid = str(uuid.uuid4())
        ts  = base_ts + random.randint(0, 7 * 24 * 3600)
        conv_prob = 0.08 if variant == "A" else 0.12
        converted = 1 if random.random() < conv_prob else 0
        bounce    = 0 if converted else (1 if random.random() < 0.4 else 0)
        dur       = random.randint(30, 300) if not bounce else random.randint(5, 30)
        color     = random.choice(COLORS) if converted else None
        conn.execute(
            "INSERT OR IGNORE INTO visits (id, variant, timestamp, session_dur, bounce, converted, color_pref, device, country) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vid, variant, ts, dur, bounce, converted, color, random.choice(devices), random.choice(countries))
        )
        if color:
            conn.execute("INSERT INTO color_votes (variant, color, timestamp) VALUES (?, ?, ?)", (variant, color, ts))

    conn.commit()
    conn.close()
    return jsonify({"status": "demo data seeded", "visits": 500})

@app.route("/")
def dashboard():
    return """
    <html><body style="font-family:sans-serif;padding:2rem;background:#0f172a;color:#e2e8f0">
    <h1>A/B Test Engine Running</h1>
    <p>API Endpoints:</p>
    <ul>
      <li>POST /api/visit — log a visit</li>
      <li>POST /api/convert — log conversion</li>
      <li>POST /api/bounce — log bounce</li>
      <li>POST /api/color_vote — log colour preference</li>
      <li>GET  /api/results — get all statistics</li>
      <li>POST /api/seed_demo — populate demo data</li>
    </ul>
    <p>Open the dashboard artifact in Claude to visualize results.</p>
    </body></html>
    """

if __name__ == "__main__":
    import os
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
