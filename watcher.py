#!/usr/bin/env python3
"""job-watcher — watch company career boards, alert on the ones you care about.

  python watcher.py add URL             add a company from its careers page link
  python watcher.py verify              check every board token responds
  python watcher.py run                 sweep every tier
  python watcher.py run --tier 1        sweep only your watchlist companies
  python watcher.py stats               score histogram, for tuning thresholds
  python watcher.py rejects             what got filtered out and why
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import tomllib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from jobwatch import ats, discover, match, notify
from jobwatch.store import Store

ROOT = Path(__file__).parent


# ------------------------------------------------------------------- config


def load_config(path: Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_companies(path: Path) -> list[dict]:
    """Each line: ats:token   tier   notify|silent   [Display Name]"""
    out = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        code = parts[0]
        tier = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3
        flag = parts[2].lower() if len(parts) > 2 else "silent"
        name = " ".join(parts[3:]) if len(parts) > 3 else ""
        out.append({"code": code, "tier": tier, "notify": flag == "notify", "name": name})
    return out


# -------------------------------------------------------------- fetch layer


class Throttle:
    """One shared gate per host. Workday-style APIs rate-limit by IP across all
    tenants, so backing off has to be global, not per company."""

    def __init__(self, delay_ms: int):
        self.delay = delay_ms / 1000.0
        self.lock = threading.Lock()
        self.next_at: dict[str, float] = defaultdict(float)

    def wait(self, host: str) -> None:
        with self.lock:
            now = time.monotonic()
            gap = self.next_at[host] - now
            self.next_at[host] = max(now, self.next_at[host]) + self.delay
        if gap > 0:
            time.sleep(gap)


def fetch_board(code: str, client: httpx.Client, throttle: Throttle, retries: int = 2):
    host = code.split(":", 1)[0]
    last = None
    for attempt in range(retries + 1):
        throttle.wait(host)
        try:
            return ats.fetch(code, client), None
        except httpx.HTTPStatusError as exc:
            last = f"HTTP {exc.response.status_code}"
            if exc.response.status_code in (404, 410):
                break  # wrong token; retrying will not help
            time.sleep(1.5 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    return None, last


# ---------------------------------------------------------------- commands


def cmd_verify(cfg, companies, args) -> int:
    throttle = Throttle(cfg["run"]["per_host_delay_ms"])
    ok = bad = 0
    with httpx.Client(timeout=cfg["run"]["request_timeout"], follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=cfg["run"]["concurrency"]) as pool:
            results = pool.map(
                lambda c: (c, *fetch_board(c["code"], client, throttle, retries=1)), companies
            )
            for company, postings, err in results:
                if postings is None:
                    bad += 1
                    print(f"  FAIL  {company['code']:<34} {err}")
                else:
                    ok += 1
                    print(f"  ok    {company['code']:<34} {len(postings):>4} open")
    print(f"\n{ok} boards responding, {bad} need attention")
    return 1 if bad else 0


def cmd_run(cfg, companies, args) -> int:
    if args.tier:
        companies = [c for c in companies if c["tier"] in args.tier]
    if not companies:
        print("no companies selected")
        return 1

    store = Store(ROOT / cfg["run"]["database"])
    ceiling = cfg["match"]["max_years_experience"]
    families = set(cfg["match"]["role_families"])
    scorer = match.get_scorer(cfg["profile"]["text"], cfg["match"]["use_embeddings"])
    print(f"scorer: {scorer.name} · {len(companies)} boards")
    if scorer.name == "lexical" and cfg["match"]["min_score_notify"] > 55:
        print(
            "  note: lexical scores run well below embedding scores. Your notify"
            f" cutoff of {cfg['match']['min_score_notify']} will probably alert on"
            " nothing. Run `watcher.py stats` and retune."
        )

    throttle = Throttle(cfg["run"]["per_host_delay_ms"])
    tally = defaultdict(int)
    failed: list[str] = []
    notify_boards = {c["code"] for c in companies if c["notify"]}

    with httpx.Client(timeout=cfg["run"]["request_timeout"], follow_redirects=True) as client:
        with ThreadPoolExecutor(max_workers=cfg["run"]["concurrency"]) as pool:
            jobs = pool.map(
                lambda c: (c, *fetch_board(c["code"], client, throttle)), companies
            )

            for company, postings, err in jobs:
                code = company["code"]

                # A failed board is NOT an empty board. Skip it entirely so we
                # never close jobs that are still perfectly live.
                if postings is None:
                    store.board_failed(code, err or "unknown")
                    failed.append(f"{code} ({err})")
                    continue

                seeding = not store.is_seeded(code)
                postings = postings[: cfg["run"]["max_jobs_per_company"]]
                live = {p.uid for p in postings}

                keep = []
                for p in postings:
                    family = match.title_family(p.title)
                    if family is None or family not in families:
                        store.reject(p, "title")
                        continue
                    if match.TOO_SENIOR.search(p.title):
                        store.reject(p, "seniority")
                        continue
                    exp = match.parse_experience(p.description, p.title)
                    # Over the ceiling is a flag, not a delete. Parsing years out
                    # of prose is maybe 85% right, so a wrong guess must never
                    # silently lose you a job. These are hidden on the dashboard
                    # behind a toggle and never trigger an alert.
                    over = not match.within_ceiling(exp[0], ceiling)
                    keep.append((p, family, exp, over))

                scores = scorer.score([f"{p.title}\n{p.description}" for p, _, _, _ in keep])
                for (p, family, exp, over), score in zip(keep, scores):
                    if score < cfg["match"]["min_score_keep"]:
                        store.reject(p, "score", score)
                        continue
                    verdict = store.record(p, family, exp, score, seeding, over)
                    tally[verdict] += 1
                    if verdict == "new" and over:
                        tally["over_ceiling"] += 1

                closed = store.close_missing(code, live, cfg["run"]["close_after_missing_runs"])
                tally["closed"] += closed
                store.board_ok(code)
                if seeding:
                    tally["seeded_boards"] += 1

    # Silent companies still land on the dashboard; they just never buzz.
    alerts = store.pending_alerts(
        cfg["match"]["min_score_notify"],
        notify_boards,
        cfg["match"].get("us_only", False),
        cfg["match"].get("exclude_interns", False),
    )
    store.clear_alert_backlog()
    if notify.send(alerts, cfg["telegram"]["max_per_message"]):
        store.mark_notified([r["uid"] for r in alerts])
    store.prune()
    store.commit()

    written = store.export(
        ROOT / cfg["run"]["export_path"],
        cfg["match"]["min_score_dashboard"],
        cfg["run"]["dashboard_days"],
        cfg["run"].get("max_live_days", 0),
        ROOT / "sponsors.json",
    )

    print(
        f"new {tally['new']} (+{tally['over_ceiling']} over the year ceiling, hidden)"
        f" · reposts {tally['repost']} · seen {tally['seen']}"
        f" · closed {tally['closed']} · seeded {tally['seeded']} jobs"
        f" across {tally['seeded_boards']} new boards"
    )
    print(f"alerts sent: {len(alerts)} · dashboard rows: {written}")
    if failed:
        print(f"\n{len(failed)} board(s) failed this run:")
        for f in failed[:20]:
            print(f"  {f}")
        if len(failed) > len(companies) * 0.5:
            notify.heartbeat(f"job-watcher: {len(failed)}/{len(companies)} boards failed")
            return 1
    return 0


def cmd_add(cfg, companies, args) -> int:
    """Paste a careers URL; get the right line appended to companies.txt."""
    known = {c["code"] for c in companies}
    path = ROOT / args.companies
    added: list[str] = []

    with httpx.Client(timeout=cfg["run"]["request_timeout"], follow_redirects=True) as client:
        for url in args.urls:
            print(f"\n{url}")
            codes, how = discover.discover(url, client)
            if not codes:
                print(f"  {how}.")
                print("  Open the page, right-click a job link, copy the link address,")
                print("  and run this again with that link instead of the careers page.")
                continue
            print(f"  {how}: {', '.join(codes)}")

            for code in codes:
                if code in known:
                    print(f"  {code} is already in your list")
                    continue
                try:
                    postings = ats.fetch(code, client)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {code} did not answer ({type(exc).__name__}), skipping")
                    continue
                if not postings:
                    print(f"  {code} answered but has no open jobs; adding anyway")
                name = postings[0].company if postings else discover.slug_from_url(url)
                flag = "notify" if args.notify else "silent"
                line = f"{code:<28} {args.tier}   {flag:<8} {name}"
                added.append(line)
                known.add(code)
                print(f"  added: {line.strip()}  ({len(postings)} open)")

    if added:
        with open(path, "a") as fh:
            fh.write("\n" + "\n".join(added) + "\n")
        print(f"\nWrote {len(added)} line(s) to {path.name}.")
        print("Run `python watcher.py run` twice: the first sweep of a new board")
        print("records its jobs quietly so you do not get flooded.")
    else:
        print("\nNothing added.")
    return 0


def cmd_stats(cfg, companies, args) -> int:
    store = Store(ROOT / cfg["run"]["database"])
    print("score distribution across everything kept:\n")
    rows = store.histogram()
    peak = max((n for _, n in rows), default=1) or 1
    for label, n in rows:
        print(f"  {label}  {'#' * round(40 * n / peak):<40} {n}")
    print(
        f"\ndashboard cutoff {cfg['match']['min_score_dashboard']}"
        f" · notify cutoff {cfg['match']['min_score_notify']}"
    )
    print("aim for 5-15 rows a day above the notify cutoff.")
    return 0


def cmd_rejects(cfg, companies, args) -> int:
    store = Store(ROOT / cfg["run"]["database"])
    rows = store.db.execute(
        "SELECT stage, COUNT(*) c FROM rejects GROUP BY stage ORDER BY c DESC"
    ).fetchall()
    for r in rows:
        print(f"  {r['stage']:<12} {r['c']}")
    if args.grep:
        print(f"\nrejected titles matching {args.grep!r}:")
        hits = store.db.execute(
            "SELECT title, board, stage, score FROM rejects WHERE title LIKE ? LIMIT 40",
            (f"%{args.grep}%",),
        ).fetchall()
        for h in hits:
            print(f"  [{h['stage']:<10}] {h['title']}  ({h['board']}, score {h['score']})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--companies", default="companies.txt")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="sweep boards and update the dashboard")
    run.add_argument("--tier", type=int, nargs="*", help="only these tiers, e.g. --tier 1 2")
    add = sub.add_parser("add", help="add companies from their careers page URLs")
    add.add_argument("urls", nargs="+", help="careers page or job posting links")
    add.add_argument("--tier", type=int, default=2, choices=[1, 2, 3])
    add.add_argument("--notify", action="store_true", help="put it on the Telegram watchlist")
    sub.add_parser("verify", help="check every board token responds")
    sub.add_parser("stats", help="score histogram for tuning")
    rej = sub.add_parser("rejects", help="audit what got filtered out")
    rej.add_argument("--grep", help="show rejected titles containing this")

    args = ap.parse_args()
    cfg = load_config(ROOT / args.config)
    companies = load_companies(ROOT / args.companies)

    fn = {"run": cmd_run, "add": cmd_add, "verify": cmd_verify,
          "stats": cmd_stats, "rejects": cmd_rejects}[args.cmd]
    return fn(cfg, companies, args)


if __name__ == "__main__":
    sys.exit(main())
