"""Procurement lineage: search for an RFP's predecessor notices and related records.

README requires a predecessor search for every RFP, reading the **text of downloaded
documents** rather than matching portal titles alone, and requires that a failed search
produce a completed trace record naming the sources, queries, identifiers and date ranges
checked. "No predecessor found" means the search came back empty, not that no earlier
notice existed, and the output says so explicitly.

Access research established that California offers no deterministic join from a
solicitation to its eventual award: SCPRS is keyed by purchase document number, unrelated
to the Cal eProcure event id, and solicitation numbers rarely survive into award
descriptions. Every relationship produced here is therefore `inferred` with match evidence
and confidence, never `confirmed`.
"""
from __future__ import annotations

import collections
import datetime as dt
import difflib
import re
from typing import Any, Iterable

from .predict import _parse_date

# Solicitation-number shapes seen in California: zero-padded event ids, Caltrans style,
# and agency-prefixed numbers such as RFQ ISD26-4620 or IFB 26C650001.
SOLICITATION_TOKEN = re.compile(
    r"(?<![0-9A-Za-z])("
    r"\d{2}[A-Z]\d{4,}"                     # 04A7615
    r"|[A-Z]{2,5}\d{2}-\d{3,}"              # ISD26-4620
    r"|\d{2}[A-Z]{1,3}\d{5,}"               # 26C650001
    r"|\d{10}"                              # 0000040242
    r")(?![0-9A-Za-z])")
# Phrases that mark a reference to an earlier procurement rather than to this one.
PREDECESSOR_PHRASE = re.compile(
    r"(?:previous|prior|earlier|preceding|superseded?|replaces?|re-?bid|re-?solicit\w*|"
    r"originally\s+(?:issued|advertised|posted)|request\s+for\s+information|\bRFI\b|"
    r"sources\s+sought|market\s+(?:survey|research)|pre-?solicitation|draft\s+solicitation|"
    r"industry\s+day|cancell?ed\s+(?:solicitation|event)|incumbent\s+contract)", re.I)
TITLE_SIMILARITY_THRESHOLD = 0.62
_WS = re.compile(r"\s+")


def _norm_title(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return _WS.sub(" ", text).strip()


def _similarity(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio(), 4)


def self_identifiers(opportunity: dict[str, Any]) -> set[str]:
    """Every identifier that refers to THIS solicitation, in every form it appears in.

    Without the solicitation number in this set, a document that merely restates its own
    RFQ number is reported as a predecessor. That happened on the first real run: the DMV
    package names `ISD26-4620` on its title page, and the search called it a predecessor
    because only the event id had been excluded.
    """
    out: set[str] = set()
    for key in ("event_id", "solicitation_number", "external_id"):
        value = opportunity.get(key)
        if value:
            text = str(value).strip()
            out.add(text)
            out.add(text.lstrip("0"))
            out.add(text.upper())
    # A title often embeds the solicitation number, e.g. "04A7615 - A&E On-call".
    for token in SOLICITATION_TOKEN.findall(str(opportunity.get("title") or "")):
        out.add(token)
        out.add(token.lstrip("0"))
    return {o for o in out if o}


def references_in_documents(
    pages: Iterable[dict[str, Any]], business_unit: str, event_id: str,
    *, exclude: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Solicitation numbers in this event's documents, excluding its own identifiers.

    A document naming a *different* solicitation number is the strongest lineage signal
    available, and it is only visible by reading the text -- portal metadata never carries
    it. The sentence carrying the reference travels with the match as evidence.
    """
    excluded = {e.upper() for e in exclude} | {e.upper().lstrip("0") for e in exclude}
    found: dict[str, dict[str, Any]] = {}
    for page in pages:
        if (page.get("business_unit") != business_unit
                or page.get("event_id") != event_id):
            continue
        text = page.get("text") or ""
        for sentence in re.split(r"(?<=[.\n])\s+", text):
            tokens = {t for t in SOLICITATION_TOKEN.findall(sentence)
                      if t.upper() not in excluded
                      and t.upper().lstrip("0") not in excluded}
            if not tokens:
                continue
            phrase = PREDECESSOR_PHRASE.search(sentence)
            for token in tokens:
                existing = found.get(token)
                # Prefer a mention that also carries predecessor language.
                if existing and not (phrase and not existing["predecessor_language"]):
                    continue
                found[token] = {
                    "referenced_identifier": token,
                    "predecessor_language": bool(phrase),
                    "matched_phrase": phrase.group(0) if phrase else None,
                    "document": page.get("displayed_filename"),
                    "page": page.get("page"),
                    "sha256": page.get("sha256"),
                    "evidence_sentence": _WS.sub(" ", sentence).strip()[:300],
                }
    # Strongest first: explicit predecessor language beats a bare number.
    return sorted(found.values(),
                  key=lambda m: (not m["predecessor_language"], m["referenced_identifier"]))


def find_predecessors(
    opportunity: dict[str, Any], *, events: Iterable[dict[str, Any]],
    awards: Iterable[dict[str, Any]], pages: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Search every available surface for predecessors, and always return a trace."""
    business_unit = str(opportunity.get("business_unit") or "")
    event_id = str(opportunity.get("event_id") or "")
    title = opportunity.get("title") or ""
    agency = opportunity.get("department") or opportunity.get("agency")
    category = opportunity.get("category")
    events = list(events)
    awards = list(awards)
    pages = list(pages)

    queries: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []

    # 1. Document text -- the signal README insists on and the only one that can name an
    #    earlier solicitation directly.
    own = self_identifiers(opportunity)
    doc_refs = references_in_documents(pages, business_unit, event_id, exclude=own)
    queries.append({
        "surface": "caleprocure_event_package",
        "method": "regex scan of extracted document text for solicitation identifiers "
                  "and predecessor language",
        "pages_searched": sum(1 for p in pages
                              if p.get("business_unit") == business_unit
                              and p.get("event_id") == event_id),
        "identifiers_found": [r["referenced_identifier"] for r in doc_refs],
        "self_identifiers_excluded": sorted(own),
    })
    for ref in doc_refs:
        token = ref["referenced_identifier"]
        # event_id is unique only within a business unit, and the feed zero-pads it while
        # documents usually do not. Compare on both, the way self_identifiers already does.
        variants = {token, token.lstrip("0"), token.upper()}
        resolved = next(
            (e for e in events
             if {str(e.get("event_id") or ""), str(e.get("event_id") or "").lstrip("0")}
             & variants
             and (not ref.get("business_unit")
                  or e.get("business_unit") == ref.get("business_unit"))),
            None)
        matches.append({
            "relationship": "predecessor_reference",
            "referenced_identifier": token,
            "resolved_to_active_event": bool(resolved),
            "resolved_event": ({"business_unit": resolved.get("business_unit"),
                                "event_id": resolved.get("event_id"),
                                "title": resolved.get("title")} if resolved else None),
            "confidence": "medium" if ref["predecessor_language"] else "low",
            "confidence_basis": ("document text uses predecessor language alongside the "
                                 "identifier" if ref["predecessor_language"] else
                                 "identifier appears in document text with no explicit "
                                 "predecessor language; may be an unrelated reference"),
            "evidence_class": "inferred",
            "evidence": ref,
        })

    # 2. Same buyer, similar title, among other active events.
    sibling_hits = []
    for event in events:
        if (event.get("business_unit"), event.get("event_id")) == (business_unit, event_id):
            continue
        if business_unit and event.get("business_unit") != business_unit:
            continue
        score = _similarity(title, event.get("title") or "")
        if score >= TITLE_SIMILARITY_THRESHOLD:
            sibling_hits.append({
                "relationship": "possible_related_solicitation",
                "business_unit": event.get("business_unit"),
                "event_id": event.get("event_id"),
                "title": event.get("title"),
                "title_similarity": score,
                "confidence": "low",
                "confidence_basis": "same buyer and similar title only; title similarity "
                                    "alone is explicitly insufficient per the brief",
                "evidence_class": "inferred",
            })
    queries.append({
        "surface": "caleprocure_event_list",
        "method": f"same business_unit plus normalised title similarity >= "
                  f"{TITLE_SIMILARITY_THRESHOLD}",
        "records_searched": len(events),
        "matches": len(sibling_hits),
    })
    matches.extend(sorted(sibling_hits, key=lambda m: -m["title_similarity"])[:10])

    # 3. Prior awards with the same buyer and category -- incumbency context, not lineage.
    incumbent_hits = []
    dates = []
    for award in awards:
        if agency and award.get("department") != agency:
            continue
        if category and award.get("category") != category:
            continue
        incumbent_hits.append(award)
        if award.get("start_date"):
            dates.append(award["start_date"])
    queries.append({
        "surface": "caleprocure_scprs",
        "method": "award rows filtered to the same buyer and category",
        "records_searched": len(awards),
        "matches": len(incumbent_hits),
        # Sorted as dates, not as strings: lexicographic order over MM/DD/YYYY puts
        # 01/02/2027 before 12/31/2026 and reports a range that never happened.
        "date_range_present": (f"{min(parsed)}..{max(parsed)}"
                               if (parsed := sorted(d for d in
                                                    (_parse_date(x) for x in dates) if d))
                               else None),
    })

    predecessors = [m for m in matches if m["relationship"] == "predecessor_reference"]
    trace = {
        "searched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "target": {"business_unit": business_unit, "event_id": event_id, "title": title,
                   "buyer": agency, "category": category},
        "surfaces_checked": [q["surface"] for q in queries],
        "queries": queries,
        "surfaces_not_available": [
            {"surface": "caleprocure_response_bid_inquiry",
             "reason": "requires login; not attempted per SECURITY.md"},
            {"surface": "dgs_historical_contracts",
             "reason": "bulk export discontinued in 2018; pre-2015 data by manual request only"},
            {"surface": "data_ca_gov_purchase_orders",
             "reason": "robots.txt disallows the datastore API; unresolved with the trial author"},
        ],
        "result": "predecessors_found" if predecessors else "no_predecessor_found",
        "no_match_meaning": (
            "no predecessor was found in the surfaces listed above. This does not establish "
            "that no earlier RFI, sources-sought notice or prior solicitation existed."),
    }
    return {
        "target_event": f"{business_unit}/{event_id}",
        "predecessor_matches": predecessors,
        "related_records": [m for m in matches
                            if m["relationship"] != "predecessor_reference"],
        "incumbent_context": {
            "awards_same_buyer_and_category": len(incumbent_hits),
            "distinct_suppliers": len({a.get("supplier_id") for a in incumbent_hits
                                       if a.get("supplier_id")}),
            "top_suppliers": [
                {"supplier_id": sid, "supplier_name": name, "awards": n}
                for (sid, name), n in collections.Counter(
                    (a.get("supplier_id"), a.get("supplier_name"))
                    for a in incumbent_hits if a.get("supplier_id")).most_common(10)],
            "evidence_class": "derived",
            "note": ("incumbency here means holding awards with this buyer in this category; "
                     "it cannot mean winning this specific solicitation, because no "
                     "deterministic solicitation-to-award join exists in California"),
        },
        "lineage_links": {
            "predecessor_record_id": None,
            "solicitation_record_id": None,
            "resulting_contract_record_id": None,
            "basis": "left null: no verified deterministic link was established",
        },
        "trace": trace,
    }
