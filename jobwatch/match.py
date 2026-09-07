"""Sieve one (title), the experience parser, and sieve two (match score)."""

from __future__ import annotations

import math
import re
from collections import Counter

# ---------------------------------------------------------------- sieve one

# ---------------------------------------------------------------------------
# EDIT ME. This is the hard gate: a title that matches nothing here is never
# scored and never appears. Add a title by dropping the words into the right
# family, separated by |. Use [\s-]? between words so "devops", "dev ops" and
# "dev-ops" all match. Then run: python tests/test_pipeline.py
# ---------------------------------------------------------------------------
ROLE_FAMILIES: dict[str, re.Pattern] = {
    "ai": re.compile(
        r"\b(machine[\s-]?learning|ml|ai|a\.i\.|ai[/\s-]?ml|deep[\s-]?learning|nlp|llm|"
        r"computer[\s-]?vision|applied[\s-]?scien(?:ce|tist|tists)|"
        r"research[\s-]?(?:engineer|scientist)|mlops|genai|generative[\s-]?ai|"
        r"data[\s-]?science[\s-]?engineer)\b",
        re.I,
    ),
    "data": re.compile(
        r"\b(data[\s-]?scien(?:ce|tist|tists)|data[\s-]?engineer|data[\s-]?analyst|"
        r"analytics[\s-]?engineer|business[\s-]?intelligence|quantitative[\s-]?analyst|"
        r"decision[\s-]?scien(?:ce|tist|tists))\b",
        re.I,
    ),
    "swe": re.compile(
        r"\b(software[\s-]?engineer|software[\s-]?developer|"
        r"software[\s-]?development[\s-]?engineer|swe|sde|backend|back[\s-]?end|"
        r"frontend|front[\s-]?end|full[\s-]?stack|fullstack|platform[\s-]?engineer|"
        r"infrastructure[\s-]?engineer|systems?[\s-]?engineer|application[\s-]?developer|"
        r"web[\s-]?developer|api[\s-]?engineer|dev[\s-]?ops|site[\s-]?reliability|sre|"
        r"cloud[\s-]?engineer|mobile[\s-]?(?:app[\s-]?)?(?:engineer|developer)|"
        r"ios[\s-]?(?:engineer|developer)|android[\s-]?(?:engineer|developer)|"
        r"distributed[\s-]?systems)\b",
        re.I,
    ),
}

# Titles that are above the ceiling no matter what the description says.
TOO_SENIOR = re.compile(
    r"\b(staff|principal|distinguished|fellow|architect|"
    r"engineering[\s-]?manager|director|head[\s-]?of|vp|vice[\s-]?president|"
    r"cto|chief|president)\b",
    re.I,
)

# Titles that look like a match but are a different job entirely.
NOT_ENGINEERING = re.compile(
    r"\b(sales[\s-]?engineer|solutions?[\s-]?engineer|support[\s-]?engineer|"
    r"customer[\s-]?engineer|field[\s-]?engineer|recruiter|technical[\s-]?writer|"
    r"account[\s-]?executive|product[\s-]?manager|program[\s-]?manager|"
    r"project[\s-]?manager|designer|marketing)\b",
    re.I,
)

JUNIOR = re.compile(r"\b(intern|internship|new[\s-]?grad|graduate|entry[\s-]?level|junior|jr\.?)\b", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|lead)\b", re.I)


def title_family(title: str) -> str | None:
    """Which role family this title belongs to, or None if it is not one of ours.

    Order matters: 'machine learning engineer' should land in ai, not swe.
    """
    if not title:
        return None
    if NOT_ENGINEERING.search(title):
        return None
    for family in ("ai", "data", "swe"):
        if ROLE_FAMILIES[family].search(title):
            return family
    return None


# ---------------------------------------------------------- experience parser

WORD_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_RANGE = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2})\s*\+?\s*(?:\+|plus)?\s*(?:years?|yrs?)",
    re.I,
)
_MIN_PLUS = re.compile(r"(\d{1,2})\s*(?:\+|plus)\s*(?:years?|yrs?)", re.I)
_MIN_WORDS = re.compile(
    r"(?:minimum|min\.?|at\s+least|over|more\s+than)\s+(?:of\s+)?(\d{1,2}|"
    + "|".join(WORD_NUM)
    + r")\s*(?:\+|plus)?\s*(?:years?|yrs?)",
    re.I,
)
_PLAIN = re.compile(
    r"\b(\d{1,2}|" + "|".join(WORD_NUM) + r")\s*(?:\+|plus)?\s*(?:years?|yrs?)\b", re.I
)

# A bare "N years" is ambiguous. These two anchor it to an actual requirement.
_CTX = r"experience|background|expertise|professional|industry|hands[-\s]?on|track\s+record"
_CTX_BEFORE = re.compile(
    r"(?:" + _CTX + r")\s*(?:of|with|in|:)?\s*(\d{1,2}|" + "|".join(WORD_NUM)
    + r")\s*(?:\+|plus)?\s*(?:years?|yrs?)", re.I
)
_CTX_AFTER = re.compile(
    r"\b(\d{1,2}|" + "|".join(WORD_NUM) + r")\s*(?:\+|plus)?\s*(?:years?|yrs?)"
    r"[^.;]{0,35}?(?:" + _CTX + r")", re.I
)

# Company boilerplate that also contains a year count: "we've been building for
# 10 years", "founded 8 years ago". Never a requirement.
_BOILER = re.compile(
    r"\b(been|founded|since|ago|history|anniversary|celebrat|company|"
    r"for\s+the\s+past|over\s+the\s+last)\b", re.I
)


def _num(token: str) -> int | None:
    token = token.lower()
    if token.isdigit():
        return int(token)
    return WORD_NUM.get(token)


def parse_experience(text: str, title: str = "") -> tuple[int | None, int | None]:
    """Return (min_years, max_years). (None, None) means the posting never says.

    Only the MINIMUM is used for filtering. '3-8 years' has a floor of 3 and you
    are eligible; '8+ years' has a floor of 8 and you are not. When several
    numbers appear, the lowest wins, because being conservative keeps you in the
    running instead of filtering yourself out of a role you could do.
    """
    body = (text or "")[:12000]
    ranges: list[tuple[int, int | None]] = []

    for lo, hi in _RANGE.findall(body):
        a, b = _num(lo), _num(hi)
        if a is not None and b is not None and a <= b <= 30:
            ranges.append((a, b))
    for m in _MIN_PLUS.findall(body):
        v = _num(m)
        if v is not None and v <= 30:
            ranges.append((v, None))
    for m in _MIN_WORDS.findall(body):
        v = _num(m)
        if v is not None and v <= 30:
            ranges.append((v, None))

    if not ranges:
        for pattern in (_CTX_BEFORE, _CTX_AFTER):
            for m in pattern.findall(body):
                v = _num(m)
                if v is not None and 0 < v <= 30:
                    ranges.append((v, None))

    if not ranges:
        # Last resort: a bare "N years", but only when the 45 characters before
        # it are not company boilerplate.
        for m in _PLAIN.finditer(body):
            v = _num(m.group(1))
            if v is None or not (0 < v <= 30):
                continue
            if _BOILER.search(body[max(0, m.start() - 45): m.start()]):
                continue
            ranges.append((v, None))

    if ranges:
        floor = min(r[0] for r in ranges)
        tops = [r[1] for r in ranges if r[1] is not None and r[0] == floor]
        return floor, (max(tops) if tops else None)

    # No number anywhere. Guess from the title, but only loosely.
    if JUNIOR.search(title):
        return 0, 2
    if TOO_SENIOR.search(title):
        return 8, None
    if SENIOR.search(title):
        return 4, 8
    return None, None


def within_ceiling(exp_min: int | None, ceiling: int) -> bool:
    """Postings that state nothing are kept. Only an explicit floor can exclude."""
    return exp_min is None or exp_min < ceiling


# ---------------------------------------------------------------- sieve two

STOP = set(
    """a an and are as at be by for from has have if in into is it its of on or
    that the to was were will with you your we our us they their this these those
    role team work working experience years year job position company candidate
    apply applicants opportunity benefits equal employer including able strong
    excellent great good new all any more most other such than then there here
    who what when how why not no can may must should would could about across""".split()
)

_TOKEN = re.compile(r"[a-z][a-z0-9+#.\-]{1,}")


def tokenize(text: str) -> Counter:
    tokens = [t for t in _TOKEN.findall((text or "").lower()) if t not in STOP and len(t) > 2]
    return Counter(tokens)


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    wa = {k: 1 + math.log(v) for k, v in a.items()}
    wb = {k: 1 + math.log(v) for k, v in b.items()}
    common = wa.keys() & wb.keys()
    if not common:
        return 0.0
    dot = sum(wa[k] * wb[k] for k in common)
    na = math.sqrt(sum(v * v for v in wa.values()))
    nb = math.sqrt(sum(v * v for v in wb.values()))
    return dot / (na * nb) if na and nb else 0.0


class LexicalScorer:
    """Dependency-free fallback. Word overlap, not meaning.

    Scores land lower than the embedding scorer, so thresholds are not
    interchangeable between the two. Run `watcher.py stats` after switching.
    """

    name = "lexical"

    def __init__(self, profile: str):
        self.profile = tokenize(profile)

    def score(self, texts: list[str]) -> list[int]:
        return [min(100, round(_cosine(self.profile, tokenize(t)) * 150)) for t in texts]


class EmbeddingScorer:
    """Real semantic matching. Runs locally on CPU, no API and no key."""

    name = "embedding"

    def __init__(self, profile: str, model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        self.model = SentenceTransformer(model)
        self.profile_vec = self.model.encode(
            profile[:4000], normalize_embeddings=True, show_progress_bar=False
        )

    def score(self, texts: list[str]) -> list[int]:
        if not texts:
            return []
        vecs = self.model.encode(
            [t[:4000] for t in texts], normalize_embeddings=True, show_progress_bar=False
        )
        return [max(0, min(100, round(float(v @ self.profile_vec) * 100))) for v in vecs]


def get_scorer(profile: str, prefer_embeddings: bool = True):
    if prefer_embeddings:
        try:
            return EmbeddingScorer(profile)
        except Exception as exc:  # noqa: BLE001
            print(f"  embedding scorer unavailable ({exc}); using lexical fallback")
    return LexicalScorer(profile)
