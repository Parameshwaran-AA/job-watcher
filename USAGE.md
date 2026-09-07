# How to use job-watcher

Everything from an empty folder to a working job radar, in order.

---

## What it does, in one paragraph

Four times a day (or hourly, your choice) it asks a list of companies "what's
open right now?", throws away everything that isn't your kind of role, scores
what's left against your résumé, remembers what it has already seen, puts the
matches on a web page, and messages your phone about the handful of companies
you actually care about. It never applies to anything. Every Apply button opens
the company's own page and you do the applying.

---

## Part 1 — One-time setup

### 1.1 Install

```bash
cd job-watcher
pip install -r requirements.txt
```

That pulls in `httpx` (small) and `sentence-transformers` (large, around 500 MB
with its dependencies). The big one is what gives you real meaning-based
matching. If you'd rather skip it for now, open `config.toml` and set:

```toml
use_embeddings = false
```

The tool then uses a keyword fallback and still works. You can switch later.

### 1.2 Write your profile

Open `config.toml`. Find the `profile.text` block and replace it with your
résumé, or a plain description of the work you want.

This is the single most important thing you will write. Every job description
gets compared against this text. Aim for 200–600 words. Skills and tools matter;
adjectives don't.

Good:

```
Python, Java, TypeScript, SQL. REST APIs, microservices, PostgreSQL, Redis,
Docker, Kubernetes, AWS. PyTorch, scikit-learn, pandas, transformers, RAG
pipelines, vector search. Looking for software engineer, backend engineer,
machine learning engineer or data scientist roles. Early career.
```

Bad:

```
Motivated self-starter passionate about technology and eager to learn.
```

The first one has words that will actually appear in job descriptions. The
second one has none.

### 1.3 Set up Telegram (10 minutes, optional but do it)

1. Open Telegram, search for **@BotFather**, send `/newbot`.
2. Give it any name. It replies with a token like `8123456:AAF...`. Copy it.
3. Search for **@userinfobot**, send it any message. It replies with your
   numeric ID. Copy that too.
4. Message your new bot once (say "hi") so it's allowed to message you back.

Then set them in your terminal:

```bash
export TELEGRAM_BOT_TOKEN="8123456:AAF..."
export TELEGRAM_CHAT_ID="123456789"
```

On Windows PowerShell: `$env:TELEGRAM_BOT_TOKEN="..."`

Without these the tool runs fine, it just prints "telegram not configured" and
holds the alerts.

---

## Part 2 — Building your company list

### 2.1 The add command

You never write a company line by hand. You paste the URL you were already
looking at:

```bash
python watcher.py add https://www.notion.so/careers
```

It figures out which hiring software Notion runs on, checks the board answers,
reads the real company name off the response, and writes the line for you.

Several at once:

```bash
python watcher.py add https://jobs.lever.co/plaid https://boards.greenhouse.io/stripe
```

**If it says it found nothing:** the careers page is custom-branded and hiding
the hiring software. Open the page, right-click any single job posting, copy the
link address, and run `add` on that link instead. The job link nearly always
exposes it even when the landing page doesn't.

A small number of companies proxy everything server-side and leave no trace at
all. Those need Workday support, which isn't in this version. Skip them.

### 2.2 Tiers — how often a company gets checked

Every company sits in one of three tiers. The tier decides **how often** it gets
swept, nothing else. All three tiers appear on the same dashboard.

| Tier | Swept | Worst-case delay | Put here |
|---|---|---|---|
| **1** | Every hour | 1 hour | Your 20–50 dream companies |
| **2** | Every 6 hours | 6 hours | Solid fits, a few hundred |
| **3** | Once a day | 24 hours | The long tail, thousands |

Set it when you add:

```bash
python watcher.py add https://boards.greenhouse.io/stripe --tier 1
python watcher.py add https://jobs.ashbyhq.com/linear --tier 2
python watcher.py add https://jobs.lever.co/someco --tier 3
```

`--tier 2` is the default if you don't say.

**Why tiers exist.** A popular role gets 200–400 applications in its first 48
hours. Being early is the whole point of this tool. But sweeping 5,000 companies
every hour is rude to their servers and slow for you. Tiers let you have both:
hour-level freshness where it matters, daily coverage everywhere else.

**Why this makes thousands of companies practical.** The code doesn't care
whether your list has 100 lines or 5,000. Tiering is what keeps the request
volume sane as you grow. Start with 100 and add more once it runs reliably.

### 2.3 Notify vs silent — who is allowed to buzz your phone

Separate from tiers. This decides **who can interrupt you**.

```bash
python watcher.py add https://www.notion.so/careers --tier 1 --notify
```

- `--notify` — a new match here sends a Telegram message.
- (no flag) — silent. It still appears on the dashboard, it just never buzzes.

**Keep this list short.** Twenty notify companies is plenty. If everything
notifies, you'll mute the bot within a week and the whole project dies. The
default is silent for exactly this reason.

Three things must all be true before your phone buzzes:

1. The company is marked `notify`, **and**
2. the job is genuinely new (never seen before), **and**
3. it scores at or above `min_score_notify` in `config.toml`.

That third condition is why a watchlist company posting a sales role won't wake
you up.

### 2.4 Editing by hand

`companies.txt` is a plain text file. Each line:

```
ats:token                    tier   notify|silent   Display name
greenhouse:stripe            1      notify          Stripe
ashby:notion                 2      silent          Notion
```

Change a tier or flip notify/silent by editing the line. Delete a line to stop
watching a company. Lines starting with `#` are ignored.

### 2.5 Check everything works

```bash
python watcher.py verify
```

```
  ok    greenhouse:stripe                   518 open
  ok    ashby:notion                         84 open
  FAIL  lever:acmecorp                      HTTP 404

2 boards responding, 1 needs attention
```

`HTTP 404` means the token is wrong. Go back to that company's careers page,
open a job link, and run `add` on it.

**Do this before your first real sweep.** The starter tokens shipped in
`companies.txt` are educated guesses, not a verified list. Some will be wrong.

---

## Part 3 — Your first sweep

```bash
python watcher.py run
python watcher.py run
```

**Yes, twice. This matters.**

The first time the tool ever sees a company, it records every one of that
company's jobs *silently* — no alerts, nothing marked new. Only from the second
sweep onward can something count as new.

Without this, day one would send you 5,000 notifications, and every time you
added companies later it would happen again. The seeding rule is per company, so
adding 400 new companies next month is just as quiet.

What you'll see:

```
scorer: embedding · 34 boards
new 0 (+0 over the year ceiling, hidden) · reposts 0 · seen 0 · closed 0
  · seeded 1847 jobs across 34 new boards
alerts sent: 0 · dashboard rows: 61
```

Second run:

```
new 12 (+3 over the year ceiling, hidden) · reposts 1 · seen 1834 · closed 0
alerts sent: 2 · dashboard rows: 73
```

Reading that line:

| Word | Meaning |
|---|---|
| `new` | Never seen before. These are the ones that matter. |
| `over the year ceiling` | New, but asks 8+ years. Kept, hidden, no alert. |
| `reposts` | Same job under a fresh ID. Not alerted twice. |
| `seen` | Already knew about it. Nothing to do. |
| `closed` | Gone from the board for two sweeps running. Marked dead. |
| `seeded` | Recorded quietly on a board's first sweep. |

---

## Part 4 — The dashboard

```bash
python -m http.server -d site 8000
```

Open `http://localhost:8000`.

To preview the layout before your first sweep, copy `docs/jobs.sample.json` to
`docs/jobs.json` first.

### 4.1 What a row tells you

```
new  Machine learning engineer                    2h ago      91
     Ramp · New York, NY · 2–4 yrs               live 1d    [Apply]
```

| Part | Meaning |
|---|---|
| `new` | Found in the last 24 hours |
| `2h ago` | When **your** system first saw it |
| `live 1d` | How long it's been open. Lower = fewer applicants ahead of you |
| `91` | Match score against your profile, 0–100 |
| `2–4 yrs` | Experience parsed from the description |
| `Apply` | Opens the company's own posting |

### 4.2 The filters

| Control | Does |
|---|---|
| **Company or title** | Type `notion` to see only Notion. Also matches titles and locations, so `backend` works. Autocompletes from your companies. |
| **Role** | Software / AI-ML / Data |
| **Found** | Last 24 hours, 3 days, 7 days |
| **Sort** | Newest found, best match, least competition, company |
| **Min match** | Drag up to see only strong matches |
| **Include 8+ yr roles** | Unhides the roles asking for 8+ years |
| **Clear** | Resets everything |

**Fastest trick:** click any company name inside a row and it instantly filters
to that company. Faster than typing.

**Why "newest found" is the default sort** rather than newest posted: it uses
your own clock, which never lies. Company posted-dates are missing or wrong
often enough to scramble the order confusingly.

### 4.3 About the score

Every job gets a 0–100 number for how close it is to your profile. Three cutoffs
in `config.toml` use it:

| Setting | Default | Meaning |
|---|---|---|
| `min_score_keep` | 25 | Below this, don't even store it |
| `min_score_dashboard` | 45 | Below this, keep but hide from the page |
| `min_score_notify` | 70 | Below this, no Telegram message |

These need tuning. See Part 6.

---

## Part 5 — The experience ceiling

You said you only want roles under 8 years, and that you didn't trust an
automatic filter to get that right. You were right, so here's exactly how it
behaves.

### 5.1 It never deletes anything

Years-of-experience is not a field any hiring software provides. It's buried in
prose. The parser is right most of the time, not all of the time.

So a posting whose experience floor reads as 8 or more is **still collected,
still scored, still stored**. It is just:

- marked `asks 8+ yrs` on its row,
- hidden on the dashboard by default,
- never allowed to send a Telegram alert.

Tick **Include 8+ yr roles** and every one of them reappears. The row count
tells you how many are hidden right now:

```
73 of 96 roles · 23 hidden as 8+ yrs
```

A wrong guess costs you one checkbox click. It never costs you a job.

### 5.2 The three rules it follows

**It filters on the minimum, never the maximum.** A posting saying "3–8 years"
has a floor of 3, so you're eligible and it shows normally. A posting saying
"8+ years" has a floor of 8, so it gets hidden. Filtering on the top number
would wrongly bury the first one.

**When several numbers appear, the lowest wins.** "5 years Python, 2 years
Kubernetes" is treated as 2. Being conservative keeps you in the running instead
of filtering yourself out of something you could do.

**A posting that says nothing is kept.** It shows as `exp not stated` and is
never hidden. A large share of postings never mention years, and dropping them
would lose you a lot of good roles.

### 5.3 What it ignores

Company boilerplate that happens to contain a year count:

- "We have **been** building this for 10 years" → ignored
- "**Founded** 9 years **ago** in Berlin" → ignored
- "Celebrating our 12 year **anniversary**" → ignored

A year count sitting near *been, founded, since, ago, history, anniversary,
company* is treated as marketing, not a requirement.

### 5.4 Changing the ceiling

`config.toml`:

```toml
max_years_experience = 8
```

Set it to `10` and only 10+ roles get hidden. Set it to `99` and nothing is ever
hidden.

### 5.5 One thing it does drop

Titles are different from descriptions. A title containing *staff, principal,
distinguished, fellow, architect, engineering manager, director, head of, VP,
chief* is filtered out at the title stage, before scoring. These aren't
ambiguous — no parsing is involved, the title says it plainly.

If you disagree with any of that, `jobwatch/match.py` has the list in
`TOO_SENIOR` and you can edit it.

---

### 5.6 Adding job titles the tool doesn't know

There are two layers, and only one of them is a word list.

**Layer 1, the title gate, is a literal list.** If a title matches nothing in it,
the job is never scored and never appears. This is the layer you edit.

**Layer 2, the match score, is the semantic part.** It reads the whole
description and understands meaning, so it handles wording you never listed. But
it only ever sees jobs that already got through layer 1. The semantic scoring
cannot rescue a title the gate rejected.

So: to widen what you see, edit the gate. Open `jobwatch/match.py`, find
`ROLE_FAMILIES` at the top, and add words to the right family separated by `|`:

```python
"swe": re.compile(
    r"\b(software[\s-]?engineer|...|dev[\s-]?ops|"
    r"security[\s-]?engineer|qa[\s-]?engineer)\b",   # <- your additions
    re.I,
),
```

Use `[\s-]?` between words so `devops`, `dev ops` and `dev-ops` all match.

Two rules that will save you an hour:

- **Never end a pattern mid-word.** `data[\s-]?scien` looks like it should catch
  "Data Scientist" but the closing `\b` cannot sit inside a word, so it matches
  nothing at all. Write the whole word, or list the endings:
  `data[\s-]?scien(?:ce|tist)`.
- **Run the tests after every edit:** `python tests/test_pipeline.py`.

To find what you're missing, use the audit:

```bash
python watcher.py rejects --grep "cloud"
```

Anything showing `[title]` was blocked by the gate. That is your to-do list.

There is also a blocklist, `NOT_ENGINEERING`, which throws out titles that look
like matches but aren't: sales engineer, solutions engineer, support engineer,
product manager, designer, recruiter. Edit it the same way.

## Part 6 — Tuning, week one

The plumbing is the easy part. Getting ten good matches a day instead of two
hundred mediocre ones is the actual work. Budget about a week of nudging.

### 6.1 Look at the score spread

```bash
python watcher.py stats
```

```
   0-9    #                                        12
  10-19   ####                                     58
  20-29   ############                            174
  30-39   ##################################      501
  40-49   ########################################598
  50-59   ###################                     286
  60-69   #########                               131
  70-79   ###                                      44
  80-89   #                                        11
  90-99                                             2
```

You want your notify cutoff to land where roughly 5–15 jobs a day clear it.
Start low, watch for a few days, raise it until the volume feels right.

**Scores from the two scorers are not on the same scale.** The embedding scorer
runs higher than the keyword fallback. If you switch between them, re-run
`stats` and retune. The tool warns you when the two look mismatched.

### 6.2 Audit what got thrown away

This is the one that keeps you trusting the tool.

```bash
python watcher.py rejects
```

```
  title        4821
  score         612
  seniority     198
```

And when you find a great job somewhere else and wonder why this missed it:

```bash
python watcher.py rejects --grep "machine learning"
```

```
  [title     ] Machine Learning Operations Specialist  (greenhouse:acme, score None)
  [score     ] Machine Learning Engineer, Ads          (lever:globex, score 31)
```

Now you know: the first was rejected because the title pattern didn't match
"Operations Specialist", the second because it scored 31 and your keep floor is
45. Both are fixable — widen the pattern in `match.py`, or lower the floor.

Without this you'd just quietly stop believing the tool. Use it.

---

## Part 7 — Running it automatically

Everything so far was manual. Now make it run itself.

### 7.1 GitHub Actions (free, recommended)

1. Push this folder to a GitHub repo.
2. Repo → **Settings → Secrets and variables → Actions → New repository secret**.
   Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Repo → **Settings → Pages** → source `main`, folder `/docs`. Your dashboard is
   now a real URL you can open from your phone.
4. Repo → **Actions** tab → enable workflows.

`.github/workflows/watch.yml` then runs on its own:

| Trigger | Sweeps |
|---|---|
| Every hour at :05 | tier 1 |
| 02:20, 08:20, 14:20, 20:20 UTC | tiers 1 and 2 |
| 03:40 UTC daily | everything |

You can also hit **Run workflow** manually from the Actions tab any time.

**Two things to know.** Public repo means unlimited Actions minutes but your
config is visible to the world — keep the Telegram token in secrets, never in
`config.toml`. And GitHub delays scheduled runs by 10–30 minutes under load and
never tells you when one fails, which is why the workflow has a heartbeat job
that messages you on failure. Don't remove it. A silently dead sweep is how
these projects end.

### 7.2 Or your own machine

`crontab -e`, then:

```
5  *    * * *  cd /path/to/job-watcher && ./run.sh --tier 1
20 */6  * * *  cd /path/to/job-watcher && ./run.sh --tier 1 2
40 3    * * *  cd /path/to/job-watcher && ./run.sh --tier 1 2 3
```

Where `run.sh` exports your two Telegram variables and calls
`python watcher.py run "$@"`. Only works while the machine is on and awake,
which is why GitHub Actions is the better default.

---

## Part 8 — Your daily routine

Once it's running, this is the whole thing:

**Morning.** Open the dashboard. Sort by newest found. Scan the `new` rows.
Anything above 75 gets a proper look.

**During the day.** Telegram buzzes only for watchlist companies. Those are
worth stopping for — you're seeing the posting within an hour of it going up,
before the 400 applications arrive.

**Applying.** Click Apply, land on the company's own page, write something real.
This is the part no tool should do for you. Volume is not the game any more —
recruiters have adapted to mass applications and a generic submission now hurts
you. Twenty thoughtful applications beat two hundred automated ones.

**Weekly.** Run `stats` and adjust the cutoffs. Run `rejects --grep` on anything
you found elsewhere. Add companies as you discover them.

---

## Part 9 — When something looks wrong

| Symptom | What's happening |
|---|---|
| No alerts ever | Check the three conditions in 2.3. Usually `min_score_notify` is too high — run `stats`. |
| Flooded with alerts | Too many `notify` companies, or the cutoff is too low. |
| Everything is "new" | You skipped the second seeding run. Run again; it settles. |
| A company shows nothing | `python watcher.py verify` — the token is probably wrong. |
| A job I know about is missing | `python watcher.py rejects --grep "part of the title"` |
| Dashboard is blank | The page needs serving, not opening as a file. Use `python -m http.server -d site`. |
| `FAIL HTTP 404` on verify | Wrong token. Re-run `add` on an individual job link. |
| `FAIL HTTP 429` | You're sweeping too hard. Raise `per_host_delay_ms` in `config.toml`. |
| Nothing has run for days | GitHub disabled the schedule, or a run is failing silently. Check the Actions tab. |

Jobs that disappear from a board are marked closed after two consecutive
successful sweeps, so you won't apply to dead links. A board that fails to
respond is skipped entirely rather than having its jobs closed — a broken
request is never mistaken for an empty company.

---

## Command reference

| Command | Does |
|---|---|
| `python watcher.py add URL [--tier N] [--notify]` | Add a company from a careers link |
| `python watcher.py verify` | Check every board responds |
| `python watcher.py run` | Sweep everything |
| `python watcher.py run --tier 1` | Sweep only the watchlist |
| `python watcher.py run --tier 1 2` | Sweep tiers 1 and 2 |
| `python watcher.py stats` | Score histogram for tuning |
| `python watcher.py rejects` | Counts of what was filtered |
| `python watcher.py rejects --grep TEXT` | Why a specific job was filtered |
| `python -m http.server -d site 8000` | View the dashboard |
| `python tests/test_pipeline.py` | 66 offline tests, no network needed |

---

## Files

| File | What it's for |
|---|---|
| `config.toml` | Your profile text and all the thresholds |
| `companies.txt` | Who to watch, their tier, and who may notify you |
| `docs/index.html` | The dashboard |
| `docs/jobs.json` | The data it reads. Written by every sweep. |
| `jobs.db` | The memory. Deleting it means re-seeding from scratch. |
| `jobwatch/match.py` | Title patterns, experience parser, scorers |
| `jobwatch/ats.py` | The five hiring-software adapters |
| `.github/workflows/watch.yml` | The schedule |
