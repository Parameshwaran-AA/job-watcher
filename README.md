# job-watcher

Watches company career boards directly through their public APIs, scores every
new posting against your résumé, shows the matches on a static page, and pushes
a Telegram message only for the companies you actually care about.

It never applies to anything. Every Apply button opens the company's own page.

```
companies.txt  →  ATS APIs  →  title sieve  →  experience sieve  →  match score
                                                                          ↓
                            Telegram (watchlist only)  ←  memory  →  site/jobs.json
```

**New here? Read [USAGE.md](USAGE.md)** — the full walkthrough, tiers and
experience handling explained end to end. This file is the short version.

## Setup

**1. Install**

```bash
pip install -r requirements.txt
```

`sentence-transformers` is a large install. If you skip it, the tool falls back
to a keyword scorer automatically and still runs — set `use_embeddings = false`
in `config.toml` to silence the warning.

**2. Write your profile**

Open `config.toml` and replace `profile.text` with your résumé or a description
of the work you want. This is the text every job description gets compared
against. 200–600 words, heavy on skills and tools, light on adjectives.

**3. Add companies by pasting their careers URL**

You never hand-write a company line. Paste the link:

```bash
python watcher.py add https://www.notion.so/careers
python watcher.py add https://boards.greenhouse.io/stripe --tier 1 --notify
python watcher.py add https://jobs.lever.co/plaid https://jobs.ashbyhq.com/linear
```

It works out which hiring software the page runs on, checks the board actually
answers, reads the real company name off the response, and appends the line to
`companies.txt`. `--notify` puts it on the Telegram watchlist; without it the
company is silent and only shows on the dashboard.

If a careers page is custom-branded and `add` finds nothing, open the page,
right-click any individual job, copy the link address, and run `add` on that
instead. The job link almost always exposes the ATS even when the landing page
hides it. A few companies proxy everything server-side and leave no trace at
all — those need Workday support, which is not in this version.

You can still edit `companies.txt` by hand. Each line is:

```
ats:token          tier   notify|silent   Display name
```

**4. Verify before you trust it**

```bash
python watcher.py verify
```

Prints every board with its live job count, or the reason it failed. Fix the
`FAIL` lines before your first real sweep. The starter tokens shipped in
`companies.txt` are a reasonable guess, not a verified list.

**5. Sweep twice**

```bash
python watcher.py run
python watcher.py run
```

The first sweep of any board records everything **silently**. Only from the
second sweep onward can a job count as new. This is what stops 5,000
notifications on day one, and it applies again every time you add companies.

**6. Look at it**

```bash
python -m http.server -d site 8000
```

Open `http://localhost:8000`.

## Tuning

The plumbing is easy. Getting ten good matches a day instead of two hundred
mediocre ones is the actual work.

```bash
python watcher.py stats            # score histogram
python watcher.py rejects          # what got filtered, by stage
python watcher.py rejects --grep "machine learning"
```

Start with `min_score_notify` low, watch what comes through for a few days, then
raise it until you get 5–15 alerts a day. **Embedding and lexical scores are not
on the same scale** — if you switch scorers, re-run `stats` and retune.

`rejects` is the audit trail. When you find a great job elsewhere and wonder why
this tool missed it, grep for it and you will see which sieve dropped it.

## Running it on GitHub Actions

Push to a repo, then add two repository secrets: `TELEGRAM_BOT_TOKEN` (from
@BotFather) and `TELEGRAM_CHAT_ID` (message @userinfobot).

`.github/workflows/watch.yml` sweeps tier 1 hourly, tier 2 every six hours, and
everything daily. Turn on GitHub Pages pointing at `/site` and the dashboard is
live.

Two things worth knowing:

- **Public repo = unlimited Actions minutes, but your config is public.** Keep
  your Telegram token in secrets, never in `config.toml`. If your profile text is
  sensitive, use a private repo and drop tier 3 to daily to stay inside the 2,000
  free minutes.
- **Scheduled runs are delayed 10–30 minutes under load, and GitHub never tells
  you when one fails.** The heartbeat job in the workflow messages you on
  failure. Do not remove it — a silently dead sweep is how these projects end.

## Commands

| | |
|---|---|
| `watcher.py add URL` | add a company from its careers page link |
| `watcher.py verify` | check every board token responds |
| `watcher.py run` | sweep everything |
| `watcher.py run --tier 1` | sweep only the watchlist |
| `watcher.py stats` | score histogram |
| `watcher.py rejects` | audit the filters |
| `python tests/test_pipeline.py` | 80 offline tests, no network |

## What it handles

Written into the code, not left as an exercise:

- **First sweep seeds silently** — per board, so adding companies later never
  floods you.
- **A failed board is never treated as an empty board.** If a request errors, that
  company is skipped entirely rather than having all its jobs marked closed.
- **Jobs close only after two consecutive successful sweeps** miss them.
- **Reposts are caught** by a company + normalised title + location hash, so a
  requisition deleted and reposted under a new ID does not alert twice.
- **Rate limiting is per host, shared globally**, because ATS platforms limit by
  IP across all tenants, not per company.
- **Experience is parsed from prose**, filtered on the minimum, and never used to
  delete a posting — only to hide it behind a toggle.
- **Per-company caps** stop one agency board flooding a sweep.
- **Closed jobs are pruned** after 120 days so the database stays small.

## Not in this version

Granular experience filtering on the dashboard, Workday support, and a
watchlist-only toggle on the page.

## About the experience ceiling

Years-of-experience is never a structured field. It is pulled out of prose, and
prose lies: "we've been building for 10 years" is not a requirement, "8+ years
preferred, 4+ required" has two numbers, and plenty of postings say nothing.

The parser is right most of the time, not all of the time. So it does not delete
anything. A posting whose floor reads as 8 or more is stored, marked, hidden on
the dashboard behind the **Include 8+ yr roles** checkbox, and never allowed to
trigger a Telegram alert. A wrong guess costs you a checkbox click, not a job.

Three rules it follows:

- Filter on the minimum, never the maximum. "3–8 years" has a floor of 3 and you
  are eligible.
- When several numbers appear, the lowest wins.
- A posting that states nothing is kept, tagged "exp not stated", never dropped.

Company boilerplate is filtered out: a year count preceded by *been*, *founded*,
*since*, *ago*, *history* or *anniversary* is ignored.
