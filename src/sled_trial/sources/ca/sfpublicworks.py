"""San Francisco Public Works bid tabulations: a second source naming losing bidders.

Where Caltrans posts a weekly HTML page, San Francisco posts a PDF. Each contract award
going to the Public Works Commission carries an attachment headed `TABULATION OF BIDS`
listing every company that bid, its local-business status, and its price, plus the
engineer's estimate -- a benchmark Caltrans results do not carry, and the thing that says
whether a field came in under or over what the agency expected to pay.

Two differences from `caltrans` that matter, both of them traps:

* **Bidders are listed in the order their envelopes were opened, not by price.** Measured
  on Pavement Renovation No. 78: six bidders reading $7.66M, $6.56M, $6.69M, $6.60M,
  $8.11M, $7.30M. Taking rank from list position would name the wrong apparent low bidder,
  so rank is derived by sorting on amount and the page's own ordering is preserved
  separately as `listed_position`.
* **There is no Cal eProcure event to join to.** San Francisco is a city and does not
  appear in the state portal, so the identity is SF's own sourcing id under a `SFPW`
  business unit. Inventing a state business unit would fabricate a join.

Like Caltrans, a posted tabulation is not an award: it starts the five-working-day protest
period, and the low bidder still has to clear responsibility review.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

BASE = "https://sfpublicworks.org"
CALENDAR_URL = f"{BASE}/about/public-works-commission-calendar"
# San Francisco is not in Cal eProcure, so it gets its own namespace rather than a
# borrowed state business unit.
BUSINESS_UNIT = "SFPW"

_HEADER = re.compile(r"TABULATION\s+OF\s+BIDS", re.I)
_BIDDER_HEADER = re.compile(r"^BIDDERS\b.*?:", re.I)
_FIELD = {
    "sourcing_id": re.compile(r"^SOURCING\s+ID:\s*(.+)$", re.I),
    "contract_title": re.compile(r"^CONTRACT\s+TITLE:\s*(.+)$", re.I),
    "full_title": re.compile(r"^FULL\s+TITLE:\s*(.+)$", re.I),
    "bids_received": re.compile(r"^BIDS\s+RECEIVED:\s*(.+)$", re.I),
}
_ESTIMATE = re.compile(r"^Engineer'?s\s+Estimate:\s*\$?([\d,]+(?:\.\d{2})?)", re.I)
# A bidder line ends in the price. Anything between the company name and that price is the
# local-business status, which is sometimes absent.
_BID_LINE = re.compile(
    r"^(?P<name>.+?)\s+(?P<lbe>(?:Micro|Small|SBE|Non)[- ]?LBE\b[^$]*?)?\s*"
    r"\$(?P<amount>[\d,]+(?:\.\d{2})?)\s*$")
# Lines that end in a price but are totals, not companies.
_SUMMARY = re.compile(r"^(?:Average\s+Bid|Engineer'?s\s+Estimate|Total|Median|Low\s+Bid|"
                      r"%|cc)\b", re.I)
_PDF_LINK = re.compile(r'href="([^"]*?/sites/default/files/Commissions/[^"]*?\.pdf)"', re.I)


def _amount(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def parse_tabulation(text: str) -> dict[str, Any] | None:
    """One `TABULATION OF BIDS` page into a solicitation with its full field of bidders.

    Returns None when the text is not a tabulation. Award memos reference an attachment
    called "Tabulation" without containing one, so the header must actually be present --
    a filename or a mention is not enough, which is the lesson the document corpus already
    taught.
    """
    if not _HEADER.search(text or ""):
        return None

    out: dict[str, Any] = {key: None for key in _FIELD}
    out["engineers_estimate"] = None
    bidders: list[dict[str, Any]] = []
    in_bidders = False

    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        for key, pattern in _FIELD.items():
            found = pattern.match(line)
            if found:
                out[key] = found.group(1).strip()
        estimate = _ESTIMATE.match(line)
        if estimate:
            out["engineers_estimate"] = _amount(estimate.group(1))
        if _BIDDER_HEADER.match(line):
            in_bidders = True
            continue
        if not in_bidders or _SUMMARY.match(line):
            continue
        bid = _BID_LINE.match(line)
        if not bid:
            continue
        bidders.append({
            "vendor_name": bid.group("name").strip(),
            "lbe_status": (bid.group("lbe") or "").strip() or None,
            "bid_amount_raw": f"${bid.group('amount')}",
            "bid_amount": _amount(bid.group("amount")),
            "listed_position": len(bidders) + 1,
        })

    # Rank is derived, because the page's order is the order envelopes were opened. A bid
    # whose amount did not parse is left unranked rather than sorted as if it were zero.
    ranked = sorted((b for b in bidders if b["bid_amount"] is not None),
                    key=lambda b: b["bid_amount"])
    for position, bidder in enumerate(ranked, 1):
        bidder["rank"] = position
    for bidder in bidders:
        bidder.setdefault("rank", None)

    out["bidders"] = bidders
    out["bidder_count"] = len(bidders)
    out["rank_basis"] = ("derived by sorting on bid amount; the page lists bidders in the "
                         "order received and opened, which is not price order")
    out["status_note"] = ("a posted tabulation starts the five-working-day protest period "
                          "and precedes responsibility review; the low bidder is not yet "
                          "the awardee")
    return out


def commission_pdf_links(page: str) -> list[str]:
    """Absolute URLs of the commission PDFs linked from a calendar or meeting page."""
    found = set()
    for href in _PDF_LINK.findall(page or ""):
        found.add(href if href.startswith("http") else f"{BASE}{href}")
    return sorted(found)


def bidder_candidates(tabulation: dict[str, Any], *,
                      source_url: str | None = None) -> list[dict[str, Any]]:
    """Flatten a tabulation into one observed-candidate row per bidder.

    Same field names as the Caltrans adapter and the document extractor, so these reach
    `supabase_export.participant_rows` without a third export path.
    """
    rows: list[dict[str, Any]] = []
    for bidder in tabulation.get("bidders") or []:
        rows.append({
            "business_unit": BUSINESS_UNIT,
            "event_id": tabulation.get("sourcing_id"),
            "vendor_name_raw": bidder["vendor_name"],
            "amount_raw": bidder["bid_amount_raw"],
            "amount_numeric": bidder["bid_amount"],
            "rank": bidder["rank"],
            "listed_position": bidder["listed_position"],
            "bidder_count": tabulation.get("bidder_count"),
            "lbe_status": bidder["lbe_status"],
            "engineers_estimate": tabulation.get("engineers_estimate"),
            "source_key": "sfpublicworks_bid_tabulation",
            "evidence_class": "observed",
            "evidence_url": source_url,
            "evidence_row": (f"{bidder['vendor_name']} | "
                             f"{bidder['lbe_status'] or 'no LBE status'} | "
                             f"{bidder['bid_amount_raw']}"),
            "confidence_note": ("named on an official SF Public Works bid tabulation; "
                                "vendor identity unresolved, and SF vendors do not appear "
                                "in the state supplier registry"),
            "rank_basis": tabulation.get("rank_basis"),
            "status_note": tabulation.get("status_note"),
        })
    return rows


# Filenames worth downloading. This is a fetch filter, not a classifier: the trial's own
# document corpus produced four false positives for every true one from filename keywords,
# so `parse_tabulation` still has to find the header before anything is recorded.
_WORTH_OPENING = re.compile(r"attach|tabul|award", re.I)
_NOT_WORTH_OPENING = re.compile(r"minutes|agenda|correspondence|calendar|clipping|"
                                r"cancellation|notice", re.I)


def likely_tabulation(url: str) -> bool:
    """Is this commission PDF worth downloading to look for a tabulation?"""
    name = (url or "").rsplit("/", 1)[-1]
    if _NOT_WORTH_OPENING.search(name):
        return False
    return bool(_WORTH_OPENING.search(name))


def harvest(urls: Iterable[str], read_pages: Callable[[str], Iterable[str]], *,
            max_pages: int = 5) -> dict[str, Any]:
    """Read each PDF and pull out any bid tabulation it contains.

    `read_pages` takes a URL and returns that document's page texts, which keeps the
    network and PDF handling in the caller and this function testable offline.

    Only the first `max_pages` are searched: a tabulation is the front matter of its
    attachment, and one real attachment runs to 221 pages, so scanning every page of every
    document would spend most of its time in appendices.
    """
    tabulations: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    read = 0
    without = 0

    for url in urls:
        try:
            pages = list(read_pages(url))[:max_pages]
        except Exception as exc:
            # An unreadable document is an explicit failure, never a silent omission.
            failures.append({"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        read += 1
        found = next((t for t in (parse_tabulation(page or "") for page in pages) if t), None)
        if not found:
            without += 1
            continue
        found["source_url"] = url
        tabulations.append(found)
        candidates.extend(bidder_candidates(found, source_url=url))

    return {
        "tabulations": tabulations,
        "candidates": candidates,
        "documents_read": read,
        "documents_without_tabulation": without,
        "failures": failures,
    }
