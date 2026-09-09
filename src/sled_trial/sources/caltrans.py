"""Caltrans weekly bid results: the one California surface that names losing bidders.

Cal eProcure's Response Bid Inquiry is authenticated, so the state portal exposes awardees
and nothing about who they beat. Caltrans publishes the whole field -- every bidder, ranked,
with the amount and the Small Business preference flag -- on a public weekly page that needs
no login, no key and no browser.

The join is exact rather than probabilistic, which is unusual here. Each contract number on
the page links to `caleprocure.ca.gov/event/2660/<contract>`, and 2660 is the Department of
Transportation, whose event ids in the active feed carry that same contract-number format.
So a bidder row reaches a Cal eProcure event by string equality on `(business_unit,
event_id)` -- no title similarity, no date window, no inference tier.

Two limits the caller must respect:

* Results are **preliminary**, subject to verification of SB/DVBE preference, licensing,
  bonding and responsibility. The posted low bidder is not necessarily the awardee. Rank is
  observed; award is not, and this module never claims one.
* Pages are dated to the **Sunday** of their week, and only a rolling window of roughly nine
  months is populated. Older slugs return HTTP 200 with an empty template rather than a 404,
  so a zero-row parse means "no page", never "no bids that week" -- see `looks_populated`.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterator

from .caleprocure import CalEProcureSession, _text
from .scprs import amount_to_numeric

WEEK_URL = "https://dot.ca.gov/programs/procurement-and-contracts/bid-results/bid-week-{date}"
INDEX_URL = "https://dot.ca.gov/programs/procurement-and-contracts/bid-results"
# Caltrans is business unit 2660 in Cal eProcure and FI$Cal.
BUSINESS_UNIT = "2660"

_ROW = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
_EVENT_LINK = re.compile(r"caleprocure\.ca\.gov/event/(\d+)/([A-Za-z0-9._-]+)", re.I)
_LIST_ITEM = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S | re.I)
_TITLE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)
_SB_FLAG = re.compile(r"^SB:\s*([YN])\b", re.I)
_BR = re.compile(r"<br\s*/?>", re.I)


def _bidder(raw_item: str, rank: int) -> dict[str, Any] | None:
    """One `<li>` into a bidder row. Returns None when the item is not a bidder entry.

    The three fields are separated by `<br>` rather than by markup that names them, so the
    split has to happen before tags are stripped: `_text` over the whole item would run the
    company name into the SB flag.
    """
    parts = [_text(p) for p in _BR.split(raw_item)]
    parts = [p for p in parts if p]
    if not parts:
        return None
    name = parts[0]
    flag = next((m.group(1).upper() for p in parts if (m := _SB_FLAG.match(p))), None)
    amount_raw = next((p for p in parts if p.startswith("$")), None)
    numeric = amount_to_numeric(amount_raw)
    if not name or flag is None:
        return None
    return {
        "vendor_name": name,
        "rank": rank,
        "small_business_preference": flag == "Y",
        "bid_amount_raw": amount_raw,
        # An unparseable amount stays null rather than becoming zero: a bid of zero and a
        # bid we could not read are different facts.
        "bid_amount": float(numeric) if numeric is not None else None,
    }


def week_slugs(start: dt.date, end: dt.date) -> Iterator[str]:
    """Page slugs covering `start`..`end`, one per week, oldest first.

    Each page is dated to the Sunday its week begins, so a date is rounded *back* to its
    Sunday. Rounding forward would skip the page holding the first week's bids.
    """
    sunday = start - dt.timedelta(days=(start.weekday() + 1) % 7)
    while sunday <= end:
        yield sunday.isoformat()
        sunday += dt.timedelta(days=7)


def looks_populated(page: str) -> bool:
    """Does this page carry a bid table, or is it the empty shell an unused week returns?

    Unpopulated weeks answer HTTP 200 with a template rather than 404, so status alone
    cannot tell them apart and a zero-row parse is ambiguous. A page that links at least
    one Cal eProcure event has a table; one that does not is a shell, and the caller must
    record "no page" rather than "no bids that week".
    """
    return bool(_EVENT_LINK.search(page))


def parse_bid_results(page: str) -> list[dict[str, Any]]:
    """Solicitations on one weekly page, each with its full ranked field of bidders."""
    results: list[dict[str, Any]] = []
    for row in _ROW.findall(page):
        link = _EVENT_LINK.search(row)
        if not link:
            continue
        bidders = [b for b in (_bidder(item, rank)
                               for rank, item in enumerate(_LIST_ITEM.findall(row), 1))
                   if b]
        if not bidders:
            continue
        title = _TITLE.search(row)
        results.append({
            "business_unit": link.group(1),
            "event_id": link.group(2),
            "title": _text(title.group(1)) if title else None,
            "bidders": bidders,
            "bidder_count": len(bidders),
            "source_key": "caltrans_bid_results",
            "evidence_class": "observed",
            "status_note": ("preliminary bid results, subject to verification of SB/DVBE "
                            "preference, licensing, bonding and responsibility; rank is "
                            "observed, award is not"),
        })
    return results


def bidder_candidates(solicitations: Iterable[dict[str, Any]], *,
                      week: str | None = None) -> list[dict[str, Any]]:
    """Flatten parsed solicitations into one observed-candidate row per bidder.

    Deliberately emits the field names `supabase_export.participant_rows` already reads
    from document-extracted candidates -- `vendor_name_raw`, `amount_raw`,
    `amount_numeric` -- so bidder evidence from this source needs no second export path.
    Identity stays unresolved: the page gives a company name and no supplier id, so the
    match to an SCPRS `supplier_id` is a name comparison the caller must make and grade.
    """
    rows: list[dict[str, Any]] = []
    for sol in solicitations:
        for bidder in sol["bidders"]:
            rows.append({
                "business_unit": sol["business_unit"],
                "event_id": sol["event_id"],
                "vendor_name_raw": bidder["vendor_name"],
                "amount_raw": bidder["bid_amount_raw"],
                "amount_numeric": bidder["bid_amount"],
                "rank": bidder["rank"],
                "bidder_count": sol["bidder_count"],
                "small_business_preference": bidder["small_business_preference"],
                "source_key": "caltrans_bid_results",
                "evidence_class": "observed",
                "evidence_url": sol.get("source_url")
                                or (WEEK_URL.format(date=week) if week else None),
                "evidence_row": (f"{bidder['vendor_name']} | SB: "
                                 f"{'Y' if bidder['small_business_preference'] else 'N'} | "
                                 f"{bidder['bid_amount_raw']}"),
                "confidence_note": ("named on the official Caltrans bid-results page for "
                                    "this solicitation; vendor identity unresolved against "
                                    "SCPRS supplier_id"),
                "status_note": sol["status_note"],
            })
    return rows


def harvest(session: CalEProcureSession, start: dt.date, end: dt.date) -> dict[str, Any]:
    """Fetch every weekly page covering `start`..`end` and parse the bidder fields.

    Weeks are reported in two lists rather than one count. An absent week is a page that
    was never published, not a week in which nobody bid, and collapsing the two would let
    a rolling-window boundary read as a market fact.
    """
    solicitations: list[dict[str, Any]] = []
    populated: list[str] = []
    absent: list[str] = []
    for slug in week_slugs(start, end):
        url = WEEK_URL.format(date=slug)
        body, _ = session.get(url)
        page = body.decode("utf-8", "replace")
        if not looks_populated(page):
            absent.append(slug)
            continue
        populated.append(slug)
        for sol in parse_bid_results(page):
            sol["week"] = slug
            sol["source_url"] = url
            solicitations.append(sol)
    return {
        "solicitations": solicitations,
        "weeks_populated": populated,
        "weeks_absent": absent,
        "absent_note": ("these slugs returned HTTP 200 with an empty template; the page "
                        "was never published, which is not evidence that no bids opened"),
    }
