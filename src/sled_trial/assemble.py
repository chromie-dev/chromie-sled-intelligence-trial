"""Assembly of build/ artifacts from the raw pipeline outputs.

Separated from `cli.py` so the command layer stays argument parsing and orchestration.
Everything here is pure: rows in, rows out, no network and no argparse.
"""
from __future__ import annotations

import collections
import csv
import json
import pathlib
from typing import Any, Iterable

from . import documents, extract

def _participants(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candidate participants, each carrying the document and page that support it.

    These are candidates, never resolved vendors: the name still has to reconcile against
    an SCPRS supplier_id, and the evidence must travel with any downstream claim.
    """
    out: list[dict[str, Any]] = []
    for page in pages:
        for cand in extract.participants_from_tables(page.get("tables") or []):
            out.append({
                **cand,
                "business_unit": page.get("business_unit"),
                "event_id": page.get("event_id"),
                "displayed_filename": page.get("displayed_filename"),
                "document_ref": page.get("document_ref"),
                "sha256": page.get("sha256"),
                "page": page.get("page"),
                "extraction_method": page.get("method"),
                "evidence_class": "observed",
                "confidence_note": "table row in an official document; vendor identity unresolved",
            })
    return out


# Profile enrichments, declared once. `analyze` rebuilds vendor profiles from award records
# every run, which destroys anything attached to them afterwards. That bug was fixed three
# separate times -- for the document manifest, the page corpus and the spending index -- and
# then reintroduced a fourth time by adding the location enrichment without wiring it in.
# Patching instances clearly does not work, so enrichments are now a list: adding one means
# adding a row here, and `test_cli.py` asserts every declared enrichment is applied.
#
#   (cache filename, key inside the cache or None for the whole file, attach function name)
ENRICHMENTS = (
    ("spending_index.json", "index", "attach_spending"),
    ("supplier_locations.json", None, "attach_location"),
    # A .jsonl cache: `load_enrichment` reads either form, because the bidder harvest is a
    # row stream while the other two are single documents.
    ("caltrans_bidders.jsonl", None, "attach_bid_history"),
)


def load_enrichment(cache: pathlib.Path, key: str | None) -> Any:
    """Read one enrichment cache, JSON or JSONL, and unwrap it if it names a key."""
    if cache.suffix == ".jsonl":
        return _read_jsonl(cache)
    payload = json.loads(cache.read_text())
    return (payload.get(key) or {}) if key else payload


def _read_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _merge_rows(existing: list[dict[str, Any]], fresh: list[dict[str, Any]],
                *, key: Any) -> list[dict[str, Any]]:
    """Fresh rows win on a key collision; everything else is preserved."""
    merged: dict[Any, dict[str, Any]] = {key(r): r for r in existing}
    for row in fresh:
        merged[key(row)] = row
    return list(merged.values())


def _source_coverage(registry_csv: str = "sources/source_registry.csv") -> dict[str, Any]:
    """What each source provides, when it becomes public, freshness, access and gaps."""
    import csv

    path = pathlib.Path(registry_csv)
    if not path.exists():
        return {"sources": [], "note": f"{registry_csv} not present"}
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    usable = [r for r in rows if not r["automation_feasibility"].lower().startswith("none")]
    return {
        "generated_at": documents.utc_now(),
        "source_count": len(rows),
        "automatable_source_count": len(usable),
        "sources": [{
            "source_key": r["source_key"],
            "portal": r["portal"],
            "source_name": r["source_name"],
            "official_url": r["official_url"],
            "provides": r["data_type"],
            "access_method": r["access_method"],
            "authentication_required": r["auth_required"],
            "when_data_becomes_public": r["when_public"],
            "historical_depth": r["historical_depth"],
            "freshness": r["update_cadence"],
            "stable_identifiers": r["stable_identifiers"],
            "automation_feasibility": r["automation_feasibility"],
            "terms_or_access_constraints": r["terms_access_constraints"],
            "samples_collected": r["sample_records_collected"],
            "known_gaps": r["known_gaps"],
            "verified_on": r["verified_on"],
        } for r in rows],
        "dead_ends_recorded": [r["source_key"] for r in rows
                               if r["automation_feasibility"].lower().startswith("none")],
    }


def _opportunity_intelligence(
    opportunity: dict[str, Any], *, known: list[dict[str, Any]],
    prediction: dict[str, Any], lineage_result: dict[str, Any],
    documents_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the opportunity debrief: facts, predictions and gaps kept separate."""
    retrieved = [d for d in documents_manifest if d.get("download_status") == "downloaded"]
    return {
        "generated_at": documents.utc_now(),
        "opportunity": {k: v for k, v in opportunity.items() if not k.startswith("_")},
        "known_bidders": {
            "count": len(known),
            "evidence_class": "observed",
            "basis": "named in an official document attached to this event, with an amount",
            "participants": known,
            "note": ("empty means no attached document named a participant. It does not "
                     "mean nobody bid: California publishes no bidder lists."),
        },
        "likely_bidders": {
            "count": len(prediction.get("predictions", [])),
            "evidence_class": "predicted",
            "cutoff": prediction.get("cutoff"),
            "candidates_scored": prediction.get("candidates_scored"),
            "excluded_no_relevant_history": prediction.get("excluded_no_relevant_history"),
            "excluded_non_competitor_entities":
                len(prediction.get("excluded_non_competitor_entities") or []),
            "predictions": prediction.get("predictions", []),
            "note": "ranked likelihoods, never confirmed bidders",
        },
        "incumbent_context": lineage_result.get("incumbent_context"),
        "competitive_intensity": {
            "candidates_with_relevant_history": prediction.get("candidates_scored"),
            "basis": "count of vendors holding a prior award with this buyer or in this "
                     "category before the cutoff",
            "evidence_class": "derived",
        },
        "evidence_summary": {
            "documents_enumerated": len(documents_manifest),
            "documents_retrieved": len(retrieved),
            "document_hashes": [d.get("sha256") for d in retrieved if d.get("sha256")],
        },
        "data_gaps": [
            "no public bidder or planholder list exists for California solicitations",
            "the response bid inquiry surface requires a login and was not accessed",
            "no deterministic join exists from this solicitation to its eventual award",
            "vendor ads for this event were not harvested in this run",
        ],
    }




def enumeration_failure_row(business_unit: str, event_id: str,
                            exc: BaseException) -> dict[str, Any]:
    """Manifest row for an event whose attachment list could not be read.

    README requires an inaccessible document to be recorded as an explicit failure, so a
    portal shape change costs one row rather than the whole event.
    """
    return {
        "business_unit": business_unit, "event_id": event_id,
        "document_ref": f"{business_unit}/{event_id}", "displayed_filename": None,
        "download_status": "enumeration_failed",
        "validation_notes": [f"{type(exc).__name__}: {exc}"[:300]],
        "retrieved_at": documents.utc_now(),
    }


def merge_document_corpus(outdir: pathlib.Path, manifest: list[dict[str, Any]],
                          pages: list[dict[str, Any]],
                          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fold fresh document rows into whatever the build directory already holds.

    Replacing rather than merging is the bug this exists to prevent: the brief wants a
    corpus covering every evaluated record, built event by event, and analysing one
    opportunity afterwards once cut 84 documents down to 8. Deduplicated on
    (document, hash) and (document, page).
    """
    manifest = _merge_rows(_read_jsonl(outdir / "documents_manifest.jsonl"), manifest,
                           key=lambda r: (r.get("document_ref"), r.get("sha256")))
    pages = _merge_rows(_read_jsonl(outdir / "document_pages.jsonl"), pages,
                        key=lambda r: (r.get("document_ref"), r.get("page")))
    documents.write_jsonl(manifest, outdir / "documents_manifest.jsonl")
    documents.write_jsonl(pages, outdir / "document_pages.jsonl")
    return manifest, pages


def observed_participants(document_candidates: list[dict[str, Any]],
                          outdir: pathlib.Path) -> list[dict[str, Any]]:
    """Document-extracted candidates plus any harvested Caltrans bidder rows.

    Kept as a merge rather than a second corpus because both are the same kind of claim --
    an official source naming a company against a specific solicitation -- and the export
    already reads this shape. Deduplicated on (event, vendor name) so re-running the
    harvest does not inflate the participant count.
    """
    rows = list(document_candidates)
    cached = _read_jsonl(outdir / "caltrans_bidders.jsonl")
    seen = {(r.get("business_unit"), r.get("event_id"), r.get("vendor_name_raw"))
            for r in rows}
    for row in cached:
        key = (row.get("business_unit"), row.get("event_id"), row.get("vendor_name_raw"))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def unresolved_identity_review(known: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Review rows for observed participants whose vendor identity is not yet resolved.

    Observed participants arrive in two shapes: extracted from a document page, and read
    off a Caltrans bid-results row that cites a URL rather than a filename. Indexing a
    filename on every candidate crashed the run when the second shape appeared, so the
    citation is whichever the row actually carries.
    """
    return [{
        "type": "unresolved_participant_identity",
        "vendor_name_raw": row.get("vendor_name_raw"),
        "source_key": row.get("source_key") or "caleprocure_event_package",
        "citation": row.get("displayed_filename") or row.get("evidence_url"),
        "page": row.get("page"),
        "action": "match against an SCPRS supplier_id before treating as resolved",
    } for row in known]
