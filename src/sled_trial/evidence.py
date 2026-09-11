"""Does every claim in the export actually point at something?

Schema validation already answers "is this row shaped correctly", and one test answers
"do participants reference a record that exists". Neither answers the question the brief
actually asks, which is whether a reviewer following a citation arrives anywhere.

Three ways a claim can be unsupported, and they need separating because they mean
different things:

* **Dangling** -- it cites an id that is not in the export. A reader following it gets
  nothing. This is a defect.
* **Unciteable** -- it carries no citation at all. Depending on the row that may be
  legitimate (a derived aggregate) or a hole (an observed bidder with no source).
* **Unresolvable** -- it cites something outside the export, like a URL. We cannot prove
  it resolves without fetching it, so it is counted separately rather than passed off as
  verified. Saying "checked" about something unchecked is worse than saying nothing.

Nothing here fetches anything. It reads what was exported and reports what does not hang
together, so a failing run is visible rather than shipped.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# A citation has to name a retrievable thing. A document plus page, a purchase document,
# or a URL all qualify; a bare source_key does not, because it names the surface rather
# than the record on it.
_CITATION_FIELDS = ("document", "document_id", "page", "purchase_doc", "url",
                    "evidence_row", "sha256", "platform_vendor_id")
_URL = re.compile(r"^https?://", re.I)


def _rows(tables: dict[str, Iterable[dict[str, Any]]], name: str) -> list[dict[str, Any]]:
    return list(tables.get(name) or [])


def _ids(rows: Iterable[dict[str, Any]], field: str = "id") -> set[str]:
    return {str(r.get(field)) for r in rows if r.get(field) is not None}


def check_foreign_keys(tables: dict[str, Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every reference between exported tables must land on a row that exists.

    Ordering was already enforced elsewhere; existence between *all* pairs was not, and
    a dangling reference is invisible until something tries to follow it.
    """
    records = _ids(_rows(tables, "gov_procurement_records"))
    competitors = _ids(_rows(tables, "gov_competitors"))
    documents = _ids(_rows(tables, "gov_procurement_documents"))
    problems: list[dict[str, Any]] = []

    def require(table: str, field: str, universe: set[str], target: str) -> None:
        for row in _rows(tables, table):
            value = row.get(field)
            if value is None or str(value) in universe:
                continue
            problems.append({"kind": "dangling", "table": table, "row_id": row.get("id"),
                             "field": field, "value": str(value), "expected_in": target})

    require("gov_procurement_participants", "record_id", records,
            "gov_procurement_records")
    require("gov_procurement_participants", "competitor_id", competitors,
            "gov_competitors")
    require("gov_procurement_documents", "record_id", records,
            "gov_procurement_records")
    require("document_content_handoff", "document_id", documents,
            "gov_procurement_documents")
    require("partner_match_payloads", "record_id", records, "gov_procurement_records")
    return problems


def check_page_references(tables: dict[str, Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    """A cited page must exist in the extracted content for that document.

    Citing page 12 of an eight-page PDF is the same failure as citing a document that
    was never downloaded: the reader arrives nowhere. It is easy to introduce by
    off-by-one and impossible to notice by reading the row.
    """
    pages: dict[str, set[int]] = {}
    for row in _rows(tables, "document_content_handoff"):
        doc = str(row.get("document_id"))
        try:
            pages.setdefault(doc, set()).add(int(row.get("page")))
        except (TypeError, ValueError):
            continue

    problems = []
    for row in _rows(tables, "gov_procurement_participants"):
        cited = (row.get("evidence") or {})
        doc, page = cited.get("document_id"), cited.get("page")
        if doc is None or page is None:
            continue
        available = pages.get(str(doc))
        if available is None:
            problems.append({"kind": "dangling", "table": "gov_procurement_participants",
                             "row_id": row.get("id"), "field": "evidence.document_id",
                             "value": str(doc), "expected_in": "document_content_handoff"})
        elif int(page) not in available:
            problems.append({"kind": "page_out_of_range",
                             "table": "gov_procurement_participants",
                             "row_id": row.get("id"), "document_id": str(doc),
                             "page": page, "pages_available": len(available)})
    return problems


def classify_citation(evidence: dict[str, Any] | None) -> str:
    """What kind of support does this claim carry?"""
    if not evidence:
        return "uncited"
    present = [f for f in _CITATION_FIELDS if evidence.get(f) not in (None, "", [], {})]
    if not present:
        return "uncited"
    url = evidence.get("url")
    if present == ["url"] or (len(present) == 1 and url and _URL.match(str(url))):
        # Nothing here fetched it, so it is external and unverified rather than checked.
        return "external_only"
    return "cited"


def check_citations(tables: dict[str, Iterable[dict[str, Any]]]) -> dict[str, Any]:
    """How well supported are the claims, by role?

    Reported per role because the answer differs legitimately: an awardee derived from
    an award row cites a purchase document, while a bidder read off a page cites that
    page. A role with no citations at all is the finding.
    """
    by_role: dict[str, dict[str, int]] = {}
    uncited: list[dict[str, Any]] = []
    for row in _rows(tables, "gov_procurement_participants"):
        role = str(row.get("role") or "unknown")
        kind = classify_citation(row.get("evidence"))
        by_role.setdefault(role, {}).setdefault(kind, 0)
        by_role[role][kind] += 1
        if kind == "uncited":
            uncited.append({"row_id": row.get("id"), "role": role,
                            "source_key": (row.get("evidence") or {}).get("source_key")})
    return {"by_role": by_role, "uncited": uncited}


def check_source_keys(tables: dict[str, Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every claim should name a surface the source registry knows about.

    A source_key that appears in the data but not in the registry means a harvester is
    emitting rows under a name nobody documented, which is how an undocumented source
    reaches a reviewer.
    """
    known = {str(r.get("source_key")) for r in _rows(tables, "gov_procurement_sources")
             if r.get("source_key")}
    if not known:
        return []
    problems = []
    seen: set[tuple[str, str]] = set()
    for table in ("gov_procurement_participants", "gov_procurement_records"):
        for row in _rows(tables, table):
            key = (row.get("source_key")
                   or (row.get("evidence") or {}).get("source_key"))
            if not key or str(key) in known or (table, str(key)) in seen:
                continue
            seen.add((table, str(key)))
            problems.append({"kind": "unregistered_source", "table": table,
                             "source_key": str(key)})
    return problems


def audit(tables: dict[str, Iterable[dict[str, Any]]]) -> dict[str, Any]:
    """Everything above, as one report.

    `sound` means nothing dangles and no page citation points past the end of its
    document. It deliberately does not mean every claim is verified: external URLs are
    counted and not followed, and calling those checked would be a lie a reviewer could
    not see through.
    """
    dangling = check_foreign_keys(tables)
    pages = check_page_references(tables)
    citations = check_citations(tables)
    sources = check_source_keys(tables)
    defects = dangling + pages
    return {
        "sound": not defects,
        "defects": defects,
        "defect_count": len(defects),
        # Counts every dangling reference, including one that cites a document with no
        # extracted content. Counting only the foreign-key kind made a page citation
        # into a defect that did not appear in the defect tally.
        "dangling_references": len([d for d in defects if d["kind"] == "dangling"]),
        "page_citations_out_of_range": len([p for p in pages
                                            if p["kind"] == "page_out_of_range"]),
        "citation_coverage": citations["by_role"],
        "uncited_claims": len(citations["uncited"]),
        "unregistered_sources": sources,
        "note": ("external URLs are counted, not followed; nothing here fetches, so a "
                 "sound report means the export hangs together internally rather than "
                 "that every citation was retrieved"),
    }
