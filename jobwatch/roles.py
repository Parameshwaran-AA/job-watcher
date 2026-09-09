"""Tell an internship apart from a real job, by title alone.

Deliberately narrow. Only titles that clearly say intern, co-op, apprentice or
trainee are caught. New-grad and early-career postings are NOT interns and stay
in the main list, because they are real salaried jobs.
"""

from __future__ import annotations

import re

# \bintern\b will not match "internal" or "international": those have a word
# character straight after "intern", so the closing boundary fails.
_INTERN = re.compile(
    r"\b(?:intern|interns|interning|internship|internships"
    r"|co-?op|co-?ops"
    r"|apprentice|apprenticeship|trainee)\b",
    re.I,
)


def is_intern(title: str | None) -> bool:
    """True if the title is an internship, co-op, apprenticeship or traineeship."""
    if not title:
        return False
    return bool(_INTERN.search(title))
