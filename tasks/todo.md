# SLED Competitive Intelligence Trial — plan

Target spec: `README.md` (confirmed). `PROJECT_BRIEF.md` and `sources.yaml` are stale; their useful
requirements (dedup, amendment linking, review queue, freshness) are folded in below.
Data-contract snapshot is authored locally as a placeholder (confirmed). See `DECISIONS.md`.

## Access: settled. No browser, no Browserbase, no API key.

| Surface | State |
| --- | --- |
| Event list `AUC_RESP_INQ_AUC.GBL` | DONE — 375 rows, 10/10 fields, 375/375 unique |
| Event detail `AUC_RESP_INQ_DTL.GBL` | DONE — UNSPSC, addenda, controls |
| Event attachments (postback chain) | DONE — 6/6 PDFs, hashed, live-verified |
| SCPRS awards `ZZ_SCPRS1_CMP.GBL` | endpoint verified public; parser to port |
| Vendor ads postback | control located; extraction to build |
| Payment Progress Search | reachable; fields unmapped |
| Open FI$Cal bulk CSVs | manifest + schema verified |
| data.ca.gov historical corpus | robots question open with Ananth; not depended on |

## Done

- [x] venv, deps, baseline tests green
- [x] OCR binaries confirmed present (tesseract, pdftoppm, pdfinfo)
- [x] Access research across all README source families -> `sources/source_registry.csv` (10 surfaces)
- [x] Cal eProcure adapter: session/state chain, event list, detail, attachment download
- [x] 18 offline tests, synthetic fixtures, no network
- [x] Live end-to-end verification of the adapter
- [x] `DECISIONS.md` — scope, placeholders, corrections, both PeopleSoft traps

## Next

### 1. Rubric area: document acquisition and extraction (15 pts)
- [ ] Sweep attachments across a sample of events; measure how many carry documents at all
- [ ] Persist to `data/raw/documents/<bu>_<event_id>/` + emit `build/documents_manifest.jsonl`
- [ ] Validate content type, magic bytes, size cap before processing; dedupe on SHA-256
- [ ] Record blocked/expired/malformed as typed failures, never silent omission
- [ ] pdfplumber page extraction -> `build/document_pages.jsonl` (text, method, tables, warnings)
- [ ] OCR fallback for image-only pages; degrade with a warning if binaries absent
- [ ] Validate the filename-prefix role convention across agencies before trusting it

### 2. Rubric area: bidder events and provenance (15 pts)
- [ ] Port `parse_scprs.py`; slice queries by date/department to stay under the 200-row pager cap
- [ ] Vendor-ad extraction; tag `prime_seeking_sub` / `sub_seeking_prime`; record "no ads" positively
- [ ] Search bid-tab / award / intent-to-award PDFs for named bidders — the only observed-bidder path
- [ ] Participation types kept strictly distinct; evidence tier on every record

### 3. Rubric area: vendor identity and profiles (15 pts)
- [ ] Canonicalize on SCPRS `supplier_id`; Open FI$Cal joined by name at low confidence
- [ ] Ambiguous identities -> review queue, never merged
- [ ] `build/vendor_profiles.json`

### 4. Rubric area: prediction (15 pts)
- [ ] Hold out 10 events before any feature work
- [ ] Explainable features with per-feature contributions; UNSPSC + agency axes
- [ ] Never treat certification or registration alone as a bid signal

### 5. Rubric area: primes and teaming (15 pts)
- [ ] Require evidence of comparable prime awards
- [ ] Flag likely-competitor-also-viable-partner

### 6. Lineage, contracts, demo
- [ ] Predecessor search reading document text, not just titles; explicit no-match trace records
- [ ] Opportunity-to-award linkage as `inferred` only — no deterministic join exists
- [ ] Author `contracts/supabase/*.schema.json` + `data/examples/active_opportunity.json`
- [ ] 7 Supabase-shaped JSONL exports + `validation_report.json`
- [ ] Evaluate: precision@3, precision@5, bidder coverage; 20-page manual extraction review
- [ ] `build/report.md`; answer README's 8 questions; propose next 3 sources

## Standing rules
- [ ] `pytest` green before every handoff; tests stay offline
- [ ] Raw source ids and official URLs preserved through every transform
- [ ] Missing stays null — never 0, never a default
- [ ] Predicted never presented as observed
- [ ] Per-host rate limiting; attachments are serial per event (ICStateNum chain)
- [ ] No secrets; raw bytes stay under gitignored `data/raw/`

## Risks
- **Observed bidders may not exist in California at all.** Not public on the portal; the remaining
  hope is bid-tab PDFs in attachments. If those are absent too, the honest deliverable is
  declared-interest plus inferred competitors, with the limitation demonstrated.
- **SCPRS 200-row pager** — mitigated by slicing, not yet implemented.
- **Signed attachment URLs are per-request**, so they cannot be stored as durable locators.
- **Six 15-pt areas, days left.** A thin complete slice beats two polished areas.

## Review

All six 15-point rubric areas have working, tested code. Built in dependency order: access
research, then documents, then identity, then prediction, then teaming, then exports and report.

| Rubric area | Pts | State |
| --- | ---: | --- |
| Source discovery and access research | 15 | done — 14 surfaces measured in `sources/source_registry.csv` |
| Document acquisition and PDF extraction | 15 | done — 84 documents, 863 pages, OCR exercised |
| Bidder-event accuracy and provenance | 15 | done — observed awardee extracted from a real award notice |
| Vendor identity resolution and profiles | 15 | done — canonical `supplier_id`, 634 profiles |
| Likely-bidder prediction quality | 15 | done — explainable, precision@3 0.0727, lift 1.2x over the best trivial baseline |
| Prime and teaming recommendations | 15 | done — 21 of 68 eligible vendors qualified, dual-role flagged |
| Tests, failure handling, reproducibility | 5 | 356 offline tests, typed failures, bounded retries |
| Demo and product recommendations | 5 | `build/report.md` generated from artifacts |

### What the trial establishes

The central question — can public California records name who competes — has a definite
answer. Not from portal fields: bidder identity lives in documents attached to events, and
the DMV intent-to-award notice proved the full chain (document -> named awardee with amount ->
canonical `supplier_id` -> 9,537-award history).

### The deliverable command

`python -m sled_trial.cli analyze --opportunity data/examples/active_opportunity.json
--download-documents --output build` runs verbatim and produces all ten required artifacts
plus the seven Supabase tables. `--reuse-awards` replays it in ~41s without re-querying the
award registry. `events` and `documents` are narrower entry points; `evaluate` and
`backfill-primes` sit outside `analyze` so the precision figure is reproducible offline and
the prime corpus can be deepened without re-running the crawl. Install and command costs are
in `docs/RUNNING.md`.

### What remains honestly short

- **Prediction is weak** (precision@3 0.0727 on the unselected 55-event set, 1.2x the best
  trivial baseline) and the ground truth is purchase-level, not
  solicitation-level. A solicitation-level evaluation set must be assembled from award-notice
  documents; its size is bounded by how many agencies post one.
- **Minimums partly met.** 634 vendor profiles against 25 required, and 55 held-out events
  evaluated. Bidder-event observations from documents number 1, not 100 — because only one
  event in thirty sampled carried an award notice. Volume comes from award history instead.
- **Lineage finds no predecessors on the demonstrated event.** The searcher is built and
  reads document text, but the one event exercised has no public predecessor to find. It
  needs running across many events to show it can find one, and a live run initially produced
  a false positive by matching the solicitation's own number.
- **Vendor ads not harvested.** The strongest forward-looking signal California exposes, and
  the highest-value next increment.
- **Supabase contracts are authored placeholders**, not the promised snapshot.

### Open with the trial author

1. The frozen data-contract snapshot is absent from the repository.
2. `data.ca.gov/robots.txt` disallows `/api/`, which the historical corpus query needs.
