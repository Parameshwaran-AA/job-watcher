"""Decide whether a posting's location could be in the United States.

The rule is deliberately lopsided. A location that names the US or a US place
passes. A location that names somewhere else fails. Anything we cannot read --
blank, "Hybrid", "Remote, Global" -- passes, because an unfilled location field
is far more often a US company that skipped it than a deliberate exclusion, and
missing a real job costs more than showing one extra.
"""

from __future__ import annotations

import re

_STATES = (
    "alabama alaska arizona arkansas california colorado connecticut delaware florida "
    "georgia hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland "
    "massachusetts michigan minnesota mississippi missouri montana nebraska nevada ohio "
    "oklahoma oregon pennsylvania tennessee texas utah vermont virginia washington "
    "wisconsin wyoming"
).split()

# Two-letter postal codes. Matched case-sensitively so a lowercase word like
# "or" or "in" in prose cannot masquerade as Oregon or Indiana.
_CODES = (
    "AL AK AZ AR CA CO CT DC DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN MO MS MT "
    "NC ND NE NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT WA WI WV WY"
).split()

_US = re.compile(
    r"\b(?:united\s+states|north\s+america|"
    r"san\s+francisco|new\s+york\s+city|los\s+angeles|san\s+diego|san\s+jose|"
    r"seattle|bellevue|redmond|portland|denver|boulder|austin|dallas|houston|"
    r"chicago|boston|philadelphia|pittsburgh|atlanta|miami|nashville|detroit|"
    r"minneapolis|phoenix|salt\s+lake\s+city|mountain\s+view|palo\s+alto|"
    r"sunnyvale|menlo\s+park|santa\s+clara|brooklyn|bay\s+area|silicon\s+valley|"
    r"new\s+hampshire|new\s+jersey|new\s+mexico|new\s+york|north\s+carolina|"
    r"north\s+dakota|rhode\s+island|south\s+carolina|south\s+dakota|west\s+virginia|"
    + "|".join(_STATES) + r")\b",
    re.I,
)

# Kept separate because a trailing \b cannot follow the "." in "U.S.".
_ABBR = re.compile(r"(?:\bu\.\s?s\.(?:\s?a\.)?|\bu\.?s\.?a\b|\bus\b)", re.I)

_CODE = re.compile(r"\b(?:" + "|".join(_CODES) + r")\b")

_ELSEWHERE = re.compile(
    r"\b(?:united\s+kingdom|uk|u\.k\.|england|scotland|wales|ireland|london|manchester|"
    r"edinburgh|dublin|belfast|"
    r"canada|canadian|toronto|vancouver|montreal|ottawa|calgary|waterloo|"
    r"india|bangalore|bengaluru|hyderabad|delhi|mumbai|pune|chennai|gurgaon|noida|"
    r"poland|warsaw|krak[oó]w|wroc[lł]aw|gda[nń]sk|"
    r"germany|berlin|munich|m[uü]nchen|hamburg|frankfurt|cologne|"
    r"france|paris|lyon|spain|madrid|barcelona|valencia|portugal|lisbon|porto|"
    r"netherlands|amsterdam|utrecht|rotterdam|belgium|brussels|"
    r"switzerland|zurich|z[uü]rich|geneva|austria|vienna|"
    r"sweden|stockholm|norway|oslo|denmark|copenhagen|finland|helsinki|"
    r"iceland|reykjav[ií]k|estonia|tallinn|lithuania|vilnius|latvia|riga|"
    r"czech|prague|romania|bucharest|hungary|budapest|bulgaria|sofia|"
    r"serbia|belgrade|croatia|zagreb|greece|athens|ukraine|kyiv|kiev|"
    r"israel|tel\s?aviv|jerusalem|turkey|istanbul|"
    r"uae|dubai|abu\s+dhabi|saudi|qatar|doha|egypt|cairo|"
    r"italy|rome|milan|turin|"
    r"japan|tokyo|osaka|korea|seoul|china|shanghai|beijing|shenzhen|"
    r"hong\s?kong|taiwan|taipei|singapore|malaysia|kuala\s+lumpur|"
    r"philippines|manila|indonesia|jakarta|vietnam|hanoi|thailand|bangkok|"
    r"australia|sydney|melbourne|brisbane|perth|new\s+zealand|auckland|wellington|"
    r"brazil|brasil|s[aã]o\s+paulo|rio\s+de\s+janeiro|mexico|m[eé]xico|guadalajara|"
    r"argentina|buenos\s+aires|chile|santiago|colombia|bogot[aá]|peru|lima|"
    r"uruguay|montevideo|costa\s+rica|"
    r"south\s+africa|cape\s+town|johannesburg|nigeria|lagos|kenya|nairobi|"
    r"pakistan|karachi|lahore|bangladesh|dhaka|sri\s+lanka|colombo|"
    r"emea|apac|latam|anz)\b",
    re.I,
)


def is_us(location: str | None) -> bool:
    """True if the posting could be in the United States."""
    if not location or not location.strip():
        return True
    text = location.strip()
    # A multi-region posting that lists the US anywhere counts as US.
    if _US.search(text) or _ABBR.search(text) or _CODE.search(text):
        return True
    return not _ELSEWHERE.search(text)
