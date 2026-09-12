"""Open FI$Cal: California department-to-vendor payment records.

The landing page is JavaScript, but its source publishes a pointer manifest URL directly:
a 1,230-row CSV naming one downloadable file per department per fiscal year, FY16 to FY25,
154 departments, about 10.6 GB in total. Plain HTTP, no login, no CAPTCHA, and HTTP Range
is supported.

This is spending, not awards. It shows money actually paid, which is a different and
complementary fact: a vendor can hold a contract and never be paid under it. Payment
therefore evidences an *active* supplier relationship where an award alone evidences only
that one exists.

The join back to vendor identity is the weak point and is treated as such. These records
carry `VENDOR_NAME` and no supplier id, and the names are truncated at 25 characters
("WESTERN STATES COUNCIL OF" for "... OF CARPENTERS"). Matching to an SCPRS `supplier_id`
is therefore name-based and always low confidence -- see `match_confidence`.

Truncation is not the only mangling: "STATE BLDG & CONST TRADES" abbreviates CONSTRUCTION
as well as cutting the name, and no prefix rule can join that to its SCPRS spelling. Those
names stay unmatched rather than being fuzzily merged.
"""
from __future__ import annotations

import collections
import bisect
import csv
import io
import re
from typing import Any, Iterable

from .caleprocure import CalEProcureSession

BLOB = "https://adwoutputfilesadlsstore.blob.core.windows.net/transparency"
VENDOR_MANIFEST = f"{BLOB}/DepartmentVendorTransactionPointer/DepartmentVendorTransactionPointer.csv"

# Observed truncation length of VENDOR_NAME in these files. Names at or above this may be
# cut off, so an exact comparison against a full SCPRS name would wrongly fail.
TRUNCATION_LENGTH = 25
_SIZE = re.compile(r"([\d.,]+)\s*(KB|MB|GB)", re.I)
_FY = re.compile(r"_(FY\d\d)\.csv$", re.I)
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^A-Z0-9 ]")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# What a file of unknown size is charged against the download budget. `size_mb` still
# reports 0 for "not stated" rather than guessing, but spending nothing for it would let a
# manifest of malformed rows blow a budget the module treats as mandatory.
UNKNOWN_SIZE_MB = 100.0


def size_mb(text: str | None) -> float:
    """'75 MB' -> 75.0. Unparseable sizes return 0 rather than guessing."""
    m = _SIZE.match((text or "").strip())
    if not m:
        return 0.0
    value = float(m.group(1).replace(",", ""))
    return value * {"KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}[m.group(2).upper()]


def fetch_manifest(session: CalEProcureSession) -> list[dict[str, Any]]:
    """One row per downloadable department-year file."""
    body, _ = session.get(VENDOR_MANIFEST)
    text = body.decode("utf-8-sig", "replace")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        name = (row.get("FileName") or "").strip()
        if not name:
            continue
        fy = _FY.search(name)
        rows.append({
            "filename": name,
            "department": re.sub(r"^Vendor_\d+_|_FY\d\d\.csv$", "", name),
            "business_unit": (name.split("_")[1] if name.count("_") >= 2 else None),
            "fiscal_year": fy.group(1).upper() if fy else None,
            "size_mb": size_mb(row.get("FileSize")),
            "url": (row.get("Download") or "").strip(),
            "upload_date": (row.get("UploadDate") or "").strip(),
        })
    return rows


def select_files(manifest: list[dict[str, Any]], *, business_units: Iterable[str] = (),
                 fiscal_years: Iterable[str] = (), max_total_mb: float = 400.0,
                 ) -> list[dict[str, Any]]:
    """Choose files to download under an explicit size budget.

    The full set is about 10.6 GB, so a budget is mandatory. `business_units` is the
    relevance filter and matters more than the budget: selection preserves the order those
    units are given in, because the caller knows which departments its vendors actually
    serve.

    An earlier version sorted smallest-first, reasoning that a fixed budget would then cover
    more departments. It did -- 203 files, every one from a tiny agency with almost no
    spending, and none of the departments the vendors under analysis worked for. File size
    here is a proxy for departmental spending, so smallest-first systematically selects the
    least informative data. Largest-first within the relevant set is the right default: a
    department's biggest year is where its vendor relationships show up.
    """
    units = [str(u) for u in business_units]
    unit_rank = {u: i for i, u in enumerate(units)}
    years = {str(y).upper() for y in fiscal_years}
    candidates = [
        row for row in manifest
        if (not units or row["business_unit"] in unit_rank)
        and (not years or row["fiscal_year"] in years)
        and row["url"]
    ]
    # Caller-supplied unit order first, then largest file within a unit.
    candidates.sort(key=lambda r: (unit_rank.get(r["business_unit"], 0), -r["size_mb"]))
    chosen, running, taken = [], 0.0, collections.Counter()
    already: set[str] = set()
    # One file per department before taking a second from any, so a fixed budget buys
    # breadth across the departments the caller cares about. An earlier version took
    # largest-first outright and spent 466 MB of a 600 MB budget on one department's two
    # years, leaving 35 other relevant departments uncovered.
    for allowance in (1, 2, 3):
        for row in candidates:
            if row["filename"] in already:
                continue
            if taken[row["business_unit"]] >= allowance:
                continue
            # A file whose size did not parse is charged UNKNOWN_SIZE_MB, not zero: an
            # unstated size is unknown, not free.
            cost = row["size_mb"] or UNKNOWN_SIZE_MB
            if running + cost > max_total_mb:
                continue
            chosen.append(row)
            already.add(row["filename"])
            taken[row["business_unit"]] += 1
            running += cost
    return chosen


def normalize_vendor(name: str) -> str:
    """Comparison key only. Never replaces a canonical name."""
    text = _PUNCT.sub(" ", (name or "").upper())
    return _WS.sub(" ", text).strip()


class SpendingLookup:
    """Narrow the payee index to the few names `match_confidence` could accept.

    `attach_spending` asked the matcher about every (profile, payee) pair. At 1,739
    profiles that was 22 million calls and took seconds; at 25,078 profiles on the
    twelve-month corpus it was 316 million and would have taken the afternoon. The
    matcher has three tiers and each is answerable by lookup: an exact normalised name is
    a dict hit, a truncated payee that prefixes our name is one dict hit per prefix
    length, and our own truncated name prefixing a payee is a contiguous range in sorted
    order. This finds those candidates and then asks `match_confidence` about only them.
    The matcher stays the oracle; this only decides who it is asked about.
    """

    def __init__(self, spending: dict[str, Any]) -> None:
        self.spending = spending
        # Original dict order, so ties downstream resolve exactly as they always did.
        self.order = {key: i for i, key in enumerate(spending)}
        self.by_norm: dict[str, list[str]] = collections.defaultdict(list)
        self.truncated_by_norm: dict[str, list[str]] = collections.defaultdict(list)
        for key in spending:
            norm = normalize_vendor(key)
            if not norm:
                continue                    # the matcher refuses an empty name
            self.by_norm[norm].append(key)
            if len((key or "").strip()) >= TRUNCATION_LENGTH:
                self.truncated_by_norm[norm].append(key)
        self.sorted_norms = sorted(self.by_norm)

    def candidates(self, scprs_name: str) -> list[tuple[str, str, dict[str, Any]]]:
        a = normalize_vendor(scprs_name)
        if not a:
            return []
        keys: set[str] = set(self.by_norm.get(a, ()))
        for length in range(1, len(a)):
            keys.update(self.truncated_by_norm.get(a[:length], ()))
        if len((scprs_name or "").strip()) >= TRUNCATION_LENGTH:
            lo = bisect.bisect_left(self.sorted_norms, a)
            hi = bisect.bisect_left(self.sorted_norms, a + "\uffff")
            for norm in self.sorted_norms[lo:hi]:
                keys.update(self.by_norm[norm])
        out = []
        for key in sorted(keys, key=self.order.__getitem__):
            ok, confidence, basis = match_confidence(scprs_name, key)
            if ok:
                out.append((confidence, basis, self.spending[key]))
        return out


def parse_transactions(data: bytes) -> Iterable[dict[str, str]]:
    """Rows from one transaction file. Streams: selected files reach several hundred MB."""
    return csv.DictReader(io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig",
                                           errors="replace"))


def aggregate_by_vendor(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Payment totals per vendor name.

    Amounts that do not parse are counted separately rather than dropped or zeroed, so a
    total always states how much of the data it covers.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_name = (row.get("VENDOR_NAME") or "").strip()
        if not raw_name:
            continue
        key = normalize_vendor(raw_name)
        entry = out.setdefault(key, {
            "vendor_name_raw": raw_name, "payments": 0, "amount_total": 0.0,
            "amount_unparseable": 0, "departments": collections.Counter(),
            "fiscal_years": collections.Counter(), "first_date": None, "last_date": None,
            # Exactly at the cut, not at-or-above it: a 41-character name is proof the
            # file did NOT truncate it. `>=` flagged every long name as truncated.
            "truncated_name": len(raw_name) == TRUNCATION_LENGTH,
        })
        entry["payments"] += 1
        try:
            entry["amount_total"] += float((row.get("monetary_amount") or "").strip())
        except ValueError:
            entry["amount_unparseable"] += 1
        if row.get("department_name"):
            entry["departments"][row["department_name"].strip()] += 1
        if row.get("fiscal_year_begin"):
            entry["fiscal_years"][row["fiscal_year_begin"].strip()] += 1
        date = (row.get("accounting_date") or "").strip()
        # Lexicographic min/max is only correct for ISO dates. These files publish
        # YYYY-MM-DD; anything else is skipped rather than silently mis-ranged.
        if date and _ISO_DATE.match(date):
            entry["first_date"] = min(entry["first_date"] or date, date)
            entry["last_date"] = max(entry["last_date"] or date, date)
    for entry in out.values():
        entry["amount_total"] = round(entry["amount_total"], 2)
        entry["departments"] = dict(entry["departments"].most_common(10))
        entry["fiscal_years"] = dict(sorted(entry["fiscal_years"].items()))
    return out


def match_confidence(scprs_name: str, spending_name: str) -> tuple[bool, str, str]:
    """Can this payment record be attributed to this SCPRS vendor?

    Returns (matched, confidence, basis). Never `high`: these files carry no supplier id, so
    every match here is a name comparison and a name comparison can always be wrong.
    """
    a, b = normalize_vendor(scprs_name), normalize_vendor(spending_name)
    if not a or not b:
        return False, "none", "a name was empty"
    if a == b:
        return True, "medium", "names match exactly after normalisation"
    # Truncation happens in the raw name, so the length test has to read the raw name.
    # Measured on the normalised one it fails the module's own headline example:
    # "STATE BLDG & CONST TRADES" normalises to 23 characters and never looked truncated.
    raw_a, raw_b = (scprs_name or "").strip(), (spending_name or "").strip()
    # A prefix match is expected against a truncated name rather than suspicious -- but it
    # is weaker, because two firms can share a prefix.
    if len(raw_b) >= TRUNCATION_LENGTH and a.startswith(b):
        return True, "low", (f"spending name is truncated at {len(raw_b)} characters and is "
                             f"a prefix of the SCPRS name")
    if len(raw_a) >= TRUNCATION_LENGTH and b.startswith(a):
        return True, "low", "SCPRS name is a prefix of the spending name"
    return False, "none", "names do not match"
