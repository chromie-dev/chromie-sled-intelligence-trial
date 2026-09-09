# Supabase mapping — proposed contract

**Status: proposed, not production.** The schemas in `contracts/supabase/` were authored from
the pattern table in `README.md`. The trial author confirmed on 2026-09-08 that no separate
data-contract snapshot is coming, so nothing here has been checked against Chromie's real
schema. Validation passing means the trial's own outputs are internally consistent. It does
**not** mean they would import into Chromie. Assumptions and known gaps are listed at the end,
and every one of them is a place this could be wrong.

Generated fixtures live in `build/supabase/`. `build/supabase/handoff.json` carries the same
facts in machine-readable form, produced by `src/sled_trial/supabase_export.py`. Where this
document and that file disagree, the module is authoritative — a test asserts they match.

## Tables

Seven tables, mapped from the README pattern table.

| Table | One row is | Populated from |
| --- | --- | --- |
| `gov_procurement_sources` | one portal or source surface | `sources/source_registry.csv` |
| `gov_competitors` | one canonical vendor identity | SCPRS `supplier_id`, via `vendors.build_profiles` |
| `gov_procurement_records` | one solicitation, award, contract or purchase order | Cal eProcure event feed and SCPRS award rows |
| `gov_procurement_participants` | one evidence-backed vendor-to-record relationship | SCPRS awardees, plus vendors named in official documents |
| `gov_procurement_documents` | one attachment, retrieved or not | `documents_manifest.jsonl` |
| `document_content_handoff` | one page of one document | `document_pages.jsonl` |
| `partner_match_payloads` | one prime/teaming result set for one record | `primes.recommend_primes` |

## Relationships

```
gov_procurement_sources
├── gov_competitors            (source_ref)
├── gov_procurement_records    (source_ref)
│   ├── gov_procurement_participants  (record_id, competitor_id -> gov_competitors)
│   ├── gov_procurement_documents     (record_id, source_ref)
│   │   └── document_content_handoff  (document_id)
│   └── partner_match_payloads        (record_id, results[].competitor_id)
```

`gov_procurement_records` also carries three self-references for lineage —
`predecessor_record_id`, `solicitation_record_id`, `resulting_contract_record_id`. **All three
are currently null in every emitted row.** California publishes no deterministic join from a
solicitation to its eventual award: SCPRS is keyed by purchase document number, unrelated to
the Cal eProcure event id, and solicitation numbers rarely survive into award descriptions.
Populating them would mean asserting a link the public record does not support, so they stay
null and `procurement_lineage.json` carries the probabilistic findings with their evidence.

## Import order

Dependency order, not declaration order. Each table lands after everything it references.

| # | Table | References |
| --: | --- | --- |
| 1 | `gov_procurement_sources` | — |
| 2 | `gov_competitors` | sources |
| 3 | `gov_procurement_records` | sources |
| 4 | `gov_procurement_participants` | records, competitors |
| 5 | `gov_procurement_documents` | records, sources |
| 6 | `document_content_handoff` | documents |
| 7 | `partner_match_payloads` | records, competitors |

This ordering was wrong until it was written down: `gov_competitors` originally sat at
position 6, after the participants that reference it, and the test only spot-checked two of
the four dependencies. The full graph is now asserted from `supabase_export.FOREIGN_KEYS`.

## Natural upsert keys

Every table has a business key independent of its surrogate id, so a re-export or a partial
re-run updates rows rather than duplicating them.

| Table | Natural key |
| --- | --- |
| `gov_procurement_sources` | `source_key` |
| `gov_competitors` | `source_ref`, `external_source_id` |
| `gov_procurement_records` | `source_ref`, `record_type`, `external_id` |
| `gov_procurement_participants` | `record_id`, `competitor_id`, `role` |
| `gov_procurement_documents` | `record_id`, `displayed_filename`, `sha256` |
| `document_content_handoff` | `document_id`, `page` |
| `partner_match_payloads` | `record_id`, `engine_version` |

Two notes on why these keys and not others:

- **Records are keyed on `external_id`, not on title or date.** For a solicitation the
  external id is `business_unit/event_id`, because an event id alone is not unique across
  agencies and its format varies by department (`0000040242` and `04A7615` both occur). For an
  award it is the purchase document number.
- **Documents include `sha256` in the key.** An agency can replace an attachment while keeping
  the filename. Keying on filename alone would silently overwrite the earlier version and lose
  the amendment; including the hash makes a replacement a new row, which is what an audit
  trail needs.

## Conflict behaviour

On conflict against the natural key, update mutable observation fields — amounts, dates,
status, `processing_state`, `observed_at` — and leave identity and evidence fields alone.

One rule matters more than the rest: **never overwrite a stronger `evidence_class` with a
weaker one.** The ladder is `observed` > `derived` > `predicted`. A vendor named in an
intent-to-award notice is `observed`; the same vendor inferred from award history is `derived`.
If a later run happens to process the derived path first, a naive upsert would downgrade a fact
to an inference, and the downstream product would stop being able to tell the difference. The
same applies to `identity_confidence`: `high` must not be replaced by `unresolved`.

`gov_procurement_participants` never contains a `predicted` row. Predictions live in
`build/likely_bidders*.jsonl` and inside `partner_match_payloads.results`, and are labelled
there. That separation is deliberate and should survive ingestion.

## Local-to-production ID mapping

Every id in these fixtures is a deterministic UUIDv5 over a fixed local namespace
(`65bfa1ac-0a07-59e0-b30b-b8cc512ee521`, derived from a trial-only URL) and the row's natural
key. Consequences:

- A re-run reproduces byte-identical ids, so fixtures are diffable and relationships survive
  re-export.
- No production UUID is assumed, fabricated, or read anywhere.
- Ids are reproducible across machines, so two people generating fixtures agree.

Mapping plan for a future controlled ingestion:

1. Import tables in the order above.
2. For each table, upsert on the natural key and capture the production id the database
   assigns, building a `local_id -> production_id` map keyed by natural key.
3. Before importing each child table, rewrite its foreign keys through that map.
4. Never carry a local id into production as a primary key; it is an export-stability device,
   not an identity.

Fields that can only be resolved inside Chromie are left unresolved rather than guessed, and
are listed in `handoff.json` under `production_ids_unresolved`: `organization_id`,
`client_company_id`, `user_id`, `workspace_id`.

**No script in this repository points at, authenticates to, or writes to any Supabase
instance.** Exports are files on disk.

## Assumptions

Each of these is a guess that a real snapshot would settle.

1. **Column names follow the README prose.** Where the brief names a concept ("submitted
   amount", "identity confidence") the column name was derived from it. Real names may differ.
2. **`additionalProperties` is true on every schema.** A real table will carry columns this
   trial cannot know about, and rejecting them would be a false failure. The cost is that a
   misspelled column of ours passes validation.
3. **Amounts are numeric with the raw string retained beside them.** Every money field appears
   twice: `amount` as a number and `amount_raw` as the portal's own string. An unparseable
   amount leaves the numeric field null rather than zero.
4. **Dates stay as source strings.** Cal eProcure returns `09/08/2026 10:00AM PDT`, SCPRS
   returns `09/03/2026`. Neither is normalised to ISO, because inventing a timezone for a
   naive date would be a fabricated fact. Normalisation belongs at ingestion, once the target
   column type is known.
5. **`evidence_class` is a three-value ladder.** Assumed to exist as a concept because the
   brief insists facts, inferences and predictions stay separable; the real column may be
   named or shaped differently.
6. **One source row per surface, not per portal.** Cal eProcure appears as six rows because its
   event list, event detail, attachment postback, vendor ads, SCPRS and payment search have
   genuinely different access methods, freshness and gaps. A real schema may model the portal
   as the unit instead.

## Validation gaps

What passing validation does **not** demonstrate.

1. **No production comparison has been made.** Zero rows have been tested against a real
   Chromie table. This is the whole caveat.
2. **Types are permissive.** Nullable unions (`["string", "null"]`) accept both, so a field
   that should always be present can be null here and still validate.
3. **Referential integrity is not enforced by the schemas.** JSON Schema cannot express a
   foreign key. Ordering and mapping are asserted by tests over `FOREIGN_KEYS`, not by the
   contracts themselves.
4. **`partner_match_payloads` has exactly one row.** One opportunity has been analysed end to
   end, so the table's shape is exercised but not its volume.
5. **Enumerations are open.** `record_type`, `role`, `access_mode` and `processing_state` are
   plain strings. Real columns are probably constrained, and our vocabulary
   (`solicitation`, `award`, `awardee`, `known_bidder`) may not match theirs.
6. **Document content is inlined.** `document_content_handoff.text` carries full page text,
   which makes `build/supabase/document_content_handoff.jsonl` the largest fixture by far.
   A real handoff may expect a storage reference instead of the bytes.
