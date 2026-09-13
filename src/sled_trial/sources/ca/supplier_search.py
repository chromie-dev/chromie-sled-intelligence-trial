"""Cal eProcure supplier search: vendor location, certifications and industry codes.

`ZZ_PO.ZZ_PUBSRCH.GBL` is public, needs no login, and answers the question the brief asks of
it -- "which supplier identifiers, categories, locations, and SB/DVBE certifications support
vendor resolution and profiling". It is the only surface found that publishes a vendor's
address, which makes it the source for the geography dimension.

Two deliberate limits.

**Contact fields are not captured.** The result grid includes `ZZ_PUBSRCH_VW_FIRST_NAME`,
`LAST_NAME`, `EMAILID`, `PHONE3` and `FAX`. README puts private contact enrichment out of
scope, so those columns are read past and never stored, even though they are returned. The
fields taken are location, certifications, business type and industry codes.

**Coverage is probably partial.** The component is titled "Custom Component for SB orDVBE",
which suggests it indexes certification-registered suppliers rather than every state
supplier. That has to be measured against a known vendor set rather than assumed, and
`coverage_note` on every result says so.

The join is by name. Unlike the LPA search, no `supplier_id` appears in the results, so
attribution to an SCPRS vendor inherits all the weakness of name matching -- a search for
"AVIATE" returns `AVIATE ROOFING FLOORING &`, which is a different company from
`AVIATE ENTERPRISES INC`.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Iterable

from .caleprocure import COMP, CalEProcureSession, _text, hidden_fields

SEARCH_URL = f"{COMP}/ZZ_PO.ZZ_PUBSRCH.GBL"
SEARCH_ACTION = "ZZ_PUBSRCH1_WRK_BUTTON"
CRITERIA = {
    "name": "ZZ_PUBSRCH1_WRK_NAME1",
    "certification_id": "ZZ_PUBSRCH1_WRK_ZZ_CERT_ID",
}

# Only the ZZ_PUBSRCH_VW_* family is the result grid. Everything else on the page that
# looks like a row set is the search form's own dropdowns: ZZ_CERTYPLBL_VW_DESCR254 had 6
# rows and ZZ_BUS_TYP_VW_BUSINESS_DESCR had 4 on a search that returned 2 suppliers, and
# ZZ_NAICS_VW / ZZ_CLASSCD_VW / ZZ_KEYWORD_VW / ZZ_POSTAL_VW / ZZ_SRVCAREA_VW are single-row
# filter inputs. A first version keyed rows off the highest index across every family, which
# reported 6 results and stapled unrelated business types and certifications onto suppliers.
# Parsing one family is both correct and simpler.
FIELDS = {
    "supplier_name": "ZZ_PUBSRCH_VW_ZZ_NAME1",
    "supplier_name_alt": "ZZ_PUBSRCH_VW_ZZ_NAME1_AC",
    "description": "ZZ_PUBSRCH_VW_DESCRLONG",
    "certifications_raw": "ZZ_PUBSRCH_VW_DESCR1",
    "certification_id": "ZZ_PUBSRCH_VW_ZZ_CERT_ID",
    "address1": "ZZ_PUBSRCH_VW_ADDRESS1",
    "address2": "ZZ_PUBSRCH_VW_ADDRESS2",
    "address3": "ZZ_PUBSRCH_VW_ADDRESS3",
    "city": "ZZ_PUBSRCH_VW_CITY",
    "state": "ZZ_PUBSRCH_VW_STATE",
    "postal": "ZZ_PUBSRCH_VW_POSTAL",
    "country": "ZZ_PUBSRCH_VW_COUNTRY",
    "website": "ZZ_PUBSRCH_VW_URL",
}
# Present in the result grid and deliberately not read. Listed so the omission reads as a
# decision in code review rather than an oversight.
CONTACT_FIELDS_NOT_CAPTURED = (
    "ZZ_PUBSRCH_VW_FIRST_NAME", "ZZ_PUBSRCH_VW_LAST_NAME", "ZZ_PUBSRCH_VW_EMAILID",
    "ZZ_PUBSRCH_VW_PHONE3", "ZZ_PUBSRCH_VW_FAX",
)

_Q = r"['\"]"
_SPLIT_CERTS = re.compile(r"\s*[,;|]\s*")


def parse_results(page: str) -> list[dict[str, Any]]:
    """Parse the supplier result grid. Quote-agnostic, like every grid on this portal.

    Row count comes from the name field alone, not from the highest index seen anywhere on
    the page, so form dropdowns cannot inflate it.
    """
    name_pattern = re.compile(
        rf"id={_Q}(?:{FIELDS['supplier_name']}|{FIELDS['supplier_name_alt']})\$(\d+){_Q}"
        rf"[^>]*>(.*?)</(?:span|a|div)>", re.S)
    row_indices = sorted({int(i) for i, _ in name_pattern.findall(page)})

    rows: dict[int, dict[str, Any]] = {index: {} for index in row_indices}
    for key, base in FIELDS.items():
        pattern = re.compile(rf"id={_Q}{base}\$(\d+){_Q}[^>]*>(.*?)</(?:span|a|div)>", re.S)
        for raw_index, value in pattern.findall(page):
            index = int(raw_index)
            if index not in rows:
                continue
            text = _text(value)
            if text:
                rows[index][key] = text

    out = []
    for index in sorted(rows):
        row = rows[index]
        name = row.get("supplier_name") or row.get("supplier_name_alt")
        if not name:
            continue
        certs = sorted({part.strip() for part in
                        _SPLIT_CERTS.split(row.get("certifications_raw") or "")
                        if part.strip()})
        street = " ".join(v for v in (row.get("address1"), row.get("address2"),
                                      row.get("address3")) if v)
        out.append({
            "supplier_name": name,
            "description": row.get("description"),
            "certifications": certs,
            "certification_id": row.get("certification_id"),
            "website": row.get("website"),
            "location": {
                "street": street or None,
                "city": row.get("city"),
                "state": row.get("state"),
                "postal": row.get("postal"),
                "country": row.get("country"),
            },
            "has_location": bool(row.get("city") or row.get("postal")),
            "source_key": "caleprocure_supplier_search",
            "evidence_class": "observed",
            "coverage_note": (
                "from the SB/DVBE supplier registry component; may not index every state "
                "supplier, so absence here is not evidence a vendor is unregistered"),
            "contact_fields_omitted": list(CONTACT_FIELDS_NOT_CAPTURED),
        })
    return out


def search(session: CalEProcureSession, **criteria: str) -> dict[str, Any]:
    """One supplier search. `name` or `certification_id`; at least one is required."""
    unknown = set(criteria) - set(CRITERIA)
    if unknown:
        raise ValueError(f"unknown supplier-search criteria: {sorted(unknown)}")
    if not any((criteria.get(k) or "").strip() for k in CRITERIA):
        # A blank search returns the empty form, which parses as zero results and looks
        # exactly like "this vendor is not registered".
        raise ValueError("supplier search needs a name or certification id")

    body, _ = session.get(SEARCH_URL)
    page = body.decode("utf-8", "replace")
    fields = hidden_fields(page)
    fields.update({CRITERIA[k]: v for k, v in criteria.items() if v})
    fields["ICAction"] = SEARCH_ACTION
    request_body = urllib.parse.urlencode(fields).encode()
    result, _ = session.post_raw(SEARCH_URL, request_body, referer=SEARCH_URL)
    result_page = result.decode("utf-8", "replace")
    rows = parse_results(result_page)
    return {
        "criteria": dict(criteria),
        "rows": rows,
        "count": len(rows),
        "no_results": not rows,
    }


def location_index(session: CalEProcureSession, names: Iterable[str],
                   *, on_progress: Any = None) -> dict[str, Any]:
    """Look each vendor name up and build the name-keyed index the profiles read.

    This exists because the index was previously produced by hand: `supplier_locations.json`
    sat in the build directory with nothing in the repository able to regenerate it, which
    is the same reproducibility hole as a headline metric no command can rebuild.

    A lookup that fails is recorded. "Not in the registry" and "we could not ask" are
    different answers, and the registry only indexes certified suppliers anyway, so the
    first is already a weak signal and must not absorb the second.
    """
    say = on_progress or (lambda _m: None)
    wanted = [n for n in dict.fromkeys((n or "").strip() for n in names) if n]
    index: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for n, name in enumerate(wanted, start=1):
        try:
            rows = search(session, name=name)["rows"]
        except Exception as exc:
            failures.append({"name": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        for row in rows:
            index.setdefault(row["supplier_name"], row)
        if n % 25 == 0:
            say(f"{n}/{len(wanted)} names searched, {len(index)} suppliers indexed")
    say(f"{len(index)} suppliers indexed from {len(wanted)} names; "
        f"{len(failures)} lookups failed")
    return {"index": index, "names_searched": len(wanted),
            "suppliers_indexed": len(index), "failures": failures}
