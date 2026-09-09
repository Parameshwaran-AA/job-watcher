"""SQLite memory. This is the thing that decides what counts as new."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

from jobwatch import geo, roles

SCHEMA = """
CREATE TABLE IF NOT EXISTS boards (
  code        TEXT PRIMARY KEY,
  seeded      INTEGER NOT NULL DEFAULT 0,
  last_ok     REAL,
  last_error  TEXT,
  fail_count  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS jobs (
  uid          TEXT PRIMARY KEY,
  board        TEXT NOT NULL,
  company      TEXT NOT NULL,
  title        TEXT NOT NULL,
  location     TEXT,
  url          TEXT,
  family       TEXT,
  exp_min      INTEGER,
  exp_max      INTEGER,
  score        INTEGER,
  posted_at    REAL,
  first_seen   REAL NOT NULL,
  last_seen    REAL NOT NULL,
  missing_runs INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'open',
  notified     INTEGER NOT NULL DEFAULT 0,
  dupe_key     TEXT,
  over_ceiling INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_board ON jobs(board);
CREATE INDEX IF NOT EXISTS jobs_dupe  ON jobs(dupe_key);
CREATE TABLE IF NOT EXISTS rejects (
  uid   TEXT PRIMARY KEY,
  board TEXT, title TEXT, stage TEXT, score INTEGER, seen REAL
);
"""

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_ROMAN = re.compile(r"\b(i{1,3}|iv|v)\b")


def dupe_key(company: str, title: str, location: str) -> str:
    """Catches the same job reposted under a fresh ATS id."""
    norm = lambda s: _ROMAN.sub("", _PUNCT.sub(" ", (s or "").lower())).split()
    blob = " ".join(norm(company) + norm(title) + norm(location)[:2])
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}
        if "over_ceiling" not in cols:
            self.db.execute("ALTER TABLE jobs ADD COLUMN over_ceiling INTEGER NOT NULL DEFAULT 0")
        self.db.commit()

    # ---------------------------------------------------------------- boards

    def is_seeded(self, code: str) -> bool:
        row = self.db.execute("SELECT seeded FROM boards WHERE code=?", (code,)).fetchone()
        return bool(row and row["seeded"])

    def board_ok(self, code: str) -> None:
        self.db.execute(
            "INSERT INTO boards(code, seeded, last_ok, fail_count) VALUES(?,1,?,0) "
            "ON CONFLICT(code) DO UPDATE SET seeded=1, last_ok=excluded.last_ok, "
            "fail_count=0, last_error=NULL",
            (code, time.time()),
        )

    def board_failed(self, code: str, error: str) -> None:
        self.db.execute(
            "INSERT INTO boards(code, last_error, fail_count) VALUES(?,?,1) "
            "ON CONFLICT(code) DO UPDATE SET last_error=excluded.last_error, "
            "fail_count=boards.fail_count+1",
            (code, error[:300]),
        )

    # ------------------------------------------------------------------ jobs

    def record(self, posting, family, exp, score, seeding: bool, over: bool = False) -> str:
        """Returns 'new', 'seeded', 'repost' or 'seen'."""
        now = time.time()
        code = f"{posting.ats}:{posting.board}"
        row = self.db.execute("SELECT uid FROM jobs WHERE uid=?", (posting.uid,)).fetchone()
        if row:
            self.db.execute(
                "UPDATE jobs SET last_seen=?, missing_runs=0, status='open', score=? WHERE uid=?",
                (now, score, posting.uid),
            )
            return "seen"

        key = dupe_key(posting.company, posting.title, posting.location)
        twin = self.db.execute(
            "SELECT uid FROM jobs WHERE dupe_key=? AND first_seen > ? LIMIT 1",
            (key, now - 60 * 86400),
        ).fetchone()

        verdict = "seeded" if seeding else ("repost" if twin else "new")
        self.db.execute(
            "INSERT INTO jobs(uid, board, company, title, location, url, family, exp_min,"
            " exp_max, score, posted_at, first_seen, last_seen, notified, dupe_key, over_ceiling)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                posting.uid, code, posting.company, posting.title,
                posting.location, posting.url, family, exp[0], exp[1], score,
                posting.posted_at, now, now,
                0 if (verdict == "new" and not over) else 1, key, int(over),
            ),
        )
        return verdict

    def reject(self, posting, stage: str, score: int | None = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO rejects(uid, board, title, stage, score, seen)"
            " VALUES(?,?,?,?,?,?)",
            (posting.uid, f"{posting.ats}:{posting.board}", posting.title, stage,
             score, time.time()),
        )

    def close_missing(self, board: str, live_uids: set[str], after: int = 2) -> int:
        """Only ever call this when the board's fetch SUCCEEDED."""
        rows = self.db.execute(
            "SELECT uid FROM jobs WHERE board=? AND status='open'", (board,)
        ).fetchall()
        gone = [r["uid"] for r in rows if r["uid"] not in live_uids]
        if not gone:
            return 0
        marks = ",".join("?" * len(gone))
        self.db.execute(
            f"UPDATE jobs SET missing_runs=missing_runs+1 WHERE uid IN ({marks})", gone
        )
        cur = self.db.execute(
            f"UPDATE jobs SET status='closed' WHERE uid IN ({marks}) AND missing_runs>=?",
            (*gone, after),
        )
        return cur.rowcount

    def pending_alerts(self, min_score: int, boards: set[str],
                       us_only: bool = False,
                       skip_interns: bool = False) -> list[sqlite3.Row]:
        rows = self.db.execute(
            "SELECT * FROM jobs WHERE notified=0 AND status='open' AND score>=?"
            " ORDER BY score DESC",
            (min_score,),
        ).fetchall()
        rows = [r for r in rows if r["board"] in boards]
        if us_only:
            rows = [r for r in rows if geo.is_us(r["location"])]
        if skip_interns:
            rows = [r for r in rows if not roles.is_intern(r["title"])]
        return rows

    def mark_notified(self, uids: list[str]) -> None:
        self.db.executemany("UPDATE jobs SET notified=1 WHERE uid=?", [(u,) for u in uids])

    def clear_alert_backlog(self) -> None:
        """Anything not on a notify board never needs an alert."""
        self.db.execute("UPDATE jobs SET notified=1 WHERE notified=0")

    def commit(self) -> None:
        self.db.commit()

    # --------------------------------------------------------------- outputs

    def export(self, path: str | Path, min_score: int, keep_days: int = 45,
               max_live_days: int = 0, sponsors_path: str | Path | None = None) -> int:
        now = time.time()
        # H-1B approvals per company, if tools/sponsors.py has been run.
        # Absent file means "unknown", which the dashboard shows as a blank, not a no.
        sponsors: dict = {}
        if sponsors_path and Path(sponsors_path).exists():
            try:
                sponsors = json.loads(Path(sponsors_path).read_text()).get("companies", {})
            except (OSError, ValueError):
                sponsors = {}
        rows = self.db.execute(
            "SELECT * FROM jobs WHERE status='open' AND score>=? AND first_seen > ?"
            " ORDER BY first_seen DESC",
            (min_score, now - keep_days * 86400),
        ).fetchall()
        jobs = []
        for r in rows:
            live_days = max(0, round((now - (r["posted_at"] or r["first_seen"])) / 86400))
            # A job open on the company site longer than max_live_days is stale.
            # Only trust the posted date to make that call; if we never got one,
            # keep the job rather than hide it on a guess.
            if max_live_days and r["posted_at"] and live_days > max_live_days:
                continue
            jobs.append({
                "id": r["uid"],
                "title": r["title"],
                "company": r["company"],
                "location": r["location"] or "",
                "url": r["url"],
                "family": r["family"],
                "expMin": r["exp_min"],
                "expMax": r["exp_max"],
                "score": r["score"],
                "found": round(r["first_seen"]),
                "posted": round(r["posted_at"]) if r["posted_at"] else None,
                "liveDays": live_days,
                "over": bool(r["over_ceiling"]),
                "us": geo.is_us(r["location"]),
                "intern": roles.is_intern(r["title"]),
                "h1b": (sponsors.get(r["board"].partition(":")[2], {}).get("approvals")
                        if sponsors else None),
            })
        companies = sorted({j["company"] for j in jobs})
        payload = {
            "generated": round(now),
            "count": len(jobs),
            "companies": companies,
            "jobs": jobs,
        }
        Path(path).write_text(json.dumps(payload, separators=(",", ":")))
        return len(jobs)

    def prune(self, days: int = 120) -> int:
        """Closed jobs stop earning their storage. Keeps the repo small."""
        import time as _t
        cur = self.db.execute(
            "DELETE FROM jobs WHERE status='closed' AND last_seen < ?",
            (_t.time() - days * 86400,),
        )
        self.db.execute("DELETE FROM rejects WHERE seen < ?", (_t.time() - 30 * 86400,))
        return cur.rowcount

    def histogram(self) -> list[tuple[str, int]]:
        buckets = []
        for lo in range(0, 100, 10):
            n = self.db.execute(
                "SELECT COUNT(*) c FROM jobs WHERE score>=? AND score<?", (lo, lo + 10)
            ).fetchone()["c"]
            buckets.append((f"{lo:>2}-{lo + 9:<2}", n))
        return buckets
