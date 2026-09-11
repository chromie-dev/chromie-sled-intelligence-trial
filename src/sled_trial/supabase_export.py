"""Supabase-shaped exports and their sanitized data contracts.

Identifiers are deterministic UUIDv5 values derived from natural keys, so relationships are
testable without production identifiers and a re-run produces byte-identical ids. No script
here points at or writes to any Supabase instance.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import uuid
from typing import Any, Iterable

from . import sources

# Fixed namespace so ids are reproducible across machines and runs. Not a Chromie value.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://chromie.dev/trial/sled/local")

TABLES = (
    "gov_procurement_sources",
    "gov_procurement_records",
    "gov_procurement_participants",
    "gov_procurement_documents",
    "document_content_handoff",
    "gov_competitors",
    "partner_match_payloads",
)

# Import order is dependency order, not declaration order: every child must land after the
# rows it references. gov_competitors has to precede gov_procurement_participants, because
# a participant row carries competitor_id -- it sat after it until writing
# docs/supabase_mapping.md exposed the inversion.
#
#   sources            -> (none)
#   competitors        -> sources
#   records            -> sources
#   participants       -> records, competitors
#   documents          -> records, sources
#   content handoff    -> documents
#   partner match      -> records, competitors
IMPORT_ORDER = [
    "gov_procurement_sources",
    "gov_competitors",
    "gov_procurement_records",
    "gov_procurement_participants",
    "gov_procurement_documents",
    "document_content_handoff",
    "partner_match_payloads",
]
# table -> tables it references, so ordering can be asserted rather than trusted.
FOREIGN_KEYS = {
    "gov_procurement_sources": [],
    "gov_competitors": ["gov_procurement_sources"],
    "gov_procurement_records": ["gov_procurement_sources"],
    "gov_procurement_participants": ["gov_procurement_records", "gov_competitors"],
    "gov_procurement_documents": ["gov_procurement_records", "gov_procurement_sources"],
    "document_content_handoff": ["gov_procurement_documents"],
    "partner_match_payloads": ["gov_procurement_records", "gov_competitors"],
}
NATURAL_KEYS = {
    "gov_procurement_sources": ["source_key"],
    "gov_procurement_records": ["source_ref", "record_type", "external_id"],
    "gov_procurement_participants": ["record_id", "competitor_id", "role"],
    "gov_procurement_documents": ["record_id", "displayed_filename", "sha256"],
    "document_content_handoff": ["document_id", "page"],
    "gov_competitors": ["source_ref", "external_source_id"],
    "partner_match_payloads": ["record_id", "engine_version"],
}


def local_id(table: str, *parts: Any) -> str:
    """Deterministic local UUID from a table name and natural-key parts."""
    # A missing key part and an empty-string key part are different facts about the source
    # record, so they must not collide into one id. None gets a sentinel that cannot appear
    # in portal data.
    key = table + "|" + "|".join("\x00None" if p is None else str(p) for p in parts)
    return str(uuid.uuid5(NAMESPACE, key))


def _s(*types: str) -> dict[str, Any]:
    return {"type": [*types]}


NULLABLE_STRING = _s("string", "null")
NULLABLE_NUMBER = _s("number", "null")
NULLABLE_INT = _s("integer", "null")
NULLABLE_BOOL = _s("boolean", "null")


def _schema(title: str, required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "description": (
            "PROPOSED CONTRACT - not an export of Chromie's production schema. Authored "
            "from the pattern table in README.md; the trial author confirmed on 2026-09-08 "
            "that no separate snapshot is coming. Validating against this proves internal "
            "consistency of the trial's own outputs, and makes no claim of production "
            "compatibility. Assumptions and validation gaps: docs/supabase_mapping.md."),
        "type": "object",
        "required": required,
        "properties": properties,
        # Deliberately open: a real Chromie table will carry columns this trial cannot know
        # about, and rejecting them would be a false negative.
        "additionalProperties": True,
    }


SCHEMAS: dict[str, dict[str, Any]] = {
    "gov_procurement_sources": _schema(
        "gov_procurement_sources", ["id", "source_key", "provider", "jurisdiction"],
        {"id": _s("string"), "source_key": _s("string"), "provider": _s("string"),
         "portal": NULLABLE_STRING, "jurisdiction": _s("string"),
         "platform": NULLABLE_STRING, "official_url": NULLABLE_STRING,
         "search_url": NULLABLE_STRING, "adapter_key": NULLABLE_STRING,
         "access_mode": NULLABLE_STRING, "capabilities": {"type": ["array", "null"]},
         "refresh_cadence": NULLABLE_STRING, "verification_state": NULLABLE_STRING,
         "known_access_gaps": NULLABLE_STRING, "observed_at": _s("string")}),
    "gov_procurement_records": _schema(
        "gov_procurement_records", ["id", "source_ref", "record_type", "jurisdiction"],
        {"id": _s("string"), "source_ref": _s("string"), "record_type": _s("string"),
         "external_id": NULLABLE_STRING, "jurisdiction": _s("string"),
         "buyer_name": NULLABLE_STRING, "buyer_code": NULLABLE_STRING,
         "title": NULLABLE_STRING, "description": NULLABLE_STRING,
         "posted_date": NULLABLE_STRING, "due_date": NULLABLE_STRING,
         "start_date": NULLABLE_STRING, "end_date": NULLABLE_STRING,
         "amount": NULLABLE_NUMBER, "amount_raw": NULLABLE_STRING,
         "category": NULLABLE_STRING, "set_aside": NULLABLE_STRING,
         "competition_method": NULLABLE_STRING, "canonical_url": NULLABLE_STRING,
         "predecessor_record_id": NULLABLE_STRING,
         "solicitation_record_id": NULLABLE_STRING,
         "resulting_contract_record_id": NULLABLE_STRING,
         "lineage": {"type": ["object", "array", "null"]},
         "raw_provider_data": {"type": ["object", "null"]},
         "provenance": {"type": ["object", "null"]}, "observed_at": _s("string")}),
    "gov_procurement_participants": _schema(
        "gov_procurement_participants",
        ["id", "record_id", "competitor_id", "role", "evidence_class"],
        {"id": _s("string"), "record_id": _s("string"), "competitor_id": _s("string"),
         "role": _s("string"), "rank": NULLABLE_INT,
         "submitted_amount": NULLABLE_NUMBER, "submitted_amount_raw": NULLABLE_STRING,
         "score": NULLABLE_NUMBER, "identity_confidence": _s("string"),
         "evidence_class": _s("string"), "evidence": {"type": ["object", "null"]},
         "observed_at": _s("string")}),
    "gov_procurement_documents": _schema(
        "gov_procurement_documents",
        ["id", "record_id", "source_ref", "displayed_filename", "processing_state"],
        {"id": _s("string"), "record_id": _s("string"), "source_ref": _s("string"),
         "document_role": NULLABLE_STRING, "displayed_filename": _s("string"),
         "official_url": NULLABLE_STRING, "source_page": NULLABLE_STRING,
         "content_type": NULLABLE_STRING, "bytes": NULLABLE_INT,
         "sha256": NULLABLE_STRING, "published_at": NULLABLE_STRING,
         "retrieved_at": NULLABLE_STRING, "download_status": _s("string"),
         "processing_state": _s("string"),
         "validation_notes": {"type": ["array", "null"]},
         "filename_solicitation_mismatch": NULLABLE_BOOL}),
    "document_content_handoff": _schema(
        "document_content_handoff", ["id", "document_id", "page", "extraction_method"],
        {"id": _s("string"), "document_id": _s("string"), "page": NULLABLE_INT,
         "extraction_method": _s("string"), "text": NULLABLE_STRING,
         "char_count": NULLABLE_INT, "ocr_confidence": NULLABLE_NUMBER,
         "table_count": NULLABLE_INT, "table_row_counts": {"type": ["array", "null"]},
         "warnings": {"type": ["array", "null"]}, "sha256": NULLABLE_STRING}),
    "gov_competitors": _schema(
        "gov_competitors", ["id", "legal_name_normalized", "profile_status"],
        {"id": _s("string"), "source_ref": NULLABLE_STRING,
         "external_source_id": NULLABLE_STRING, "legal_name": NULLABLE_STRING,
         "legal_name_normalized": _s("string"), "aliases": {"type": ["array", "null"]},
         "public_identifiers": {"type": ["object", "null"]},
         "certifications": {"type": ["array", "null"]},
         "profile_status": _s("string"), "derived_profile": {"type": ["object", "null"]},
         "identity_confidence": NULLABLE_STRING, "observed_at": _s("string")}),
    "partner_match_payloads": _schema(
        "partner_match_payloads",
        ["id", "record_id", "engine_version", "generated_at", "results"],
        {"id": _s("string"), "record_id": _s("string"),
         "recommended_direction": NULLABLE_STRING, "preview": {"type": ["object", "null"]},
         "results": {"type": "array"}, "source_summary": {"type": ["object", "null"]},
         "engine_version": _s("string"), "generated_at": _s("string"),
         "expires_at": NULLABLE_STRING,
         "production_ids_unresolved": {"type": ["array", "null"]}}),
}


def write_contracts(root: str | pathlib.Path = "contracts/supabase") -> list[str]:
    path = pathlib.Path(root)
    path.mkdir(parents=True, exist_ok=True)
    written = []
    for table, schema in SCHEMAS.items():
        target = path / f"{table}.schema.json"
        target.write_text(json.dumps(schema, indent=2) + "\n")
        written.append(str(target))
    return written


def validate_rows(table: str, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Validate rows against the proposed contract, collecting every failure."""
    import jsonschema

    schema = SCHEMAS[table]
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[dict[str, Any]] = []
    count = 0
    for index, row in enumerate(rows):
        count += 1
        for err in validator.iter_errors(row):
            errors.append({"row_index": index,
                           "path": "/".join(str(p) for p in err.absolute_path),
                           "message": err.message[:220]})
    return {"table": table, "rows": count, "errors": errors, "valid": not errors,
            "contract": f"contracts/supabase/{table}.schema.json",
            "contract_status": "proposed contract from README patterns; "
                               "not production schema"}


def handoff_manifest() -> dict[str, Any]:
    """Import order, upsert keys, conflict behaviour and the ID remapping plan."""
    return {
        "import_order": IMPORT_ORDER,
        "foreign_keys": FOREIGN_KEYS,
        "natural_upsert_keys": NATURAL_KEYS,
        "conflict_behaviour": (
            "upsert on the natural key; on conflict update mutable observation fields "
            "(amounts, dates, status, processing_state, observed_at) and never overwrite a "
            "stronger evidence_class with a weaker one"),
        "id_strategy": (
            "deterministic UUIDv5 over a fixed local namespace and the natural key, so a "
            "re-run reproduces identical ids and relationships survive re-export"),
        "id_remapping_plan": (
            "on a controlled ingestion, insert parents first and build a local->production "
            "id map keyed by natural key, then rewrite child foreign keys through that map. "
            "No production UUID is assumed or fabricated anywhere in these fixtures"),
        "production_ids_unresolved": [
            "organization_id", "client_company_id", "user_id", "workspace_id"],
        "safety": "no script in this repository points at or writes to any Supabase instance",
    }


def write_exports(tables: dict[str, list[dict[str, Any]]],
                  root: str | pathlib.Path = "build/supabase") -> dict[str, Any]:
    """Write one JSONL per table plus a validation report and the handoff manifest."""
    path = pathlib.Path(root)
    path.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "contract_status": (
            "PROPOSED CONTRACT, not production schema. Authored from README's pattern table; "
            "the trial author confirmed no snapshot is coming. Passing validation proves "
            "internal consistency only - no production compatibility is claimed. See "
            "docs/supabase_mapping.md for assumptions and validation gaps."),
        "tables": [], "all_valid": True,
    }
    for table in TABLES:
        rows = tables.get(table, [])
        target = path / f"{table}.jsonl"
        with target.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        result = validate_rows(table, rows)
        result["file"] = str(target)
        report["tables"].append(result)
        report["all_valid"] &= result["valid"]
    (path / "handoff.json").write_text(json.dumps(handoff_manifest(), indent=2) + "\n")
    (path / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


# --- mappers from this pipeline's artifacts to the table shapes ----------------------
# Kept as pure functions over already-produced artifacts so exporting never re-fetches and
# an export can be replayed offline from build/.

ENGINE_VERSION = "sled-trial-baseline-0.1"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def source_rows(registry_csv: str | pathlib.Path = "sources/source_registry.csv",
                ) -> list[dict[str, Any]]:
    import csv
    path = pathlib.Path(registry_csv)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out.append({
                "id": local_id("gov_procurement_sources", row["source_key"]),
                "source_key": row["source_key"],
                "provider": row.get("portal") or "unknown",
                "portal": row.get("portal"),
                "jurisdiction": row.get("jurisdiction") or "California",
                "platform": row.get("portal"),
                "official_url": row.get("official_url"),
                "search_url": row.get("official_url"),
                "adapter_key": row["source_key"],
                "access_mode": row.get("access_method"),
                "capabilities": [row.get("data_type")] if row.get("data_type") else [],
                "refresh_cadence": row.get("update_cadence"),
                "verification_state": "verified" if row.get("verified_on") else "unverified",
                "known_access_gaps": row.get("known_gaps"),
                "observed_at": row.get("verified_on") or _now(),
            })
    return out


DEFAULT_RECORD_SOURCE = "caleprocure_event_list"


def event_record_rows(events: Iterable[dict[str, Any]],
                      target: dict[str, Any] | None = None,
                      participants: Iterable[dict[str, Any]] = (),
                      ) -> list[dict[str, Any]]:
    """Solicitation records for every event this run refers to.

    Three inputs, because three things can name a solicitation and only one of them is the
    active feed:

    * `events` — the feed, which lists open events only.
    * `target` — the opportunity under analysis. The feed drops an event at close, so
      analysing a closed one would leave its partner payload pointing at nothing.
    * `participants` — observed bidders. A harvested bidder field names solicitations the
      feed never carried, in Caltrans' case long closed and in San Francisco's case never
      state events at all. Without a record each of those participants dangles.

    Each record is attributed to the registry that actually lists it, which is why a city
    solicitation does not claim to be a Cal eProcure event.
    """
    events = [dict(e, _source=DEFAULT_RECORD_SOURCE) for e in events]
    seen = {(e.get("business_unit"), e.get("event_id")) for e in events}

    def add(row: dict[str, Any], source: str) -> None:
        key = (row.get("business_unit"), row.get("event_id"))
        if not all(key) or key in seen:
            return
        seen.add(key)
        events.append(dict(row, _source=source))

    if target:
        add(target, DEFAULT_RECORD_SOURCE)
    for candidate in participants:
        declared = sources.BY_KEY.get(candidate.get("source_key") or "")
        add(candidate, declared.record_source if declared else DEFAULT_RECORD_SOURCE)

    out = []
    for event in events:
        source = event.get("_source", DEFAULT_RECORD_SOURCE)
        external = f"{event.get('business_unit')}/{event.get('event_id')}"
        out.append({
            "id": local_id("gov_procurement_records", source, "solicitation", external),
            "source_ref": local_id("gov_procurement_sources", source),
            "source_key": source,
            "record_type": "solicitation",
            "external_id": external,
            "jurisdiction": "California",
            "buyer_name": event.get("agency"),
            "buyer_code": event.get("business_unit"),
            "title": event.get("title"),
            "description": None,
            "due_date": event.get("end_dttm"),
            "amount": None, "amount_raw": None,
            "category": event.get("event_type"),
            "competition_method": event.get("format"),
            "canonical_url": (f"https://caleprocure.ca.gov/event/"
                              f"{event.get('business_unit')}/{event.get('event_id')}"),
            "raw_provider_data": dict(event),
            "provenance": {"source_key": "caleprocure_event_list",
                           "buyer_email": event.get("buyer_email")},
            "observed_at": _now(),
        })
    return out


def award_record_rows(awards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """SCPRS awards -> gov_procurement_records of type `award`."""
    from .sources.ca import scprs
    out = []
    for award in awards:
        doc = award.get("purchase_doc")
        if not doc:
            continue
        numeric = scprs.amount_to_numeric(award.get("awarded_amt"))
        out.append({
            "id": local_id("gov_procurement_records", "caleprocure_scprs", "award", doc),
            "source_ref": local_id("gov_procurement_sources", "caleprocure_scprs"),
            "record_type": "award",
            "external_id": doc,
            "jurisdiction": "California",
            "buyer_name": award.get("department"),
            "buyer_code": None,
            "title": (award.get("description") or "")[:200] or None,
            "description": award.get("description"),
            "start_date": award.get("start_date"),
            "end_date": award.get("end_date"),
            "amount": float(numeric) if numeric is not None else None,
            "amount_raw": award.get("awarded_amt"),
            "category": award.get("category"),
            "set_aside": award.get("cert_type"),
            "competition_method": award.get("acq_method"),
            "raw_provider_data": dict(award),
            "provenance": {"source_key": "caleprocure_scprs",
                           "lpa_contract": award.get("lpa_contract")},
            "observed_at": _now(),
        })
    return out


def competitor_rows(profiles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    from .vendors import normalize_name
    out = []
    for profile in profiles:
        sid = profile["supplier_id"]
        out.append({
            "id": local_id("gov_competitors", "caleprocure_scprs", sid),
            "source_ref": local_id("gov_procurement_sources", "caleprocure_scprs"),
            "external_source_id": sid,
            "legal_name": profile.get("canonical_name"),
            "legal_name_normalized": normalize_name(profile.get("canonical_name") or ""),
            "aliases": profile.get("aliases") or [],
            "public_identifiers": {"scprs_supplier_id": sid},
            "certifications": profile.get("certifications") or [],
            "profile_status": "profiled" if profile.get("awards_observed") else "stub",
            "derived_profile": {
                k: profile.get(k) for k in
                ("awards_observed", "agency_count", "agency_concentration", "amount_stats",
                 "categories", "acquisition_methods", "first_award_date", "last_award_date",
                 "competitive_awards", "non_competitive_awards", "vehicle_awards",
                 "role_evidence", "implausible_date_count", "win_rate_note")},
            "identity_confidence": profile.get("identity_confidence"),
            "observed_at": profile.get("observed_at") or _now(),
        })
    return out


def participant_rows(observed: Iterable[dict[str, Any]],
                     awards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evidence-backed participation only. Predictions never land in this table.

    Two roles are emitted: `awardee` derived from an SCPRS award row, and `known_bidder`
    observed in an official document that names a vendor and an amount.
    """
    from .sources.ca import scprs
    out = []
    for award in awards:
        doc, sid = award.get("purchase_doc"), award.get("supplier_id")
        if not doc or not sid:
            continue
        numeric = scprs.amount_to_numeric(award.get("awarded_amt"))
        record_id = local_id("gov_procurement_records", "caleprocure_scprs", "award", doc)
        competitor_id = local_id("gov_competitors", "caleprocure_scprs", sid)
        out.append({
            "id": local_id("gov_procurement_participants", record_id, competitor_id, "awardee"),
            "record_id": record_id, "competitor_id": competitor_id, "role": "awardee",
            "rank": None,
            "submitted_amount": float(numeric) if numeric is not None else None,
            "submitted_amount_raw": award.get("awarded_amt"),
            "score": None, "identity_confidence": "high",
            "evidence_class": "derived",
            "evidence": {"source_key": "caleprocure_scprs", "purchase_doc": doc,
                         "basis": "SCPRS award row names this supplier_id as the awardee"},
            "observed_at": _now(),
        })
    for candidate in observed:
        external = f"{candidate.get('business_unit')}/{candidate.get('event_id')}"
        # The solicitation record belongs to whichever registry actually lists it. A city
        # has no Cal eProcure event, so hanging its sourcing id off the state event list
        # would assert a record that does not exist. Declared per source, not branched on.
        declared = sources.BY_KEY.get(candidate.get("source_key") or "")
        record_source = declared.record_source if declared else "caleprocure_event_list"
        record_id = local_id("gov_procurement_records", record_source,
                             "solicitation", external)
        # A resolved row links to the same competitor the award rows build, so the bidder
        # evidence joins the profile made from that supplier_id. Without one the identity
        # is still open and the competitor is derived from the raw name instead.
        supplier_id = (candidate.get("supplier_id") or "").strip()
        competitor_id = (local_id("gov_competitors", "caleprocure_scprs", supplier_id)
                         if supplier_id else
                         local_id("gov_competitors", "document_extracted",
                                  candidate.get("vendor_name_raw")))
        out.append({
            "id": local_id("gov_procurement_participants", record_id, competitor_id,
                           "known_bidder"),
            "record_id": record_id, "competitor_id": competitor_id,
            # Rank is null for a document-extracted candidate -- an intent-to-award
            # notice names one company -- but the Caltrans bid-results page publishes
            # the whole field in order, and that ordering is the evidence. Where a
            # source publishes amounts without ranking them, the adapter derives the
            # order and it is carried here; `rank_basis` says which it is, so a derived
            # position is never read as one the agency stated.
            "role": "known_bidder",
            "rank": candidate.get("rank") or candidate.get("derived_rank"),
            "rank_basis": ("stated" if candidate.get("rank")
                           else "derived_from_amount" if candidate.get("derived_rank")
                           else None),
            "submitted_amount": (float(candidate["amount_numeric"])
                                 if candidate.get("amount_numeric") else None),
            "submitted_amount_raw": candidate.get("amount_raw"),
            "score": None,
            "identity_confidence": (candidate.get("identity_confidence") or "unresolved"
                                    if supplier_id else "unresolved"),
            "evidence_class": "observed",
            "evidence": {"source_key": candidate.get("source_key")
                                       or "caleprocure_event_package",
                         "document": candidate.get("displayed_filename"),
                         "page": candidate.get("page"),
                         "sha256": candidate.get("sha256"),
                         "url": candidate.get("evidence_url"),
                         "bidders_on_this_solicitation": candidate.get("bidder_count"),
                         # A platform vendor id, where the source has one. Namespaced
                         # under its source key because it is NOT an SCPRS supplier_id:
                         # it deduplicates a vendor across that platform's agencies and
                         # does not cross into state data.
                         "platform_vendor_id": (
                             {candidate["source_key"]: candidate["vendor_id"]}
                             if candidate.get("vendor_id") and candidate.get("source_key")
                             else None),
                         "evidence_row": candidate.get("evidence_row")},
            "observed_at": _now(),
        })
    return out


def document_rows(manifest: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in manifest:
        external = f"{row.get('business_unit')}/{row.get('event_id')}"
        record_id = local_id("gov_procurement_records", "caleprocure_event_list",
                             "solicitation", external)
        out.append({
            "id": local_id("gov_procurement_documents", record_id,
                           row.get("displayed_filename"), row.get("sha256")),
            "record_id": record_id,
            "source_ref": local_id("gov_procurement_sources", "caleprocure_event_package"),
            "document_role": row.get("document_role"),
            "displayed_filename": row.get("displayed_filename") or "unnamed",
            "official_url": row.get("serving_url"),
            "source_page": row.get("source_page"),
            "content_type": row.get("content_type"),
            "bytes": row.get("bytes"),
            "sha256": row.get("sha256"),
            "retrieved_at": row.get("retrieved_at"),
            "download_status": row.get("download_status") or "unknown",
            "processing_state": ("extracted" if row.get("download_status") == "downloaded"
                                 else "not_processed"),
            "validation_notes": row.get("validation_notes") or [],
            "filename_solicitation_mismatch": row.get("filename_solicitation_mismatch"),
        })
    return out


def handoff_rows(pages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for page in pages:
        external = f"{page.get('business_unit')}/{page.get('event_id')}"
        record_id = local_id("gov_procurement_records", "caleprocure_event_list",
                             "solicitation", external)
        document_id = local_id("gov_procurement_documents", record_id,
                               page.get("displayed_filename"), page.get("sha256"))
        out.append({
            "id": local_id("document_content_handoff", document_id, page.get("page")),
            "document_id": document_id,
            "page": page.get("page"),
            "extraction_method": page.get("method") or "unknown",
            "text": page.get("text"),
            "char_count": page.get("char_count"),
            "ocr_confidence": page.get("ocr_confidence"),
            "table_count": page.get("table_count"),
            "table_row_counts": page.get("table_row_counts") or [],
            "warnings": page.get("warnings") or [],
            "sha256": page.get("sha256"),
        })
    return out


def partner_match_rows(prime_results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for result in prime_results:
        opportunity = result.get("opportunity", {})
        # Same key `event_record_rows` emits. `event_ref` exists only on holdout evaluation
        # events, so a real opportunity fell through to the department name and pointed the
        # payload at a solicitation record nothing had written.
        bu, eid = opportunity.get("business_unit"), opportunity.get("event_id")
        external = (f"{bu}/{eid}" if bu and eid else
                    opportunity.get("event_ref") or opportunity.get("department")
                    or "unknown")
        record_id = local_id("gov_procurement_records", "caleprocure_event_list",
                             "solicitation", external)
        candidates = result.get("prime_candidates", [])
        out.append({
            "id": local_id("partner_match_payloads", record_id, ENGINE_VERSION),
            "record_id": record_id,
            "recommended_direction": "seek_prime" if candidates else "insufficient_evidence",
            "preview": {"top_prime": candidates[0]["vendor_name"] if candidates else None,
                        "qualified": result.get("candidates_qualified", 0)},
            "results": [{
                "competitor_id": local_id("gov_competitors", "caleprocure_scprs",
                                          c["supplier_id"]),
                "supplier_id": c["supplier_id"], "vendor_name": c["vendor_name"],
                "prime_score": c["prime_score"], "confidence": c["confidence"],
                "credibility_case": c["credibility_case"],
                "teaming_case": c["teaming_case"],
                "disqualifiers": c["disqualifiers"],
                "also_likely_competitor": c["also_likely_competitor"],
            } for c in candidates],
            "source_summary": {"source_key": "caleprocure_scprs",
                               "vendors_considered": result.get("vendors_considered"),
                               "qualification_rule": result.get("qualification_rule")},
            "engine_version": ENGINE_VERSION,
            "generated_at": _now(),
            "expires_at": (dt.datetime.now(dt.timezone.utc)
                           + dt.timedelta(days=30)).isoformat(timespec="seconds"),
            "production_ids_unresolved": handoff_manifest()["production_ids_unresolved"],
        })
    return out
