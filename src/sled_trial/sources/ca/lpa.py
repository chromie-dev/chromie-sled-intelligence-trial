"""Leveraged Procurement Agreements: the statewide contracts a vendor already sits on.

`ZZ_PO.ZZ_CNT_SRC_CMP_BKP.GBL` ("LPA/Dept Contract Search") is public and needs no login.
It matters for two reasons the other Cal eProcure surfaces cannot cover.

**It joins on an identifier, not a name.** The result grid carries `VENDOR_ID1`, which is
the same supplier id SCPRS awards carry, and `CNTRCT_ID`, which is the same value SCPRS
rows carry as `lpa_contract`. Every other vendor surface here -- the supplier search
included -- forces a name match and inherits its errors. This one does not.

**It populates a prediction feature that has always scored zero.** `predict` scores
"presence on a statewide contract or purchasing vehicle" and nothing has ever supplied
it, so the term has been dead weight in every evaluation run to date.

A contract is not an award: holding a vehicle means a department *may* buy without
re-competing, not that anyone has. The rows carry their validity window so an expired
vehicle is not read as current standing.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from .caleprocure import COMP, CalEProcureSession, _text

SEARCH_URL = f"{COMP}/ZZ_PO.ZZ_CNT_SRC_CMP_BKP.GBL"
SEARCH_ACTION = "ZZ_CTR_SRC2_WRK_SEARCH_BTN"
SOURCE_KEY = "caleprocure_lpa"

CRITERIA = {
    "contract_id": "ZZ_CTR_SRC2_WRK_CNTRCT_ID",
    "supplier_id": "ZZ_CTR_SRC2_WRK_VENDOR_ID",
    "supplier_name": "ZZ_CTR_SRC2_WRK_NAME1",
    "acq_type": "ZZ_CTR_SRC2_WRK_ZZ_ACQ_TYPE",
    "buyer_id": "ZZ_CTR_SRC2_WRK_BUYER_ID",
}

# The result grid. Field names are as the component emits them, verified live against
# supplier 0000005196 (WW GRAINGER INC) -> contract 7-25-51-02. Left as observed rather
# than tidied into names never seen on a page.
FIELDS = {
    "contract_id": "CNTRCT_ID",
    "supplier_name": "NAME11",
    "supplier_id": "VENDOR_ID1",
    "contract_type": "ZZ_CNTRCT_TYPE",
    "description": "DESCR2",
    "acq_type": "ZZ_CTR_SRC_VW_ZZ_ACQ_TYPE",
    "begin_date": "CNTRCT_BEGIN_DT",
    "expire_date": "CNTRCT_EXPIRE_DT1",
    "buyer": "OPRDEFNDESC1",
}
_ROW = "CNTRCT_ID"


def parse_results(page: str) -> list[dict[str, Any]]:
    """Rows from a search response.

    Anchored on `CNTRCT_ID`: a row exists because it has a contract id, not because some
    unrelated field family happened to have an index. The supplier search shipped that
    bug once and reported six results for a two-supplier query.
    """
    indexes = sorted(int(i) for i in
                     set(re.findall(rf"id='{_ROW}\$(\d+)'", page)))
    rows = []
    for i in indexes:
        row: dict[str, Any] = {}
        for key, field in FIELDS.items():
            match = re.search(rf"id='{field}\${i}'[^>]*>(.*?)<", page, re.S)
            if match is None:
                match = re.search(rf"id='{field}\${i}'[^>]*value='([^']*)'", page)
            row[key] = _text(match.group(1)).strip() if match else None
        if row.get("contract_id"):
            rows.append(row)
    return rows


def _date(value: str | None) -> dt.date | None:
    try:
        return dt.datetime.strptime((value or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def is_current(row: dict[str, Any], on: dt.date | None = None) -> bool | None:
    """Is the vehicle in force? None when the dates cannot be read.

    Never guess: an unparseable window has to stay unknown rather than default to
    current, because "vendor holds a live statewide contract" is a claim about standing.
    """
    start, end = _date(row.get("begin_date")), _date(row.get("expire_date"))
    if start is None and end is None:
        return None
    day = on or dt.date.today()
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def search(session: CalEProcureSession, **criteria: str) -> dict[str, Any]:
    """One LPA search. Criteria are the named keys above, not raw field ids."""
    unknown = set(criteria) - set(CRITERIA)
    if unknown:
        raise ValueError(f"unknown LPA criteria: {sorted(unknown)}")
    if not any(v for v in criteria.values()):
        raise ValueError("refusing an unfiltered LPA search; pass a criterion")
    body, _ = session.get(SEARCH_URL)
    session.absorb_state(body)
    extra = {CRITERIA[k]: v for k, v in criteria.items() if v}
    result, _ = session.post_action(SEARCH_ACTION, referer=SEARCH_URL,
                                    url=SEARCH_URL, extra=extra)
    page = result.decode("utf-8", "replace")
    rows = parse_results(page)
    return {"criteria": dict(criteria), "rows": rows, "row_count": len(rows)}


def vehicles_by_supplier(session: CalEProcureSession,
                         supplier_ids: Iterable[str],
                         *, on_progress: Any = None) -> dict[str, Any]:
    """Look up every vehicle held by each supplier id.

    Keyed by supplier id because that is what joins cleanly to the award corpus. A
    lookup that fails is recorded, so "this vendor holds no vehicle" stays
    distinguishable from "we did not manage to ask".
    """
    say = on_progress or (lambda _m: None)
    ids = [s for s in dict.fromkeys(supplier_ids) if s]
    by_supplier: dict[str, list[dict[str, Any]]] = {}
    failures = []
    for n, supplier_id in enumerate(ids, start=1):
        try:
            found = search(session, supplier_id=supplier_id)["rows"]
        except Exception as exc:
            failures.append({"supplier_id": supplier_id,
                             "error": f"{type(exc).__name__}: {exc}"})
            continue
        if found:
            by_supplier[supplier_id] = found
        if n % 25 == 0:
            say(f"{n}/{len(ids)} suppliers checked, "
                f"{len(by_supplier)} hold at least one vehicle")
    say(f"{len(by_supplier)} of {len(ids)} suppliers hold a vehicle; "
        f"{len(failures)} lookups failed")
    return {"by_supplier": by_supplier, "suppliers_checked": len(ids),
            "suppliers_with_vehicles": len(by_supplier), "failures": failures,
            "source_key": SOURCE_KEY}


def vehicle_rows(by_supplier: dict[str, list[dict[str, Any]]],
                 on: dt.date | None = None) -> list[dict[str, Any]]:
    """Flatten to one row per (supplier, contract), for the profile enrichment."""
    rows = []
    for supplier_id, vehicles in by_supplier.items():
        for v in vehicles:
            rows.append({
                "supplier_id": supplier_id,
                "contract_id": v.get("contract_id"),
                "contract_type": v.get("contract_type"),
                "description": v.get("description"),
                "acq_type": v.get("acq_type"),
                "begin_date": v.get("begin_date"),
                "expire_date": v.get("expire_date"),
                "current": is_current(v, on),
                "source_key": SOURCE_KEY,
                "evidence_url": SEARCH_URL,
            })
    return rows
