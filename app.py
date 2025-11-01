from flask import Flask, g, jsonify, request, send_file, render_template, abort
import sqlite3
import os
from datetime import date, timedelta, datetime

# ---------- Paths ----------
APP_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.environ.get(
    "BOWLING_DB",
    r"C:\sites\bowling\bowling.sqlite3" if os.name == "nt" else os.path.join(APP_DIR, "bowling.sqlite3")
)

TIPS_PATH = os.path.join(APP_DIR, "365_bowling_tips.txt")

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---------- Tips ----------
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

# ---------- DB Helpers ----------
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

def _column_exists(db, table, col):
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"].lower() == col.lower() for r in rows)

def ensure_defaults():
    """Seed reference data and evolve schema safely."""
    db = get_db()

    # alleys
    for name in [
        "Zodos Lanes", "Camarillo Bowl", "Sunset Lanes", "Lilac Lanes",
        "North Bowl", "Winnetka Bowl", "Milwaukie Bowl"
    ]:
        db.execute("INSERT OR IGNORE INTO alleys (name) VALUES (?)", (name,))

    # bowlers
    for name, grp in [
        ("Rajan", "A"), ("Medina", "A"),
        ("Baule", "B"), ("Barsotti", "B"), ("RJB", "B")
    ]:
        db.execute("INSERT OR IGNORE INTO bowlers (name, bix_group) VALUES (?,?)", (name, grp))
        db.execute(
            "UPDATE bowlers SET bix_group=? WHERE name=? AND (bix_group IS NULL OR bix_group='')",
            (grp, name)
        )

    # games.like_count
    if not _column_exists(db, "games", "like_count"):
        db.execute("ALTER TABLE games ADD COLUMN like_count INTEGER DEFAULT 0")

    # games.created_at
    if not _column_exists(db, "games", "created_at"):
        try:
            db.execute("ALTER TABLE games ADD COLUMN created_at TEXT DEFAULT (datetime('now'))")
        except Exception:
            pass

    # game_reactions
    db.execute("""
        CREATE TABLE IF NOT EXISTS game_reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            user_name TEXT,
            comment TEXT,
            is_like INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_game_reactions_game_id ON game_reactions(game_id)"
    )
    db.commit()

@app.before_request
def ensure_db():
    if not os.path.exists(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        ensure_defaults()
    except Exception:
        pass

def rows_to_dicts(rows):
    return [dict(r) for r in rows]

# ---------- Utility: Compute stats ----------
def compute_session_stats(db, sid):
    row = db.execute(
        "SELECT ROUND(AVG(score),2) AS avg_score, MIN(score) AS low_score, MAX(score) AS high_score, COUNT(*) AS games_count "
        "FROM games WHERE session_id=?",
        (sid,),
    ).fetchone()
    if not row or not row["games_count"]:
        return {"avg": None, "low": None, "high": None, "count": 0}
    return {
        "avg": float(row["avg_score"]),
        "low": row["low_score"],
        "high": row["high_score"],
        "count": row["games_count"],
    }

# ---------- Routes ----------
@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/lookups")
def api_lookups():
    db = get_db()
    bowlers = rows_to_dicts(db.execute("SELECT id,name,bix_group FROM bowlers ORDER BY name"))
    alleys = rows_to_dicts(
        db.execute("SELECT id,name FROM alleys WHERE name!='Milwaukie Lanes' ORDER BY name")
    )
    return jsonify({"bowlers": bowlers, "alleys": alleys})

# ---------- Sessions (list + detail) ----------
@app.get("/api/sessions")
def api_sessions():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.id, s.session_date, b.name AS bowler, a.name AS alley,
               (SELECT COUNT(*) FROM games WHERE session_id=s.id) AS games,
               (SELECT ROUND(AVG(score),2) FROM games WHERE session_id=s.id) AS session_avg
        FROM sessions s
        JOIN bowlers b ON b.id=s.bowler_id
        JOIN alleys a ON a.id=s.alley_id
        ORDER BY s.session_date DESC, b.name
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/session/<int:sid>/games")
def api_session_games(sid):
    db = get_db()
    sess = db.execute(
        "SELECT s.id, s.session_date, b.name AS bowler, a.name AS alley "
        "FROM sessions s JOIN bowlers b ON b.id=s.bowler_id "
        "JOIN alleys a ON a.id=s.alley_id WHERE s.id=?",
        (sid,),
    ).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    has_created_at = _column_exists(db, "games", "created_at")
    if has_created_at:
        games = rows_to_dicts(
            db.execute(
                "SELECT id, game_number, score, COALESCE(like_count,0) AS like_count, created_at "
                "FROM games WHERE session_id=? ORDER BY game_number",
                (sid,),
            )
        )
    else:
        games = rows_to_dicts(
            db.execute(
                "SELECT id, game_number, score, COALESCE(like_count,0) AS like_count "
                "FROM games WHERE session_id=? ORDER BY game_number",
                (sid,),
            )
        )
        for g in games:
            g["created_at"] = None

    # Attach comments per game
    for g in games:
        g["comments"] = rows_to_dicts(
            db.execute(
                "SELECT id, user_name, comment, created_at FROM game_reactions "
                "WHERE game_id=? AND (comment IS NOT NULL AND comment!='') "
                "ORDER BY id DESC",
                (g["id"],),
            )
        )

    stats = compute_session_stats(db, sid)
    return jsonify(
        {
            "id": sess["id"],
            "session_date": sess["session_date"],
            "bowler": sess["bowler"],
            "alley": sess["alley"],
            "games": games,
            "stats": stats,
        }
    )

# ---------- NEW: Create/append sessions ----------
@app.post("/api/session")
def api_create_or_append_session():
    """
    Creates a session for (bowler_id, alley_id, session_date) if not exists,
    then inserts provided scores (max 12 total per session).
    Request JSON: { bowler_id, alley_id, session_date: 'YYYY-MM-DD', scores: [int,...] }
    """
    db = get_db()
    data = request.get_json(silent=True) or {}
    bowler_id = int(data.get("bowler_id") or 0)
    alley_id = int(data.get("alley_id") or 0)
    session_date = (data.get("session_date") or "").strip()
    scores = data.get("scores") or []

    if not bowler_id or not alley_id or not session_date:
        return jsonify({"error": "bowler_id, alley_id, session_date required"}), 400
    if not isinstance(scores, list) or not scores:
        return jsonify({"error": "scores array required"}), 400

    # Find or create session
    row = db.execute(
        "SELECT id FROM sessions WHERE bowler_id=? AND alley_id=? AND session_date=?",
        (bowler_id, alley_id, session_date)
    ).fetchone()
    if row:
        sid = row["id"]
    else:
        db.execute(
            "INSERT INTO sessions (bowler_id, alley_id, session_date) VALUES (?,?,?)",
            (bowler_id, alley_id, session_date)
        )
        db.commit()
        sid = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    # current count / next game_number
    cur = db.execute("SELECT COUNT(*) FROM games WHERE session_id=?", (sid,)).fetchone()[0] or 0
    if cur >= 12:
        return jsonify({"error": "This session already has 12 games."}), 400

    next_num = cur + 1
    to_add = []
    for s in scores:
        try:
            sc = int(s)
        except Exception:
            return jsonify({"error": f"Invalid score: {s}"}), 400
        if sc < 1 or sc > 300:
            return jsonify({"error": "Scores must be 1–300"}), 400
        if next_num > 12:
            break
        to_add.append((sid, next_num, sc))
        next_num += 1

    if not to_add:
        return jsonify({"error": "No scores were added (limit is 12 per session)."}), 400

    db.executemany(
        "INSERT INTO games (session_id, game_number, score) VALUES (?,?,?)",
        to_add
    )
    db.commit()

    return jsonify({"ok": True, "session_id": sid, "added": len(to_add)})

@app.post("/api/sessions/<int:sid>/games")
def api_add_game_to_session(sid):
    """Append one game to an existing session, enforcing the 12-game cap. JSON: {score:int}"""
    db = get_db()
    sess = db.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchone()
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        score = int(data.get("score"))
    except Exception:
        return jsonify({"error": "score required"}), 400
    if score < 1 or score > 300:
        return jsonify({"error": "Score must be 1–300"}), 400

    cur = db.execute("SELECT COUNT(*) FROM games WHERE session_id=?", (sid,)).fetchone()[0] or 0
    if cur >= 12:
        return jsonify({"error": "This session already has 12 games."}), 400

    next_num = cur + 1
    db.execute(
        "INSERT INTO games (session_id, game_number, score) VALUES (?,?,?)",
        (sid, next_num, score)
    )
    db.commit()
    return jsonify({"ok": True, "game_number": next_num})

# ---------- Likes & Comments ----------
@app.post("/api/games/<int:gid>/like")
def api_like_game(gid):
    db = get_db()
    game = db.execute("SELECT id FROM games WHERE id=?", (gid,)).fetchone()
    if not game:
        return jsonify({"error": "Invalid game ID"}), 404

    data = request.get_json(silent=True) or {}
    user_name = (data.get("user_name") or "").strip() or None
    comment = (data.get("comment") or "").strip() or None

    db.execute(
        "INSERT INTO game_reactions (game_id, user_name, comment, is_like) VALUES (?,?,?,1)",
        (gid, user_name, comment),
    )
    db.execute("UPDATE games SET like_count=COALESCE(like_count,0)+1 WHERE id=?", (gid,))
    db.commit()

    likes = db.execute(
        "SELECT COALESCE(like_count,0) FROM games WHERE id=?", (gid,)
    ).fetchone()[0]
    comments = rows_to_dicts(
        db.execute(
            "SELECT id, user_name, comment, created_at FROM game_reactions "
            "WHERE game_id=? AND (comment IS NOT NULL AND comment!='') ORDER BY id DESC",
            (gid,),
        )
    )
    return jsonify({"ok": True, "likes": likes, "comments": comments})

# ---------- Totals (includes comments) ----------
@app.get("/api/totals")
def api_totals():
    db = get_db()
    bowlers = rows_to_dicts(db.execute("SELECT id,name,bix_group FROM bowlers ORDER BY name"))
    totals = []
    bix_by_name = {}

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
            bix += 0.25 * c150

        return {
            "avg": round(avg, 2) if games_count else 0.0,
            "games": games_count,
            "c200": c200, "c210": c210, "c250": c250, "c300": c300, "c150": c150,
            "bix": round(bix, 2)
        }

    for b in bowlers:
        met = compute_bix_for_bowler(db, b["id"], b["bix_group"])
        alleys = compute_alley_breakdown(db, b["id"])

        # Likes
        likes = db.execute(
            "SELECT COALESCE(SUM(like_count),0) FROM games "
            "WHERE session_id IN (SELECT id FROM sessions WHERE bowler_id=?)",
            (b["id"],)
        ).fetchone()[0] or 0

        # Comments count
        comments_count = db.execute(
            """
            SELECT COUNT(*) FROM game_reactions gr
            JOIN games g ON g.id=gr.game_id
            JOIN sessions s ON s.id=g.session_id
            WHERE s.bowler_id=? AND gr.comment IS NOT NULL AND gr.comment<>''
            """,
            (b["id"],),
        ).fetchone()[0] or 0

        # Recent comments (10)
        recent_comments = rows_to_dicts(
            db.execute(
                """
                SELECT gr.id, COALESCE(gr.user_name,'') AS user_name, gr.comment, gr.created_at,
                       g.id AS game_id, g.game_number, s.session_date, a.name AS alley
                FROM game_reactions gr
                JOIN games g ON g.id=gr.game_id
                JOIN sessions s ON s.id=g.session_id
                JOIN alleys a ON a.id=s.alley_id
                WHERE s.bowler_id=? AND gr.comment IS NOT NULL AND gr.comment<>''
                ORDER BY gr.id DESC LIMIT 10
                """,
                (b["id"],),
            )
        )

        totals.append({
            "name": b["name"],
            "bix_group": b["bix_group"],
            **met,
            "alleys": alleys,
            "likes": int(likes),
            "comments_count": int(comments_count),
            "comments_recent": recent_comments
        })
        bix_by_name[b["name"]] = met["bix"]

    # Rivalry line (Rajan vs Medina), monthly avgs, and total likes — expected by UI
    r_bix = bix_by_name.get("Rajan")
    m_bix = bix_by_name.get("Medina")
    bix_msg = None
    if isinstance(r_bix, (int, float)) and isinstance(m_bix, (int, float)):
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
    by_name = {"Rajan": {}, "Medina": {}}
    for r in monthly_rows:
        by_name.setdefault(r["name"], {})[r["ym"]] = round(r["avg_score"], 2) if r["avg_score"] is not None else None

    total_likes = db.execute("SELECT COALESCE(SUM(like_count),0) FROM games").fetchone()[0] or 0

    return jsonify({
        "totals": totals,
        "bix_message": bix_msg,
        "monthly_avgs": by_name,
        "tip_of_day": tip_for_today(),
        "total_likes": total_likes
    })

# ---------- NEW: Honor Roll + Likes total ----------
def _week_range(d: date):
    # Monday..Sunday for the week containing d
    start = d - timedelta(days=(d.weekday()))
    end = start + timedelta(days=6)
    return start, end

@app.get("/api/honor-roll")
def api_honor_roll():
    db = get_db()
    today = date.today()
    wk_start, wk_end = _week_range(today)
    mo_start = today.replace(day=1)
    # month end: next month minus one day
    if mo_start.month == 12:
        next_month = mo_start.replace(year=mo_start.year+1, month=1, day=1)
    else:
        next_month = mo_start.replace(month=mo_start.month+1, day=1)
    mo_end = next_month - timedelta(days=1)

    def fmt(d): return d.strftime("%Y-%m-%d")

    def top_scores(d1, d2, limit=3):
        rows = db.execute(
            """
            SELECT g.score, b.name AS bowler, s.session_date, a.name AS alley
            FROM games g
            JOIN sessions s ON s.id=g.session_id
            JOIN bowlers b ON b.id=s.bowler_id
            JOIN alleys a ON a.id=s.alley_id
            WHERE s.session_date BETWEEN ? AND ?
            ORDER BY g.score DESC, s.session_date DESC
            LIMIT ?
            """,
            (fmt(d1), fmt(d2), limit)
        ).fetchall()
        return [dict(score=r["score"], bowler=r["bowler"], session_date=r["session_date"], alley=r["alley"]) for r in rows]

    def top_avgs(d1, d2, limit=3):
        rows = db.execute(
            """
            SELECT b.name AS bowler, ROUND(AVG(g.score),2) AS avg_score, COUNT(*) AS games
            FROM games g
            JOIN sessions s ON s.id=g.session_id
            JOIN bowlers b ON b.id=s.bowler_id
            WHERE s.session_date BETWEEN ? AND ?
            GROUP BY b.name
            HAVING COUNT(*) >= 3
            ORDER BY avg_score DESC
            LIMIT ?
            """,
            (fmt(d1), fmt(d2), limit)
        ).fetchall()
        return [dict(bowler=r["bowler"], avg=float(r["avg_score"]), games=r["games"]) for r in rows]

    # Year top score
    y_start = today.replace(month=1, day=1)
    y_end = today.replace(month=12, day=31)
    yrow = db.execute(
        """
        SELECT g.score, b.name AS bowler, s.session_date, a.name AS alley
        FROM games g
        JOIN sessions s ON s.id=g.session_id
        JOIN bowlers b ON b.id=s.bowler_id
        JOIN alleys a ON a.id=s.alley_id
        WHERE s.session_date BETWEEN ? AND ?
        ORDER BY g.score DESC, s.session_date DESC
        LIMIT 1
        """,
        (fmt(y_start), fmt(y_end))
    ).fetchone()
    year_top = None
    if yrow:
        year_top = {
            "score": yrow["score"],
            "bowler": yrow["bowler"],
            "session_date": yrow["session_date"],
            "alley": yrow["alley"],
        }

    return jsonify({
        "week": {
            "range": [fmt(wk_start), fmt(wk_end)],
            "top_scores": top_scores(wk_start, wk_end),
            "top_avgs": top_avgs(wk_start, wk_end),
        },
        "month": {
            "range": [fmt(mo_start), fmt(mo_end)],
            "top_scores": top_scores(mo_start, mo_end),
            "top_avgs": top_avgs(mo_start, mo_end),
        },
        "year": {
            "top_score": year_top
        }
    })

@app.get("/api/likes/total")
def api_likes_total():
    db = get_db()
    total = db.execute("SELECT COALESCE(SUM(like_count),0) FROM games").fetchone()[0] or 0
    return jsonify({"total_likes": int(total)})

# ---------- Debug ----------
@app.get("/api/debug/diag")
def api_debug_diag():
    db = get_db()
    def cols(t):
        return [dict(r) for r in db.execute(f"PRAGMA table_info({t})").fetchall()]
    return jsonify(
        {
            "db_path": DB_PATH,
            "exists": os.path.exists(DB_PATH),
            "tables": {
                "games": cols("games"),
                "sessions": cols("sessions"),
                "bowlers": cols("bowlers"),
                "alleys": cols("alleys"),
                "game_reactions": cols("game_reactions"),
            },
        }
    )

# ---------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
