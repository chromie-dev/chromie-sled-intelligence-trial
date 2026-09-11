"""Vendor advertisements on a Cal eProcure event: companies announcing themselves.

Reached by firing `ZZ_VNDR_AD_WRK_VENDOR_DETAILS_PB` on an event detail page. The
resulting "View Vendor Ad" page carries two independent boards:

* **Prime Seeking Sub** — a company that intends to bid this event and wants
  subcontractors. The strongest forward-looking signal Cal eProcure exposes, because
  posting one is a statement about *this* solicitation.
* **Sub Seeking Prime** — a company offering itself to whoever bids. Weaker, and where
  the noise lives.

Three limits are built in rather than noted.

**These are never bidders.** An ad is `declared_interest`. It names a person and a
company in free text and carries no supplier id, so promoting it to `known_bidder` would
manufacture a competitive field out of marketing copy.

**Absence is stated, not inferred.** The page says "No Ad for Prime Seeking Sub" in so
many words. That is a different fact from a request that failed, and the two must not
collapse into one -- the same distinction the soft-404 handling makes elsewhere.

**Generic bid-assistance ads are flagged.** Observed live: a certified small business
posting "We can help you search and bid on opportunities" against an event it has no
intention of bidding. Those recur across unrelated solicitations, so counting them as
interest would attach the same handful of companies to everything.

Contact fields are read past and never stored, matching the supplier-search decision:
the README puts private contact enrichment out of scope, and these ads are the one place
a named individual's email and phone sit in plain sight.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .caleprocure import EVENT_DETAIL_URL, _text

ACTION = "ZZ_VNDR_AD_WRK_VENDOR_DETAILS_PB"
SOURCE_KEY = "caleprocure_vendor_ads"

# The two boards, and the stated-absence marker for each.
BOARDS = {
    "sub_seeking_prime": ("ZZ_VNDR_SUB_VW_", "No Ad for Sub Seeking Prime"),
    "prime_seeking_sub": ("ZZ_VNDR_PRIM_VW_", "No Ad for Prime Seeking Sub"),
}
FIELDS = {
    "vendor_name": "NAME1",
    "description": "DESCRLONG",
    "response_deadline": "LAST_ENTRY_DATE",
    "created": "CREATE_DTTM",
    "updated": "UPDATE_DTTM",
}
# Present on the page, deliberately not captured. See the module docstring.
CONTACT_FIELDS_NOT_CAPTURED = ("EMAILID_VNDR", "PHONE")

_EVENT = {
    "business_unit": "ZZ_VNDR_AD_TBL_BUSINESS_UNIT",
    "event_id": "ZZ_VNDR_AD_TBL_AUC_ID",
    "event_name": "ZZ_VNDR_AD_WRK_ZZ_AUC_NAME",
}

# Phrases that mark an ad as touting a service to bidders rather than announcing an
# intention to bid. Drawn from observed copy, not imagination.
_GENERIC = re.compile(
    r"help you (search|find|bid)|search and bid on opportunit|"
    r"bid (assistance|matching) service|we can help you|"
    r"recruiting abilities|after you win", re.I)


def _one(page: str, element_id: str) -> str | None:
    # Escaped: a PeopleSoft row id ends in `$0`, and an unescaped `$` is an end-of-line
    # anchor, so every field silently read as None and the ad was dropped as empty.
    eid = re.escape(element_id)
    match = re.search(rf"id='{eid}'[^>]*>(.*?)<", page, re.S)
    if match is None:
        match = re.search(rf"id='{eid}'[^>]*value='([^']*)'", page)
    if match is None:
        return None
    return _text(match.group(1)).strip() or None


def parse_event(page: str) -> dict[str, Any]:
    """Which solicitation this ad page belongs to."""
    return {key: _one(page, element) for key, element in _EVENT.items()}


# Contractors routinely cite their state licence in the ad copy. Observed live:
# "licensed by the CSLB #1155122 under C-13 Fencing". That number is the one identifier
# that crosses sources -- these ads carry no supplier id, and a CSLB licence keys the
# same company in the contractor registry.
_LICENCE = re.compile(r"(?:CSLB|licen[cs]e|lic\.?)[^0-9#]{0,20}#?\s*(\d{6,8})\b", re.I)


def licence_numbers(description: str | None) -> list[str]:
    """CSLB licence numbers cited in the ad text, if any."""
    return sorted({m.group(1) for m in _LICENCE.finditer(description or "")})


def looks_generic(description: str | None) -> bool:
    """Is this an ad for bid-assistance services rather than interest in the event?"""
    return bool(_GENERIC.search(description or ""))


def parse_board(page: str, board: str) -> dict[str, Any]:
    """One board's ads, or an explicit statement that it has none."""
    if board not in BOARDS:
        raise ValueError(f"unknown board {board!r}; expected {sorted(BOARDS)}")
    prefix, absent_marker = BOARDS[board]
    if absent_marker in page:
        # Stated absence. Not the same as a failure, and not the same as "unknown".
        return {"board": board, "stated_absent": True, "ads": []}

    indexes = sorted(int(i) for i in
                     set(re.findall(rf"id='{prefix}{FIELDS['vendor_name']}\$(\d+)'",
                                    page)))
    ads = []
    for i in indexes:
        ad = {key: _one(page, f"{prefix}{element}${i}")
              for key, element in FIELDS.items()}
        if not (ad.get("vendor_name") or ad.get("description")):
            continue
        ad["board"] = board
        ad["generic_bid_assistance"] = looks_generic(ad.get("description"))
        ad["cslb_licences"] = licence_numbers(ad.get("description"))
        ads.append(ad)
    return {"board": board, "stated_absent": False, "ads": ads}


def parse_ad_page(page: str) -> dict[str, Any]:
    """Both boards for one event."""
    event = parse_event(page)
    boards = {name: parse_board(page, name) for name in BOARDS}
    return {
        **event,
        "boards": boards,
        "ad_count": sum(len(b["ads"]) for b in boards.values()),
        "generic_count": sum(1 for b in boards.values()
                             for a in b["ads"] if a["generic_bid_assistance"]),
    }


def declared_interest_rows(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Ads as declared-interest rows. Never bidder rows.

    A prime seeking a sub is saying it means to bid this event; a sub seeking a prime is
    saying it wants work from whoever does. Both are interest, at different strengths,
    and neither is a bid -- so `participation` is fixed and there is no code path that
    can emit one of these as a `known_bidder`.
    """
    bu, eid = parsed.get("business_unit"), parsed.get("event_id")
    rows = []
    for board in parsed["boards"].values():
        for ad in board["ads"]:
            rows.append({
                "business_unit": bu,
                "event_id": eid,
                "vendor_name_raw": ad.get("vendor_name"),
                "participation": "declared_interest",
                "interest_direction": ad["board"],
                "intends_to_bid": ad["board"] == "prime_seeking_sub",
                "generic_bid_assistance": ad["generic_bid_assistance"],
                "cslb_licences": ad["cslb_licences"],
                "description": ad.get("description"),
                "ad_created": ad.get("created"),
                "response_deadline": ad.get("response_deadline"),
                # No supplier id exists on this surface, so identity is unresolved by
                # construction and any later match is a name match.
                "supplier_id": None,
                "identity_confidence": "unresolved",
                "source_key": SOURCE_KEY,
                "evidence_url": EVENT_DETAIL_URL,
            })
    return rows


def harvest(fetch_ad_page, events: Iterable[dict[str, str]], *,
            on_progress: Any = None) -> dict[str, Any]:
    """Read the ad page for each event.

    `fetch_ad_page(business_unit, event_id) -> str` performs the postback; this module
    never does. Events whose page cannot be read are recorded, and kept apart from
    events whose page said there were no ads.
    """
    say = on_progress or (lambda _m: None)
    rows: list[dict[str, Any]] = []
    checked = with_ads = 0
    stated_none: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for event in events:
        bu, eid = event.get("business_unit"), event.get("event_id")
        try:
            page = fetch_ad_page(bu, eid)
        except Exception as exc:
            failures.append({"business_unit": bu, "event_id": eid,
                             "error": f"{type(exc).__name__}: {exc}"})
            continue
        checked += 1
        parsed = parse_ad_page(page)
        if parsed["ad_count"]:
            with_ads += 1
            rows += declared_interest_rows(parsed)
        else:
            stated_none.append({"business_unit": bu, "event_id": eid})
        if checked % 25 == 0:
            say(f"{checked} events read, {with_ads} carried an ad")
    generic = sum(1 for r in rows if r["generic_bid_assistance"])
    say(f"{checked} events read, {with_ads} carried an ad, {len(rows)} ads "
        f"({generic} generic bid-assistance), {len(failures)} failed")
    return {"rows": rows, "events_checked": checked, "events_with_ads": with_ads,
            "events_stating_no_ads": stated_none, "failures": failures,
            "generic_bid_assistance": generic, "source_key": SOURCE_KEY}
