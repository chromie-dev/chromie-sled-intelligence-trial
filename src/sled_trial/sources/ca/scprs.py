"""SCPRS: California's State Contract and Procurement Registration System.

The award registry behind Cal eProcure, and the volume source for participation history.
`supplier_id` here is a stable canonical vendor key, which is what makes vendor identity
resolvable without fuzzy name matching.

Two shape notes carried over from access research:

* The bare component URL redirects to a login page. The `FolderPath` / `IsFolder` /
  `IgnoreParamTempl` query parameters are what make it publicly reachable.
* The result grid uses double-quoted HTML attributes while the surrounding page uses
  single quotes, the same trap as the event attachment grid.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable, Iterator

from .caleprocure import CalEProcureSession, COMP, _text

SEARCH_URL = (
    f"{COMP}/ZZ_PO.ZZ_SCPRS1_CMP.GBL"
    "?FolderPath=PORTAL_ROOT_OBJECT.ZZ_FISCAL_SCPRS.ZZ_SCPRS1_CMP_GBL"
    "&IsFolder=false&IgnoreParamTempl=FolderPath%2cIsFolder"
)
SEARCH_ACTION = "ZZ_SCPRS_SP_WRK_BUTTON"

# Criteria the public form exposes, mapped to their PeopleSoft work-record fields.
CRITERIA = {
    # Takes the FI$Cal business-unit CODE ("0820"), not the display name. Verified: the
    # code "0820" returns 5 rows for Department of Justice on 09/02/2026, while the name
    # "Department of Justice" returns 0. A name silently matches nothing, which reads as
    # "this department bought nothing that day" -- hence the deliberate parameter name.
    "business_unit": "ZZ_SCPRS_SP_WRK_BUSINESS_UNIT",
    "description": "ZZ_SCPRS_SP_WRK_DESCR254",
    "purchase_doc": "ZZ_SCPRS_SP_WRK_CRDMEM_ACCT_NBR",
    "from_date": "ZZ_SCPRS_SP_WRK_FROM_DATE",
    "to_date": "ZZ_SCPRS_SP_WRK_TO_DATE",
    "supplier_name": "ZZ_SCPRS_SP_WRK_NAME1",
    "supplier_id": "ZZ_SCPRS_SP_WRK_SUPPLIER_ID",
    "acq_method": "ZZ_SCPRS_SP_WRK_ZZ_ACQ_MTHD",
    "acq_type": "ZZ_SCPRS_SP_WRK_ZZ_ACQ_TYPE",
}

FIELDS = {
    "purchase_doc": "PURCHASE_DOC",
    "department": "ZZ_SCPR_RSLT_VW_DESCR",
    "description": "ZZ_SCPR_RSLT_VW_DESCR254_MIXED",
    "where_cf": "ZZ_SCPR_RSLT_VW_WHERE_CF",
    "start_date": "ZZ_SCPR_RSLT_VW_START_DATE",
    # Note the family: every sibling is ZZ_SCPR_RSLT_VW_*, this one names the search-form
    # work record. Left as observed rather than "corrected" to a name never seen on a live
    # page; rows are anchored on PURCHASE_DOC, so a stray family cannot inflate the grid.
    "end_date": "ZZ_SCPRS_SP_WRK_END_DATE",
    "awarded_amt": "ZZ_SCPR_RSLT_VW_AWARDED_AMT",
    "supplier_id": "ZZ_SCPR_RSLT_VW_SUPPLIER_ID",
    "supplier_name": "ZZ_SCPR_RSLT_VW_NAME1",
    "cert_type": "ZZ_SCPR_RSLT_VW_ZZ_CERT_TYPE",
    "category": "ZZ_SCPR_RSLT_VW_ZZ_COMMENT1",
    "acq_method": "ZZ_SCPR_RSLT_VW_ZZ_ACQ_MTHD",
    "lpa_contract": "ZZ_SCPR_RSLT_VW_ZZ_LPACONTRACTNBR",
}

# The grid returns at most this many rows and its NEXT control does not advance under
# automation, so a wider result set must be sliced rather than paged.
PAGE_LIMIT = 200

_Q = r"['\"]"
_PAGER = re.compile(r"(\d+)\s+to\s+(\d+)\s+of\s+([\d,]+)")
_NO_RESULTS = re.compile(r"no\s+(?:matching\s+)?(?:rows|results|records)", re.I)
_MONEY = re.compile(r"^\$?\s*-?[\d,]+(?:\.\d{1,2})?$")


def parse_pager(page: str) -> tuple[int, int, int] | None:
    """(first, last, total) from the grid pager, e.g. '1 to 200 of 46,242'."""
    m = _PAGER.search(page)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3).replace(",", ""))


def parse_results(page: str) -> list[dict[str, str]]:
    """Parse the award grid. Quote-agnostic: the grid differs from the page around it.

    Row count comes from PURCHASE_DOC alone. Keying off the highest index seen in any `$N`
    family is what let a search form's own dropdowns inflate the supplier grid -- the same
    bug, found and fixed in `supplier_search.parse_results`, and it applies here too.
    """
    anchor = re.compile(rf"id={_Q}{FIELDS['purchase_doc']}\${{0,1}}(\d+){_Q}", re.S)
    indices = {int(i) for i in anchor.findall(page)}
    rows: dict[int, dict[str, str]] = {i: {} for i in indices}
    for key, base in FIELDS.items():
        pat = re.compile(rf"id={_Q}{base}\${{0,1}}(\d+){_Q}[^>]*>(.*?)</(?:span|a)>", re.S)
        for index, value in pat.findall(page):
            if int(index) not in rows:
                continue
            text = _text(value)
            if text:
                rows[int(index)][key] = text
    return [rows[i] for i in sorted(rows) if rows[i]]


def amount_to_numeric(value: str | None) -> str | None:
    """Awarded amounts are display strings; never coerce an unparseable one to zero."""
    if not value:
        return None
    cleaned = value.strip()
    if not _MONEY.match(cleaned):
        return None
    return cleaned.replace("$", "").replace(",", "").strip() or None


def search(session: CalEProcureSession, **criteria: str) -> dict[str, Any]:
    """Run one SCPRS search. Returns rows plus the pager and a truncation flag."""
    unknown = set(criteria) - set(CRITERIA)
    if unknown:
        raise ValueError(f"unknown SCPRS criteria: {sorted(unknown)}")
    body, _ = session.get(SEARCH_URL)
    session.absorb_state(body)
    extra = {CRITERIA[k]: v for k, v in criteria.items() if v}
    result, _ = session.post_action(
        SEARCH_ACTION, referer=SEARCH_URL, url=SEARCH_URL, extra=extra)
    page = result.decode("utf-8", "replace")
    rows = parse_results(page)
    pager = parse_pager(page)
    total = pager[2] if pager else len(rows)
    return {
        "criteria": dict(criteria),
        "rows": rows,
        "pager": pager,
        "total_reported": total,
        # The grid caps at PAGE_LIMIT and cannot be paged, so a larger total means the
        # caller is seeing a truncated slice and must narrow the query.
        "truncated": bool(pager and pager[2] > pager[1]),
        "no_results": bool(_NO_RESULTS.search(page)) and not rows,
    }


def _d(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%m/%d/%Y").date()


def _s(value: dt.date) -> str:
    return value.strftime("%m/%d/%Y")


def observed_acq_methods(rows: Iterable[dict[str, Any]]) -> list[str]:
    """Acquisition methods seen in already-collected rows, for use as a subdivision axis.

    `acq_method` is the only field that is both a result column and a search criterion, so
    it is the one axis whose values can be read back out of the data and fed straight in.
    The list is a lower bound read off whatever has been collected, which is exactly why
    the caller measures coverage afterwards instead of trusting it.
    """
    return sorted({(row.get("acq_method") or "").strip()
                   for row in rows} - {""})


def observed_business_units(events: Iterable[dict[str, Any]]) -> list[str]:
    """Business-unit CODES seen in the Cal eProcure event feed, as a subdivision axis.

    SCPRS takes the code ("0820"), not the display name, and its result rows carry only
    the name -- so unlike `acq_method` this axis cannot be read back out of award rows.
    The event feed is where the codes live.
    """
    return sorted({(e.get("business_unit") or "").strip()
                   for e in events} - {""})


def search_date_sliced(
    session: CalEProcureSession, from_date: str, to_date: str,
    *, max_depth: int = 8,
    subdivide_by: tuple[str, list[str]] | list[tuple[str, list[str]]] | None = None,
    **criteria: str,
) -> Iterator[dict[str, Any]]:
    """Bisect a date range until each slice fits under the grid's 200-row cap.

    The grid's NEXT control does not advance under automation, so slicing is the only way
    to walk a large result set. When a slice is down to a single day and still over the
    cap, `subdivide_by` supplies further axes to cut it on, tried in order: a child that
    is still capped after the first axis is cut again on the second, and so on.

    Completeness is *measured*, not assumed. The portal reports a total per query, so
    after subdividing we compare the rows the children returned against the total the
    parent claimed. That verdict holds whether or not a value list is exhaustive, which
    matters because none of the candidate axes has an enumerable vocabulary: the
    reference window showed 26 categories, 29 acquisition methods and 93 departments, all
    lower bounds read off an already-truncated sample.
    """
    if subdivide_by is None:
        axes: list[tuple[str, list[str]]] = []
    elif isinstance(subdivide_by, tuple):
        axes = [subdivide_by]
    else:
        axes = list(subdivide_by)
    for field, _ in axes:
        if field not in CRITERIA:
            raise ValueError(f"unknown subdivide_by criterion: {field!r}")

    # (start, end, depth, pinned criteria, index of the next axis to try)
    stack: list[tuple[dt.date, dt.date, int, dict[str, str], int]] = [
        (_d(from_date), _d(to_date), 0, {}, 0)]
    while stack:
        start, end, depth, pinned, axis_i = stack.pop()
        active = {**criteria, **pinned}
        result = search(session, from_date=_s(start), to_date=_s(end), **active)
        result["slice"] = {"from": _s(start), "to": _s(end), "depth": depth, **pinned}
        if not result["truncated"] or depth >= max_depth or start >= end:
            if result["truncated"] and axis_i < len(axes):
                field, values = axes[axis_i]
                covered = 0
                for value in values:
                    child_pinned = {**pinned, field: value}
                    sub = search(session, from_date=_s(start), to_date=_s(end),
                                 **{**criteria, **child_pinned})
                    sub["slice"] = {"from": _s(start), "to": _s(end),
                                    "depth": depth, **child_pinned}
                    covered += len(sub["rows"])
                    if sub["truncated"] and axis_i + 1 < len(axes):
                        # Still capped pinned to this value. Push it back to be cut on
                        # the next axis rather than written off -- writing it off is how
                        # rows go missing without anything saying so.
                        stack.append((start, end, depth, child_pinned, axis_i + 1))
                        continue
                    if sub["truncated"]:
                        sub["shortfall_note"] = (
                            f"{field}={value!r} on {_s(start)} still reports "
                            f"{sub['total_reported']} rows above the {PAGE_LIMIT} cap, "
                            "and no further axis was supplied")
                    yield sub
                reported = int(result["total_reported"] or 0)
                result["subdivided"] = True
                result["subdivision_field"] = field
                result["subdivision_rows_seen"] = covered
                result["subdivision_complete"] = covered >= reported
                result["subdivision_shortfall"] = max(reported - covered, 0)
                result["shortfall_note"] = (
                    f"{_s(start)} reports {reported} rows; subdividing by {field} across "
                    f"{len(values)} values returned {covered}. "
                    + ("Every reported row is accounted for."
                       if covered >= reported else
                       f"{reported - covered} row(s) are still unaccounted for."))
                yield result
                continue
            if result["truncated"]:
                result["shortfall_note"] = (
                    f"slice {_s(start)}..{_s(end)} still reports "
                    f"{result['total_reported']} rows above the {PAGE_LIMIT} cap "
                    f"at depth {depth}"
                    + ("" if axes else "; pass subdivide_by to go further"))
            yield result
            continue
        middle = start + (end - start) / 2
        stack.append((middle + dt.timedelta(days=1), end, depth + 1, pinned, axis_i))
        stack.append((start, middle, depth + 1, pinned, axis_i))
