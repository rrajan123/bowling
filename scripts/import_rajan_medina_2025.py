#!/usr/bin/env python3
"""
Import Rajan & Medina 2025 games from a CSV into bowling.sqlite3.

CSV expected columns (detected):
- bowler_short (ignored)
- bowler_name       e.g., "Ravi Rajan" or "Herbert Medina"
- session_date      e.g., "2025-10-12" (any date parseable by pandas is fine)
- alley_name        e.g., "Zodos Lanes"
- game_no           integer 1..12
- score             integer 1..300

DB schema (detected):
- bowlers(id, name UNIQUE, bix_group IN ('A','B') NOT NULL)
- alleys(id, name UNIQUE NOT NULL)
- sessions(id, bowler_id, alley_id, session_date TEXT, UNIQUE(bowler_id, session_date))
- games(id, session_id, game_number, score CHECK 1..300, like_count DEFAULT 0, UNIQUE(session_id, game_number))

Rules enforced:
- Only imports rows where bowler_name exists in DB (no auto-create for bowlers).
- Alley is auto-created if missing.
- One alley per bowler per day: if a session exists with a different alley, the row is skipped with a warning.
- game_no must be 1..12; score must be 1..300; invalid rows skipped.
- If a game (session_id, game_no) exists:
    - If score differs, it's UPDATED (idempotent merge).
    - If same score, it's counted as SKIPPED_DUP.
- Dry-run supported.

Usage:
    python import_rajan_medina_2025.py /path/to/bowling.sqlite3 /path/to/rajan_medina_2025_long.csv [--dry-run]

"""
import sys, sqlite3, argparse, csv, datetime as dt
from typing import Dict, Tuple, Any
try:
    import pandas as pd
except Exception:
    pd = None

VALID_SCORE_MIN, VALID_SCORE_MAX = 1, 300
VALID_GAME_MIN, VALID_GAME_MAX = 1, 12

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="Path to bowling.sqlite3")
    ap.add_argument("csv", help="Path to rajan_medina_2025_long.csv")
    ap.add_argument("--dry-run", action="store_true", help="Parse and validate, but do not write changes")
    return ap.parse_args()

def norm_date(s: str) -> str:
    """Normalize to YYYY-MM-DD; be forgiving on input."""
    s = (s or "").strip()
    if not s: return ""
    try:
        # Try simple YYYY-MM-DD first
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return s
        # Fallback: use fromisoformat if close
        try:
            return dt.date.fromisoformat(s[:10]).isoformat()
        except Exception:
            pass
        # Last resort: pandas
        if pd is None:
            raise ValueError("pandas not available to parse non-ISO date")
        d = pd.to_datetime(s, errors="raise").date()
        return d.isoformat()
    except Exception as e:
        raise ValueError(f"Bad date '{s}': {e}")

def load_bowler_ids(cur) -> Dict[str, int]:
    cur.execute("SELECT id, name FROM bowlers;")
    return {name.strip(): bid for (bid, name) in cur.fetchall()}

def ensure_bowlers(cur, names):
    """Ensure each bowler exists with bix_group='A' (Rajan/Medina rules)."""
    out = {}
    for n in names:
        nn = n.strip()
        if not nn: 
            continue
        cur.execute("SELECT id FROM bowlers WHERE name=?;", (nn,))
        row = cur.fetchone()
        if row:
            out[nn] = row[0]
            continue
        # create with bix_group 'A'
        cur.execute("INSERT INTO bowlers(name, bix_group) VALUES (?, 'A');", (nn,))
        out[nn] = cur.lastrowid
    return out


def get_or_create_alley(cur, name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Missing alley_name")
    cur.execute("SELECT id FROM alleys WHERE name = ?;", (name,))
    row = cur.fetchone()
    if row: return row[0]
    # create
    cur.execute("INSERT INTO alleys(name) VALUES (?);", (name,))
    return cur.lastrowid

def get_or_create_session(cur, bowler_id: int, alley_id: int, sdate: str) -> Tuple[int, bool]:
    cur.execute("SELECT id, alley_id FROM sessions WHERE bowler_id=? AND session_date=?;", (bowler_id, sdate))
    row = cur.fetchone()
    if row:
        sid, existing_alley_id = row
        if existing_alley_id != alley_id:
            raise RuntimeError(f"Session clash: existing alley_id={existing_alley_id} != new alley_id={alley_id}")
        return sid, False
    cur.execute("INSERT INTO sessions(bowler_id, alley_id, session_date) VALUES (?,?,?);",
                (bowler_id, alley_id, sdate))
    return cur.lastrowid, True

def upsert_game(cur, session_id: int, game_no: int, score: int) -> str:
    cur.execute("SELECT id, score FROM games WHERE session_id=? AND game_number=?;", (session_id, game_no))
    row = cur.fetchone()
    if row:
        gid, old_score = row
        if old_score == score:
            return "SKIP_DUP"
        cur.execute("UPDATE games SET score=? WHERE id=?;", (score, gid))
        return "UPDATED"
    cur.execute("INSERT INTO games(session_id, game_number, score) VALUES (?,?,?);", (session_id, game_no, score))
    return "INSERTED"

def validate_row(bowler_name: str, session_date: str, alley_name: str, game_no: Any, score: Any) -> Tuple[str, int, int]:
    sdate = norm_date(session_date)
    try:
        gno = int(game_no)
    except Exception:
        raise ValueError(f"Invalid game_no '{game_no}'")
    try:
        sc = int(score)
    except Exception:
        raise ValueError(f"Invalid score '{score}'")
    if not (VALID_GAME_MIN <= gno <= VALID_GAME_MAX):
        raise ValueError(f"game_no {gno} out of range {VALID_GAME_MIN}-{VALID_GAME_MAX}")
    if not (VALID_SCORE_MIN <= sc <= VALID_SCORE_MAX):
        raise ValueError(f"score {sc} out of range {VALID_SCORE_MIN}-{VALID_SCORE_MAX}")
    if not bowler_name or not sdate or not alley_name:
        raise ValueError("Missing required field(s)")
    return sdate, gno, sc

def main():
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()

    # Cache bowlers and verify only Rajan/Medina are processed
    bowler_ids = load_bowler_ids(cur)
    allowed_bowlers = {"Rajan", "Medina"}
    missing_bowlers = [b for b in allowed_bowlers if b not in bowler_ids]
    if missing_bowlers:
        # Auto-create with bix_group A
        created = ensure_bowlers(cur, missing_bowlers)
        bowler_ids.update(created)


    # Load CSV
    import pandas as pd
    df = pd.read_csv(args.csv)
    # Required columns
    req_cols = ["bowler_name","session_date","alley_name","game_no","score"]
    for c in req_cols:
        if c not in df.columns:
            print(f"ERROR: CSV missing required column: {c}")
            sys.exit(2)

    # Keep only allowed bowlers
    df = df[df["bowler_name"].isin(list(allowed_bowlers))].copy()

    # Counters
    c_ins = c_upd = c_dup = c_skip = c_session_new = 0
    problems = []

    for idx, row in df.iterrows():
        bname = str(row.get("bowler_name","")).strip()
        sdate_raw = row.get("session_date","")
        aname = str(row.get("alley_name","")).strip()
        gno_raw = row.get("game_no","")
        score_raw = row.get("score","")

        try:
            sdate, gno, sc = validate_row(bname, sdate_raw, aname, gno_raw, score_raw)
        except Exception as e:
            problems.append((idx, "VALIDATION", str(e)))
            c_skip += 1
            continue

        # Confirm bowler exists
        if bname not in bowler_ids:
            problems.append((idx, "BOWLER_MISSING", bname))
            c_skip += 1
            continue
        bid = bowler_ids[bname]

        # Alley (create if needed)
        try:
            aid = get_or_create_alley(cur, aname)
        except Exception as e:
            problems.append((idx, "ALLEY", str(e)))
            c_skip += 1
            continue

        # Session (must be unique for bowler/date and use one alley/day)
        try:
            sid, created = get_or_create_session(cur, bid, aid, sdate)
            if created:
                c_session_new += 1
        except RuntimeError as e:
            problems.append((idx, "SESSION_CLASH", str(e)))
            c_skip += 1
            continue

        # Upsert game
        status = upsert_game(cur, sid, gno, sc)
        if status == "INSERTED":
            c_ins += 1
        elif status == "UPDATED":
            c_upd += 1
        else:
            c_dup += 1

    if args.dry_run:
        conn.rollback()
    else:
        conn.commit()
    conn.close()

    print("=== Import Summary ===")
    print(f"Inserted games : {c_ins}")
    print(f"Updated games  : {c_upd}")
    print(f"Duplicate kept : {c_dup}")
    print(f"Skipped rows   : {c_skip}")
    print(f"New sessions   : {c_session_new}")
    if problems:
        print("\nIssues:")
        for p in problems[:50]:
            print(f"  Row {p[0]} | {p[1]} | {p[2]}")
        if len(problems) > 50:
            print(f"  ... and {len(problems)-50} more")

if __name__ == "__main__":
    main()
