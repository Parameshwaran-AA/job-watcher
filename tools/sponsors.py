"""Build sponsors.json: which of our watched companies actually get H-1Bs approved.

Source is the USCIS H-1B Employer Data Hub, one CSV per fiscal year:
  https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-YYYY.csv

Those files are the record of petitions USCIS actually APPROVED, which is the
question worth asking. DOL's LCA files are bigger and richer but only show what
an employer filed, and employers over-file.

    python tools/sponsors.py                 # download the last 3 years, build
    python tools/sponsors.py --years 2024 2025
    python tools/sponsors.py --local data/   # use CSVs already on disk

Matching legal entity names to our board slugs is the part that can go wrong, so
every match records the employer name it came from. Read the summary before you
trust a row.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{year}.csv"

# Legal wrapping that carries no identity. Stripped from both sides before matching.
_NOISE = re.compile(
    r"\b(?:inc|inc'd|incorporated|llc|l\.l\.c|llp|lp|plc|pbc|corp|corporation|co|company|"
    r"ltd|limited|holdings?|group|technologies|technology|tech|labs?|laboratories|"
    r"software|systems|solutions|services|international|worldwide|global|"
    r"usa|us|u\.s|america|american|north|na|opco|topco|midco|bidco|"
    r"the|and|of)\b",
    re.I,
)

# Where the legal name shares nothing with the brand, or where a bare prefix
# match would be dangerous. Values are normalised USCIS employer names.
ALIASES = {
    "block":      ["block", "square"],
    "openai":     ["openai"],
    "waymo":      ["waymo"],
    "scaleai":    ["scale ai", "scale"],
    "grafanalabs": ["grafana"],
    "doordashusa": ["doordash"],
    "lucidmotors": ["lucid", "atieva"],
    "project44":  ["project44"],
    "anthropic":  ["anthropic"],
}


def norm(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or ""))
    s = _NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def read_companies(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) < 3:
            continue
        code = parts[0]
        slug = code.partition(":")[2]
        display = " ".join(parts[3:]) or slug
        out.append({"code": code, "slug": slug, "display": display})
    return out


def pick(header: list[str], *wanted: str) -> str | None:
    """Find a column by fuzzy name, so a USCIS header tweak does not break us."""
    flat = {re.sub(r"[^a-z0-9]", "", h.lower()): h for h in header}
    for w in wanted:
        key = re.sub(r"[^a-z0-9]", "", w.lower())
        if key in flat:
            return flat[key]
        for k, orig in flat.items():
            if key in k:
                return orig
    return None


def load_year(text: str, year: str, tally: dict) -> int:
    rdr = csv.DictReader(io.StringIO(text))
    header = rdr.fieldnames or []
    col_emp = pick(header, "employer", "petitioner", "employername")
    col_ia = pick(header, "initialapproval", "initialapprovals", "initialapproval")
    col_ca = pick(header, "continuingapproval", "continuingapprovals")
    if not col_emp or not col_ia:
        print(f"  ! {year}: could not find the columns I need.")
        print(f"    header was: {header}")
        return 0

    n = 0
    for row in rdr:
        emp = row.get(col_emp)
        if not emp:
            continue
        def num(c):
            try:
                return int(float(str(row.get(c) or 0).replace(",", "")))
            except ValueError:
                return 0
        appr = num(col_ia) + (num(col_ca) if col_ca else 0)
        if appr <= 0:
            continue
        e = tally[norm(emp)]
        e["approvals"] += appr
        e["initial"] += num(col_ia)
        e["years"].add(year)
        e["names"].add(emp.strip())
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", default=["2023", "2024", "2025"])
    ap.add_argument("--local", help="folder of already-downloaded CSVs")
    ap.add_argument("--out", default="sponsors.json")
    ap.add_argument("--companies", default="companies.txt")
    args = ap.parse_args()

    tally: dict = defaultdict(lambda: {"approvals": 0, "initial": 0, "years": set(), "names": set()})
    got = []

    for year in args.years:
        if args.local:
            f = Path(args.local) / f"h1b_datahubexport-{year}.csv"
            if not f.exists():
                print(f"  - {year}: {f} not found, skipping")
                continue
            text = f.read_text(errors="replace")
        else:
            import httpx  # noqa: PLC0415
            url = URL.format(year=year)
            print(f"  downloading {url}")
            try:
                r = httpx.get(url, timeout=120, follow_redirects=True,
                              headers={"User-Agent": "job-watcher"})
                r.raise_for_status()
                text = r.text
            except Exception as exc:  # noqa: BLE001
                print(f"  - {year}: {type(exc).__name__}: {exc}")
                continue
        rows = load_year(text, year, tally)
        if rows:
            got.append(year)
            print(f"  {year}: {rows:,} employer rows with approvals")

    if not got:
        print("\nNo data loaded. Nothing written.")
        return 1

    companies = read_companies(ROOT / args.companies)
    out: dict = {}
    for c in companies:
        keys = ALIASES.get(c["slug"], [norm(c["display"]), norm(c["slug"])])
        keys = [k for k in dict.fromkeys(keys) if k]
        hits = {}
        for k in keys:
            if k in tally:
                hits[k] = tally[k]
        if not hits:  # fall back to a prefix match, but only on a name long enough to be safe
            for k in keys:
                if len(k) < 5:
                    continue
                for emp, v in tally.items():
                    if emp == k or emp.startswith(k + " "):
                        hits[emp] = v
        if not hits:
            out[c["slug"]] = {"approvals": 0, "years": [], "matched": []}
            continue
        total = sum(v["approvals"] for v in hits.values())
        years = sorted({y for v in hits.values() for y in v["years"]})
        names = sorted({n for v in hits.values() for n in v["names"]})[:4]
        out[c["slug"]] = {"approvals": total, "years": years, "matched": names}

    payload = {"source": "USCIS H-1B Employer Data Hub",
               "fiscal_years": got, "companies": out}
    (ROOT / args.out).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")

    yes = [c for c in companies if out[c["slug"]]["approvals"] > 0]
    no = [c for c in companies if out[c["slug"]]["approvals"] == 0]
    print(f"\nWrote {args.out} for FY {', '.join(got)}.")
    print(f"{len(yes)} of {len(companies)} watched companies have approved H-1Bs.\n")
    for c in sorted(yes, key=lambda c: -out[c["slug"]]["approvals"]):
        d = out[c["slug"]]
        print(f"  {d['approvals']:6,}  {c['display'][:22]:22} matched: {', '.join(d['matched'][:2])[:52]}")
    if no:
        print("\n  no approvals found (check the name match before believing it):")
        print("   ", ", ".join(c["display"] for c in no))
    return 0


if __name__ == "__main__":
    sys.exit(main())
