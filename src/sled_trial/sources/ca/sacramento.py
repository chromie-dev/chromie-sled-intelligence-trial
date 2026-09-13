"""City of Sacramento Bid Activities Report: competitive intensity, published as open data.

The city publishes its bid activity as an ArcGIS feature layer, so this is the only
source in the corpus that arrives as clean typed JSON with no scraping and no browser.

**It counts bidders rather than naming them.** Each solicitation carries how many vendors
were notified, how many became prospective bidders, and how many of those were local.
That is competitive intensity and local-participation rate -- useful, and not a bidder
list. Nothing here can be joined to a vendor.

The local ratio is the interesting column: it is the only measure in the corpus of how
much of a field an agency draws from its own city, and Sacramento publishes it directly
rather than leaving it to be inferred from addresses.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

LAYER = ("https://services5.arcgis.com/54falWtcpty3V47Z/arcgis/rest/services"
         "/BidActivitiesReport/FeatureServer/0")
SOURCE_KEY = "sacramento_bid_activities"
BUSINESS_UNIT = "SACCITY"
# The layer caps a query at this many features and reports it in its own metadata.
PAGE_SIZE = 1000

# Category flags arrive as "X" or "", one column each, rather than as a single field.
CATEGORY_FLAGS = ("General", "Public_Works", "Professional_Services")
TYPE_FLAGS = ("Bid", "RFI", "RFP", "RFQ", "RFQual")


def query_url(offset: int = 0, page_size: int = PAGE_SIZE) -> str:
    return (f"{LAYER}/query?where=1%3D1&outFields=*&f=json"
            f"&resultOffset={offset}&resultRecordCount={page_size}")


def count_url() -> str:
    return f"{LAYER}/query?where=1%3D1&returnCountOnly=true&f=json"


def _epoch_ms(value: Any) -> str | None:
    """ArcGIS dates are epoch milliseconds. Null and 0 both mean 'no date'."""
    if not value:
        return None
    try:
        return dt.datetime.fromtimestamp(int(value) / 1000, dt.UTC).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _flags(row: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    return [n for n in names if (row.get(n) or "").strip().upper() == "X"]


def _number(value: Any) -> int | None:
    """A count, or None. Zero is a real count here and must survive."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _amount(value: Any) -> float | None:
    """Award amount, or None. Zero means 'not published', not a free contract."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def parse_features(payload: Any) -> list[dict[str, Any]]:
    """Solicitations from one ArcGIS query response."""
    out = []
    for feature in (payload or {}).get("features", []):
        row = feature.get("attributes") or {}
        notified = _number(row.get("Notified_Total"))
        prospective = _number(row.get("Prospective__Bidder_Total"))
        local = _number(row.get("Prospective_Bidders_Local"))
        out.append({
            "business_unit": BUSINESS_UNIT,
            "event_id": (row.get("Invitation_Num") or "").strip() or None,
            "title": (row.get("Project_Title") or "").strip() or None,
            "department": (row.get("Department") or "").strip() or None,
            "posted": _epoch_ms(row.get("Posted")),
            "due_date": _epoch_ms(row.get("Due_Date")),
            "stage": (row.get("Project_Stage") or "").strip() or None,
            "categories": _flags(row, CATEGORY_FLAGS),
            "solicitation_types": _flags(row, TYPE_FLAGS),
            "vendors_notified": notified,
            "prospective_bidders": prospective,
            "prospective_bidders_local": local,
            "local_share": (round(local / prospective, 3)
                            if prospective and local is not None else None),
            "award_amount": _amount(row.get("Award_Amount_Totaldollars")),
            "award_amount_local": _amount(row.get("Award_Amount_Localdollars")),
            "source_key": SOURCE_KEY,
            "evidence_url": LAYER,
            # Counts only. Stated in the data so nothing downstream reads
            # `prospective_bidders` as a list it can resolve to vendors.
            "names_bidders": False,
        })
    return out


def harvest(fetch_json: Callable[[str], Any], *, page_size: int = PAGE_SIZE,
            on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Page the layer until it is exhausted, and reconcile against its own count.

    The layer reports how many features exist, so a short harvest is detectable rather
    than looking like a small city.
    """
    say = on_progress or (lambda _m: None)
    reported = None
    try:
        reported = int((fetch_json(count_url()) or {}).get("count"))
        say(f"layer reports {reported} solicitations")
    except Exception as exc:
        say(f"count unavailable: {type(exc).__name__}")

    rows: list[dict[str, Any]] = []
    offset = 0
    failures: list[dict[str, Any]] = []
    while True:
        try:
            payload = fetch_json(query_url(offset, page_size))
        except Exception as exc:
            failures.append({"offset": offset, "error": f"{type(exc).__name__}: {exc}"})
            break
        chunk = parse_features(payload)
        rows += chunk
        if len(chunk) < page_size or not payload.get("exceededTransferLimit", False):
            break
        offset += page_size

    with_counts = sum(1 for r in rows if r["prospective_bidders"])
    say(f"{len(rows)} solicitations, {with_counts} carrying a bidder count; "
        f"{len(failures)} failures")
    return {"rows": rows, "collected": len(rows), "reported_by_layer": reported,
            "complete": reported is None or len(rows) >= reported,
            "with_bidder_counts": with_counts, "failures": failures,
            "source_key": SOURCE_KEY, "names_bidders": False}
