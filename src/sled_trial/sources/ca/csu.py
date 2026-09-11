"""CSU public bid portal: 23 campuses and the Chancellor's Office on one endpoint.

`bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=CalState` is the Jaggaer portal
the California State University system publishes through, covering every campus since
2020. It answers plain HTTP with no login and no browser.

**It is a solicitation source, not a bidder source, and that limit is the point.** The
portal has an Award tab, and a row there is marked `Awarded` -- but the awardee is not
named anywhere in the public listing, and the event detail behind each row redirects to
a JAGGAER supplier login. So this widens the opportunity picture across the education
segment and adds nothing to the competitive one. Recording that plainly beats shipping
an adapter whose name implies award data.

What it does give per solicitation: campus, status, type, solicitation number, open and
close datetimes, a buyer contact, and a link to the event PDF on S3.
"""
from __future__ import annotations

import html as htmllib
import re
from typing import Any, Callable, Iterable

BASE = "https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=CalState"
SOURCE_KEY = "csu_public_bid_portal"
BUSINESS_UNIT = "CSU"

# The portal's own tabs. `all` is a superset but is kept separate rather than used
# alone, because a row's tab is how its lifecycle stage is known.
TABS = {
    "open": "PHX_NAV_SourcingOpenForBid",
    "closed": "PHX_NAV_SourcingClosed",
    "awarded": "PHX_NAV_SourcingAward",
    "upcoming": "PHX_NAV_SourcingUpcoming",
    "all": "PHX_NAV_SourcingAllOpps",
}

# Attribute quoting is mixed across this markup exactly as it is on the PeopleSoft
# surfaces, so every pattern accepts either. A single-quote-only pattern parses the live
# page to zero rows, which is indistinguishable from a tab with no solicitations --
# the same trap `caleprocure.Q` exists to avoid, walked into again here.
Q = r"['\"]"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_STATUS = re.compile(rf"class={Q}mosaic status-badge[^'\"]*{Q}[^>]*>([^<]+)<", re.I)
_TITLE = re.compile(rf"class={Q}btn btn-link[^'\"]*{Q}[^>]*>([^<]+)<", re.I)
# Every field is a `phx` div. Labels carry several different classes -- `multicolumn`,
# `table-row-layout`, `column` -- but a value is always `table-cell-layout`, so pairing
# is positional: a label div followed by the next value div. Matching on label classes
# instead captured the wrong pairs and silently lost Type, Close and Contact.
_CELL = re.compile(rf"<div[^>]*class={Q}(phx[^'\"]*){Q}[^>]*>(.*?)</div>", re.S | re.I)
_VALUE_CLASS = "table-cell-layout"
_DESCRIPTION_CLASS = "label-mini"
_EVENT_PDF = re.compile(
    rf"href={Q}(https://solutions-selectsite-documents\.s3\.amazonaws\.com/[^'\"]+){Q}",
    re.I)
# Contact renders as "Name email@campus.edu". The name is kept and the address is not,
# matching the supplier-search and vendor-ad decisions: the README puts private contact
# enrichment out of scope.
_EMAIL = re.compile(r"\s*[\w.+-]+@[\w.-]+\.\w+\s*")


def _fields(row: str) -> tuple[dict[str, str], str | None]:
    """Label -> value for one row, plus the free-text description."""
    cells = [(cls, _text(re.sub(r"<[^>]+>", " ", body)))
             for cls, body in _CELL.findall(row)]
    description = next((v for cls, v in cells
                        if _DESCRIPTION_CLASS in cls and v), None)
    fields: dict[str, str] = {}
    pending: str | None = None
    for cls, value in cells:
        if not value:
            continue
        if _VALUE_CLASS in cls:
            if pending:
                fields[pending] = value
                pending = None
        elif _DESCRIPTION_CLASS not in cls:
            pending = value
    return fields, description


# A solicitation number leads with its campus: SSU-IFB-00000823, SJSU-RFP-00000831-2026.
# CSUCO is the Chancellor's Office rather than a campus.
_CAMPUS = re.compile(r"^([A-Z]{2,6})-")


def campus_of(number: str | None) -> str | None:
    """Campus code from the solicitation number, which is where it is encoded."""
    match = _CAMPUS.match((number or "").strip())
    return match.group(1) if match else None


def tab_url(tab: str = "all", page: int = 1) -> str:
    if tab not in TABS:
        raise ValueError(f"unknown tab {tab!r}; expected {sorted(TABS)}")
    return f"{BASE}&tab={TABS[tab]}" + (f"&PageNum={page}" if page > 1 else "")


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    return htmllib.unescape(re.sub(r"\s+", " ", value)).strip() or None


def parse_solicitations(page: str, tab: str | None = None) -> list[dict[str, Any]]:
    """Solicitation rows from one listing page."""
    out = []
    for match in _ROW.finditer(page):
        row = match.group(1)
        status = _STATUS.search(row)
        title = _TITLE.search(row)
        if not status or not title:
            continue
        fields, description = _fields(row)
        number = fields.get("Number")
        pdf = _EVENT_PDF.search(row)
        contact = fields.get("Contact")
        buyer = _EMAIL.sub(" ", contact).strip() if contact else None
        out.append({
            "business_unit": BUSINESS_UNIT,
            "event_id": number,
            "campus": campus_of(number),
            "status": _text(status.group(1)),
            "title": _text(title.group(1)),
            "solicitation_type": fields.get("Type"),
            "opens": fields.get("Open"),
            "closes": fields.get("Close"),
            "description": description,
            "buyer": buyer,
            "event_pdf_url": pdf.group(1) if pdf else None,
            "listing_tab": tab,
            "source_key": SOURCE_KEY,
            # Stated once, in the data, so a consumer cannot mistake this for a source
            # that names winners: the Award tab marks status only.
            "names_awardee": False,
        })
    return out


def harvest(fetch_page: Callable[[str], str],
            tabs: Iterable[str] = ("open", "closed", "awarded", "upcoming"),
            *, max_pages: int = 20,
            on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Walk the listing tabs. `fetch_page(url) -> str`; this module never requests.

    Pages are followed until one returns nothing new. A tab that fails is recorded
    rather than dropped, so a missing lifecycle stage is visible instead of looking
    like a stage with no solicitations.
    """
    say = on_progress or (lambda _m: None)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    failures: list[dict[str, str]] = []
    per_tab: dict[str, int] = {}
    for tab in tabs:
        before = len(rows)
        for page in range(1, max_pages + 1):
            try:
                found = parse_solicitations(fetch_page(tab_url(tab, page)), tab)
            except Exception as exc:
                failures.append({"tab": tab, "page": page,
                                 "error": f"{type(exc).__name__}: {exc}"})
                break
            fresh = [r for r in found
                     if r["event_id"] and r["event_id"] not in seen]
            for r in fresh:
                seen.add(r["event_id"])
            rows += fresh
            if not fresh:
                break
        per_tab[tab] = len(rows) - before
        say(f"{tab}: {per_tab[tab]} solicitations")
    campuses = sorted({r["campus"] for r in rows if r["campus"]})
    say(f"{len(rows)} solicitations across {len(campuses)} campuses; "
        f"{len(failures)} tab failures")
    return {"rows": rows, "per_tab": per_tab, "campuses": campuses,
            "failures": failures, "source_key": SOURCE_KEY,
            "names_awardee": False}
