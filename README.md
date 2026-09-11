# SLED Competitive Intelligence Trial

Build a production-shaped research pipeline that identifies the companies competing for state and local government contracts, profiles those companies, predicts which vendors are likely to bid on an active opportunity, and recommends credible prime contractors for subcontracting outreach.

The trial starts with California and Cal eProcure. The goal is not nationwide opportunity aggregation. The goal is to prove that public SLED procurement records can become useful competitive and teaming intelligence inside Chromie.

## Why this matters

An opportunity record alone does not tell a contractor how to win. Chromie should help answer:

1. Who has bid on similar work for this agency?
2. Who has won, lost, or repeatedly participated?
3. Which vendors are likely to bid on this opportunity?
4. Which likely bidders are credible primes for this pursuit?
5. Where does a client have a competitive or teaming advantage?

Cal eProcure is the initial proving ground because its public surfaces include solicitation events, response/bid inquiries, supplier search, contract and procurement records, certifications, and expenditure data. The intern must determine which information is available, when it becomes public, how it can be accessed reliably, and what cannot be known from public evidence.

## One-week outcome

Produce an evidence-backed California competitive-intelligence dataset and a working demo that accepts an active opportunity and returns:

- Known bidders on the opportunity, when publicly disclosed.
- Likely bidders, clearly labeled as predictions rather than facts.
- Vendor profiles built from historical bids, awards, spending, certifications, commodities, agencies, and geography.
- Similar-contract competitors and incumbents.
- The procurement lineage for the opportunity, including any earlier RFI, request for information, sources-sought-style notice, draft solicitation, forecast entry, prior solicitation, or resulting contract that can be verified.
- Recommended prime contractors for subcontracting outreach.
- Evidence, confidence, and data gaps for every material claim.

The result should be shaped for eventual integration into Chromie's pre-click opportunity debrief and teaming workflow, but it must not connect to Chromie production systems during the trial.

## Document-first research requirement

Portal fields are a discovery index, not the complete source of truth. Most procurement context lives in the underlying PDFs and attachments. The pipeline must autonomously discover, download, preserve, extract, and analyze all publicly available documents needed to understand an opportunity and its history.

For every target procurement, attempt to collect:

- Early notices, forecasts, RFIs, RFQs, requests for qualifications, market surveys, and draft solicitations.
- The final RFP, IFB, or solicitation package.
- All attachments, exhibits, scopes of work, pricing sheets, and forms.
- Amendments, addenda, questions and answers, and revised documents.
- Interested-vendor, planholder, respondent, or bidder lists when public.
- Bid tabulations, evaluation notices, notices of intent to award, award notices, contracts, and purchase orders.
- Relevant board agendas, staff reports, budget documents, and approval packets linked to the procurement.

When portal metadata conflicts with an official document, preserve both values, flag the conflict, and treat the most recent authoritative document as controlling only when that precedence can be justified.

### Autonomous document acquisition

The implementation must include a document-discovery and download layer that:

- Enumerates document links from opportunity pages and related records.
- Resolves safe public redirects and downloads supported attachments.
- Validates HTTP status, content type, file signature, and file size before processing.
- Applies per-host rate limits, bounded retries, timeouts, and maximum file-size limits.
- Computes a SHA-256 content hash and deduplicates identical files.
- Preserves the original official URL, source page, displayed filename, final URL, retrieval timestamp, content type, size, and download status.
- Records blocked, expired, malformed, or inaccessible documents as explicit failures rather than silently omitting them.
- Never executes macros, embedded files, scripts, or downloaded binaries.

Downloaded bytes should be stored under a gitignored local directory such as `data/raw/documents/`. The checked-in fixtures should use a small, legally redistributable sample set or synthetic documents. The document manifest and hashes must remain reproducible even when raw documents cannot be committed.

### PDF extraction

For each PDF, create page-addressable extracted output containing:

- Stable document reference and content hash.
- Page number.
- Extracted text.
- Extraction method: native text, OCR, or hybrid.
- OCR confidence when applicable.
- Table and layout indicators needed to recover bidder names, pricing, dates, requirements, and references.
- Extraction warnings and page-level failures.

Use native PDF text extraction first and OCR as a fallback for scanned or image-based pages. The analysis must cite the document and page supporting each material claim. Portal snippets alone are not sufficient evidence when the underlying document is available.

The `gov_procurement_documents`-shaped export stores document identity, provenance, hashes, retrieval state, and processing state. Page-level extracted content should be emitted separately for later ingestion through Chromie's existing government-intelligence and document-processing infrastructure.

### Optional browser API

A browser-based API key can be provided if direct HTTP requests cannot reliably enumerate documents from a JavaScript-heavy public portal. Browser access is an optional acquisition adapter, not a dependency of the core data model.

- Read the key only from an environment variable such as `BROWSER_API_KEY`; never commit or print it.
- Keep provider-specific code behind a documented adapter interface.
- Use it only to access public pages and public documents that a normal user may view.
- Do not use it to bypass authentication, CAPTCHA, paywalls, rate limits, robots restrictions, or other access controls.
- Fall back to a reproducible manual acquisition manifest when compliant automation is unavailable.

## Core deliverable

```bash
python -m sled_trial.cli analyze \
  --opportunity data/examples/active_opportunity.json \
  --download-documents \
  --output build
```

The command must create:

- `build/opportunity_intelligence.json`: opportunity summary, known bidders, likely bidders, incumbent context, and evidence.
- `build/procurement_lineage.json`: the RFP's verified predecessor notices and related procurement records, including explicit no-match results.
- `build/documents_manifest.jsonl`: every discovered attachment, download result, hash, document role, and provenance record.
- `build/document_pages.jsonl`: page-level PDF text, extraction method, confidence, layout indicators, and warnings.
- `build/vendor_profiles.json`: resolved vendor profiles and historical participation.
- `build/prime_candidates.json`: ranked potential primes with teaming rationale.
- `build/source_coverage.json`: what each source provides, availability timing, freshness, access method, and known gaps.
- `build/review_queue.json`: unresolved vendor identities, conflicting records, and low-confidence predictions.
- `build/report.md`: a readable competitive landscape and recommended next actions.
- `build/supabase/`: import-shaped JSONL fixtures and a validation report matching Chromie's current procurement data contracts.

## Chromie Supabase compatibility contract

The intern will not receive a Supabase URL, key, database dump, production schema export, or production access. The repository will provide a frozen, sanitized data-contract snapshot representing the relevant Chromie tables. All pipeline outputs must validate against that snapshot.

The output should map to these existing Chromie patterns:

| Chromie pattern | Trial output responsibility |
| --- | --- |
| `gov_procurement_sources` | One normalized source record per portal/source surface, including `source_key`, provider, portal, jurisdiction, platform, official/search URLs, adapter key, access mode, capabilities, refresh cadence, verification state, and known access gaps. |
| `gov_procurement_records` | One canonical row per RFI, RFP, award, contract, purchase order, or related instrument. Preserve `source_ref`, `record_type`, jurisdiction, buyer, dates, amounts, category, set-aside, competition method, raw provider data, provenance, and observation time. |
| `gov_procurement_participants` | One evidence-backed relationship between a procurement record and a resolved competitor, with role, rank, submitted amount, score when public, identity confidence, evidence, and observation time. |
| `gov_procurement_documents` | Document identity and provenance for RFIs, RFPs, addenda, bidder lists, tabulations, notices of intent, and awards. Preserve source reference, document role, official URL, hashes when downloaded, publication/retrieval time, and processing state. |
| `gov_competitors` | Canonical vendor identity with normalized legal name, aliases, public identifiers, external source IDs, profile status, and a provenance-backed derived profile. |
| `gov_partner_match_snapshots` | Produce a compatible partner-match result payload containing ranked primes, recommended direction, preview, results, source summary, engine version, generation time, and expiry assumptions. Production-only IDs remain unresolved placeholders. |

Required files:

- `contracts/supabase/*.schema.json`: sanitized JSON Schemas for every trial output.
- `build/supabase/gov_procurement_sources.jsonl`.
- `build/supabase/gov_procurement_records.jsonl`.
- `build/supabase/gov_procurement_participants.jsonl`.
- `build/supabase/gov_procurement_documents.jsonl`.
- `build/supabase/document_content_handoff.jsonl` for Chromie's existing government-intelligence and document-processing path.
- `build/supabase/gov_competitors.jsonl`.
- `build/supabase/partner_match_payloads.jsonl`.
- `build/supabase/validation_report.json`.

The fixtures must use deterministic local UUIDs so relationships can be tested without production identifiers. The handoff must document the intended import order, natural upsert keys, conflict behavior, and how local IDs would be remapped during a future controlled ingestion. No script may point at or write to Chromie Supabase.

## Required procurement-lineage analysis

When the target is an RFP, the pipeline must attempt to locate earlier related notices before completing the competitive analysis. Search for:

- A prior RFI or request for information.
- A sources sought, market survey, request for qualifications, or vendor outreach notice serving a similar function.
- A draft solicitation or pre-solicitation notice.
- A budget, forecast, board agenda, or planned-procurement entry.
- A prior version, cancelled event, predecessor solicitation, award, or incumbent contract.

Candidate lineage matches should use multiple signals where available:

- Exact or related solicitation and event numbers.
- Same buyer, department, procurement office, or contact.
- Title and scope similarity.
- Shared commodity/category codes.
- Matching attachments, dates, locations, funding references, or contract numbers.
- Explicit references inside the RFP or its attachments.

The lineage search must inspect the text of downloaded RFPs and attachments for references to earlier events, studies, contracts, outreach, draft requirements, solicitation numbers, and procurement timelines. Title-level portal matching alone is insufficient.

Represent each discovered RFI or predecessor as its own `gov_procurement_records`-shaped record. Connect verified relationships using the local equivalents of `predecessor_record_id`, `solicitation_record_id`, `resulting_contract_record_id`, and `lineage`. Store RFI documents separately using the `gov_procurement_documents` shape.

If no predecessor is found, output a completed trace record listing the sources, queries, identifiers, and date ranges checked. `No predecessor found` means no match was found in the searched sources; it does not prove that no earlier RFI existed.

## Required data model

### Bidder event

Each bidder-event record should capture:

- Solicitation or event identifier.
- Agency and contracting entity.
- Vendor name and resolved vendor identifier.
- Participation type: interested vendor, planholder, respondent, bidder, awardee, incumbent, or unknown.
- Bid amount, rank, status, and award outcome when public.
- Commodity codes, service category, location, and relevant certifications.
- Event date, publication date, and observation timestamp.
- Source URL or official document reference.
- Evidence classification: observed, derived, or predicted.
- Confidence score and explanation.

### Vendor profile

Each vendor profile should include, when supported:

- Canonical name and known aliases.
- Website and public supplier identifiers.
- SB, DVBE, or other public certifications.
- Commodity and service categories.
- Agencies and jurisdictions served.
- Historical bids, wins, losses, and known contract values.
- Typical contract size and geography.
- Recency and frequency of participation.
- Likely prime or subcontractor role.
- Source provenance and unresolved identity conflicts.

### Opportunity competitor assessment

For each active opportunity, return:

- Known participants disclosed by an official source.
- Likely bidders ranked by an explainable score.
- Similar historical procurements used as evidence.
- Incumbent or recent awardees.
- Competitive intensity estimate.
- Potential teaming candidates.
- Factors supporting and weakening each prediction.

Never present a likely bidder as a confirmed bidder. A vendor should be labeled `known_bidder` only when an official source explicitly associates that vendor with the event.

## Source-discovery requirement

Source discovery is a first-class deliverable, not preliminary busywork. Create `sources/source_registry.csv` with one row per source surface and these fields:

- Jurisdiction and agency coverage.
- Portal and source name.
- Official URL.
- Data type: solicitations, responses, bidders, awards, contracts, suppliers, certifications, expenditures, planholders, vendor ads, or forecasts.
- Access method: HTML, document, download, API, browser request, or manual-only.
- Authentication requirement.
- When the data becomes public.
- Historical depth.
- Update cadence.
- Stable identifiers.
- Automation feasibility.
- Terms or access constraints.
- Sample records collected.
- Known gaps.

Start with these official California source families:

| Source | Initial research question |
| --- | --- |
| [Cal eProcure public search](https://caleprocure.ca.gov/pages/public-search.aspx) | Which solicitation, event, agency, commodity, date, and status fields are publicly queryable? |
| [Cal eProcure Response Bid Inquiry](https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL?page=AUC_RESP_INQ_AUC) | Which respondent or bidder fields are exposed, and at what stage do names, amounts, ranks, or outcomes become public? |
| [Cal eProcure supplier search](https://caleprocure.ca.gov/pages/PublicSearch/supplier-search.aspx?psNewWin=true) | Which supplier identifiers, categories, locations, and SB/DVBE certifications support vendor resolution and profiling? |
| [SCPRS contract search](https://caleprocure.ca.gov/pages/SCPRSSearch/scprs-search.aspx) | Can awards and purchase records connect vendors to agencies, categories, dates, and contract values? |
| [Leveraged Procurement Agreement search](https://caleprocure.ca.gov/pages/LPASearch/lpa-search.aspx) | Which vendors already hold purchasing vehicles relevant to an opportunity? |
| [Open FI$Cal department vendor transactions](https://open.fiscal.ca.gov/dept_vendor_transaction.html) | Can vendor spending histories reveal active supplier relationships and agency concentration? |
| [DGS historical contracts data](https://www.dgs.ca.gov/en/PD/Resources/Page-Content/Procurement-Division-Resources-List-Folder/SCPRS-CSCR-Historical-Contracts-Data) | What historical exports exist, and can they seed bidder, award, and vendor histories? |
| [California procurement datasets](https://data.ca.gov/dataset?tags=Procurement) | Which downloadable datasets add awards, noncompetitive purchases, forecasts, or other competitive signals? |

The intern may inspect public browser network requests to understand how a portal loads data. They may not bypass authentication, CAPTCHA, access controls, rate limits, or terms of use.

## Five-day plan

| Day | Target |
| --- | --- |
| 1 | Map the California source landscape and frozen Supabase data contracts. Manually trace at least five procurements from early notice or RFI through RFP, bidder response, award, and contract records. |
| 2 | Implement the Cal eProcure adapter plus autonomous document discovery, download, hashing, PDF extraction, and OCR fallback. Normalize procurement/document records and build RFI-to-RFP lineage from both metadata and document text. |
| 3 | Resolve vendor identities and generate profiles from bid history, awards, certifications, supplier records, and expenditure data. Export validated Supabase-shaped fixtures. |
| 4 | Build an explainable likely-bidder baseline and prime-contractor recommendation model. Create a review queue for weak identities, lineage links, and predictions. |
| 5 | Evaluate against held-out historical events, demonstrate one active RFP from predecessor search through competitive/team analysis, validate all Supabase-shaped outputs, and propose the next three SLED sources to add. |

## Minimum evaluation set

The final submission must include:

- At least 30 historical California procurement events, unless the intern documents a verified portal limitation.
- At least 100 bidder-event observations across those procurements.
- At least 25 resolved vendor profiles.
- At least 10 historical events withheld from feature development and used for evaluation.
- One active opportunity used for the end-to-end competitive and teaming demo.
- A documented predecessor-notice search for every RFP in the evaluation set.
- A document corpus and manifest covering the solicitation packages and related records used in the evaluation.

If a source prevents collection at this scale, the intern must demonstrate the access limitation, preserve the research completed, and implement the strongest compliant fallback workflow.

## Acceptance criteria

- Every known bidder, award, certification, and expenditure claim links to official evidence.
- Vendor aliases are resolved without merging unrelated companies.
- The system distinguishes interested vendors, planholders, respondents, bidders, awardees, and incumbents.
- Predictions include feature contributions and confidence, not just an opaque score.
- Historical evaluation reports precision at 3, precision at 5, and coverage of actual bidders.
- Prime recommendations require evidence of relevant prime awards or comparable contract performance.
- The system identifies when a likely competitor may also be a viable teaming partner.
- Every RFP receives a predecessor search, and every claimed RFI-to-RFP relationship includes match evidence and confidence.
- Every evaluated procurement enumerates its public attachments; successfully retrieved PDFs have hashes, page-level extraction, and source provenance.
- At least 95% of publicly downloadable evaluation documents are acquired successfully, with every remaining failure classified and explained.
- A manual review of at least 20 representative PDF pages measures text, table, bidder-name, price, and date extraction quality.
- All normalized outputs validate against the frozen Chromie Supabase data contracts.
- No output depends on a production UUID; deterministic local identifiers preserve all relationships.
- Missing or unavailable public data remains unknown rather than becoming a negative fact or zero.
- No Chromie production data, customer data, private contact data, or proprietary GovWin data is used.
- Tests run locally with synthetic fixtures and no credentials.

## Baseline prediction features

The first model should remain explainable. Candidate features may include:

- Prior bids to the same agency.
- Prior bids for similar commodity or service codes.
- Relevant awards or expenditures from the same buyer.
- Geographic activity.
- Contract-size similarity.
- Recency and frequency of participation.
- Certification or set-aside compatibility.
- Incumbency or related contract history.
- Presence on a relevant statewide contract or purchasing vehicle.
- Evidence that the vendor commonly primes similar work.

Do not use company size, certification, or supplier registration alone as proof that a vendor will bid.

## Prime-contractor recommendation logic

A strong prime candidate should have evidence of several of the following:

- Has served as prime on comparable SLED work.
- Has bid to or won work from the same agency or jurisdiction.
- Covers the required scope, vehicle, geography, and certifications.
- Has contract history at a comparable value and complexity.
- Has a plausible capability gap the client's offering can fill.
- Is not disqualified by an obvious conflict, eligibility issue, or scope mismatch.

The output must explain both why the company is credible as a prime and why a subcontracting relationship could be strategically useful.

## Evaluation rubric (100)

| Area | Points |
| --- | ---: |
| Source discovery and access research | 15 |
| Autonomous document acquisition and PDF extraction | 15 |
| Bidder-event accuracy and provenance | 15 |
| Vendor identity resolution and profiles | 15 |
| Likely-bidder prediction quality | 15 |
| Prime and teaming recommendations | 15 |
| Tests, failure handling, and reproducibility | 5 |
| Demo and product recommendations | 5 |

## Out of scope

- Nationwide SLED coverage.
- Production ingestion or database changes.
- Automated outreach to vendors.
- Private contact enrichment.
- Scraping paid or authenticated competitor products.
- Claiming access to a bid response before the government makes it public.
- A complex black-box model unsupported by the evaluation set.

## Final presentation questions

1. Which California sources reveal actual bidders, and at what stage of procurement?
2. Which records reveal only interest or eligibility rather than an actual bid?
3. How accurately can historical participation predict the next bidder set?
4. Which vendor attributes are most useful for prime-contractor matching?
5. What source or data limitation most constrains the product today?
6. Which three portals or datasets should Chromie integrate next, and why?
7. What changed between the predecessor RFI or early notice and the final RFP, including scope, eligibility, evaluation, dates, and likely competitive field?
8. Which conclusions were available only from downloaded PDFs or attachments rather than portal metadata?

## Definition of done

The trial is complete when a reviewer can give the system one active California RFP URL and the system autonomously retrieves the relevant public documents, traces the procurement lineage, and returns a defensible competitive landscape, a ranked list of likely bidders, and a shortlist of credible primes for subcontracting outreach—with every fact traceable to a source document and page, every prediction clearly labeled, and every output validated against Chromie's frozen Supabase data contracts.

See `PROJECT_BRIEF.md`, `SECURITY.md`, and `AGENTS.md` before coding.

---

## Running this submission

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q                 # 709 tests, offline, no credentials

python -m sled_trial.cli analyze \
  --opportunity data/examples/active_opportunity.json \
  --download-documents --output build
```

`analyze` reads whatever the harvesters have already cached, so the commands below feed it.
Each writes its own coverage file recording what it collected against what the source
said existed.

**Who bid** — the surfaces that name competitors, not just winners:
`planetbids` (agency portals; largest bidder source, needs a browser),
`bidders` (Caltrans weekly results; resumable, so a long backfill survives interruption),
`tabulations` (SF Public Works).

**Who won, and who they are:** `spending`, `lpa` (statewide contract vehicles, joined on
supplier id), `suppliers` (location and certification index), `cslb` (contractor register).

**Opportunities:** `events`, `documents`, `csu` (23 campuses), `sacramento`.

**Reporting:** `coverage` (what every source holds, reconciled against portal totals),
`evaluate` (regenerates the precision figures offline — run it before `analyze` if you
want `report.md` to quote current ones), `backfill-primes`.

**Credentialed sources:** `auth --source <key>` signs in once through a hosted browser and
saves the session; `limits` reports what the browser key is allowed to do. Credentials live
in `.env` only — see `SECURITY.md` for what is and is not in bounds.

`build/` and `data/raw/` are generated and gitignored. Findings, dead ends and measured
source limits are in `DECISIONS.md`; the surveyed surfaces are in
`sources/source_registry.csv` and `docs/SOURCES.md`.
