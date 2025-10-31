from flask import Flask, g, jsonify, request, send_file, render_template, abort
import sqlite3, os, json
from datetime import date, timedelta, datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "bowling.sqlite3")
TIPS_PATH = os.path.join(APP_DIR, "365_bowling_tips.txt")

app = Flask(__name__, template_folder="templates", static_folder="static")

# -------------------- Tips loader --------------------
_TIPS_CACHE = None
def _load_tips():
    global _TIPS_CACHE
    if _TIPS_CACHE is not None:
        return _TIPS_CACHE
    tips = []
    try:
        with open(TIPS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t:
                    tips.append(t)
    except Exception:
        tips = [
            "Focus on your target arrow, not the pins.",
            "Keep your swing smooth and relaxed.",
            "Maintain consistent timing in your approach.",
            "Follow through straight toward your target.",
            "Use a ball that fits your hand comfortably.",
        ]
    _TIPS_CACHE = tips
    return tips

def tip_for_today() -> str:
    tips = _load_tips()
    if not tips:
        return ""
    ordinal = date.today().toordinal()
    return tips[ordinal % len(tips)]

# -------------------- DB helpers --------------------
def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    schema_file = os.path.join(APP_DIR, "schema.sql")
    with open(schema_file, "r", encoding="utf-8") as f:
        script = f.read()
    db.executescript(script)
    db.commit()

def ensure_defaults():
    """
    Seed alleys and bowlers (idempotent).
    Group A: Rajan/Medina
    Group B: Barsotti/Baule/RJB
    """
    db = get_db()

    # Do NOT seed "Milwaukie Lanes"
    default_alleys = [
        "Zodos Lanes",
        "Camarillo Bowl",
        "Sunset Lanes",
        "Lilac Lanes",
        "North Bowl",
        "Winnetka Bowl",
        "Milwaukie Bowl",   # Medina + RJB UI default
    ]
    for name in default_alleys:
        db.execute("INSERT OR IGNORE INTO alleys (name) VALUES (?)", (name,))

    default_bowlers = [
        ("Rajan",    "A"),
        ("Medina",   "A"),
        ("Baule",    "B"),
        ("Barsotti", "B"),
        ("RJB",      "B"),
    ]
    for name, grp in default_bowlers:
        db.execute("INSERT OR IGNORE INTO bowlers (name, bix_group) VALUES (?, ?)", (name, grp))
        db.execute(
            "UPDATE bowlers SET bix_group=? WHERE name=? AND (bix_group IS NULL OR bix_group='')",
            (grp, name),
        )

    db.commit()

@app.before_request
def ensure_db():
    if not os.path.exists(DB_PATH):
        init_db()
    try:
        ensure_defaults()
    except Exception:
        pass

def rows_to_dicts(rows):
    return [dict(r) for r in rows]

# -------------------- BIX & analytics --------------------
def compute_alley_breakdown(db, bowler_id):
    rows = db.execute(
        "SELECT a.name AS alley, AVG(g.score) AS avg_score, COUNT(*) AS games "
        "FROM sessions s JOIN alleys a ON a.id=s.alley_id "
        "JOIN games g ON g.session_id=s.id "
        "WHERE s.bowler_id=? "
        "GROUP BY a.name ORDER BY a.name",
        (bowler_id,)
    ).fetchall()
    return [
        {"alley": r["alley"], "avg": round(r["avg_score"],2) if r["avg_score"] is not None else 0.0, "games": r["games"]}
        for r in rows
    ]

def compute_bix_for_bowler(db, bowler_id, bix_group):
    avg_row = db.execute(
        "SELECT AVG(score) AS avg_score, COUNT(*) AS games "
        "FROM games WHERE session_id IN (SELECT id FROM sessions WHERE bowler_id=?)",
        (bowler_id,)
    ).fetchone()
    avg = (avg_row["avg_score"] or 0)
    games_count = avg_row["games"] or 0

    r = db.execute(
        "SELECT "
        "SUM(CASE WHEN score>=200 THEN 1 ELSE 0 END) AS c200, "
        "SUM(CASE WHEN score>=210 THEN 1 ELSE 0 END) AS c210, "
        "SUM(CASE WHEN score>=250 THEN 1 ELSE 0 END) AS c250, "
        "SUM(CASE WHEN score=300 THEN 1 ELSE 0 END) AS c300, "
        "SUM(CASE WHEN score>=150 THEN 1 ELSE 0 END) AS c150 "
        "FROM games WHERE session_id IN (SELECT id FROM sessions WHERE bowler_id=?)",
        (bowler_id,)
    ).fetchone()
    c200 = r["c200"] or 0
    c210 = r["c210"] or 0
    c250 = r["c250"] or 0
    c300 = r["c300"] or 0
    c150 = r["c150"] or 0

    bix = avg
    if bix_group == "A":
        bix += 0.25 * c210
        bix += 0.50 * c250
        bix += 2.50 * c300
        bonus = db.execute(
            "SELECT SUM(CASE WHEN cnt=12 AND avg_score>=210 THEN 2.5 ELSE 0 END) AS bonus "
            "FROM ("
            "  SELECT id, COUNT(*) AS cnt, AVG(score) AS avg_score "
            "  FROM games WHERE session_id IN (SELECT id FROM sessions WHERE bowler_id=?) "
            "  GROUP BY session_id"
            ")",
            (bowler_id,)
        ).fetchone()
        bix += (bonus["bonus"] or 0)
    else:
        # Group B (Barsotti/Baule/RJB): +0.25 per game >=150
        bix += 0.25 * c150

    return {
        "avg": round(avg, 2) if games_count else 0.0,
        "games": games_count,
        "c200": c200, "c210": c210, "c250": c250, "c300": c300, "c150": c150,
        "bix": round(bix, 2)
    }

# -------------------- Session-level stats helper --------------------
def compute_session_stats(db, sid: int):
    row = db.execute(
        "SELECT ROUND(AVG(score),2) AS avg_score, MIN(score) AS low_score, MAX(score) AS high_score, COUNT(*) AS games_count "
        "FROM games WHERE session_id=?",
        (sid,)
    ).fetchone()
    if not row or (row["games_count"] or 0) == 0:
        return {"avg": None, "low": None, "high": None, "count": 0}
    return {
        "avg": float(row["avg_score"]) if row["avg_score"] is not None else None,
        "low": row["low_score"],
        "high": row["high_score"],
        "count": row["games_count"]
    }

# -------------------- Period helpers (week/month/year) --------------------
def period_bounds(kind: str):
    today = date.today()
    if kind == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif kind == "month":
        start = today.replace(day=1)
        if start.month == 12:
            nm = date(start.year + 1, 1, 1)
        else:
            nm = date(start.year, start.month + 1, 1)
        end = nm - timedelta(days=1)
    elif kind == "year":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
    else:
        start = end = today
    return (start.isoformat(), end.isoformat())

def top_games_in_range(db, start, end, limit):
    rows = db.execute(
        "SELECT g.score, s.session_date, b.name AS bowler, a.name AS alley "
        "FROM games g "
        "JOIN sessions s ON s.id=g.session_id "
        "JOIN bowlers b ON b.id=s.bowler_id "
        "JOIN alleys a ON a.id=s.alley_id "
        "WHERE s.session_date BETWEEN ? AND ? "
        "ORDER BY g.score DESC, s.session_date ASC "
        "LIMIT ?",
        (start, end, limit)
    ).fetchall()
    return rows_to_dicts(rows)

def top_avg_in_range(db, start, end, limit):
    rows = db.execute(
        "SELECT b.name AS bowler, ROUND(AVG(g.score),2) AS avg_score, COUNT(*) AS games "
        "FROM games g "
        "JOIN sessions s ON s.id=g.session_id "
        "JOIN bowlers b ON b.id=s.bowler_id "
        "WHERE s.session_date BETWEEN ? AND ? "
        "GROUP BY b.id "
        "HAVING COUNT(*) > 0 "
        "ORDER BY avg_score DESC, games DESC "
        "LIMIT ?",
        (start, end, limit)
    ).fetchall()
    return [{"bowler": r["bowler"], "avg": float(r["avg_score"]), "games": r["games"]} for r in rows]

# -------------------- Routes --------------------
@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/lookups")
def api_lookups():
    db = get_db()
    bowlers = rows_to_dicts(db.execute("SELECT id,name,bix_group FROM bowlers ORDER BY name"))
    # Hide "Milwaukie Lanes" even if it exists in DB
    alleys  = rows_to_dicts(db.execute("SELECT id,name FROM alleys WHERE name!='Milwaukie Lanes' ORDER BY name"))
    return jsonify({"bowlers": bowlers, "alleys": alleys})

@app.get("/api/daily-tip")
def api_daily_tip():
    return jsonify({"date": date.today().isoformat(), "tip": tip_for_today()})

@app.post("/api/alleys")
def api_add_alley():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error":"Name required"}), 400
    db = get_db()
    try:
        db.execute("INSERT OR IGNORE INTO alleys (name) VALUES (?)", (name,))
        db.commit()
        row = db.execute("SELECT id,name FROM alleys WHERE name=?", (name,)).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400

@app.get("/api/sessions")
def api_sessions():
    db = get_db()
    rows = rows_to_dicts(db.execute(
        "SELECT s.id, s.session_date, b.name AS bowler, a.name AS alley, "
        "(SELECT COUNT(*) FROM games WHERE session_id=s.id) AS games, "
        "(SELECT ROUND(AVG(score),2) FROM games WHERE session_id=s.id) AS session_avg "
        "FROM sessions s "
        "JOIN bowlers b ON b.id=s.bowler_id "
        "JOIN alleys a ON a.id=s.alley_id "
        "ORDER BY s.session_date DESC, b.name"
    ))
    # Convert None to 0.0? Keep None so UI can display "—"
    return jsonify(rows)

@app.get("/api/session/<int:sid>/games")
def api_session_games(sid):
    db = get_db()
    head = db.execute(
        "SELECT s.id, s.session_date, b.name AS bowler, a.name AS alley "
        "FROM sessions s JOIN bowlers b ON b.id=s.bowler_id "
        "JOIN alleys a ON a.id=s.alley_id WHERE s.id=?",
        (sid,)
    ).fetchone()
    if head is None:
        return jsonify({"error": "Session not found"}), 404

    games = rows_to_dicts(db.execute(
        "SELECT game_number, score FROM games WHERE session_id=? ORDER BY game_number",
        (sid,)
    ))
    stats = compute_session_stats(get_db(), sid)

    return jsonify({
        "id": head["id"],
        "session_date": head["session_date"],
        "bowler": head["bowler"],
        "alley": head["alley"],
        "games": games,
        "stats": stats
    })

@app.put("/api/session/<int:sid>/games")
def api_update_session_games(sid):
    db = get_db()
    head = db.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
    if head is None:
        return jsonify({"error":"Session not found"}), 404
    data = request.get_json(silent=True) or {}
    scores = data.get("scores", [])
    if not isinstance(scores, list) or len(scores)==0:
        return jsonify({"error":"At least one score is required"}), 400
    try:
        scores = [int(s) for s in scores]
    except (TypeError, ValueError):
        return jsonify({"error":"Scores must be integers 1–300"}), 400
    if len(scores) > 12 or any(s<1 or s>300 for s in scores):
        return jsonify({"error":"Scores must be integers 1–300 (max 12 games)"}), 400
    try:
        db.execute("DELETE FROM games WHERE session_id=?", (sid,))
        for i, sc in enumerate(scores, start=1):
            db.execute("INSERT INTO games (session_id, game_number, score) VALUES (?,?,?)", (sid, i, sc))
        db.commit()
        return jsonify({"ok": True, "session_id": sid, "games": len(scores)})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400

@app.post("/api/session")
def api_save_session():
    data = request.get_json(silent=True) or {}

    def to_int(x):
        try:
            return int(x) if x not in (None, "") else None
        except (TypeError, ValueError):
            return None

    bowler_id = to_int(data.get("bowler_id"))
    alley_id  = to_int(data.get("alley_id"))
    session_date = (data.get("session_date") or "").strip()
    scores = data.get("scores", [])

    if bowler_id is None or alley_id is None or not session_date:
        return jsonify({"error":"bowler_id, alley_id, session_date required"}), 400
    if not isinstance(scores, list) or len(scores) == 0:
        return jsonify({"error":"At least one score is required"}), 400
    try:
        scores = [int(s) for s in scores]
    except (TypeError, ValueError):
        return jsonify({"error":"Scores must be integers 1–300"}), 400
    if len(scores) > 12 or any(s < 1 or s > 300 for s in scores):
        return jsonify({"error":"Scores must be integers 1–300 (max 12 games)"}), 400

    db = get_db()
    try:
        if db.execute("SELECT 1 FROM bowlers WHERE id=?", (bowler_id,)).fetchone() is None:
            return jsonify({"error":"Invalid bowler_id"}), 400
        if db.execute("SELECT 1 FROM alleys WHERE id=?", (alley_id,)).fetchone() is None:
            return jsonify({"error":"Invalid alley_id"}), 400

        db.execute("INSERT OR IGNORE INTO sessions (bowler_id, alley_id, session_date) VALUES (?,?,?)",
                   (bowler_id, alley_id, session_date))
        sid_row = db.execute("SELECT id FROM sessions WHERE bowler_id=? AND session_date=?",
                             (bowler_id, session_date)).fetchone()
        if sid_row is None:
            return jsonify({"error":"Failed to find or create session"}), 500
        sid = sid_row["id"]

        db.execute("UPDATE sessions SET alley_id=? WHERE id=?", (alley_id, sid))

        db.execute("DELETE FROM games WHERE session_id=?", (sid,))
        for i, sc in enumerate(scores, start=1):
            db.execute("INSERT INTO games (session_id, game_number, score) VALUES (?,?,?)",
                       (sid, i, sc))
        db.commit()
        return jsonify({"ok": True, "session_id": sid})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400


@app.get("/api/totals")
def api_totals():
    db = get_db()
    bowlers = rows_to_dicts(db.execute("SELECT id,name,bix_group FROM bowlers ORDER BY name"))
    totals = []
    bix_by_name = {}

    for b in bowlers:
        met = compute_bix_for_bowler(db, b["id"], b["bix_group"])
        alleys = compute_alley_breakdown(db, b["id"])

        # Likes per bowler (sum of like_count across all games in bowler's sessions)
        likes_row = db.execute(
            "SELECT COALESCE(SUM(g.like_count), 0) AS likes "
            "FROM games g WHERE g.session_id IN (SELECT id FROM sessions WHERE bowler_id=?)",
            (b["id"],)
        ).fetchone()
        likes = likes_row["likes"] if likes_row and likes_row["likes"] is not None else 0

        trow = {"name": b["name"], "bix_group": b["bix_group"], **met, "alleys": alleys, "likes": int(likes)}
        totals.append(trow)
        bix_by_name[b["name"]] = met["bix"]

    r_bix = bix_by_name.get("Rajan")
    m_bix = bix_by_name.get("Medina")
    bix_msg = None
    if isinstance(r_bix, (int,float)) and isinstance(m_bix, (int,float)):
        diff = round(r_bix - m_bix, 2)
        if diff == 0:
            bix_msg = "Rajan and Medina are tied in BIX."
        elif diff > 0:
            bix_msg = f"Rajan's BIX is {abs(diff):.2f} higher than Medina."
        else:
            bix_msg = f"Medina's BIX is {abs(diff):.2f} higher than Rajan."

    monthly_rows = rows_to_dicts(db.execute(
        "SELECT b.name AS name, strftime('%Y-%m', s.session_date) AS ym, AVG(g.score) AS avg_score "
        "FROM bowlers b "
        "JOIN sessions s ON s.bowler_id=b.id "
        "JOIN games g ON g.session_id=s.id "
        "WHERE b.name IN ('Rajan','Medina') "
        "GROUP BY b.name, ym "
        "ORDER BY ym DESC"
    ))
    by_name = {"Rajan":{}, "Medina":{}}
    for r in monthly_rows:
        by_name.setdefault(r["name"], {})[r["ym"]] = round(r["avg_score"],2) if r["avg_score"] is not None else None

    # include total likes across all games for optional UI badge
    total_likes = db.execute("SELECT COALESCE(SUM(like_count),0) AS total FROM games").fetchone()["total"]

    return jsonify({
        "totals": totals,
        "bix_message": bix_msg,
        "monthly_avgs": by_name,
        "tip_of_day": tip_for_today(),
        "total_likes": total_likes
    })

@app.get("/api/honor-roll")
def api_honor_roll():
    db = get_db()
    wk_start, wk_end = period_bounds("week")
    mo_start, mo_end = period_bounds("month")
    yr_start, yr_end = period_bounds("year")

    week_top3  = top_games_in_range(db, wk_start, wk_end, 3)
    month_top3 = top_games_in_range(db, mo_start, mo_end, 3)
    year_top1  = top_games_in_range(db, yr_start, yr_end, 1)

    week_avg3  = top_avg_in_range(db, wk_start, wk_end, 3)
    month_avg3 = top_avg_in_range(db, mo_start, mo_end, 3)
    year_avg3  = top_avg_in_range(db, yr_start, yr_end, 3)

    return jsonify({
        "week":  {"range":[wk_start, wk_end], "top_scores": week_top3,  "top_avgs": week_avg3},
        "month": {"range":[mo_start, mo_end], "top_scores": month_top3, "top_avgs": month_avg3},
        "year":  {"range":[yr_start, yr_end], "top_score": (year_top1[0] if year_top1 else None), "top_avgs": year_avg3}
    })

@app.post("/api/session/<int:sid>/game/<int:gn>/like")
def api_like_game_by_position(sid, gn):
    db = get_db()
    row = db.execute("SELECT id, COALESCE(like_count,0) AS like_count FROM games WHERE session_id=? AND game_number=?",
                     (sid, gn)).fetchone()
    if row is None:
        return jsonify({"error": "Game not found for session/position"}), 404
    new_count = (row["like_count"] or 0) + 1
    db.execute("UPDATE games SET like_count=? WHERE id=?", (new_count, row["id"]))
    db.commit()
    return jsonify({"game_id": row["id"], "likes": new_count, "session_id": sid, "game_number": gn})

@app.get("/api/export")
def api_export():
    if not os.path.exists(DB_PATH):
        abort(404)
    return send_file(DB_PATH, as_attachment=True, download_name="bowling.sqlite3")

# ---------- Like API aliases & debug ----------
# Accept both /api/game/<id>/like and /api/games/<id>/like, via POST/PUT/GET for flexibility
@app.route("/api/game/<int:gid>/like", methods=["POST","PUT"])
def api_like_game_post_put(gid):
    return api_like_game(gid)

@app.route("/api/games/<int:gid>/like", methods=["POST","PUT","GET"])
def api_like_game_alias(gid):
    # GET is treated as an increment for quick testing; switch to POST/PUT in production
    return api_like_game(gid)

@app.get("/api/debug/session/<int:sid>")
def api_debug_session(sid):
    # Quick helper to verify that games have valid IDs
    return api_session_games(sid)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
