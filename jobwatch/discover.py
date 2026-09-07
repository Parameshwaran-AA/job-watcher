"""Work out which ATS a careers page runs on, straight from its URL.

This exists so you never have to hand-write an 'ats:token' line. Paste the URL
you were already looking at and let the tool figure out the rest.
"""

from __future__ import annotations

import re

import httpx

from .ats import UA

# Order matters: the more specific API URLs are checked before the human ones.
PATTERNS: list[tuple[str, str]] = [
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:job-)?boards\.greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)"),
    ("greenhouse", r"(?:job-)?boards\.greenhouse\.io/([A-Za-z0-9_-]+)"),
    ("greenhouse", r"greenhouse\.io/[^\"'\s]*?[?&]for=([A-Za-z0-9_-]+)"),
    ("lever", r"api\.lever\.co/v0/postings/([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_-]+)"),
    ("ashby", r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/api/v1/widget/accounts/([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("recruitee", r"([A-Za-z0-9-]+)\.recruitee\.com"),
]

# Path segments that look like tokens but are not.
JUNK = {
    "embed", "job_board", "www", "api", "v0", "v1", "postings", "boards", "jobs",
    "job", "j", "o", "careers", "career", "search", "en", "us", "en-us", "index",
    "static", "assets", "cdn", "app", "widget", "accounts", "company",
}


def from_text(text: str, limit: int = 6) -> list[str]:
    """Pull every plausible 'ats:token' out of a URL or a blob of page source."""
    found: list[str] = []
    for ats_name, pattern in PATTERNS:
        for token in re.findall(pattern, text or "", re.I):
            if token.lower() in JUNK or len(token) < 2:
                continue
            # Ashby tokens are case sensitive; everyone else is lowercase.
            token = token if ats_name == "ashby" else token.lower()
            code = f"{ats_name}:{token}"
            if code not in found:
                found.append(code)
            if len(found) >= limit:
                return found
    return found


def discover(url: str, client: httpx.Client) -> tuple[list[str], str]:
    """Return (candidate codes, how they were found)."""
    direct = from_text(url)
    if direct:
        return direct, "from the URL"

    try:
        r = client.get(
            url,
            headers={"User-Agent": UA, "Accept": "text/html,*/*"},
            follow_redirects=True,
            timeout=25,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return [], f"could not load the page ({type(exc).__name__})"

    # Redirects often land straight on the ATS.
    landed = from_text(str(r.url))
    if landed:
        return landed, "from the redirect"

    body = from_text(r.text[:600_000])
    if body:
        return body, "from the page source"
    return [], "no ATS found in the page"


def slug_from_url(url: str) -> str:
    """A readable display name guess, e.g. 'notion.so/careers' -> 'Notion'."""
    m = re.search(r"https?://(?:www\.)?([A-Za-z0-9-]+)", url or "")
    return m.group(1).replace("-", " ").title() if m else ""
