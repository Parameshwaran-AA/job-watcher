"""Adapters for public ATS job-board APIs.

Every adapter takes a board token and an httpx client and returns a list of
Posting objects. Adapters RAISE on failure. That is deliberate: a board that
fails to respond must never be mistaken for a board with zero open jobs, or
the caller will close every job at that company.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

UA = "job-watcher/1.0 (personal job alert tool; contact: you@example.com)"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def clean(raw: str | None) -> str:
    """Turn an ATS description blob into readable plain text.

    Greenhouse double-escapes its HTML, so unescape twice before stripping.
    """
    if not raw:
        return ""
    text = html.unescape(html.unescape(raw))
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = _WS.sub(" ", text)
    return _NL.sub("\n\n", text).strip()


def _iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _epoch_ms(value) -> float | None:
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


@dataclass
class Posting:
    ats: str
    board: str
    company: str
    ext_id: str
    title: str
    location: str
    url: str
    description: str
    posted_at: float | None = None

    @property
    def uid(self) -> str:
        return f"{self.ats}:{self.board}:{self.ext_id}"


def _get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    r = client.get(url, headers={"User-Agent": UA, "Accept": "application/json"}, **kw)
    r.raise_for_status()
    return r


def greenhouse(token: str, client: httpx.Client) -> list[Posting]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    data = _get(client, url).json()
    company = (data.get("meta") or {}).get("company_name") or token
    out = []
    for j in data.get("jobs") or []:
        loc = (j.get("location") or {}).get("name") or ""
        out.append(
            Posting(
                ats="greenhouse",
                board=token,
                company=company,
                ext_id=str(j.get("id")),
                title=(j.get("title") or "").strip(),
                location=loc.strip(),
                url=j.get("absolute_url") or "",
                description=clean(j.get("content")),
                posted_at=_iso(j.get("first_published") or j.get("updated_at")),
            )
        )
    return out


def lever(token: str, client: httpx.Client) -> list[Posting]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    data = _get(client, url).json()
    out = []
    for j in data or []:
        cats = j.get("categories") or {}
        out.append(
            Posting(
                ats="lever",
                board=token,
                company=token,
                ext_id=str(j.get("id")),
                title=(j.get("text") or "").strip(),
                location=(cats.get("location") or "").strip(),
                url=j.get("hostedUrl") or j.get("applyUrl") or "",
                description=j.get("descriptionPlain") or clean(j.get("description")),
                posted_at=_epoch_ms(j.get("createdAt")),
            )
        )
    return out


def ashby(token: str, client: httpx.Client) -> list[Posting]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"
    data = _get(client, url).json()
    out = []
    for j in data.get("jobs") or []:
        out.append(
            Posting(
                ats="ashby",
                board=token,
                company=token,
                ext_id=str(j.get("id")),
                title=(j.get("title") or "").strip(),
                location=(j.get("location") or "").strip(),
                url=j.get("jobUrl") or j.get("applyUrl") or "",
                description=j.get("descriptionPlain") or clean(j.get("descriptionHtml")),
                posted_at=_iso(j.get("publishedAt")),
            )
        )
    return out


def recruitee(token: str, client: httpx.Client) -> list[Posting]:
    url = f"https://{token}.recruitee.com/api/offers/"
    data = _get(client, url).json()
    out = []
    for j in data.get("offers") or []:
        loc = j.get("location") or ", ".join(
            filter(None, [j.get("city"), j.get("country_code")])
        )
        out.append(
            Posting(
                ats="recruitee",
                board=token,
                company=token,
                ext_id=str(j.get("id")),
                title=(j.get("title") or "").strip(),
                location=(loc or "").strip(),
                url=j.get("careers_url") or j.get("careers_apply_url") or "",
                description=clean(j.get("description")),
                posted_at=_iso(j.get("published_at")),
            )
        )
    return out


def workable(token: str, client: httpx.Client) -> list[Posting]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    data = _get(client, url).json()
    company = data.get("name") or token
    out = []
    for j in data.get("jobs") or []:
        loc = j.get("location") or {}
        if isinstance(loc, dict):
            loc = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
        code = j.get("shortcode") or j.get("id")
        out.append(
            Posting(
                ats="workable",
                board=token,
                company=company,
                ext_id=str(code),
                title=(j.get("title") or "").strip(),
                location=str(loc).strip(),
                url=j.get("url") or f"https://apply.workable.com/{token}/j/{code}/",
                description=clean(j.get("description")),
                posted_at=_iso(j.get("published_on") or j.get("created_at")),
            )
        )
    return out


ADAPTERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "recruitee": recruitee,
    "workable": workable,
}


def fetch(code: str, client: httpx.Client) -> list[Posting]:
    """code looks like 'greenhouse:stripe'."""
    ats, _, token = code.partition(":")
    ats = ats.strip().lower()
    if ats not in ADAPTERS:
        raise ValueError(f"unknown ATS '{ats}' in '{code}'")
    if not token:
        raise ValueError(f"missing board token in '{code}'")
    return ADAPTERS[ats](token.strip(), client)
