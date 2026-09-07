"""Offline tests. No network: fake postings are pushed through the real logic."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobwatch import match  # noqa: E402
from jobwatch.ats import Posting, clean  # noqa: E402
from jobwatch.store import Store, dupe_key  # noqa: E402

ok = fail = 0


def check(label, got, want):
    global ok, fail
    if got == want:
        ok += 1
    else:
        fail += 1
        print(f"  FAIL {label}\n       got  {got!r}\n       want {want!r}")


def p(title, desc="", ext="1", company="Acme", loc="Remote"):
    return Posting("greenhouse", "acme", company, ext, title, loc,
                   f"https://x/{ext}", desc)


print("title family")
check("swe", match.title_family("Software Engineer, Backend"), "swe")
check("ai", match.title_family("Machine Learning Engineer"), "ai")
check("ai over swe", match.title_family("ML Platform Engineer"), "ai")
check("data", match.title_family("Analytics Engineer"), "data")
check("sales engineer rejected", match.title_family("Sales Engineer"), None)
check("pm rejected", match.title_family("Product Manager"), None)
check("designer rejected", match.title_family("Product Designer"), None)
check("unrelated", match.title_family("Warehouse Associate"), None)
check("new grad swe", match.title_family("New Grad Software Engineer"), "swe")
check("data scientist", match.title_family("Data Scientist"), "data")
check("decision scientist", match.title_family("Decision Scientist"), "data")
check("applied scientist", match.title_family("Applied Scientist"), "ai")
check("data science engineer", match.title_family("Data Science Engineer"), "ai")
check("devops", match.title_family("DevOps Engineer"), "swe")
check("dev ops spaced", match.title_family("Dev Ops Engineer II"), "swe")
check("sre", match.title_family("Site Reliability Engineer"), "swe")
check("amazon sde full", match.title_family("Software Development Engineer"), "swe")
check("cloud", match.title_family("Cloud Engineer"), "swe")
check("ios", match.title_family("iOS Engineer"), "swe")
check("android dev", match.title_family("Android Developer"), "swe")
check("ai slash ml", match.title_family("AI/ML Engineer"), "ai")
check("research scientist", match.title_family("Research Scientist"), "ai")
check("solutions engineer still rejected", match.title_family("Solutions Engineer"), None)

print("seniority ceiling")
check("staff", bool(match.TOO_SENIOR.search("Staff Software Engineer")), True)
check("principal", bool(match.TOO_SENIOR.search("Principal Engineer")), True)
check("eng manager", bool(match.TOO_SENIOR.search("Engineering Manager")), True)
check("senior is fine", bool(match.TOO_SENIOR.search("Senior Software Engineer")), False)

print("experience parsing")
check("range", match.parse_experience("We want 2-4 years of experience"), (2, 4))
check("en dash", match.parse_experience("3\u20135 years experience required"), (3, 5))
check("plus", match.parse_experience("5+ years of industry experience"), (5, None))
check("at least", match.parse_experience("at least three years of experience"), (3, None))
check("minimum", match.parse_experience("Minimum of 4 years"), (4, None))
check("lowest wins", match.parse_experience("5 years Python, 2 years Kubernetes"), (2, None))
check("wide range kept", match.parse_experience("3-8 years of experience"), (3, 8))
check("silent", match.parse_experience("Great team, great mission"), (None, None))
check("title junior", match.parse_experience("", "Junior Software Engineer"), (0, 2))
check("title senior", match.parse_experience("", "Senior Software Engineer"), (4, 8))
check("title staff", match.parse_experience("", "Staff Engineer"), (8, None))

print("ceiling rule")
check("3-8 passes", match.within_ceiling(3, 8), True)
check("8+ blocked", match.within_ceiling(8, 8), False)
check("10+ blocked", match.within_ceiling(10, 8), False)
check("unstated passes", match.within_ceiling(None, 8), True)

print("description cleaning")
check("double escaped", clean("&lt;p&gt;Build &amp;amp; ship&lt;/p&gt;"), "Build & ship")
check("empty", clean(None), "")

print("dedup key")
check("same job normalises", dupe_key("Acme", "Software Engineer II", "Remote"),
      dupe_key("Acme", "Software Engineer", "Remote"))
check("different job differs",
      dupe_key("Acme", "Software Engineer", "Remote") != dupe_key("Acme", "Data Engineer", "Remote"),
      True)

print("scorer")
prof = "python backend distributed systems postgres kubernetes machine learning pytorch"
sc = match.LexicalScorer(prof)
hi, lo = sc.score([
    "Backend engineer building distributed systems in Python on Kubernetes with Postgres",
    "Warehouse associate. Lift boxes, operate a forklift, morning shift.",
])
check("relevant scores above irrelevant", hi > lo, True)
check("scores are in range", 0 <= hi <= 100 and 0 <= lo <= 100, True)

print("store: seeding, newness, reposts, closing")
with tempfile.TemporaryDirectory() as tmp:
    st = Store(Path(tmp) / "t.db")

    check("board starts unseeded", st.is_seeded("greenhouse:acme"), False)
    check("first pull seeds", st.record(p("Software Engineer", ext="1"), "swe", (2, 4), 80, True), "seeded")
    st.board_ok("greenhouse:acme")
    check("board now seeded", st.is_seeded("greenhouse:acme"), True)

    check("same id again is seen", st.record(p("Software Engineer", ext="1"), "swe", (2, 4), 80, False), "seen")
    check("fresh id is new", st.record(p("Data Engineer", ext="2"), "data", (1, 3), 75, False), "new")

    # same job, brand new ATS id -> repost, must not alert twice
    check("repost detected",
          st.record(p("Software Engineer", ext="99"), "swe", (2, 4), 80, False), "repost")

    alerts = st.pending_alerts(70, {"greenhouse:acme"})
    check("only the genuinely new one alerts", [a["title"] for a in alerts], ["Data Engineer"])

    # job 2 vanishes; needs two consecutive good sweeps before it closes
    live = {"greenhouse:acme:1", "greenhouse:acme:99"}
    check("not closed after one miss", st.close_missing("greenhouse:acme", live), 0)
    check("closed after two misses", st.close_missing("greenhouse:acme", live), 1)

    st.commit()
    out = Path(tmp) / "jobs.json"
    n = st.export(out, min_score=40)
    check("export drops closed rows", n, 2)
    check("export file written", out.exists(), True)

    st.reject(p("Sales Engineer", ext="7"), "title")
    st.commit()
    rj = st.db.execute("SELECT COUNT(*) c FROM rejects").fetchone()["c"]
    check("rejects are logged", rj, 1)

print("url -> ats:token")
from jobwatch import discover  # noqa: E402
check("greenhouse job link",
      discover.from_text("https://boards.greenhouse.io/stripe/jobs/4567"), ["greenhouse:stripe"])
check("greenhouse new host",
      discover.from_text("https://job-boards.greenhouse.io/figma/jobs/12"), ["greenhouse:figma"])
check("greenhouse embed",
      discover.from_text("https://boards.greenhouse.io/embed/job_board?for=airtable"),
      ["greenhouse:airtable"])
check("lever", discover.from_text("https://jobs.lever.co/plaid/abc-def"), ["lever:plaid"])
check("lever eu", discover.from_text("https://jobs.eu.lever.co/malt"), ["lever:malt"])
check("ashby keeps case",
      discover.from_text("https://jobs.ashbyhq.com/Notion/abc123"), ["ashby:Notion"])
check("recruitee", discover.from_text("https://acme-corp.recruitee.com/o/role"),
      ["recruitee:acme-corp"])
check("workable", discover.from_text("https://apply.workable.com/dataloop/j/ABC/"),
      ["workable:dataloop"])
check("plain careers page finds nothing",
      discover.from_text("https://www.notion.so/careers"), [])
check("finds ATS hidden in page source",
      discover.from_text('<script src="https://boards.greenhouse.io/embed/job_board/js?for=notion">'),
      ["greenhouse:notion"])
check("junk segments ignored",
      discover.from_text("https://apply.workable.com/api/v1/widget/accounts/acme"),
      ["workable:acme"])

print("experience: boilerplate must not read as a requirement")
check("been building for N years",
      match.parse_experience("We have been building this for 10 years", "Software Engineer"),
      (None, None))
check("founded N years ago",
      match.parse_experience("Founded 9 years ago in Berlin", "Software Engineer"),
      (None, None))
check("context anchored",
      match.parse_experience("You bring 3 years of hands-on experience with Go"), (3, None))
check("experience label form",
      match.parse_experience("Experience: 4 years"), (4, None))
check("bare skill years still counted",
      match.parse_experience("5 years Python, 2 years Kubernetes"), (2, None))

print("over-ceiling jobs are kept, flagged and never alerted")
with tempfile.TemporaryDirectory() as tmp:
    st2 = Store(Path(tmp) / "o.db")
    st2.record(p("Software Engineer", ext="1"), "swe", (2, 4), 90, True)
    st2.board_ok("greenhouse:acme")
    check("in-range job is new",
          st2.record(p("Software Engineer, Core", ext="2"), "swe", (2, 4), 90, False), "new")
    check("over-ceiling job is still recorded",
          st2.record(p("Software Engineer, Systems", ext="3"), "swe", (9, None), 90, False, True),
          "new")
    alerts = st2.pending_alerts(70, {"greenhouse:acme"})
    check("only the in-range one alerts", [a["title"] for a in alerts], ["Software Engineer, Core"])
    st2.commit()
    out2 = Path(tmp) / "o.json"
    st2.export(out2, min_score=40)
    import json
    data = json.loads(out2.read_text())
    check("over flag exported", sorted(j["over"] for j in data["jobs"]), [False, False, True])

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
