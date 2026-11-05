# src/jarvis/people/gate.py
"""The positive verification gate for people research (R4 D10, D-D1.2): the real control.

A deny list can only catch wording, and a bare private name ("Priya Nair") has none. So nothing
produces profile links until the first-pass search results VERIFY the subject as one of:

- PUBLIC_FIGURE: a Wikipedia or Wikidata page for that name (not a disambiguation page), or (AI
  mode only) at least two news / official pages on different sites that name the person together
  with a public role (minister, MLA, CEO, founder, author, actor, athlete, professor ...).
- DUE_DILIGENCE (AI mode only): the context names an organisation or a professional role, AND
  the results tie the NAME to it from a page the person did not write about themselves: a company
  registry, the organisation's own site or LinkedIn company page, an organisation GitHub, press, a
  conference or author page. A LinkedIn personal profile and social profiles never count: anyone
  can claim to be a director.

Anything else is UNCLEAR and gets the fixed refusal. In `strict` mode (no-AI mode, or no model
may be called) only the Wikipedia / Wikidata route verifies. `profile_platforms` then scopes the
links: the full public set for a public figure, professional surfaces only for a due-diligence
subject (never Instagram, Facebook, personal X).
"""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from jarvis.people.guard import fold
from jarvis.web.ports import SearchHit

NEWS_MIN_SITES = 2
ROLE_ONLY_MIN_SITES = 2
ROLE_WINDOW = 140  # characters either side of the name inside which the role must appear
MIN_ORG_TOKEN = 3


class Subject(StrEnum):
    PUBLIC_FIGURE = "public_figure"
    DUE_DILIGENCE = "due_diligence"
    PRIVATE = "private"
    UNCLEAR = "unclear"


PUBLIC_PLATFORMS = frozenset(
    {"linkedin", "linkedin_company", "github", "youtube", "x", "wikipedia", "instagram", "facebook"}
)
PROFESSIONAL_PLATFORMS = frozenset({"linkedin", "linkedin_company", "github", "wikipedia"})

PERSONAL_SOCIAL = frozenset(
    {"instagram.com", "facebook.com", "x.com", "twitter.com", "tiktok.com", "snapchat.com",
     "threads.net", "pinterest.com", "reddit.com", "quora.com", "youtube.com", "linktr.ee",
     "tinder.com", "bumble.com"}
)  # fmt: skip
REGISTRIES = frozenset(
    {"zaubacorp.com", "mca.gov.in", "opencorporates.com", "tofler.in", "thecompanycheck.com",
     "falconebiz.com", "instafinancials.com"}
)  # fmt: skip
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "ac", "gov", "nic", "edu"})

_I = re.IGNORECASE
_PUBLIC_ROLE = re.compile(
    r"\b(?:minister|mla|mp|member of parliament|chief minister|prime minister|president|"
    r"vice[- ]president|governor|senator|mayor|ceo|chairman|chairperson|founder|co-founder|"
    r"managing director|director[- ]general|commissioner|collector|ambassador|judge|justice|"
    r"actor|actress|singer|author|writer|poet|journalist|athlete|cricketer|footballer|olympian|"
    r"professor|scientist|economist|politician|spokesperson|industrialist|entrepreneur|"
    r"filmmaker|chief executive|secretary of|advocate general)\b",
    _I,
)
_DD_ROLE = re.compile(
    r"\b(?:vendor|supplier|bidder|contractor|candidate|applicant|director|partner|proprietor|"
    r"consultant|founder|co-founder|ceo|cto|cfo|coo|md|chairman|manager|engineer|lawyer|"
    r"advocate|auditor|representative|executive|officer|head|vp|vice president|owner|promoter|"
    r"signatory|trustee)\b",
    _I,
)
_CAP_RUN = re.compile(r"[A-Z][\w&.\-]*(?:\s+(?:[A-Z][\w&.\-]*|&|and|of))*")
_ORG_STOP = frozenset(
    {"pvt", "ltd", "llp", "inc", "corp", "corporation", "company", "co", "limited", "private",
     "technologies", "technology", "solutions", "services", "systems", "group", "industries",
     "enterprises", "and", "the", "tender", "bid", "rfp", "vendor", "supplier", "bidder"}
)  # fmt: skip


def name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"\w+", fold(name)) if len(t) > 1]


def _mentions(text: str, tokens: list[str]) -> bool:
    return bool(tokens) and all(re.search(rf"\b{re.escape(t)}\b", text) for t in tokens)


def _text(h: SearchHit) -> str:
    return fold(f"{h.title} {h.content}")


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def registrable(host: str) -> str:
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _path(url: str) -> list[str]:
    try:
        return [p for p in urlsplit(url).path.split("/") if p]
    except ValueError:
        return []


def is_personal_social(url: str) -> bool:
    return registrable(_host(url)) in PERSONAL_SOCIAL


# ---- public figure ----------------------------------------------------------------------------


def _is_disambiguation(h: SearchHit) -> bool:
    blob = f"{h.title} {h.url} {h.content[:200]}".lower()
    return "disambiguation" in blob or "may refer to" in blob


def _wiki_names(h: SearchHit, tokens: list[str]) -> bool:
    host, seg = _host(h.url), _path(h.url)
    wiki = host.endswith(".wikipedia.org") and host.count(".") == 2
    data = host in ("wikidata.org", "www.wikidata.org")
    if not (wiki or data) or len(seg) < 2 or seg[0] != "wiki" or ":" in seg[1]:
        return False
    if _is_disambiguation(h):
        return False
    slug = fold(unquote(seg[1]).replace("_", " "))
    return _mentions(f"{slug} {fold(h.title)}", tokens)


def public_by_wiki(hits: list[SearchHit], tokens: list[str]) -> bool:
    return any(_wiki_names(h, tokens) for h in hits)


def _role_near_name(h: SearchHit, tokens: list[str], role: re.Pattern[str]) -> bool:
    text = _text(h)
    if not _mentions(text, tokens):
        return False
    for m in re.finditer(rf"\b{re.escape(tokens[-1])}\b", text):
        lo, hi = max(0, m.start() - ROLE_WINDOW), m.end() + ROLE_WINDOW
        if role.search(text[lo:hi]):
            return True
    return False


def public_by_news(hits: list[SearchHit], tokens: list[str]) -> bool:
    sites = {
        registrable(_host(h.url))
        for h in hits
        if not is_personal_social(h.url)
        and "linkedin.com" not in _host(h.url)
        and _role_near_name(h, tokens, _PUBLIC_ROLE)
    }
    return len(sites) >= NEWS_MIN_SITES


# ---- due diligence ----------------------------------------------------------------------------


def org_tokens(context: str) -> list[str]:
    """Significant words of the longest capitalised phrase in `context` that is not a role."""
    best: list[str] = []
    for run in _CAP_RUN.findall(context):
        words = [
            w
            for w in re.findall(r"\w+", fold(run))
            if len(w) >= MIN_ORG_TOKEN
            and w not in _ORG_STOP
            and not _DD_ROLE.fullmatch(w)
            and not w.isdigit()
        ]
        if len(words) > len(best):
            best = words
    return best


def _independent_page(h: SearchHit, org: list[str]) -> bool:
    """A page about the person that the person did not write: not social, not a self-made
    LinkedIn profile. LinkedIn company pages, org GitHubs, registries and press count."""
    host, seg = _host(h.url), _path(h.url)
    if is_personal_social(h.url):
        return False
    if registrable(host) == "linkedin.com":
        return bool(seg) and seg[0] in ("company", "school")
    if registrable(host) == "github.com":
        return bool(seg) and any(t in seg[0].lower() for t in org)
    return True


def due_diligence(hits: list[SearchHit], tokens: list[str], context: str) -> bool:
    org = org_tokens(context)
    role = _DD_ROLE.search(context) is not None
    if not org and not role:
        return False
    if org:
        return any(
            _independent_page(h, org) and _mentions(_text(h), [*tokens, *org]) for h in hits
        )
    sites = {
        registrable(_host(h.url))
        for h in hits
        if _independent_page(h, org) and _role_near_name(h, tokens, _DD_ROLE)
    }
    return len(sites) >= ROLE_ONLY_MIN_SITES


# ---- the gate ---------------------------------------------------------------------------------


def verify(name: str, context: str, hits: list[SearchHit], *, strict: bool) -> Subject:
    """PUBLIC_FIGURE, DUE_DILIGENCE or UNCLEAR from the first-pass results. Pure and
    deterministic; never upgrades on a model's say-so."""
    tokens = name_tokens(name)
    if public_by_wiki(hits, tokens):
        return Subject.PUBLIC_FIGURE
    if strict:
        return Subject.UNCLEAR
    if public_by_news(hits, tokens):
        return Subject.PUBLIC_FIGURE
    if due_diligence(hits, tokens, context):
        return Subject.DUE_DILIGENCE
    return Subject.UNCLEAR


def profile_platforms(subject: Subject) -> frozenset[str]:
    """Which profile platforms may be offered for a verified subject (nothing otherwise)."""
    if subject is Subject.PUBLIC_FIGURE:
        return PUBLIC_PLATFORMS
    if subject is Subject.DUE_DILIGENCE:
        return PROFESSIONAL_PLATFORMS
    return frozenset()


__all__ = [
    "PROFESSIONAL_PLATFORMS",
    "PUBLIC_PLATFORMS",
    "Subject",
    "is_personal_social",
    "name_tokens",
    "org_tokens",
    "profile_platforms",
    "registrable",
    "verify",
]
