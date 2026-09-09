"""Generate docs/SOURCES.md from the source registry.

Generated rather than written by hand for a specific reason: two README-named sources went
missing from the registry during a rewrite, and because the prose describing our sources was
separate from the registry, nothing noticed. A document derived from the registry fails
visibly when the registry is wrong, instead of quietly disagreeing with it.
"""
from __future__ import annotations

import csv
import pathlib
from typing import Any

REGISTRY = "sources/source_registry.csv"
# Ordered by how useful each surface actually turned out to be, not by portal.
TIERS = {
    "In active use": [
        "caleprocure_event_list", "caleprocure_event_detail", "caleprocure_event_package",
        "caleprocure_scprs", "openfiscal_dept_vendor_tx",
    ],
    "Verified, not yet wired in": [
        "caleprocure_supplier_search", "caleprocure_lpa", "caleprocure_vendor_ads",
        "caleprocure_payment_search",
    ],
    "Blocked or unresolved": [
        "caleprocure_response_bid_inquiry", "data_ca_gov_purchase_orders",
        "suppliers_fiscal_peoplesoft",
    ],
    "Dead ends, recorded so they are not retried": [
        "dgs_historical_contracts", "caleprocure_aspx_wrapper",
    ],
}
HUMAN_PAGES = {
    "caleprocure_event_list": "https://caleprocure.ca.gov/pages/Events-BS3/event-search.aspx",
    "caleprocure_scprs": "https://caleprocure.ca.gov/pages/SCPRSSearch/scprs-search.aspx",
    "caleprocure_supplier_search":
        "https://caleprocure.ca.gov/pages/PublicSearch/supplier-search.aspx",
    "caleprocure_lpa": "https://caleprocure.ca.gov/pages/LPASearch/lpa-search.aspx",
    "openfiscal_dept_vendor_tx": "https://open.fiscal.ca.gov/dept_vendor_transaction.html",
}


def load(registry: str | pathlib.Path = REGISTRY) -> dict[str, dict[str, Any]]:
    path = pathlib.Path(registry)
    with path.open(encoding="utf-8") as handle:
        return {row["source_key"]: row for row in csv.DictReader(handle)}


def generate(registry: str | pathlib.Path = REGISTRY) -> str:
    rows = load(registry)
    out: list[str] = []
    w = out.append
    w("# Data sources")
    w("")
    w("Every California surface this pipeline touches, what it provides, and whether we can")
    w("actually use it. Generated from `sources/source_registry.csv`, which holds the full")
    w("18-field access research for each one.")
    w("")
    w("Two links are given where they differ: the **human page** you can open in a browser,")
    w("and the **machine endpoint** the pipeline calls. They are not the same. The browser")
    w("pages are JavaScript shells that carry no data; the endpoints are the PeopleSoft")
    w("components underneath them, which serve complete data anonymously. That distinction")
    w("cost a day to find and is the single most useful thing in this document.")
    w("")

    for tier, keys in TIERS.items():
        present = [k for k in keys if k in rows]
        if not present:
            continue
        w(f"## {tier}")
        w("")
        for key in present:
            row = rows[key]
            w(f"### {row['source_name']}")
            w("")
            human = HUMAN_PAGES.get(key)
            if human:
                w(f"- Browser page: {human}")
            w(f"- Endpoint we call: `{row['official_url']}`")
            w(f"- Provides: {row['data_type']}")
            w(f"- Access: {row['access_method']}")
            w(f"- Login required: {row['auth_required']}")
            w(f"- When it becomes public: {row['when_public']}")
            w(f"- History available: {row['historical_depth']}")
            w(f"- Stable identifiers: {row['stable_identifiers']}")
            w(f"- Verified: {row['verified_on']}")
            if row["known_gaps"]:
                w(f"- **Gaps and caveats:** {row['known_gaps']}")
            w("")
        w("")

    missing = sorted(set(rows) - {k for keys in TIERS.values() for k in keys})
    if missing:
        w("## Not yet tiered")
        w("")
        for key in missing:
            w(f"- `{key}`: {rows[key]['official_url']}")
        w("")

    w("## How to reach the PeopleSoft endpoints")
    w("")
    w("Three things are non-obvious and each one looked like a permission failure:")
    w("")
    w("1. **Use the bare `.GBL` component.** The URL form given in the brief for the bid")
    w("   inquiry, `...AUC_RESP_INQ_AUC.GBL?page=AUC_RESP_INQ_AUC`, redirects to a login.")
    w("   The same component without that query string does not.")
    w("2. **Some components need `FolderPath` parameters to be public.** The award registry")
    w("   returns a login page without them and full data with them.")
    w("3. **Follow redirects and keep a cookie jar.** The first request establishes a session;")
    w("   without it a detail page returns a shell whose postback yields an empty grid, which")
    w("   is indistinguishable from a record that genuinely has no attachments.")
    w("")
    w("A self-identifying crawler user-agent is required — the site returns 403 to a bare")
    w("non-browser agent — but no browser, API key or credential is needed anywhere.")
    w("")
    return "\n".join(out) + "\n"


def write(path: str | pathlib.Path = "docs/SOURCES.md",
          registry: str | pathlib.Path = REGISTRY) -> str:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate(registry))
    return str(target)
