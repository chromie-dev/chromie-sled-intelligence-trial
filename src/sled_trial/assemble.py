"""Assembly of build/ artifacts from the raw pipeline outputs.

Separated from `cli.py` so the command layer stays argument parsing and orchestration.
Everything here is pure: rows in, rows out, no network and no argparse.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import pathlib
from typing import Any, Iterable, NamedTuple

from . import documents, extract, sources
from .vendors import normalize_name

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

# Stands in for "every declared bidder cache" in ENRICHMENTS, which names single files.
BIDDER_ROWS = "<all bidder caches>"


def bidder_caches() -> tuple[str, ...]:
    """Build-directory files the declared bidder sources write, read back on every merge."""
    return tuple(source.cache for source in sources.BIDDER_SOURCES)


ENRICHMENTS = (
    ("spending_index.json", "index", "attach_spending"),
    ("supplier_locations.json", None, "attach_location"),
    # Every declared bidder cache at once. Naming one filename here meant a second
    # jurisdiction's bidders never reached the win-rate join.
    (BIDDER_ROWS, None, "attach_bid_history"),
    ("lpa_vehicles.json", None, "attach_vehicles"),
)


def enrichment_payload(outdir: pathlib.Path, filename: str,
                       key: str | None) -> Any | None:
    """Load one enrichment's data, or None when nothing has been harvested for it.

    None and empty are different answers: an absent cache means the step was never run,
    which the caller reports as an unpopulated dimension rather than as zero matches.
    """
    if filename == BIDDER_ROWS:
        rows = [row for cache in bidder_caches() for row in _read_jsonl(outdir / cache)]
        return rows or None
    cache = outdir / filename
    if not cache.exists():
        return None
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
    """Document-extracted candidates plus every harvested bidder cache.

    Kept as a merge rather than a second corpus because both are the same kind of claim --
    an official source naming a company against a specific solicitation -- and the export
    already reads this shape. Deduplicated on (event, vendor name) so re-running the
    harvest does not inflate the participant count.
    """
    rows = list(document_candidates)
    cached = [row for cache in bidder_caches() for row in _read_jsonl(outdir / cache)]
    seen = {(r.get("business_unit"), r.get("event_id"), r.get("vendor_name_raw"))
            for r in rows}
    for row in cached:
        key = (row.get("business_unit"), row.get("event_id"), row.get("vendor_name_raw"))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def observed_vendor_ids(opportunity: dict[str, Any], known: Iterable[dict[str, Any]],
                        profiles: Iterable[dict[str, Any]]) -> set[str]:
    """Vendors already named as bidders **on this solicitation**, excluded from ranking.

    Scoped to the target event on purpose. `known` now carries every harvested bidder from
    every event, and treating all of them as observed here would drop legitimate candidates
    from this opportunity's ranking because they bid on an unrelated one.

    A resolved `supplier_id` is used directly. Without one the fallback is exact equality
    of the normalised name, never a substring: "ACME" appears inside "ACME WIDGETS OF
    NEVADA" and they are different companies.
    """
    target = (opportunity.get("business_unit"), opportunity.get("event_id"))
    here = [row for row in known
            if (row.get("business_unit"), row.get("event_id")) == target]
    ids = {row["supplier_id"] for row in here if row.get("supplier_id")}
    unresolved = {normalize_name(row.get("vendor_name_raw") or "")
                  for row in here if not row.get("supplier_id")}
    unresolved.discard("")
    ids |= {p["supplier_id"] for p in profiles
            if normalize_name(p.get("canonical_name") or "") in unresolved
            and p.get("supplier_id")}
    return ids


def unresolved_identity_review(known: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Review rows for observed participants whose vendor identity is not yet resolved.

    A row that already carries a `supplier_id` has been resolved and does not belong in the
    queue; an ambiguous one does, because two suppliers normalising to one name is exactly
    what a person needs to arbitrate. Citation is a filename or a URL depending on which
    surface the row came from.
    """
    return [{
        "type": "unresolved_participant_identity",
        "vendor_name_raw": row.get("vendor_name_raw"),
        "source_key": row.get("source_key") or "caleprocure_event_package",
        "citation": row.get("displayed_filename") or row.get("evidence_url"),
        "page": row.get("page"),
        "action": "match against an SCPRS supplier_id before treating as resolved",
    } for row in known if not row.get("supplier_id")]


def profile_corpus(awards: list[dict[str, Any]],
                   outdir: pathlib.Path) -> list[dict[str, Any]]:
    """The award rows vendor profiles are built from: the sweep plus any bidder backfill.

    Profiles are descriptive -- counts, agencies, amount ranges for one vendor at a time --
    so a deeper history for some vendors makes them more accurate, not biased. Ranking is
    the opposite: enriching a subset reorders it, measurably, which is why prediction keeps
    ranking on the sweep alone and `test_analyze_ranks_on_the_sweep_not_on_the_profile_corpus`
    pins that apart.

    Deduplicated on (purchase_doc, supplier_id), the natural key the award sweep uses.
    """
    extra = _read_jsonl(outdir / "awards_bidder_enriched.jsonl")
    if not extra:
        return list(awards)
    merged = list(awards)
    seen = {(r.get("purchase_doc"), r.get("supplier_id")) for r in merged}
    for row in extra:
        key = (row.get("purchase_doc"), row.get("supplier_id"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


# How far back the award sweep reaches when the caller does not say. Seven days is what
# produced the shipped corpus; a hardcoded start date meant the README command swept a
# different window than the deliverable was built from, so the numbers could not be
# reproduced by the command the brief tells a reviewer to run.
DEFAULT_AWARD_WINDOW_DAYS = 7


def default_awards_from(cutoff: str) -> str:
    """Start of the award window for a given cutoff, both MM/DD/YYYY."""
    end = dt.datetime.strptime(cutoff, "%m/%d/%Y").date()
    return (end - dt.timedelta(days=DEFAULT_AWARD_WINDOW_DAYS)).strftime("%m/%d/%Y")


def award_sweep_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    """What the award sweep actually collected against what the portal said existed.

    The grid caps at 200 rows and cannot be paged, so a slice still truncated after
    bisection has silently dropped rows. `search_date_sliced` flags that per slice and
    nothing was reading the flag, which made a capped sweep indistinguishable from a
    complete one -- the same class of silence as a soft-404 reading as "no results".
    """
    truncated = [r for r in results if r.get("truncated")]
    collected = sum(len(r.get("rows") or []) for r in results)
    reported = sum(int(r.get("total_reported") or 0) for r in results)
    return {
        "slices": len(results),
        "slices_truncated": len(truncated),
        "rows_collected": collected,
        "rows_reported_by_portal": reported,
        "complete": not truncated,
        "truncated_slices": [
            {**(r.get("slice") or {}), "rows_collected": len(r.get("rows") or []),
             "rows_reported": r.get("total_reported")}
            for r in truncated
        ],
        "note": ("every slice came back under the grid cap, so this window is complete"
                 if not truncated else
                 f"{len(truncated)} slice(s) hit the {200}-row grid cap after bisection, so "
                 f"{reported - collected} row(s) the portal reported were not retrieved; "
                 f"narrow the window or pass a second subdivision axis"),
    }


def target_listing_state(opportunity: dict[str, Any],
                         events: list[dict[str, Any]]) -> dict[str, Any]:
    """Is the opportunity still listed as active, and what does the answer mean?

    The Cal eProcure feed carries open events only and drops one the moment it closes, so
    disappearance is the sole closure signal the portal gives. That makes absence worth
    stating rather than passing over: an event that has left the feed still serves its
    detail page and attachments, so a later run returning no documents means "gone" and
    not "this solicitation had none". An empty feed is a failed fetch, which is not
    evidence either way.
    """
    key = (opportunity.get("business_unit"), opportunity.get("event_id"))
    if not events:
        return {
            "listed_in_active_feed": None,
            "note": ("the active-event feed came back empty, so whether this opportunity "
                     "is still listed is unknown; a failed fetch is not a closure signal"),
        }
    listed = any((e.get("business_unit"), e.get("event_id")) == key for e in events)
    return {
        "listed_in_active_feed": listed,
        "note": ("listed in the active-event feed at analysis time" if listed else
                 "no longer listed in the active-event feed, which is the only closure "
                 "signal Cal eProcure gives — the event has closed or been withdrawn. Its "
                 "documents may still be retrievable by identifier, so a zero-document "
                 "result here means the event is gone, not that it carried no attachments"),
    }


# --- unified coverage -------------------------------------------------------------
#
# Each harvester reports what it collected in its own shape, which is fine for the
# command that wrote it and useless for answering "what do we actually have?". This
# reconciles them into one table: per source, what was collected against what the portal
# said existed, when it last succeeded, and what is known to be missing.
#
# A source appears here whether or not it has ever run. An absent cache is reported as
# "never harvested", which is a different answer from "harvested and empty" -- the same
# distinction the soft-404 handling makes, applied at the level of the whole pipeline.

class CoverageSource(NamedTuple):
    """How to read one harvester's own account of itself."""

    source_key: str
    coverage_file: str | None
    caches: tuple[str, ...]
    reader: str            # name of the _cov_* function below


COVERAGE_SOURCES = (
    CoverageSource("caleprocure_event_list", None, ("events.jsonl",), "_cov_rows"),
    CoverageSource("caleprocure_scprs", "awards_coverage.json",
                   ("awards.jsonl",), "_cov_awards"),
    CoverageSource("caltrans_bid_results", "caltrans_bid_results.json",
                   ("caltrans_bidders.jsonl",), "_cov_rows"),
    CoverageSource("sfpublicworks_bid_tabulation", None,
                   ("sf_bidders.jsonl",), "_cov_rows"),
    CoverageSource("planetbids_agency_portal", "planetbids_coverage.json",
                   ("planetbids_bidders.jsonl", "planetbids_declared_interest.jsonl"),
                   "_cov_planetbids"),
    CoverageSource("csu_public_bid_portal", "csu_coverage.json",
                   ("csu_solicitations.jsonl",), "_cov_csu"),
    CoverageSource("sacramento_bid_activities", "sacramento_coverage.json",
                   ("sacramento_solicitations.jsonl",), "_cov_sacramento"),
    CoverageSource("caleprocure_lpa", "lpa_coverage.json",
                   ("lpa_vehicles.json",), "_cov_lpa"),
    CoverageSource("caleprocure_supplier_search", "supplier_locations_coverage.json",
                   ("supplier_locations.json",), "_cov_suppliers"),
    CoverageSource("cslb_license_master", "cslb_coverage.json",
                   ("../data/raw/registries/cslb_license_master.PARTIAL.csv",
                    "../data/raw/registries/cslb_license_master.csv"), "_cov_cslb"),
)


def _cov_rows(cov: Any, rows: int) -> dict[str, Any]:
    return {"collected": rows, "reported": None, "complete": None}


def _cov_awards(cov: Any, rows: int) -> dict[str, Any]:
    cov = cov or {}
    return {"collected": cov.get("rows_collected", rows),
            "reported": cov.get("rows_reported_by_portal"),
            "complete": cov.get("complete"),
            "note": cov.get("note")}


def _cov_planetbids(cov: Any, rows: int) -> dict[str, Any]:
    agencies = (cov or {}).get("agencies", [])
    return {"collected": sum(a.get("bids_collected") or 0 for a in agencies) or None,
            "reported": sum(a.get("bids_reported_by_portal") or 0 for a in agencies) or None,
            "complete": all(a.get("complete") for a in agencies) if agencies else None,
            "rows": rows,
            "failures": sum(len(a.get("failures") or []) for a in agencies),
            "absent": sum(len(a.get("absent") or []) for a in agencies),
            "agencies": len(agencies)}


def _cov_csu(cov: Any, rows: int) -> dict[str, Any]:
    cov = cov or {}
    return {"collected": rows, "reported": None, "complete": None,
            "failures": len(cov.get("failures") or []),
            "campuses": len(cov.get("campuses") or [])}


def _cov_sacramento(cov: Any, rows: int) -> dict[str, Any]:
    cov = cov or {}
    return {"collected": cov.get("collected", rows),
            "reported": cov.get("reported_by_layer"),
            "complete": cov.get("complete"),
            "failures": len(cov.get("failures") or [])}


def _cov_lpa(cov: Any, rows: int) -> dict[str, Any]:
    cov = cov or {}
    return {"collected": rows, "reported": None, "complete": None,
            "failures": len(cov.get("failures") or []),
            "note": (f"{cov.get('suppliers_with_vehicles')} of "
                     f"{cov.get('suppliers_checked')} suppliers hold a vehicle"
                     if cov.get("suppliers_checked") else None)}


def _cov_suppliers(cov: Any, rows: int) -> dict[str, Any]:
    cov = cov or {}
    return {"collected": cov.get("suppliers_indexed", rows),
            "reported": cov.get("names_searched"),
            # Names searched is our own input, not something the portal claims exists,
            # so the difference is a hit rate rather than a shortfall. Calling it a
            # shortfall would report the registry as incomplete every single run.
            "reported_is_portal_total": False,
            "complete": None,
            "failures": len(cov.get("failures") or []),
            "note": ("denominator is names we searched; the registry indexes certified "
                     "suppliers only, so a miss is usually 'not certified'")}


def _cov_cslb(cov: Any, rows: int) -> dict[str, Any]:
    files = (cov or {}).get("files") or []
    if not files:
        return {"collected": None, "reported": None, "complete": None}
    best = max(files, key=lambda f: f.get("rows") or 0)
    return {"collected": best.get("rows"), "reported": None,
            "complete": best.get("complete"),
            "note": best.get("reason") or best.get("transfer_error")}


def _last_sync(paths: list[pathlib.Path]) -> str | None:
    """Most recent successful write among a source's caches."""
    stamps = [p.stat().st_mtime for p in paths if p.exists()]
    if not stamps:
        return None
    return dt.datetime.fromtimestamp(max(stamps), dt.UTC).isoformat(timespec="seconds")


def _count_rows(path: pathlib.Path) -> int:
    if not path.exists():
        return 0
    if path.suffix == ".jsonl":
        return sum(1 for line in path.open() if line.strip())
    if path.suffix == ".csv":
        with path.open(errors="replace") as handle:
            return max(sum(1 for line in handle) - 1, 0)   # less the header
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return 0
    return len(payload) if hasattr(payload, "__len__") else 0


def unified_coverage(outdir: pathlib.Path,
                     registry_csv: str = "sources/source_registry.csv") -> dict[str, Any]:
    """One reconciled account of what the pipeline actually holds.

    Joins the static research in `source_registry.csv` -- portal, record type, historical
    depth, known gaps -- to what each harvester reported on its last run, and to when
    that run last wrote anything.
    """
    static: dict[str, dict[str, str]] = {}
    registry = pathlib.Path(registry_csv)
    if registry.exists():
        with registry.open(encoding="utf-8") as handle:
            static = {row["source_key"]: row for row in csv.DictReader(handle)}

    entries = []
    for source in COVERAGE_SOURCES:
        meta = static.get(source.source_key, {})
        cov = None
        if source.coverage_file:
            path = outdir / source.coverage_file
            if path.exists():
                try:
                    cov = json.loads(path.read_text())
                except Exception:
                    cov = None
        caches = [outdir / c for c in source.caches]
        rows = sum(_count_rows(c) for c in caches)
        # "Has this ever run?" is answered by evidence of a run -- a cache file or a
        # coverage report -- not by a row count. A harvest that legitimately found
        # nothing writes an empty cache, and reporting that as "never harvested" would
        # hide a working source behind the same label as one nobody has wired up.
        ran = cov is not None or any(c.exists() for c in caches)
        detail = globals()[source.reader](cov, rows)
        collected = detail.get("collected")
        reported = detail.get("reported")
        entries.append({
            "source_key": source.source_key,
            "jurisdiction": meta.get("jurisdiction"),
            "portal": meta.get("portal"),
            "agency_coverage": meta.get("agency_coverage"),
            "record_type": meta.get("data_type"),
            "historical_depth": meta.get("historical_depth"),
            "last_sync": _last_sync(caches),
            "harvested": ran,
            "rows_on_disk": rows,
            "collected": collected,
            "reported_by_portal": reported,
            # None means the portal states no total, so completeness is unknowable
            # rather than false. Those are different answers and must stay so.
            "complete": detail.get("complete"),
            "reported_is_portal_total": detail.get("reported_is_portal_total", True),
            "shortfall": (reported - collected
                          if detail.get("reported_is_portal_total", True)
                          and isinstance(reported, int) and isinstance(collected, int)
                          and reported > collected else None),
            "failures": detail.get("failures", 0),
            "absent": detail.get("absent"),
            "known_gap": meta.get("known_gaps"),
            "note": detail.get("note"),
        })

    never = [e["source_key"] for e in entries if not e["harvested"]]
    short = [e["source_key"] for e in entries if e["shortfall"]]
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "sources": entries,
        "sources_tracked": len(entries),
        "sources_harvested": sum(1 for e in entries if e["harvested"]),
        "sources_never_harvested": never,
        "sources_short_of_portal_total": short,
        "total_failures": sum(e["failures"] or 0 for e in entries),
    }
