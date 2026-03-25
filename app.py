from flask import Flask, g, jsonify, request, render_template
import sqlite3, os
import re
from datetime import date, datetime, timedelta
from math import sqrt

# --- Display helpers ---
NAME_ALIASES = {"Steve Baule": "Baule"}

def display_bowler(name: str) -> str:
    return NAME_ALIASES.get(name, name)

# ---------- Paths ----------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "BOWLING_DB",
    r"C:\sites\bowling\bowling.sqlite3" if os.name == "nt" else os.path.join(APP_DIR, "bowling.sqlite3")
)

app = Flask(__name__, template_folder="templates", static_folder="static")

# ---------- DB ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db:
        db.close()

def current_year():
    return date.today().year

# ---------- Defaults (safe inserts) ----------
def ensure_defaults():
    db = get_db()

    
    def migrate_sessions_unique():
        """Allow up to two sessions per bowler per day (league + non-league).

        Desired rule:
          - A bowler may have **one league** AND **one non-league** session on the same date.
          - But they may NOT have two league (or two non-league) sessions on the same date.

        Enforced by UNIQUE(bowler_id, session_date, is_league).
        This handles both legacy table-level UNIQUE(bowler_id, session_date) constraints and
        legacy unique indexes that enforce (bowler_id, session_date) only.
        """
        row = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        if not row or not row[0]:
            return

        create_sql = row[0]
        lower_sql = create_sql.lower()

        # Detect the *specific* legacy constraint UNIQUE(bowler_id, session_date)
        # (Note: 'is_league' may exist elsewhere in the CREATE TABLE even in legacy DBs.)
        legacy_unique_clause = re.search(
            r"unique\s*\(\s*bowler_id\s*,\s*session_date\s*\)",
            lower_sql
        ) is not None

        # Also detect legacy unique INDEX enforcing only (bowler_id, session_date)
        idx_rows = db.execute("PRAGMA index_list(sessions)").fetchall()
        legacy_unique_index_name = None
        for ir in idx_rows:
            # ir columns: (seq, name, unique, origin, partial)
            if int(ir[2]) != 1:
                continue
            idx_name = ir[1]
            cols = [c[2] for c in db.execute(f"PRAGMA index_info({idx_name})").fetchall()]
            if cols == ["bowler_id", "session_date"]:
                legacy_unique_index_name = idx_name
                break

        # If the legacy uniqueness is a *table constraint* (autoindex), rebuild.
        if legacy_unique_clause:
            cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
            db.execute("ALTER TABLE sessions RENAME TO sessions_old")
            db.execute(
                """
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bowler_id INTEGER NOT NULL,
                    alley_id INTEGER NOT NULL,
                    session_date TEXT NOT NULL,
                    is_league INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(bowler_id, session_date, is_league),
                    FOREIGN KEY(bowler_id) REFERENCES bowlers(id),
                    FOREIGN KEY(alley_id) REFERENCES alleys(id)
                )
                """
            )

            if "is_league" in cols:
                db.execute(
                    """
                    INSERT INTO sessions(id, bowler_id, alley_id, session_date, is_league)
                    SELECT id, bowler_id, alley_id, session_date, COALESCE(is_league,0)
                    FROM sessions_old
                    """
                )
            else:
                db.execute(
                    """
                    INSERT INTO sessions(id, bowler_id, alley_id, session_date, is_league)
                    SELECT id, bowler_id, alley_id, session_date, 0
                    FROM sessions_old
                    """
                )

            db.execute("DROP TABLE sessions_old")
            # Also add an explicit unique index (harmless) for query planners / clarity.
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_bowler_date_type ON sessions(bowler_id, session_date, is_league)"
            )
            return

        # If legacy uniqueness is enforced by a droppable unique index, drop it.
        if legacy_unique_index_name and not legacy_unique_index_name.startswith("sqlite_autoindex"):
            db.execute(f"DROP INDEX IF EXISTS {legacy_unique_index_name}")

        # Ensure correct uniqueness going forward.
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_bowler_date_type ON sessions(bowler_id, session_date, is_league)"
        )
        return


    # Create tables if missing (minimal schema expected by app)
    db.execute("""
    CREATE TABLE IF NOT EXISTS bowlers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        bix_group TEXT NOT NULL
    )""")
    db.execute("""
    CREATE TABLE IF NOT EXISTS alleys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )""")
    db.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bowler_id INTEGER NOT NULL,
        alley_id INTEGER NOT NULL,
        session_date TEXT NOT NULL,
        is_league INTEGER NOT NULL DEFAULT 0,
        notes TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(bowler_id) REFERENCES bowlers(id),
        FOREIGN KEY(alley_id) REFERENCES alleys(id)
    )""")

    # --- Lightweight migrations ---
    # Add is_league column if upgrading an existing DB
    cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
    if "is_league" not in cols:
        db.execute("ALTER TABLE sessions ADD COLUMN is_league INTEGER NOT NULL DEFAULT 0")

    # Add notes column (session notes)
    cols = [r[1] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
    if "notes" not in cols:
        db.execute("ALTER TABLE sessions ADD COLUMN notes TEXT NOT NULL DEFAULT \'\'")

    # Ensure uniqueness constraint allows league + non-league on the same date.
    migrate_sessions_unique()

    db.execute("""
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        game_number INTEGER NOT NULL,
        score INTEGER NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )""")

    # Seed alleys
    for a in [
        "Zodos Lanes","Camarillo Bowl","Sunset Lanes","Lilac Lanes",
        "North Bowl","Winnetka Bowl","Milwaukie Bowl"
    ]:
        db.execute("INSERT OR IGNORE INTO alleys(name) VALUES(?)", (a,))

    # Seed bowlers (Group A uses Rajan/Medina calculation)
    for name, grp in [
        ("Rajan","A"),("Medina","A"),("William","A"),("Edward","A"),("Larry","A"),
        ("Baule","B"),("Pete Barsotti", "B"),("Barsotti","B"),("RJB","B")
    ]:
        db.execute("INSERT OR IGNORE INTO bowlers(name,bix_group) VALUES(?,?)", (name, grp))

    db.commit()

@app.before_request
def _init():
    ensure_defaults()

# ---------- Diagnostics ----------
@app.get("/api/_whoami")
def whoami():
    return jsonify({"file": os.path.abspath(__file__), "cwd": os.getcwd()})

# ---------- Pages ----------
@app.get("/")
def home():
    return render_template("index.html")

# ---------- Lookups ----------
@app.get("/api/lookups")
def lookups():
    db = get_db()
    return jsonify({
        "bowlers": [dict(r) for r in db.execute("SELECT id,name,bix_group FROM bowlers ORDER BY name")],
        "alleys": [dict(r) for r in db.execute("SELECT id,name FROM alleys ORDER BY name")]
    })

# ---------- Add Alley ----------
@app.post("/api/alleys")
def add_alley():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error":"Alley name required"}), 400
    db = get_db()
    exists = db.execute("SELECT id FROM alleys WHERE LOWER(name)=LOWER(?)", (name,)).fetchone()
    if exists:
        return jsonify({"error":"Alley already exists"}), 400
    db.execute("INSERT INTO alleys(name) VALUES(?)", (name,))
    db.commit()
    return jsonify({"ok": True, "name": name})

# ---------- Sessions (current year) ----------
@app.get("/api/sessions")
def sessions():
    db = get_db()
    y = str(current_year())
    rows = db.execute(
        """
        SELECT s.id, s.session_date, b.name AS bowler, a.name AS alley,
               s.is_league AS is_league,
               COALESCE(s.notes,'') AS notes,
               COUNT(g.id) AS games, ROUND(AVG(g.score),2) AS session_avg
        FROM sessions s
        JOIN bowlers b ON b.id=s.bowler_id
        JOIN alleys a ON a.id=s.alley_id
        JOIN games g ON g.session_id=s.id
        WHERE strftime('%Y', s.session_date)=?
        GROUP BY s.id
        ORDER BY s.session_date DESC, b.name
        """, (y,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- League Sessions (current year) ----------
@app.get("/api/league-sessions")
def league_sessions():
    db = get_db()
    y = str(current_year())
    rows = db.execute(
        """
        SELECT s.id AS session_id, s.session_date, b.name AS bowler, a.name AS alley,
               COUNT(g.id) AS games,
               COALESCE(SUM(g.score),0) AS total_pins,
               ROUND(AVG(g.score),0) AS session_avg
        FROM sessions s
        JOIN bowlers b ON b.id=s.bowler_id
        JOIN alleys a ON a.id=s.alley_id
        JOIN games g ON g.session_id=s.id
        WHERE s.is_league=1 AND strftime('%Y', s.session_date)=?
        GROUP BY s.id
        ORDER BY s.session_date DESC, b.name
        """,
        (y,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # ensure ints for display
        d["total_pins"] = int(d.get("total_pins") or 0)
        d["session_avg"] = int(d.get("session_avg") or 0)
        out.append(d)
    return jsonify(out)

# ---------- League Standings (current year) ----------
@app.get("/api/league-standings")
def league_standings():
    db = get_db()
    y = str(current_year())

    # aggregate league-only stats per bowler
    rows = db.execute(
        """
        SELECT b.id AS bowler_id, b.name AS name, b.bix_group AS bix_group,
               COUNT(g.id) AS games,
               COALESCE(SUM(g.score),0) AS total_pins,
               AVG(g.score) AS avg,
               COALESCE(SUM(CASE WHEN g.score>=200 THEN 1 ELSE 0 END),0) AS c200,
               COALESCE(SUM(CASE WHEN g.score>=210 THEN 1 ELSE 0 END),0) AS c210,
               COALESCE(SUM(CASE WHEN g.score>=250 THEN 1 ELSE 0 END),0) AS c250,
               COALESCE(SUM(CASE WHEN g.score=300 THEN 1 ELSE 0 END),0) AS c300,
               COALESCE(SUM(CASE WHEN g.score>=150 THEN 1 ELSE 0 END),0) AS c150
        FROM bowlers b
        LEFT JOIN sessions s ON s.bowler_id=b.id AND s.is_league=1 AND strftime('%Y', s.session_date)=?
        LEFT JOIN games g ON g.session_id=s.id
        GROUP BY b.id, b.name, b.bix_group
        ORDER BY avg DESC
        """,
        (y,)
    ).fetchall()

    standings = []
    for r in rows:
        games = int(r["games"] or 0)
        total_pins = int(r["total_pins"] or 0)
        avg_raw = float(r["avg"] or 0.0)
        avg_round = int(round(avg_raw)) if games else 0
        bix = compute_bix(r["bix_group"], avg_raw, int(r["c150"] or 0), int(r["c210"] or 0), int(r["c250"] or 0), int(r["c300"] or 0))
        standings.append({
            "bowler_id": r["bowler_id"],
            "name": display_bowler(r["name"]),
            "bix_group": r["bix_group"],
            "games": games,
            "total_pins": total_pins,
            "avg": avg_round,
            "bix": round(bix, 2),
        })

    # league-only BIX table for the A-group rivals
    rivals = ["Rajan", "Medina", "William", "Edward","Larry",]
    riv = [s for s in standings if s["name"] in rivals]
    riv.sort(key=lambda x: x["bix"], reverse=True)
    leader = riv[0]["bix"] if riv else 0.0
    league_bix_table = [
        {"name": r["name"], "bix": r["bix"], "diff": round(r["bix"] - leader, 2), "leader": (r["bix"] == leader)}
        for r in riv
    ]

    return jsonify({"standings": standings, "league_bix_table": league_bix_table})

@app.get("/api/session/<int:sid>/games")
def session_games(sid):
    db = get_db()
    s = db.execute(
        """
        SELECT s.session_date, b.name AS bowler, a.name AS alley, s.is_league AS is_league
        FROM sessions s
        JOIN bowlers b ON b.id=s.bowler_id
        JOIN alleys a ON a.id=s.alley_id
        WHERE s.id=?
        """, (sid,)
    ).fetchone()
    games = db.execute(
        "SELECT id, game_number, score FROM games WHERE session_id=? ORDER BY game_number",
        (sid,)
    ).fetchall()

    scores = [g["score"] for g in games]
    stats = {
        "avg": (sum(scores)/len(scores)) if scores else None,
        "low": min(scores) if scores else None,
        "high": max(scores) if scores else None
    }
    return jsonify({
        "session_date": s["session_date"] if s else None,
        "bowler": s["bowler"] if s else None,
        "alley": s["alley"] if s else None,
        "is_league": int(s["is_league"]) if s and s["is_league"] is not None else 0,
        "games": [dict(r) for r in games],
        "stats": stats
    })

@app.post("/api/session")
def create_session():
    data = request.get_json(force=True)
    bowler_id = int(data["bowler_id"])
    alley_id = int(data["alley_id"])
    session_date = data["session_date"]
    is_league = 1 if bool(data.get("is_league")) else 0
    notes = (data.get("notes") or "").strip()
    scores = data.get("scores") or []
    if not scores:
        return jsonify({"error":"Enter at least one score."}), 400
    if len(scores) > 12:
        return jsonify({"error":"Max 12 games."}), 400
    if any((not isinstance(s,int)) or s<1 or s>300 for s in scores):
        return jsonify({"error":"Scores must be 1-300."}), 400

    db = get_db()
    # Allow up to two sessions per bowler per day IF one is league and one is non-league.
    # Block only duplicates of the same type (league vs non-league).
    exists = db.execute(
        "SELECT id FROM sessions WHERE bowler_id=? AND session_date=? AND is_league=?",
        (bowler_id, session_date, is_league)
    ).fetchone()
    if exists:
        return jsonify({"error":"Session already exists for this bowler/date/type (league vs non-league). Edit it from Sessions."}), 400

    cur = db.execute(
        "INSERT INTO sessions(bowler_id, alley_id, session_date, is_league, notes) VALUES(?,?,?,?,?)",
        (bowler_id, alley_id, session_date, is_league, notes)
    )
    sid = cur.lastrowid
    for i, sc in enumerate(scores, start=1):
        db.execute(
            "INSERT INTO games(session_id, game_number, score) VALUES(?,?,?)",
            (sid, i, int(sc))
        )
    db.commit()
    return jsonify({"ok": True, "session_id": sid})

@app.post("/api/sessions/<int:sid>/games")
def add_game_to_session(sid):
    data = request.get_json(force=True)
    score = int(data.get("score") or 0)
    if score < 1 or score > 300:
        return jsonify({"error":"Score must be 1-300."}), 400
    db = get_db()
    cnt = db.execute("SELECT COUNT(*) AS c FROM games WHERE session_id=?", (sid,)).fetchone()["c"]
    if cnt >= 12:
        return jsonify({"error":"Max 12 games per session."}), 400
    db.execute(
        "INSERT INTO games(session_id, game_number, score) VALUES(?,?,?)",
        (sid, cnt+1, score)
    )
    db.commit()
    return jsonify({"ok": True})


# ---------- Edit session meta (league vs non-league) ----------
@app.put("/api/sessions/<int:sid>")
def update_session(sid: int):
    data = request.get_json(silent=True) or {}

    # Allow partial updates (is_league and/or notes)
    has_is_league = "is_league" in data
    has_notes = "notes" in data
    if not has_is_league and not has_notes:
        return jsonify({"error": "Provide is_league and/or notes."}), 400

    is_league = None
    if has_is_league:
        is_league = 1 if bool(data.get("is_league")) else 0

    notes = None
    if has_notes:
        notes = (data.get("notes") or "").strip()

    db = get_db()
    s = db.execute(
        "SELECT id, bowler_id, session_date, COALESCE(is_league,0) AS is_league, COALESCE(notes,'') AS notes FROM sessions WHERE id=?",
        (sid,),
    ).fetchone()
    if not s:
        return jsonify({"error": "Session not found."}), 404

    # If changing league flag, prevent conflicts: (bowler_id, session_date, is_league) must remain unique
    if has_is_league and int(s["is_league"] or 0) != is_league:
        conflict = db.execute(
            "SELECT id FROM sessions WHERE bowler_id=? AND session_date=? AND is_league=? AND id<>?",
            (int(s["bowler_id"]), s["session_date"], is_league, sid),
        ).fetchone()
        if conflict:
            return jsonify({"error": "Cannot change league flag: a session already exists for this bowler/date with that type."}), 400
        db.execute("UPDATE sessions SET is_league=? WHERE id=?", (is_league, sid))

    # Notes update
    if has_notes and (s["notes"] or "") != notes:
        db.execute("UPDATE sessions SET notes=? WHERE id=?", (notes, sid))

    db.commit()
    return jsonify({
        "ok": True,
        "session_id": sid,
        "is_league": int(is_league if has_is_league else (s["is_league"] or 0)),
        "notes": notes if has_notes else (s["notes"] or "")
    })

# ---------- Edit/Delete single game (used by modal) ----------
@app.put("/api/games/<int:gid>")
def update_game(gid: int):
    data = request.get_json(silent=True) or {}
    score = int(data.get("score") or 0)
    if score < 1 or score > 300:
        return jsonify({"error": "Score must be 1-300."}), 400
    db = get_db()
    g_row = db.execute("SELECT session_id FROM games WHERE id=?", (gid,)).fetchone()
    if not g_row:
        return jsonify({"error": "Game not found."}), 404
    db.execute("UPDATE games SET score=? WHERE id=?", (score, gid))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/games/<int:gid>")
def delete_game(gid: int):
    db = get_db()
    g_row = db.execute("SELECT session_id FROM games WHERE id=?", (gid,)).fetchone()
    if not g_row:
        return jsonify({"error": "Game not found."}), 404
    sid = int(g_row["session_id"])
    db.execute("DELETE FROM games WHERE id=?", (gid,))
    # Renumber remaining games
    remaining = db.execute(
        "SELECT id FROM games WHERE session_id=? ORDER BY game_number", (sid,)
    ).fetchall()
    for i, r in enumerate(remaining, start=1):
        db.execute("UPDATE games SET game_number=? WHERE id=?", (i, r["id"]))
    # If no games remain, delete the now-empty session
    if not remaining:
        db.execute("DELETE FROM sessions WHERE id=?", (sid,))
    db.commit()
    return jsonify({"ok": True})

# ---------- Totals + BIX leaderboard ----------
def compute_bix(bix_group: str, avg: float, c150: int, c210: int, c250: int, c300: int) -> float:
    bix = avg
    if bix_group == "A":
        bix += 0.25 * c210
        bix += 0.50 * c250
        bix += 2.50 * c300
    else:
        bix += 0.25 * c150
    return bix

@app.get("/api/totals")
def totals():
    db = get_db()
    y = str(current_year())

    totals_rows = []
    for b in db.execute("SELECT id,name,bix_group FROM bowlers ORDER BY name"):
        row = db.execute(
            """
            SELECT COALESCE(COUNT(g.id),0) AS games, COALESCE(AVG(g.score),0) AS avg,
                   COALESCE(SUM(g.score * g.score),0) AS sumsq,
                   COALESCE(SUM(CASE WHEN g.score>=200 THEN 1 ELSE 0 END),0) AS c200,
                   COALESCE(SUM(CASE WHEN g.score>=210 THEN 1 ELSE 0 END),0) AS c210,
                   SUM(g.score>=250) AS c250,
                   SUM(g.score=300)  AS c300,
                   COALESCE(SUM(CASE WHEN g.score>=150 THEN 1 ELSE 0 END),0) AS c150
            FROM games g
            JOIN sessions s ON s.id=g.session_id
            WHERE s.bowler_id=? AND strftime('%Y', s.session_date)=?
            """, (b["id"], y),
        ).fetchone()
        games = row["games"] or 0
        avg = float(row["avg"] or 0.0)
        sumsq = float(row["sumsq"] or 0.0)
        # Population standard deviation across all games for the year
        if games:
            ex2 = (sumsq / games)
            var = ex2 - (avg * avg)
            if var < 0 and var > -1e-9:
                var = 0.0
            stddev = sqrt(var) if var > 0 else 0.0
        else:
            stddev = 0.0
        c150 = row["c150"] or 0
        c200 = row["c200"] or 0
        c210 = row["c210"] or 0
        c250 = row["c250"] or 0
        c300 = row["c300"] or 0
        bix = compute_bix(b["bix_group"], avg, c150, c210, c250, c300)

        # Alley breakdown
        alleys = db.execute(
            """
            SELECT a.id AS alley_id, a.name AS alley,
                   COUNT(g.id) AS games,
                   AVG(g.score) AS avg
            FROM games g
            JOIN sessions s ON s.id=g.session_id
            JOIN alleys a ON a.id=s.alley_id
            WHERE s.bowler_id=? AND strftime('%Y', s.session_date)=?
            GROUP BY a.id, a.name
            ORDER BY a.name
            """, (b["id"], y)
        ).fetchall()

        # Conversion rate (lifetime): group A tracks 200+, group B tracks 150+
        if b["bix_group"] == "A":
            conversion_label = "200+ Conv"
            conversion_hits = c200
        else:
            conversion_label = "150+ Conv"
            conversion_hits = c150

        conversion_rate = round((conversion_hits / games) * 100, 2) if games else 0.0

        totals_rows.append({
            "bowler_id": b["id"],
            "name": display_bowler(b["name"]),
            "bix_group": b["bix_group"],
            "games": games,
            "avg": round(avg, 2),
            "stddev": round(stddev, 2),
            "bix": round(bix, 2),
            "c200": c200, "c210": c210, "c150": c150,
            "conversion_rate": conversion_rate,
            "conversion_label": conversion_label,
            "alleys": [{"alley_id": r["alley_id"], "alley": r["alley"], "games": r["games"], "avg": round((r["avg"] or 0),2)} for r in alleys]
        })

    # 4-bowler leaderboard (A group rivals)
    rivals = ["Rajan","Medina","William","Edward","Larry"]
    riv = [r for r in totals_rows if r["name"] in rivals]
    riv.sort(key=lambda x: x["bix"], reverse=True)
    leader_bix = riv[0]["bix"] if riv else 0.0
    leaderboard = []
    for r in riv:
        leaderboard.append({
            "name": r["name"],
            "bix": r["bix"],
            "diff": round(r["bix"] - leader_bix, 2),
            "leader": (r["bix"] == leader_bix)
        })

    return jsonify({"totals": totals_rows, "bix_table": leaderboard})

# ---------- Alley drilldown ----------
@app.get("/api/bowlers/<int:bowler_id>/alleys/<int:alley_id>/games")
def games_by_alley(bowler_id, alley_id):
    db = get_db()
    y = str(current_year())
    rows = db.execute(
        """
        SELECT s.session_date, g.game_number, g.score
        FROM games g
        JOIN sessions s ON s.id=g.session_id
        WHERE s.bowler_id=? AND s.alley_id=? AND strftime('%Y', s.session_date)=?
        ORDER BY s.session_date DESC, g.game_number
        """, (bowler_id, alley_id, y)
    ).fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- Honor Roll (includes special congrats for month high score) ----------
def _date_bounds_week(today: date):
    # week starts Monday
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end

@app.get("/api/honor-roll")
def honor_roll():
    db = get_db()
    today = date.today()

    wk_start, wk_end = _date_bounds_week(today)
    mo_start = today.replace(day=1)
    # month end
    if mo_start.month == 12:
        mo_end = mo_start.replace(year=mo_start.year+1, month=1, day=1) - timedelta(days=1)
    else:
        mo_end = mo_start.replace(month=mo_start.month+1, day=1) - timedelta(days=1)

    y_start = date(today.year, 1, 1)
    y_end = date(today.year, 12, 31)

    def top_scores(d1: date, d2: date, limit: int):
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
            """, (d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d"), limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def top_avgs(d1: date, d2: date, limit: int):
        rows = db.execute(
            """
            SELECT b.name AS bowler, COUNT(g.id) AS games, AVG(g.score) AS avg
            FROM games g
            JOIN sessions s ON s.id=g.session_id
            JOIN bowlers b ON b.id=s.bowler_id
            WHERE s.session_date BETWEEN ? AND ?
            GROUP BY b.id, b.name
            HAVING COUNT(g.id) >= 3
            ORDER BY AVG(g.score) DESC
            LIMIT ?
            """, (d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d"), limit)
        ).fetchall()
        out = []
        for r in rows:
            out.append({"bowler": r["bowler"], "games": r["games"], "avg": float(r["avg"])})
        return out

    week_scores = top_scores(wk_start, wk_end, 3)
    month_scores = top_scores(mo_start, mo_end, 3)
    year_scores = top_scores(y_start, y_end, 5)

    week_avgs = top_avgs(wk_start, wk_end, 3)
    month_avgs = top_avgs(mo_start, mo_end, 3)

    monthly_champion = month_scores[0] if month_scores else None

    return jsonify({
        "week": {"range": [wk_start.strftime("%Y-%m-%d"), wk_end.strftime("%Y-%m-%d")], "top_scores": week_scores, "top_avgs": week_avgs},
        "month": {"range": [mo_start.strftime("%Y-%m-%d"), mo_end.strftime("%Y-%m-%d")], "top_scores": month_scores, "top_avgs": month_avgs},
        "year": {"range": [y_start.strftime("%Y-%m-%d"), y_end.strftime("%Y-%m-%d")], "top_scores": year_scores},
        "months": [],  # keep shape compatible with older JS
        "monthly_champion": monthly_champion
    })

# ---------- High Scores (week/month/year/all-time) ----------
@app.get("/api/high-scores")
def high_scores():
    db = get_db()
    today = date.today()

    wk_start, wk_end = _date_bounds_week(today)
    mo_start = today.replace(day=1)
    if mo_start.month == 12:
        mo_end = mo_start.replace(year=mo_start.year+1, month=1, day=1) - timedelta(days=1)
    else:
        mo_end = mo_start.replace(month=mo_start.month+1, day=1) - timedelta(days=1)

    y_start = date(today.year, 1, 1)
    y_end = date(today.year, 12, 31)

    def best_between(d1: date, d2: date, league_only: bool = False):
        where = "s.session_date BETWEEN ? AND ?"
        params = [d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d")]
        if league_only:
            where += " AND COALESCE(s.is_league,0)=1"
        r = db.execute(
            f"""
            SELECT g.score, b.name AS bowler, s.session_date, a.name AS alley
            FROM games g
            JOIN sessions s ON s.id=g.session_id
            JOIN bowlers b ON b.id=s.bowler_id
            JOIN alleys a ON a.id=s.alley_id
            WHERE {where}
            ORDER BY g.score DESC, s.session_date DESC
            LIMIT 1
            """, tuple(params)
        ).fetchone()
        return dict(r) if r else None

    def best_all_time():
        r = db.execute(
            """
            SELECT g.score, b.name AS bowler, s.session_date, a.name AS alley
            FROM games g
            JOIN sessions s ON s.id=g.session_id
            JOIN bowlers b ON b.id=s.bowler_id
            JOIN alleys a ON a.id=s.alley_id
            ORDER BY g.score DESC, s.session_date DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(r) if r else None

    return jsonify({
        "week": {"range": [wk_start.strftime("%Y-%m-%d"), wk_end.strftime("%Y-%m-%d")], "best": best_between(wk_start, wk_end)},
        "month": {"range": [mo_start.strftime("%Y-%m-%d"), mo_end.strftime("%Y-%m-%d")], "best": best_between(mo_start, mo_end)},
        "year": {"range": [y_start.strftime("%Y-%m-%d"), y_end.strftime("%Y-%m-%d")], "best": best_between(y_start, y_end)},
        "league_year": {"range": [y_start.strftime("%Y-%m-%d"), y_end.strftime("%Y-%m-%d")], "best": best_between(y_start, y_end, league_only=True)},
        "all_time": {"best": best_all_time()}
    })



# ---------- Historical (all years) ----------
@app.get("/api/monthly-averages")
def monthly_averages():
    """Return per-bowler monthly averages for a given year (defaults to current year).
    Query params:
      - year=YYYY (optional)
      - league_only=1 (optional; only if sessions.is_league exists, otherwise ignored)
      - bowler_id=<int> (optional; when provided, returns only that bowler)
    """
    db = get_db()
    year = request.args.get("year") or str(current_year())
    league_only = str(request.args.get("league_only", "")).lower() in ("1","true","yes","y")
    bowler_id = request.args.get("bowler_id")

    # If schema doesn't have is_league, ignore league_only safely
    cols = [r["name"] for r in db.execute("PRAGMA table_info(sessions)").fetchall()]
    has_is_league = "is_league" in cols

    where = ["strftime('%Y', s.session_date)=?"]
    params = [year]
    if league_only and has_is_league:
        where.append("COALESCE(s.is_league,0)=1")
    if bowler_id:
        try:
            bid = int(bowler_id)
        except ValueError:
            return jsonify({"error": "Invalid bowler_id"}), 400
        where.append("s.bowler_id=?")
        params.append(bid)

    where_sql = " AND ".join(where)

    rows = db.execute(
        f"""
        SELECT
            b.id   AS bowler_id,
            b.name AS bowler,
            CAST(strftime('%m', s.session_date) AS INTEGER) AS month,
            COUNT(g.id) AS games,
            AVG(g.score) AS avg_score
        FROM sessions s
        JOIN games g   ON g.session_id = s.id
        JOIN bowlers b ON b.id = s.bowler_id
        WHERE {where_sql}
        GROUP BY b.id, b.name, month
        ORDER BY b.name, month
        """,
        params
    ).fetchall()

    # Shape: one row per bowler with months 1..12 filled or null
    by_bowler = {}
    for r in rows:
        bid = r["bowler_id"]
        if bid not in by_bowler:
            by_bowler[bid] = {
                "bowler_id": bid,
                "name": display_bowler(r["bowler"]),
                "months": {m: None for m in range(1,13)},
                "month_games": {m: 0 for m in range(1,13)},
            }
        m = int(r["month"])
        by_bowler[bid]["months"][m] = round(float(r["avg_score"] or 0.0), 2) if r["games"] else None
        by_bowler[bid]["month_games"][m] = int(r["games"] or 0)

    # Add YTD
    out = []
    for rec in by_bowler.values():
        total_games = sum(rec["month_games"].values())
        if total_games:
            # weighted avg
            weighted = 0.0
            for m in range(1,13):
                if rec["months"][m] is None:
                    continue
                weighted += rec["months"][m] * rec["month_games"][m]
            ytd = round(weighted / total_games, 2)
        else:
            ytd = None
        rec["ytd_games"] = total_games
        rec["ytd_avg"] = ytd
        out.append(rec)

    # Ensure bowlers with zero games still appear ONLY when not filtering to a single bowler.
    # When bowler_id is provided, return only that bowler (even if they have zero games).
    if not bowler_id:
        existing_ids = {r["bowler_id"] for r in out}
        for b in db.execute("SELECT id,name FROM bowlers ORDER BY name").fetchall():
            if b["id"] not in existing_ids:
                out.append({
                    "bowler_id": b["id"],
                    "name": display_bowler(b["name"]),
                    "months": {m: None for m in range(1,13)},
                    "month_games": {m: 0 for m in range(1,13)},
                    "ytd_games": 0,
                    "ytd_avg": None
                })
    else:
        # If filtered and there are no rows, still return the selected bowler stub.
        if not out:
            b = db.execute("SELECT id,name FROM bowlers WHERE id=?", (bid,)).fetchone()
            if b is None:
                return jsonify({"error": "Bowler not found"}), 404
            out = [{
                "bowler_id": b["id"],
                "name": display_bowler(b["name"]),
                "months": {m: None for m in range(1,13)},
                "month_games": {m: 0 for m in range(1,13)},
                "ytd_games": 0,
                "ytd_avg": None
            }]

    out.sort(key=lambda x: x["name"])
    return jsonify({"year": int(year), "league_only": bool(league_only and has_is_league), "rows": out})

@app.get("/api/history")
def history():
    """
    Returns historical averages by year for each bowler.

    Shape expected by frontend:
      {
        "years": ["2023","2024","2025"],
        "data": {
          "Rajan": {"2024": {"avg": 201.25, "games": 48}, ...},
          ...
        }
      }
    """
    db = get_db()

    # Determine which years exist in the data
    years = [r["y"] for r in db.execute(
        "SELECT DISTINCT strftime('%Y', session_date) AS y FROM sessions ORDER BY y"
    ).fetchall() if r["y"]]

    # If no sessions yet, keep stable shape
    if not years:
        return jsonify({"years": [], "data": {}})

    # Pull aggregated stats for all bowlers + years
    rows = db.execute(
        """
        SELECT b.name AS bowler,
               strftime('%Y', s.session_date) AS y,
               COUNT(g.id) AS games,
               AVG(g.score) AS avg
        FROM games g
        JOIN sessions s ON s.id=g.session_id
        JOIN bowlers b ON b.id=s.bowler_id
        GROUP BY b.id, b.name, y
        ORDER BY b.name, y
        """
    ).fetchall()

    data = {}
    for r in rows:
        bowler = r["bowler"]
        y = r["y"]
        data.setdefault(bowler, {})
        data[bowler][y] = {
            "avg": round(float(r["avg"] or 0.0), 2),
            "games": int(r["games"] or 0)
        }

    return jsonify({"years": years, "data": data})


# ---------- Debug diag ----------
@app.get("/api/debug/diag")
def debug_diag():
    db = get_db()
    return jsonify({
        "db_path": DB_PATH,
        "cwd": os.getcwd(),
        "file": os.path.abspath(__file__),
        "tables": [r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
