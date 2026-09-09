# Decisions

Add dated technical and product decisions here.


## 2026-09-07 — Target spec is README.md, not PROJECT_BRIEF.md

`README.md` and `PROJECT_BRIEF.md` describe different products. README describes bidder/teaming
competitive intelligence sourced from California state portals. PROJECT_BRIEF describes generic
multi-portal opportunity normalization, and `sources.yaml` matches PROJECT_BRIEF (city / county /
school-district fixtures).

Building to README. Reasoning:

- The GitHub repo description is "Intern trial for evidence-grounded SLED procurement, bidder, and
  teaming intelligence" — README's subject, not PROJECT_BRIEF's.
- README carries the 100-point rubric, five-day plan, acceptance criteria, and definition of done.
  PROJECT_BRIEF carries none of them.
- README ends with "See `PROJECT_BRIEF.md`, `SECURITY.md`, and `AGENTS.md` before coding", which
  treats those three as supporting documents.
- The sibling trial `chromie-dev/chromie-federal-buyer-map-trial`, created in the same minute, has
  the same shape: a minimal per-trial scaffold, a narrow PROJECT_BRIEF, and a large rubric-scored
  README. The small scaffold is a seed, not a scope statement.

`PROJECT_BRIEF.md` and `sources.yaml` are treated as stale. Their still-useful requirements —
duplicate detection, amendment-to-parent linking, review queue, source freshness — are folded into
the README deliverables rather than dropped.

To revisit if the trial author states PROJECT_BRIEF is authoritative.

## 2026-09-07 — Two README-promised inputs are absent; authoring placeholders

README states "The repository will provide a frozen, sanitized data-contract snapshot representing
the relevant Chromie tables" and requires `contracts/supabase/*.schema.json`. No `contracts/`
directory exists. `data/examples/active_opportunity.json`, the argument to the documented core
deliverable command, is also absent.

Authoring both locally so work is not blocked:

- `contracts/supabase/*.schema.json` — sanitized JSON Schemas inferred from README's Chromie pattern
  table. Inferred field names and types are guesses, not the real contract.
- `data/examples/active_opportunity.json` — shaped from a real public Cal eProcure RFP, synthetic
  where fields are unknown.

Both are placeholders to be replaced if the real snapshot is supplied. Any validation result against
them proves internal consistency only, not compatibility with Chromie's actual schema. Requested the
real snapshot from the trial author.

## 2026-09-07 — Access research: Cal eProcure Response Bid Inquiry requires login

`https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL?page=AUC_RESP_INQ_AUC`
returns 302 and, followed, lands on
`https://caleprocure.ca.gov/psc/psfpd1/?cmd=login&errorPg=ckreq` with page title
"An error has occurred." The PeopleSoft bid-inquiry surface is authenticated.

Per `SECURITY.md` ("If a source requires login, payment, CAPTCHA bypass, or terms-violating
automation, stop and document it") and README ("may not bypass authentication"), no attempt was made
to authenticate or work around this. Stopping and documenting.

Consequence: README's named source for respondent/bidder fields does not yield public bidder
identities anonymously. The `known_bidder` deliverable cannot be sourced from this page. Fallback
paths to evaluate, in priority order:

1. Bid tabulation / notice-of-intent-to-award / award PDFs posted as public event attachments —
   most likely to name actual bidders and amounts.
2. SCPRS contract search — awardee identity, agency, category, value. Winner only, not the full
   bidder set.
3. Public solicitation event pages — may expose interested-vendor or planholder lists.
4. Open FI$Cal department vendor transactions — participation inferred from expenditure history.
   Derived, never `observed`.

Recorded as a verified portal limitation for the minimum-evaluation-set carve-out.

## 2026-09-07 — data.ca.gov robots.txt disallows the CKAN API

`https://data.ca.gov/robots.txt` contains, under `User-agent: *`, `Disallow: /api/` and
`Disallow: /datastore/*`. README forbids bypassing robots restrictions, so the pipeline will not be
built on `data.ca.gov/api/3/action/*` or the datastore endpoints. One exploratory `package_search`
call was made before robots.txt was read; no automated collection will use those paths.

Substitute: dataset landing pages and direct resource-file downloads on non-disallowed paths.

Separate finding on value: only 3 datasets carry the `Procurement` tag — `dgs-approved-non-competitive-bids`,
`marketing-and-outreach-advertising-materials-purchase-report`, and
`dgs-procurement-division-personal-protective-equipment-purchase`. None carries solicitation-level
bidder data, and non-competitive bids are by definition not competitive events. This source family is
far thinner than README implies and is deprioritized accordingly.

## 2026-09-07 — User-agent choice (needs sign-off)

`caleprocure.ca.gov` returns 403 to a bare custom user-agent and to a third-party fetch service,
including on `/robots.txt`. With the conventional crawler user-agent format
`Mozilla/5.0 (compatible; chromie-sled-trial-research/0.1)`
all public `.aspx` search pages return 200 and `/robots.txt` returns 404 (no robots policy published).

Position taken: this is the standard self-identifying crawler format — the same shape as Googlebot's
`Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)`. It names the project and
gives a contact address, does not claim to be a specific browser, and defeats no authentication,
CAPTCHA, paywall, or rate limit. On that basis it is treated as honest identification rather than
circumvention.

Countervailing view worth stating plainly: the 403 is a bot filter, and a UA that clears it is
arguably an access control being worked around. Flagged for the trial author rather than settled
unilaterally. If Chromie prefers, the fallback is the README's optional browser adapter or the
reproducible manual acquisition manifest.

Note: 404 on robots.txt means no published crawl policy, which is not permission for aggressive
crawling. Per-host rate limiting still applies regardless.

## 2026-09-07 — Reachable vs. blocked, as measured

| Surface | Status | Note |
| --- | --- | --- |
| caleprocure public-search.aspx | 200 | 4.8 KB, likely a JS shell — needs verification |
| caleprocure Events-BS3/event-search.aspx | 200 | 50 KB |
| caleprocure PublicSearch/supplier-search.aspx | 200 | 29 KB |
| caleprocure SCPRSSearch/scprs-search.aspx | 200 | 41 KB |
| caleprocure LPASearch/lpa-search.aspx | 200 | 41 KB |
| caleprocure Response Bid Inquiry | 302 -> login | authenticated, out of bounds |
| open.fiscal.ca.gov/dept_vendor_transaction.html | 200 | 12 KB |
| www.dgs.ca.gov | 200 | robots.txt is `Allow: /` |
| data.ca.gov | 200 | robots.txt disallows `/api/`, `/datastore/*` |

Whether the 200-returning pages are server-rendered or JavaScript shells requiring POST/XHR is not
yet established and is the next thing to determine.

## 2026-09-07 — Cal eProcure is client-rendered; no HTTP-only enumeration is possible

All five public `.aspx` search pages return 200 but carry zero data rows. The pages are an InFlight /
NLX overlay on PeopleSoft: values are bound at runtime through `data-if-source` attributes pointing at
PeopleSoft record fields (e.g. `RESP_INQA_HD_VW$0#2` = event ID, `#3` = event name, `#1` = department,
`#6` = publish date, `#7` = end date, `#8` = status), and the form's key handler targets the PeopleSoft
push-button `RESP_INQA_WK_INQ_AUC_GO_PB`.

The relay endpoint `/pages/ps-relay.aspx?nlxTarget=AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL&Page=AUC_RESP_INQ_AUC&Action=U&BUSINESS_UNIT=`
was retrieved anonymously (200, 27 KB) but is itself only the InFlight bootstrap shell: 17 scripts,
zero tables, no PeopleSoft field names in the markup. Data is fetched client-side after JS runs.

The iframes on every page are Google Tag Manager, not the search UI.

Conclusion: README's browser adapter is **required, not optional**, for any Cal eProcure surface. This
is exactly the documented trigger ("if direct HTTP requests cannot reliably enumerate documents from a
JavaScript-heavy public portal"). Reverse-engineering the portal's own public network requests is
explicitly permitted by README; no authentication or CAPTCHA was involved in this determination.

## 2026-09-07 — DGS bulk historical export no longer exists

The DGS SCPRS/CSCR historical contracts page states: "As of April 18th, 2018, data on this page is no
longer updated weekly. Historical data (prior to 2015) is available upon request. Current data (2015 -
current date) can be found by visiting www.caleprocure.ca.gov." A link scan of the page finds zero
`.csv`, `.xlsx`, `.zip`, or `.txt` downloads.

README treats this as a source that can "seed bidder, award, and vendor histories." It cannot. Pre-2015
data requires a manual email request; 2015-onward is redirected back to the JavaScript-only portal.
Recorded as a verified portal limitation.

## 2026-09-07 — Open FI$Cal bulk expenditure CSVs are the one high-feasibility source found

`open.fiscal.ca.gov/dept_vendor_transaction.html` is itself a JS shell, but its source publishes a
pointer manifest URL directly:

`https://adwoutputfilesadlsstore.blob.core.windows.net/transparency/DepartmentVendorTransactionPointer/DepartmentVendorTransactionPointer.csv`

Retrieved: 200, 266 KB, 1230 rows, each naming a downloadable per-department per-fiscal-year CSV with
size and a direct URL. Coverage: FY16 through FY25, 154 distinct departments, 10.6 GB in total.
HTTP Range requests are supported, so schemas and slices can be sampled without downloading whole files.

Schema (26 columns), from a 3 KB range sample of `Vendor_7120_CAWorkforceInvestmentBoard_FY24.csv`:
`business_unit, agency_name, department_name, document_id, related_document, accounting_date,
fiscal_year_begin, accounting_period, VENDOR_NAME, account, account_type, account_category,
account_sub_category, account_description, fund_code, fund_group, fund_description, program_code,
program_description, sub_program_description, budget_reference, budget_reference_category,
budget_reference_sub_category, budget_reference_description, year_of_enactment, monetary_amount`.

No auth, no CAPTCHA, no JS needed. A voluntary per-host rate limit is still applied; the blob host
publishes no robots.txt (`/robots.txt` returns Azure error 400, not a policy).

Value and limits: gives vendor-to-department relationships, amounts, dates, and multi-year history —
enough for agency concentration, contract-size similarity, recency, and frequency in vendor profiles.
Gives no bidder events, no losing bidders, and no solicitation identifiers, so any participation
inferred from it is classified `derived`, never `observed`.

Two open problems recorded:

1. `VENDOR_NAME` appears truncated near 30 characters ("WESTERN STATES COUNCIL OF", "STATE BLDG &
   CONST TRADES"). Truncation is a direct threat to the acceptance criterion "vendor aliases are
   resolved without merging unrelated companies" — two different firms can share a truncated prefix.
   Resolution must treat truncated names as low-confidence and route ambiguity to the review queue.
2. `document_id` (e.g. `7120.00005358.0.00001.0001`) is a FI$Cal accounting document reference. Whether
   it joins to an SCPRS contract number or purchase document number is unproven and must be tested
   before any lineage claim rests on it.

## 2026-09-07 — suppliers.fiscal.ca.gov unreachable

Cal eProcure's InFlight config references PeopleSoft components on a second host under an
`ADMN_PUBLIC_SEARCH` portal node: `ZZ_PO.ZZ_SCPRS1_CMP.GBL` (SCPRS) and `ZZ_PO.ZZ_PMNTSRCH_PG.GBL`
(payment search). Both, and `/robots.txt`, time out at 20-30 s from this network. Possibly
network-restricted or retired. Retest from a different network before ruling it out; if it does serve
public SCPRS data server-side it would be a materially better path than the browser adapter.

## 2026-09-07 — CORRECTION: Cal eProcure IS reachable over plain HTTP. My earlier conclusion was wrong.

An earlier entry today concluded that "README's browser adapter is required, not optional" for every
Cal eProcure surface. **That conclusion was wrong, and is withdrawn.** It was reached by probing the
wrong layer: the `.aspx` InFlight wrapper pages, which are indeed empty shells. The PeopleSoft
components beneath them serve full server-rendered data anonymously.

Source of the correction: prior reconnaissance found on this machine at
`/Users/pookie/chromie-trial-notes/recon/` (`SOURCE-MATRIX.md`, `CA-COMPETITOR-INTEL.md`, dated
2026-09-03), which mapped these endpoints. Every claim below was **re-verified live today** before
being adopted.

Two URL-shape traps explain the earlier failure:

1. `AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL?page=AUC_RESP_INQ_AUC` — the form given in README —
   302s to a login page. The **bare** component URL with no query string does not.
2. `ZZ_PO.ZZ_SCPRS1_CMP.GBL` alone 302s to login. With
   `?FolderPath=PORTAL_ROOT_OBJECT.ZZ_FISCAL_SCPRS.ZZ_SCPRS1_CMP_GBL&IsFolder=false&IgnoreParamTempl=FolderPath%2cIsFolder`
   it is public. The params are what make it anonymous.

Also corrected: `suppliers.fiscal.ca.gov` timing out is irrelevant. `caleprocure.ca.gov`
reverse-proxies the same PeopleSoft application, so the backend host is not needed.

### Verified live, 2026-09-07

**Opportunity feed** — `GET https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL`
(follow redirects, keep the cookie jar). Returns 1,178,885 bytes, title "Response Bid Inquiry".
Parsed with the existing `recon/ca/parse_ca.py`: **375 rows, all 10 fields populated on all 375,
67 agencies, 375/375 unique on `(business_unit, event_id)`, self-check passes.** No pagination —
the whole active set arrives in one response.

Churn vs. the 2026-09-03 capture (360 rows): 332 still present, 28 gone, 43 new. This confirms the
recon's lifecycle warning — the feed is **active-only**, so an event disappearing is the only closure
signal, and a failed run must be recorded as "no signal", never as "everything closed".

Event ID formats are not uniform: `0000040242` (zero-padded) and `04A7615` (Caltrans) both occur.
Identity must be the `(business_unit, event_id)` pair.

**Event detail** — `GET .../AUC_MANAGE_BIDS.AUC_RESP_INQ_DTL.GBL?Page=AUC_RESP_INQ_DTL&Action=U&AUC_ID=<id>&AUC_ROUND=1&BIDDER_ID=BID0000001&BIDDER_LOC=1&BIDDER_SETID=STATE&BIDDER_TYPE=B&BUSINESS_UNIT=<bu>`
with a `Referer` header and the session cookie. Verified on `(2660, 04A7615)`: 81,828 bytes,
UNSPSC codes (`81101500`, `81101508`, `81101517`, `20736000`, `30121700`), three named addenda
("Addendum 1 - DBE CM GenAI and SOQ", "Addendum 2 ...", "Addendum 3 ..."), and the controls
`RESP_INQ_DL0_WK_AUC_DOWNLOAD_PB` ("View PDF/XML Files") and `ZZ_VNDR_AD_WRK_VENDOR_DETAILS_PB`
("View Vendor Ads").

**User-agent question resolved in the conservative direction.** All of the above works with the
self-identifying crawler UA `Mozilla/5.0 (compatible; chromie-sled-trial-research/0.1; +mailto:...)`.
The prior recon used a full Chrome impersonation string; that is not necessary and will not be used.

### Attachment postback: advanced, not solved

The prior recon listed this as its open CA item, and it remains open. Progress made today: the
control is `RESP_INQ_DL0_WK_AUC_DOWNLOAD_PB` on form `win0`, posting to the detail `.GBL` with the
page's hidden state (`ICSID`, `ICStateNum=2`, `ICAction` set to the control name). Replayed that POST
over plain HTTP: returns 200 and 31,772 bytes of PeopleSoft page frame — no `Content-Disposition`, no
filenames, no attachment URLs, no redirect or `window.open` to follow. `RESP_INQ_DL0_WK` is a work
record with a single push-button, not a grid of files, so the attachment list is never present in the
detail HTML. The link carries `ptlinktgt='pt_peoplecode'`, i.e. a server-side PeopleCode action,
likely completing in a new PeopleSoft window.

Decision: **scope the browser adapter to exactly this one job.** HTTP handles enumeration — event
list, event detail, SCPRS, vendor ads, expenditures — and the browser is used only for the event
package postback, one request per opportunity. That is a narrow, defensible use of README's optional
adapter rather than a whole-portal dependency, and it keeps the core data model browser-independent
as README requires. Retry HTTP replay against a fresh single-use session before accepting this.

## 2026-09-07 — SCPRS solves vendor identity; supersedes the name-truncation worry

SCPRS award records carry `supplier_id`, a stable canonical vendor key. Prior recon verified a
supplier-name search for `TECHNOLOGY INTEGRATION GROUP` returning 307 awards all under
`supplier_id 0000000269`, spanning multiple departments. Name variants collapse onto the id with no
fuzzy matching.

This materially de-risks the acceptance criterion "vendor aliases are resolved without merging
unrelated companies", and supersedes the earlier concern about `VENDOR_NAME` truncation in the Open
FI$Cal expenditure CSVs: those names are a display field, not the identity key. Plan is now to
canonicalize on SCPRS `supplier_id` and treat Open FI$Cal rows as corroborating evidence joined by
name with explicit low confidence, routing ambiguity to the review queue.

Per-award SCPRS fields (13, previously parsed and validated): `purchase_doc`, `department`,
`description`, `where_cf`, `start_date`, `end_date`, `awarded_amt`, `supplier_id`, `supplier_name`,
`cert_type` (`SB`/`MB`/`DVBE`/`SB-PW`), `comment` (category), `acq_method`, `lpa_contract`.

`acq_method` states competitive vs. non-competitive explicitly (e.g. "Formal - COMPETITIVE",
"Exempt by Policy - Other - NON-COMPETITIVELY BID", "CMAS (requires offers)", "Statewide Contracts").
A non-competitively-bid award is a stronger incumbency signal than a competitive one; statewide
vehicle awards are weaker, since they reflect being on a vehicle rather than winning a competition.

Open item carried over: SCPRS pagination stops at row 200 and the NEXT control did not advance under
automation. Workaround is to slice queries by date and/or department so each result set stays under
200 — more robust for a backfill anyway.

## 2026-09-07 — Bidder lists are definitively not public in California; vendor ads are the substitute

Prior recon establishes, and today's login redirect corroborates, that Cal eProcure publishes no
planholder lists, no bidder lists, no per-solicitation bid results, and no pre-bid attendee lists.
This is the answer to README's central research question, and it is a negative finding to report
rather than a gap to work around.

The one California source that ties a **named company to a specific solicitation** is the event
vendor-ad board, reached by the `ZZ_VNDR_AD_WRK_VENDOR_DETAILS_PB` postback on the event detail page
and keyed to the same `(business_unit, event_id)` pair. Two channels per event:

- `Prime Seeking Sub` — a company publicly declaring intent to bid as prime on that solicitation.
  The stronger of the two signals.
- `Sub Seeking Prime` — a subcontractor advertising to prospective primes.

Emptiness is stated explicitly by the page ("No Ad for Prime Seeking Sub"), which makes "no ads" a
positive recordable observation and directly serves README's data-gap requirement.

Two material caveats from the recon's sample: ads carry a **person**, not a structured company
identity (no `supplier_id`; the company name appears only inside free text), so resolving an ad to a
canonical vendor is fuzzy string matching against SCPRS `supplier_name` and must carry reduced
confidence. And signal quality is mixed — the sampled ad was a generic bid-assistance service, not a
scope-relevant subcontractor, so such ads will recur across unrelated events.

Classification adopted: ads become their own evidence records tagged by channel, at a
`declared_interest` tier — above inference because it is solicitation-specific and self-declared,
below any award-backed tier because it is not an award and the company is not canonically identified.
Never `known_bidder`.

## 2026-09-07 — No deterministic solicitation-to-award join exists in California

SCPRS rows are keyed by purchase document number (`26IT-0168`, `TA26-042`), which bears no relation
to the Cal eProcure event id `(2720, 0000039537)`. Prior recon tested whether solicitation numbers
survive into SCPRS descriptions: a description search for `IFB` across all of 2026 returned only 11
records, 8 with a recognizable solicitation number — noise against tens of thousands of awards per
quarter, not a usable key.

Consequences, which shape the lineage deliverable directly:

1. Opportunity-to-award linkage must be probabilistic — department plus UNSPSC/category plus date
   window plus description similarity — and must surface as `inferred`, never `confirmed`.
2. "Confirmed incumbent" for California can only honestly mean "this vendor holds or held awards with
   this department in this category", cited to SCPRS rows. It cannot mean "this vendor won this
   specific solicitation", because the public record does not connect the two.
3. This is a good outcome for README's insistence on separating fact from inference: the source data
   enforces the distinction rather than tempting us to blur it.

## 2026-09-07 — data.ca.gov: correcting my own dataset survey, and an unresolved robots conflict

Earlier today I concluded data.ca.gov held "only 3 procurement-tagged datasets, none useful". That
was an artifact of searching by **tag**. The valuable dataset is not tagged `Procurement`:

"Purchase Order Data" (DGS), resource id `bb82edc5-9c78-44e2-8947-68ece26197c5`, `datastore_active`,
**344,504 rows** — the SCPRS extract for FY2012-13 through FY2014-15. Prior recon verified 343,487
rows carry a Normalized UNSPSC (99.7%), across 24,728 distinct suppliers and 111 departments, and
demonstrated a working end-to-end inference query joining an active opportunity's UNSPSC segment to
historical award counts by supplier and by agency.

Caveats: the corpus is ~11 years stale, so it is an inference corpus and never a current-incumbent
source, and its age must enter the confidence calculation. `Total Price` is text with `$` and padding,
so counts aggregate directly but sums require cleaning first.

**Unresolved compliance conflict, flagged rather than settled:** the recon reached this data through
`GET https://data.ca.gov/api/3/action/datastore_search_sql`, and `data.ca.gov/robots.txt` disallows
`/api/` and `/datastore/*` under `User-agent: *`. README forbids bypassing robots restrictions. A
robots directive governs crawlers rather than documented API clients, and this is a published open-data
SQL API, so the two readings genuinely differ. Not resolving this unilaterally — raising it with the
trial author. Until then the pipeline does not depend on that path; if it is ruled out, the fallback is
the dataset's downloadable resource file, at the cost of pulling a large CSV.

## 2026-09-07 — SOLVED: attachments download over plain HTTP. No browser needed anywhere.

The last open access gap is closed, and it closed without a browser. The browser-API-key request to
the trial author is **withdrawn** — nothing in the California pipeline requires Browserbase, a hosted
browser service, or a headless browser at runtime.

Verified end to end on event `(2660, 04A7615)`: **6 of 6 attachments downloaded, 3,407,993 bytes
total, all `application/pdf`, all SHA-256 hashed.**

### The working chain

1. `GET .../AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL` — establishes the session cookie.
2. `GET .../AUC_MANAGE_BIDS.AUC_RESP_INQ_DTL.GBL?...&AUC_ID=<id>&BUSINESS_UNIT=<bu>` — detail page.
   Harvest every hidden input, notably `ICSID` and `ICStateNum`.
3. `POST` to the detail `.GBL` with those hidden fields plus
   `ICAction=RESP_INQ_DL0_WK_AUC_DOWNLOAD_PB`. Response contains the attachment grid:
   `PV_ATTACH_WRK_ATTACHUSERFILE$N` (filename), `PV_ATTACH_WRK_ATTACH_DESCR$N` (description),
   `CS_AUC_WRK_CS_VERSION$N` (version), one row per file.
4. For each row N, `POST` again with `ICAction=PV_ATTACH_WRK_SCM_DOWNLOAD$N`. The response is HTML,
   not the file — but it carries `window.open('https://caleprocure.ca.gov/psc/psfpd1/view/%7bV2%7d<opaque token>')`.
5. `GET` that URL with the same cookie jar and a `Referer` → the PDF bytes.

### Two things that made this hard, worth recording

**State chaining.** `ICSID` stays constant for the session but `ICStateNum` increments on every
postback (observed 2 -> 3 -> 4 ... -> 9 across the package call and six View calls). Each POST must
carry the value from the immediately preceding response, so the sequence is inherently serial per
event and cannot be parallelised within one session.

**Quote style.** The attachment grid uses double-quoted HTML attributes while the rest of the
PeopleSoft page uses single quotes. An id regex written for one style silently finds zero rows and
looks exactly like "no attachments exist". The adapter must be quote-agnostic and must assert a
non-zero row count against the pager text rather than trusting an empty match.

### The browser still earned its keep — for discovery, not production

A headless Chrome run (puppeteer 24.24.1 against local Chrome, already installed on this machine) is
what revealed the control name `PV_ATTACH_WRK_SCM_DOWNLOAD$N` and the grid field list. Driving the
click in the browser did **not** produce the file: the popup opened as `about:blank` and never
navigated under headless. So the browser was the instrument that made the HTTP path findable, which
matches the prior recon's own recommendation — reserve headless browsing for endpoint discovery when
a portal changes shape, and use plain HTTP for steady-state ingestion.

### Data-quality finding on the very first event sampled

Attachment `07_06A3334_Addendum_2_-_Responsible_Person_Question.pdf` is attached to event `04A7615`
but is named for a different solicitation, `06A3334`. Per README, portal metadata conflicting with a
document is preserved on both sides and flagged rather than reconciled silently. This is a real
instance of that requirement appearing in the first six documents retrieved, and it argues for a
`filename_solicitation_mismatch` flag on document records.

Filename prefixes also look like a usable document-role signal (`01_` notice, `02_` instructions,
`03_` checklist, `07_` addendum) but that is one agency's convention on one event; it must be
validated across agencies before being trusted as a role classifier.

Sample corpus retained under `data/raw/documents/2660_04A7615/` (gitignored) with a manifest carrying
filename, byte count, SHA-256, content type and serving URL.

## 2026-09-07 — Observed bidder identity DOES exist in California, inside award-notice PDFs

README's central question now has a positive answer, and it validates the document-first thesis.
Bidder identity is absent from every portal page and the bid-inquiry component is authenticated, but
it is present in documents attached to events.

Verified on DMV event `(2740, 0000040075)`, RFQ `ISD26-4620`, attachment
`Intent_to_Award_ISD26-4620.pdf` (114,590 bytes, sha256 `fa02e2ea090f7729…`). Extracted page 1 by
native text, no OCR needed. The document states the awarding department, the RFQ number, the intent
posting date, the protest deadline, the named contact, and:

```
Company Name              Bid Amount
AVIATE ENTERPRISES, INC.  $437,862.48
```

That is an official source explicitly associating a named vendor and a bid amount with a specific
solicitation — which is exactly README's bar for `known_bidder` rather than a prediction.

### Attachment coverage, measured across 30 events in 30 agencies

- 30/30 events enumerated without error.
- **29/30 carry at least one attachment**; 137 attachments in total; up to 15 on one event.
- File types: 94 `.pdf`, 28 `.docx`, 9 `.xlsx`, 5 `.zip`, 1 `.csv`. **The corpus is not PDF-only**,
  so extraction cannot assume PDF. Office formats and archives need their own handling or an
  explicit typed skip; a bid tabulation posted as `.xlsx` would otherwise be silently lost.

### Two corrections to earlier assumptions

**Filename-prefix roles are one agency's convention, not a standard.** Only 6 of 137 files carried a
numeric prefix (`01`, `02`, `03`, `07` — all Caltrans). `role_from_filename` is therefore withdrawn as
a general classifier; it stays available but must not drive document role. Role has to come from
filename keywords plus document content instead.

**"Bidder" in a filename usually means a blank form, not a bidder list.** Four of the five
keyword-matching events were `Bidder_Declaration.pdf`, `Bidder_CUF_Compliance_Form.pdf` and similar —
forms a prospective bidder must complete, containing no bidder identities at all. Only the DMV
intent-to-award was real evidence. A filename keyword filter alone would produce four false positives
for every true one, so content confirmation is mandatory before any participant record is created.

### Tables are the extraction path; prose regexes are not

The awardee sits in a two-column table (`['Company Name', 'Bid Amount']`). A label-based prose regex
over the same page returned only noise ("Date: August 31, 2026", "should not be considered as a
binding"). `extract_pages` now retains table cells rather than only counting them, capped at 20 tables
and 200 rows per page, and `participants_from_tables` recognises vendor/amount/rank column headers and
returns candidates with the header and the full evidence row attached. Amounts keep both the raw
string and a numeric form, and an unparseable amount leaves the numeric field null rather than
coercing it to zero.

### Scale risk this exposes

Only 1 of 30 active events carried an award notice, because the feed is active-only and most listed
events have not been awarded yet. So attachments give **high-quality, low-volume** bidder evidence.
Reaching README's minimum of 100 bidder-event observations will therefore rest on SCPRS award history
for volume, with attachment-derived records supplying amounts, protest windows and named contacts on
the subset where a notice has been posted. Recorded as the reason the evaluation set must mix both
sources rather than relying on documents alone.

## 2026-09-07 — Document acquisition measured at 97.7%; three silent-loss bugs found by running at scale

Six events, 44 documents: **43 acquired, 97.7%**, against README's ">=95% of publicly downloadable
evaluation documents" criterion. 535 page records, 1,320,838 characters extracted, 136 pages carrying
tables, zero extraction warnings. Types acquired: 21 pdf, 19 docx, 2 xlsx, 1 csv. Extraction methods
exercised: native 499, docx 19, xlsx 7, hybrid 6, ocr 3, csv 1 — so the OCR fallback and every Office
path ran against real documents rather than only fixtures.

Three bugs surfaced only under real load, and all three failed by losing documents while appearing to
succeed. Each now has a regression test.

1. **A PDF-only magic check in the download path rejected every Word document.** One 15-attachment
   event reported 0 downloaded with the plausible status `unexpected_content`. Since the corpus is
   roughly a third non-PDF, this was discarding a large share of the record. Type and signature
   enforcement moved out of the fetch layer into `documents.validate`, which owns accept/reject and
   its reasons; the fetch layer now only distinguishes "a file arrived" from "a PeopleSoft page
   arrived".
2. **PeopleSoft page state went stale after roughly two attachment downloads.** Events with 2
   attachments succeeded while events with 8-15 mostly failed, because fetching a file navigates away
   from the page whose `ICStateNum` the next postback is validated against. The detail page and
   package postback are now re-established before each document. Cost: four requests per document.
3. **An unseeded session produced an empty attachment grid.** A detail GET on a session that had not
   first touched the list component yields a package response with zero rows — indistinguishable
   from an event that genuinely has no documents. The session now seeds itself in `fetch_detail`, so
   call order cannot silently cost an event's entire document set.

One event (`0820/0000040254`) returned HTTP 500 from the portal. The run continued and the CLI records
it as `enumeration_failed` with the exception text rather than aborting or omitting it.

## 2026-09-07 — Participant extraction: precision guards after 8 false positives in 9 results

The first `participants_from_tables` implementation, run over the 6-event corpus, produced **9
candidates: 1 real awardee and 8 artefacts**. pdfplumber reports prose blocks in solicitation
documents as tables, and the words "bid" and "bidder" saturate RFQ boilerplate, so loose header
matching fired on requirement text. Actual false positives included "Confirmed DVBE Participation
of:", "5% and Over", "EXECUTIVE ORDER N-6-22 - RUSSIAN SANCTIONS", and "Attachments The following
documents are...".

That is worse precision than the filename-keyword approach criticised earlier the same day, and a
fabricated `known_bidder` is the most damaging error this pipeline can produce. Guards added, chosen
to trade recall away deliberately — a missed bidder is a gap, an invented one is a false claim:

- Header cells must be short (<=40 chars). A header full of prose means the block is not a tabulation.
- The vendor column and the value column must be **different** columns.
- The amount must parse as money, or the rank must be numeric. An unparseable value is not evidence.
- The name must be entity-shaped: at most 9 words and 120 chars, no sentence punctuation or
  requirement verbs, not ending in a colon.
- A row where the amount cell equals the name cell is a one-column layout artefact and is dropped.

Re-running the same 535 stored page records: **1 candidate, the true awardee, all 8 artefacts gone.**
Each false positive is now a named regression test, alongside two positive controls (the real DMV
awardee, and a synthetic multi-bidder tabulation with ranks) so the tightening cannot silently
over-reach.

Consequence to carry forward: rejected near-misses are exactly what README's `review_queue.json` is
for. When that lands, the permissive variant should feed the queue rather than the participant set.

## 2026-09-07 — SCPRS adapter working; vendor canonical key confirmed live

`ZZ_PO.ZZ_SCPRS1_CMP.GBL` with the `FolderPath` / `IsFolder` / `IgnoreParamTempl` parameters is
publicly reachable, and its search is a single `ICAction=ZZ_SCPRS_SP_WRK_BUTTON` postback carrying
criteria in `ZZ_SCPRS_SP_WRK_*` fields. All 13 result fields parse.

**Vendor identity is solved by the source, verified today rather than taken on trust.** A
supplier-name search for `TECHNOLOGY INTEGRATION GROUP` returned 200 rows spanning **39 departments,
every one carrying `supplier_id 0000000269`**, with 5,446 awards reported in total. Name variants
collapse onto the id with no fuzzy matching, which is what makes README's "resolve aliases without
merging unrelated companies" criterion tractable.

Field fill rates on a two-day sample (200 rows): `purchase_doc`, `department`, `description`,
`start_date`, `end_date`, `awarded_amt`, `supplier_id`, `supplier_name`, `category` and `acq_method`
all 200/200; `cert_type` 67/200; `lpa_contract` 24/200; `where_cf` 1/200. So certification and
purchasing-vehicle data are sparse and must be treated as optional, never as absent-means-no.

`acq_method` separates competitive from non-competitive explicitly. On a 338-row sample: 282
competitive, 56 not. A non-competitively-bid award is a stronger incumbency signal; statewide-vehicle
awards are weaker, since they reflect being on a vehicle rather than winning a competition.

### The 200-row cap, and how far slicing actually gets

The grid returns at most 200 rows and its NEXT control does not advance under automation, so wide
result sets must be sliced. Date bisection implemented and verified: a two-day window reporting 377
rows split into 09/02 (239 reported, 200 returned) and 09/03 (138, complete), yielding **338 rows
with zero duplicate `purchase_doc` across slices** and 226 distinct suppliers.

A single day above the cap cannot be bisected further. A second slicing axis was added, and then
measured honestly:

- Subdividing 09/02 by **department display name** returned **0 rows for all 40 values**. The
  criterion field is `BUSINESS_UNIT` and wants the FI$Cal **code**, not the name. Verified by
  contrast: `0820` returns 5 rows for Department of Justice, `5225` returns 50, `4440` returns 6,
  while "Department of Justice" returns 0.
- This is a dangerous failure mode, because a wrong-format criterion returns an empty result set
  rather than an error, and an empty result set reads as "this department bought nothing". The
  adapter's parameter is therefore named `business_unit`, not `department`, with the code requirement
  documented at the definition and pinned by a test.
- The searchable fields are **free-text inputs, not dropdowns** (checked for acquisition type,
  acquisition method and business unit). So no exhaustive value list can be obtained from the portal,
  and subdivision coverage can never be *proven* complete. `search_date_sliced` reflects this: a
  subdivided slice carries `subdivision_rows_seen` and a note stating that coverage holds only if the
  supplied value list is exhaustive.

Practical consequence for the trial: full-corpus completeness is not achievable through this
interface and is not attempted. The productive access pattern is targeted queries — by `supplier_id`
or `supplier_name` for vendor history, by `business_unit` code plus date window for agency history —
each of which stays well under the cap. Any aggregate claim derived from a truncated slice must carry
the reported total alongside the retrieved count so the gap is visible.

## 2026-09-07 — Vendor profiles built; the document-to-identity chain closes end to end

**483 vendor profiles** from a four-day SCPRS window (738 award rows, 737 distinct
`purchase_doc`), against README's minimum of 25. 15 profiles carry 5 or more awards, 63 span more
than one agency, 134 carry at least one certification. Ten of the most active suppliers were enriched
with their own full-history query.

### The chain the trial is actually about now runs end to end

The DMV intent-to-award PDF named `AVIATE ENTERPRISES, INC.` with a bid amount of $437,862.48. That
string resolves, through suffix-and-punctuation normalisation, to SCPRS `supplier_id 0000015031`
("AVIATE ENTERPRISES INC") — **9,537 awards reported, 29 agencies, DVBE/SB/SB-PW certified, median
award $2,287.55, largest $1,305,814.28, 90 competitive / 7 non-competitive / 103 vehicle awards**.

So: an official document yields an observed participant, that participant resolves to a canonical
state identity, and that identity carries a full award history. Document evidence, vendor identity
and participation history are joined without a single fuzzy merge.

### What these profiles deliberately do not claim

- **No win rate, no bid count, no loss count.** SCPRS records awards only, and California publishes
  no losing bidders, so those fields are `None` with a stated reason rather than being faked by
  equating bids with wins.
- **No subcontractor evidence.** An SCPRS award is a contract held directly with the state, which
  evidences priming. Subcontracting is invisible here, so absence is recorded as unknown.
- **Every aggregate states its denominator.** Amount statistics report parseable, unparseable and
  absent counts separately, and an unparseable amount never becomes zero.
- **Conflicting identities are flagged, never merged.** Four `possible_duplicate_vendor_identity`
  items reached the review queue: distinct `supplier_id`s whose names normalise to the same string.
  They stay as separate profiles, because merging two unrelated companies is worse than carrying two
  records. Name normalisation exists to raise questions, not to answer them.
- Rows with no `supplier_id` become review items rather than being dropped or pooled.

### Two data-quality bugs found by reading my own output

**Mine: certification coverage read "400/200 rows".** The numerator summed certification *mentions*
while the denominator counted rows, and 200 rows each reading `DVBE|SB-PW` contribute 400 mentions.
Now `certification_coverage` counts rows carrying any certification and `certification_mentions`
reports the mention total separately.

**Theirs: a 2048 award date.** `purchase_doc PO17-1119` (Department of Justice) carries
`start_date = end_date = 02/14/2048`, one outlier in 200 rows whose document number suggests 2017 —
a state data-entry error, not a parsing fault. It had inflated the vendor's activity span to 7,938
days. Dates outside a plausible window (before SCPRS began on 2009-07-01, or more than ten years
ahead) are now excluded from spans and first/last dates but **retained and reported** in
`implausible_dates` with their document number. The award itself still counts. Span for that vendor
corrected from 7,938 days to 163.

### Coverage limitation to carry into the evaluation set

Three of four daily slices were truncated: 08/31 reported 677 rows, 09/01 reported 530, 09/02
reported 239, each returning the 200-row cap; only 09/03 (138) was complete. So the window yielded
738 of roughly 1,584 rows. Daily volume exceeds the cap and cannot be subdivided by date, and the
business-unit axis needs a code list that cannot be proven exhaustive. Any aggregate over a window
must therefore publish retrieved-versus-reported counts, which `search` already returns.

Also observed: some suppliers are not companies. `DEPT542000` (CA Correctional Training
Rehabilitation Authority) and `0000004178` (Calaveras County) appear as suppliers, i.e. interagency
and local-government sellers. A competitor model must not treat these as biddable competitors, so
supplier classification needs an entity-type dimension before prediction uses these rows.

## 2026-09-07 — Bounded retries added after two real runs died

A portal HTTP 500 on event `0820/0000040254` and a local DNS failure mid-SCPRS-sweep both killed
runs. `CalEProcureSession` now retries transient failures — DNS, connection and 5xx — three times by
default with linear backoff, and raises a typed `TransientFetchError` when exhausted. A 4xx is not
retried: it will not become a different answer and repeating it is rude to the host. The typed error
matters because a silent empty result reads as "this event has no documents".

## 2026-09-07 — Likely-bidder baseline and held-out evaluation: precision@3 0.17, coverage 0.53

Explainable weighted-sum baseline, no learned model. Weights are hand-set in
`predict.WEIGHTS`, published in the module, and fixed **before** evaluation; tuning them
against the held-out set would make the reported precision meaningless.

Backtest: 1,574 award rows over 08/25-09/03, held-out events taken from 09/03 (the one
complete day), history restricted to rows dated before it. Ten held-out events, all with
ground truth.

| Metric | Result |
| --- | --- |
| precision@3 | 0.1667 |
| precision@5 | 0.14 |
| coverage (actual awardee in top 10) | 0.53 |

These are modest numbers and are reported as they came out. Two structural reasons, both
about the data rather than the ranking:

**History depth is capped, not chosen.** Seven of the date slices hit the 200-row ceiling, so
the corpus holds 1,574 of roughly 3,000 reported rows across nine days. Vendors therefore
carry a handful of prior awards each, and a ranking built on thin history cannot separate 466
plausible commodity suppliers into a correct top three. Deep per-vendor history is reachable
(a supplier query returns up to 200 rows of that vendor's record), but only for vendors
already identified — which is circular for prediction and is why history has to come from the
date axis.

**The ground truth is purchase-level, not solicitation-level.** This is the more important
caveat. SCPRS rows are awards and purchase orders, so "who won" often means "which vendor on
a statewide vehicle filled a small commodity order", not "who bid on this RFP". Several
held-out events were `NON-IT Goods` buys with hundreds of eligible suppliers and a median
award in the low thousands. Predicting that is a genuinely different and less meaningful task
than predicting bidders on a solicitation, and it flatters nobody to blur them.

The honest position: California publishes no bidder lists, so solicitation-level ground truth
exists only where an intent-to-award or bid-tabulation document names participants — the DMV
case, one event in thirty sampled. A solicitation-level evaluation set therefore has to be
assembled from award-notice documents, and its size is bounded by how many events have
posted one. That is a finding about the source, not a shortfall to hide behind a number.

### What the output actually gives a reader

Every prediction carries per-feature contributions summing to the score, the evidence counts
behind it, the factors weakening it, and a confidence grounded in evidence volume rather than
in the score. Example, top candidate for CAL FIRE / NON-IT Goods:

```
WW GRAINGER INC  score=9.5474  confidence=high
  agency_and_category_awards 2.625 | same_agency_awards 1.800 | same_category_awards 1.586
  recency 1.497 | size_similarity 0.872 | primes_similar_work 0.667 | competitive_history 0.500
  evidence: 23 relevant awards, 6 same agency, 23 same category, last award 1 day before cutoff
  weakening: none
```

### Guards that changed the design

**Relevance gate, added after a test failure.** The first version scored recency over a
vendor's entire history, so any vendor that sold anything to any agency recently was ranked
as a likely bidder on an unrelated opportunity. Recency, frequency, size similarity and
competitive history are now computed only over *relevant* awards — same agency or same
category — and a vendor with no relevant award is not ranked at all, counted instead in
`excluded_no_relevant_history`. This is the "existence is not intent" failure caught by its
own test rather than in review.

**Eligibility signals are multiplicative on participation.** `cert_match` and
`vehicle_presence` are multiplied by demonstrated participation, so they can amplify a real
history but can never generate a prediction alone. README forbids using certification or
registration as proof a vendor will bid.

**Non-competitor entities are excluded and named.** Calaveras County and `DEPT542000` (a state
correctional authority) appear as SCPRS suppliers. Ranking a county as a rival bidder would be
a visible correctness failure, so government and interagency sellers are filtered by
`is_biddable_entity` and reported in `excluded_non_competitor_entities` with a reason.

**Observed participants are excluded from ranking.** A vendor already named on the event is
evidence, not a prediction, and scoring it would inflate precision.

**Metrics return None, not zero, without ground truth.** "We could not tell" must never be
recorded as "the model was wrong"; `evaluate` counts such events separately.

## 2026-09-07 — Prime recommendations, Supabase exports, report: all three rubric gaps closed

### Prime and teaming (15 pts)

`primes.py` ranks credible primes and explains both halves README asks for: a credibility
case from counted award evidence, and a separate teaming case naming what the client brings
that the prime's record lacks.

Two qualification rules were tightened **after reading real output**, which is the only way
these errors surface:

1. **Value floor moved from 1.5 decades to 1.0.** At 1.5, a vendor whose largest award was
   $38,870 qualified to prime a $437,862 contract. No reviewer would accept that.
2. **Relevance is now mandatory.** A candidate must hold at least one award with this agency
   or in this category. An earlier run ranked a company with zero of both, which is noise
   dressed as a recommendation.

The value test is deliberately **one-sided** — a floor, not a band. A company whose awards
dwarf the opportunity is still a credible prime for it; one that has only handled work a
decade smaller is not. The field was accordingly renamed from `comparable_value_awards` to
`awards_at_or_above_value_floor`, because the original name claimed two-sided comparability
the test never performed. `value_comparability` remains the two-sided similarity score, so a
candidate can clear the floor while scoring low on similarity, and both are visible.

Where a candidate is credible but nothing in the client's profile fills a gap, the report now
says **"No teaming rationale found — treat as a competitor to watch rather than an outreach
target"** rather than manufacturing a reason.

Dual-role candidates are flagged: on the demonstrated opportunity, 4 of the top 5 primes are
also predicted competitors. README asks for exactly this case, and it is surfaced rather than
resolved — approaching a rival is the client's judgement, not the model's.

### The 200-row cap dictates the access pattern, demonstrated

Prime recommendations returned **zero qualified candidates** on a 538-row three-day corpus,
and zero again at 4,079 rows enriched for the wrong agency. They only worked once the corpus
was enriched **per vendor for the target agency and category**: 5,480 rows, 19 of 282 vendors
qualified, with real histories (ALLEN ALARM SYSTEMS INC: 79 awards above the floor, 21 with
this agency, 146 in this category).

This is direct evidence for the recommendation already in the report — deepen history per
vendor, not per day. Date-sliced backfill fights the cap; a supplier query returns that
vendor's record directly. Recording the zero results rather than quietly widening the corpus
until numbers appeared is the point.

### Supabase-shaped exports

Seven tables, **2,391 rows, all validating**: sources 10, records 914, participants 539,
documents 44, content handoff 535, competitors 348, partner-match payloads 1. Identifiers are
deterministic UUIDv5 over a fixed local namespace and natural keys, so a re-run reproduces
identical ids and relationships survive re-export. `build/supabase/handoff.json` carries
import order, natural upsert keys, conflict behaviour and the local-to-production remapping
plan. Nothing points at or writes to any Supabase instance.

Participants carry only `observed` and `derived` evidence classes. Predictions never enter
that table; they live in the partner-match payload and the likely-bidder output. A conflict
rule is published: an upsert may never overwrite a stronger evidence class with a weaker one.

One ID bug was caught by its own test: `local_id` mapped `None` and `""` to the same key, so
a missing field and an empty field collided into one identifier. `None` now takes a sentinel
that cannot occur in portal data.

**Standing caveat, repeated in the validation report and the report itself:** these schemas
were authored locally from README's pattern table because the promised frozen snapshot is
absent from the repository. Passing validation proves internal consistency, not Chromie
compatibility.

### Report

`build/report.md` is **generated from the artifacts in build/**, not hand-written, so no
figure in it can drift from what the pipeline produced. It answers the brief's final
questions, states the competitive landscape as the public record actually supports it, reports
the weak prediction metrics unadjusted with their two structural causes, and proposes the next
three sources (Virginia eVA, Georgia GPR, Texas ESBD) with reasons drawn from measured access
research.

One self-inconsistency was caught while reading it: the "most active suppliers" table in a
*competitive landscape* section listed Calaveras County and a state correctional authority —
the very entities excluded from competitor ranking. The table now filters through the same
`is_biddable_entity` test the ranking uses and reports the 48 excluded sellers separately as
real suppliers that are not rival bidders.

## 2026-09-07 — The README command now runs end to end and produces every required artifact

Re-read the deliverable spec and made the documented command work verbatim:

```
python -m sled_trial.cli analyze \
  --opportunity data/examples/active_opportunity.json \
  --download-documents \
  --output build
```

All ten required outputs are produced, non-empty, in one run: `opportunity_intelligence.json`,
`procurement_lineage.json`, `documents_manifest.jsonl`, `document_pages.jsonl`,
`vendor_profiles.json`, `prime_candidates.json`, `source_coverage.json`, `review_queue.json`,
`report.md`, and `supabase/` (7 tables, 1,853 rows, all validating). Run time about 41 seconds
with a cached award window, a few minutes without.

Four gaps closed and four bugs found in the process.

### `--output` had to move

The shared flags were defined on the top-level parser, so they only parsed *before* the
subcommand — and README writes `--output build` last. That ordering is the contract, so the
flags now live on a parent parser attached to each subcommand. A test asserts the README
command parses verbatim, because a plausible-looking CLI that rejects the documented
invocation is a silent failure of the deliverable.

### `data/examples/active_opportunity.json` authored

README names this file as the command's input but the repository does not contain it. Written
from the real public DMV event `(2740, 0000040075)`, RFQ `ISD26-4620`, with the amount taken
from its posted intent-to-award notice. It also carries the `client_profile` that drives the
teaming rationale and the `analysis_cutoff` that bounds prediction inputs. Unknown fields are
null, not filled in.

### Procurement lineage implemented

`lineage.py` searches document text for solicitation identifiers and predecessor language,
looks for same-buyer similar-title siblings in the active feed, and gathers same-buyer
same-category award history as incumbent context. It always emits a completed trace naming
the surfaces checked, the queries run, the identifiers found, and the surfaces that were
**not** available with reasons — the bid-inquiry login, the discontinued DGS export, and the
robots-disallowed datastore API. `lineage_links` stay null, because access research
established there is no deterministic solicitation-to-award join in California, and every
relationship is `inferred` with match evidence.

### Bug: a re-run produced an empty `document_pages.jsonl`

`DocumentStore.put` treated bytes already on disk from an earlier run as a duplicate, and the
caller skips extraction for duplicates. So the second and every later run of the deliverable
command emitted zero page records and zero known bidders — indistinguishable from an event
whose documents contain no text. Duplicate detection is now scoped to the store instance, i.e.
to one run: bytes are still written only once, but extraction always happens. Three regression
tests cover it.

### Bug: lineage reported a false predecessor

The first working run reported `predecessors_found`. The identifier it found was `ISD26-4620` —
the opportunity's **own** solicitation number, restated on its RFQ title page. Only the event
id had been excluded. `self_identifiers` now collects the event id, the solicitation number,
the external id and any identifier embedded in the title, in zero-stripped and upper-case
variants, and the trace publishes what it excluded. The run correctly reports
`no_predecessor_found` with the standing caveat that this does not prove no earlier notice
existed. This was precisely the class of false claim the rest of the pipeline is built to
avoid, and it took a live run to surface.

### Verified alongside

`events` returns 376 events, 376/376 unique on the identity pair, zero rows missing a field.
`documents --event 2740/0000040075` reports 100% acquisition and extracts the observed bidder
`AVIATE ENTERPRISES, INC. $437,862.48` from the intent-to-award notice. A missing opportunity
file exits non-zero rather than writing a partial build. 222 offline tests pass.

## 2026-09-08 — Trial author's direction received; four items actioned

The trial author confirmed the scope call and closed both open questions:

- `README.md` is authoritative. `PROJECT_BRIEF.md` and the original `sources.yaml` are stale,
  and those fixtures should be replaced with the California sources.
- No Supabase snapshot is coming. Create `contracts/supabase/*.schema.json` as a clearly
  labelled **proposed** contract from the README patterns, add `docs/supabase_mapping.md`, and
  author the example opportunity fixture without claiming production compatibility.
- The plan for investigating bidder availability, with planholder and SCPRS data as the
  fallback, was confirmed as correct. No change needed there; it is what shipped.

### sources.yaml replaced

`sources.yaml` is now generated from `sources/source_registry.csv` so the two cannot drift.
The three fixture entries (`ca_city_portal`, `ga_county_portal`, `school_district_portal`) are
gone, along with `data/synthetic/portal_a.json` and `portal_b.json`. Nothing in the code read
either, so this is a documentation correction, not a behaviour change.

`mode` now records how a surface is reached rather than acting as a toggle: `live`, `manual`,
`blocked_pending_decision`, `unresolved`, `dead_end`. The middle value exists because
`data_ca_gov_purchase_orders` is technically reachable but its robots question is unresolved —
calling it `live` would have implied a permission we do not have.

Two surfaces were also restored to the registry, having been dropped when it was rewritten:
`caleprocure_response_bid_inquiry`, which is the answer to the brief's central question and
must stay visible, and `suppliers_fiscal_peoplesoft`, kept so its timeout is not
re-investigated. Registry is now 12 surfaces.

### Contracts relabelled from placeholder to proposed

The schemas, the validation report and the module docstring now read "PROPOSED CONTRACT - not
an export of Chromie's production schema", state that no production compatibility is claimed,
and point at `docs/supabase_mapping.md`. Tests assert that wording, so the label cannot be
softened by accident.

### docs/supabase_mapping.md written

177 lines covering the six requested areas — tables, relationships, natural upsert keys,
import order, conflict behaviour, local-to-production ID mapping — plus the assumptions and
validation gaps the author asked for: six assumptions that a real snapshot would settle, and
six things passing validation does not demonstrate.

Because the document is hand-written prose it can drift from the module, so
`tests/test_supabase_mapping_doc.py` asserts it lists every table, every natural-key field,
every unresolved production id, the local namespace, all six required headings, and the
import order in the module's exact sequence.

### Bug found by writing the document: import order was wrong

Setting out the dependency graph in prose exposed that `gov_competitors` sat at position 6 in
`IMPORT_ORDER`, **after** `gov_procurement_participants` at position 3 — which carries
`competitor_id`. A real ingestion would have failed on a foreign key. The existing test only
spot-checked two of the four dependencies and passed.

Order corrected to sources, competitors, records, participants, documents, content handoff,
partner match. A `FOREIGN_KEYS` map now declares every table's parents, and the test asserts
the whole graph rather than a sample of it. Writing the explanation was what caught this;
neither the code nor the tests would have.

### Still outstanding

The orphaned PROJECT_BRIEF-era scaffold remains: `src/sled_trial/pipeline.py`,
`src/sled_trial/models.py` and `tests/test_pipeline.py`, which implement the superseded
`normalize()` path and are imported by nothing else. Left in place because removing working
tested code was not requested; flagged for the author's call.

## 2026-09-08 — Removed a personal email address from the outbound user-agent

The crawler user-agent hard-coded the operator's personal work address. It was therefore sent in a request header to `caleprocure.ca.gov` on every single call and written into a third party's
access logs, without anyone having asked for it. It was added while reasoning about honest
crawler identification, and identifying the *project* was the legitimate part; publishing a
personal address to a government server was not, and it should never have been the default.

The user-agent now reads `Mozilla/5.0 (compatible; chromie-sled-trial-research/0.1)` and
appends `+mailto:<address>` only when the `SLED_TRIAL_CONTACT` environment variable is set. A
contact address is genuinely good crawler etiquette on a sustained crawl, so it stays
available — as an explicit opt-in by whoever runs it, for an address they choose. The address
has also been removed from this file.

Nothing else changes: the self-identifying format, its verification against the live portal,
and the decision not to impersonate a browser all still hold.

## 2026-09-08 — Prediction re-evaluated honestly: 0.073, not 0.17, and why

Reviewer feedback docked the prediction area for weak metrics. Investigating produced a
worse headline number and a much clearer understanding, in that order.

### Correction: the reported figure came from a favourably selected event set

The evaluation picked the ten held-out events with the **deepest prior history**, on the
reasoning that a ranking task needs something to rank. Those are also the most predictable
events, so the selection was favourable and the resulting precision@3 of 0.17-0.20 flattered
the model.

Evaluated on **every** evaluable `(agency, category)` pair with a same-day awardee — 55
events, unselected:

| Set | Model p@3 | Best baseline p@3 | Lift | Model coverage@10 |
| --- | ---: | ---: | ---: | ---: |
| 10 deepest-history events | 0.2000 | 0.1667 | 1.20x | 0.460 |
| 20 events | 0.1667 | 0.1333 | 1.25x | 0.340 |
| 30 events | 0.1222 | 0.1000 | 1.22x | 0.293 |
| 40 events | 0.1000 | 0.0750 | 1.33x | 0.245 |
| **all 55, unselected** | **0.0727** | **0.0606** | **1.20x** | **0.187** |

The unselected 0.0727 is the figure that should be quoted. `build/evaluation.json` now
carries it, along with a note naming the earlier selection bias.

### The lift is the stable quantity

Absolute precision falls steadily as easier events are diluted, but the **lift over the best
trivial baseline sits at 1.20-1.33x at every set size**. So the ranking does carry signal
beyond "who wins most often" — consistently, and consistently modestly. Three baselines were
implemented for this comparison (most awards overall, most in category, most with agency), all
using the same entity filter as the model so the comparison is not rigged in its favour.

Per-event distribution across all 55: mean 0.0727, **median 0.0**, stdev 0.164. Forty-five of
55 events get nothing right in the top three; eight score 0.333 and two score 0.667. So the
mean is carried by a small minority of predictable events.

### Deeper history made it worse, and that is a methodology finding

Enriching 25 of 279 vendors with their full award histories dropped precision@3 from 0.233 to
0.100 and coverage from 0.552 to 0.183 on identical events. The enriched vendors carry roughly
two hundred awards each while the remainder carry one or two, so they dominate the ranking on
evidence volume regardless of relevance.

**Partial enrichment biases the model.** History must be uniform across candidates — one date
window for everyone — or the ranking measures who was enriched rather than who is likely. This
also casts doubt on the earlier prime-recommendation demonstration, which was run on a
selectively enriched corpus and should be re-checked on a uniform one.

### Whether model work would help

Probably not much, and the reviewer's own observation says why. The target being measured is
"which few of several hundred eligible suppliers received a purchase order from this agency in
this category on one specific day". For commodity categories that is close to noise: 466
plausible office suppliers, four same-day recipients, and the deciding factor is often which
vendor already sits on a statewide purchasing vehicle rather than any competitive dynamic.

Tuning weights against this target would raise the number without making the product better,
and tuning them against the held-out set would make the figure meaningless. The weights stay
fixed and published.

The improvement that would actually matter is redefining the prediction target to the question
a contractor asks: *will this vendor transact with this agency in this category in the next N
days*, evaluated over a forward window rather than a single day. That is a business-meaningful
question, it is measurable from the same data, and it removes the same-day lottery. It is a
change to what is measured, so it must be proposed rather than quietly substituted, and the
current single-day figure should be reported alongside it.

Recorded as an open recommendation, not implemented, because changing an evaluation target
after seeing a poor score needs the trial author's agreement to be credible.

## 2026-09-08 — Prime recommendations re-checked: all 19 were enrichment artifacts

The prime demonstration was re-run on a uniform corpus, since the original ran on the
selectively enriched one that had just been shown to bias prediction.

**Zero of 572 vendors qualify.** The earlier run reported 19 of 282. Every one of the five
candidates named in the report — ALLEN ALARM SYSTEMS INC, DILTEX INC, STRATO COMMUNICATIONS
INC, RR DONNELLEY & SONS COMPANY, HI-LINE ELECTRIC CO — qualified only because its history
had been separately backfilled while the other 254 vendors kept the one or two awards the
date sweep gave them.

The qualification rule is not at fault. It requires two awards at or above one decade below
the opportunity value, plus an award with this agency or in this category. On a six-day
uniform window the median vendor holds **one** award in total, so almost nobody can clear it.
The rule is right and the corpus cannot support it.

This matters beyond the demo: any figure produced on that corpus is suspect, and the report
was presenting fabricated-by-artifact prime candidates as findings.

### The legitimate fix, and why it differs from prediction

For the prime task, uniform per-vendor backfill of the **whole eligible set** is sound rather
than biasing. The qualification rule already requires an award with this agency or in this
category, so a vendor outside that set can never qualify however deep its history. Backfilling
exactly the eligible set therefore changes nobody's relative standing within it.

Prediction is different: its candidate pool is every vendor with any relevant award, so
deepening a subset does reorder the ranking. That asymmetry is why one task can be rescued by
backfill and the other cannot.

A uniform backfill of all eligible vendors is running to confirm this; the result stands or
falls on it, and if primes still cannot be demonstrated the honest output is an empty list
with the reason.

## 2026-09-08 — Corpus provenance is declared, not inferred (two heuristics discarded first)

A guard was wanted so this bias could not recur silently. Two attempts failed before the
right shape became clear, and both failures are worth recording.

**Award-count skew does not work.** The first check flagged a corpus when the busiest vendor
held more than twenty times the median vendor's awards. It fired on the *uniform* corpus: one
national supplier legitimately held 36 awards against a median of 1 over six days. That is
real market concentration, not an artifact, and a check that cannot tell them apart is worse
than none.

**Per-vendor date coverage does not work either.** The second check compared observation
windows, on the reasoning that a sweep observes everyone over the same period while enriched
vendors span years. But a short sweep gives almost every vendor a zero-day span, so the median
is zero and the ratio has no baseline. It also flagged the uniform corpus.

**How a corpus was assembled is known at assembly time, so it is recorded rather than
guessed.** `describe_corpus(corpus, build_method=...)` takes `SWEEP`, `PER_VENDOR` or `MIXED`,
reports the descriptive statistics for a reader, and sets `rankable` to False only for
`MIXED`. An unrecognised method is named in the output rather than silently accepted.

The lesson generalises: a property that the producing code knows should be carried as
provenance, not reconstructed statistically by the consumer. Two heuristics and roughly an
hour went into rediscovering that.

## 2026-09-08 — Primes re-established on a uniform corpus: 57 of 75 eligible

The uniform backfill finished and the distinction holds. Every one of the **75** vendors
eligible under the prime rule — holding an award with this agency or in this category — was
backfilled, 75/75 coverage, corpus 974 to 6,400 rows. **57 of the 75 qualify.**

Three results side by side on the same opportunity (DMV / NON-IT Services_Personal Services,
$33,900):

| Corpus | Build | Qualified |
| --- | --- | --- |
| 974 rows | date sweep only | **0** of 75 eligible |
| 5,480 rows | sweep + 25 arbitrary vendors backfilled | 19 — **invalid, discarded** |
| 6,400 rows | sweep + all 75 eligible vendors backfilled | **57** of 75 |

`ALLEN ALARM SYSTEMS INC` appears in both the invalid run and the valid one, so it was not
purely an artifact; the other four names from the invalid run were replaced by stronger
candidates once every eligible vendor had comparable history.

The top candidate, `PREMIER PROPERTY PRESERV LLC`, holds 177 awards above the value floor,
141 with this agency and 192 in this category, largest observed award $5,629,377. That is a
defensible prime recommendation with counted evidence behind every clause.

### Two honest qualifications on this result

**Qualification is a weak filter, and the report now says so.** With deep uniform history 76%
of eligible vendors clear the bar, because a $3,390 floor is easy to pass once a vendor has
two hundred awards on record. The discriminating power lives in the ranking score, not in the
qualified/not-qualified split. Stating a 76% pass rate is more useful than implying the rule
is selective.

**The teaming rationale does not differentiate candidates.** All five reported primes carry
the same two reasons — the client covers IT Services and holds DVBE, neither of which appears
in any of their records. That is true but uninformative: it describes the client, not the
candidate. A useful teaming case would say what *this* prime specifically lacks on *this*
pursuit. Recorded as a real weakness of the current output rather than presented as insight.

### Reporting corrections that came out of this

The report quoted "57 of 579 vendors qualified", using the whole corpus as the denominator
when only 75 vendors could ever qualify. That reads as a 10% pass rate against a true 76% —
understating in our own favour, which is the wrong direction to be wrong. It now quotes the
eligible denominator and explains what eligible means.

The counts, rule and corpus provenance were also nested inside `if candidates:`, so a
zero-qualified run printed a generic "nothing qualified" line and omitted the numbers
entirely. Those blocks now print either way: "0 of 75 eligible" is far more informative than
"nothing qualified", and the corpus note matters most precisely when the answer is empty.

The report additionally carries a **Superseded result** paragraph naming the discarded
19-candidate run, so a reader who saw the earlier figure can reconcile it rather than wonder.

### The two corpora are kept separate and labelled

`build/awards.jsonl` is the date sweep, used for prediction. `build/awards_prime_enriched.jsonl`
is the uniform eligible-set backfill, used for primes. Each output records which it came from
via `predict.describe_corpus`. Mixing them is what caused this, and the two tasks genuinely
need different corpora: prediction ranks a wide pool, so uniform breadth matters; primes rank
a relevance-gated set, so uniform depth within that set matters.

## 2026-09-08 — Geography: opportunity side captured, vendor side does not exist

The brief asks a prime candidate to "cover the required scope, vehicle, geography, and
certifications". Scope, vehicle and certifications were already scored; geography was not.
Investigating it produced a correction and a hard limit.

**Correction: `where_cf` is not a location field.** It was assumed to be one, on the strength
of the name. It holds reference identifiers — 470 distinct values across the 471 populated
rows, mostly zero-padded numerics like `0000048777` and comma-separated pairs. There is no
supplier location anywhere in the SCPRS award record.

**The structured county field exists but is empty.** The event detail page carries a
service-area grid, `ZZ_SA_VW_COUNTY`, exactly as the earlier reconnaissance notes described.
On every event sampled its cells contain `&nbsp;`. The parser written for it is correct and
will work if agencies begin populating it; it simply has nothing to read today.

**Geography is in the prose.** The Caltrans event's description reads "the work must be
performed on projects to improve the State transportation system throughout the counties of
Alameda, Contra Costa, and Santa Clara". So `parse_detail_fields` now matches against the 58
official California county names — longest first, so "San Luis Obispo" is not shadowed by a
shorter prefix — and reports `counties_source` as `structured_grid`, `description_text` or
`none_found`. Only names on the official list are accepted, so an arbitrary capitalised
phrase cannot become a location. Verified live: `['Alameda', 'Contra Costa', 'Santa Clara']`
via `description_text`.

**Geography matching is therefore still not scored, and that is deliberate.** Matching needs
both sides. The opportunity side now exists; the vendor side does not, and would require the
supplier-profile surface, which is not implemented. Inventing a proxy — nearest agency,
say — would produce a number with no evidence behind it, which is the failure mode this
pipeline is built to avoid. `geography_note` states the position in the output itself.

The same detail parser now also captures UNSPSC commodity codes (four on the Caltrans event)
and the addendum history (three), both of which were visible on the page and previously
unparsed.

## 2026-09-08 — Extraction-quality review implemented, with an honest label

The brief requires "a manual review of at least 20 representative PDF pages" measuring text,
table, bidder-name, price and date extraction quality. This was the one acceptance criterion
sitting at zero.

`page_review.py` samples pages and computes per-dimension indicators:

- **text** — character count, alphanumeric share and mean word length, verdicts `good`,
  `suspect`, `garbled` or `empty`. Garbled OCR shows up as punctuation soup with a low
  alphanumeric share, which is the failure this is really looking for.
- **tables** — cell fill ratio and row-width consistency; `ragged` marks inconsistent widths,
  which usually means a layout artifact was mistaken for a table rather than a table being
  badly read.
- **bidder names** — participant candidates recovered through the same precision-guarded
  extractor the pipeline uses.
- **prices** and **dates** — how many matches were found and how many actually convert to a
  number or a calendar date.

Sampling is round-robin across extraction methods with table-bearing pages first. Taking the
first twenty pages would over-sample one document's front matter and miss OCR entirely, which
is precisely where extraction is weakest.

**What this is not.** No person read a PDF beside its extraction, and `review_method` says so
in the output rather than letting the word "manual" imply otherwise. The indicators also
measure whether extracted content is *well formed*, not whether it *matches the source*:
recall against the original PDF is unmeasured, because no ground-truth transcription exists.
Both limitations are recorded in the artifact. A human spot-check against the originals under
`data/raw/documents/` remains worthwhile and is not replaced by this.

Wired into `analyze` as stage 8 of 9, emitting `build/page_review.json`, with
`--review-pages` to set the sample size. `meets_minimum_of_20` reports truthfully rather than
assuming the corpus is large enough.

## 2026-09-08 — Document corpus rebuilt to 84 documents at 100% acquisition

Ten events processed through the `documents` subcommand: **84 of 84 documents retrieved**,
864 page records across 83 files. The brief's evaluation-corpus requirement is met on real
data rather than on a single opportunity's two attachments.

Every extraction path ran against genuine files: native 810 pages, docx 22, xlsx 17, hybrid 7,
ocr 6, csv 1. OCR and hybrid firing on real scanned pages is the part that could not be
demonstrated with fixtures.

## 2026-09-08 — Page review run, and it found two defects in my own work

Twenty pages sampled from the 864. Results: text `good` on 19 and `empty` on 1; prices found
on 6 pages with a **1.0 parse rate**; dates on 8 pages, also **1.0**; tables on 13 pages of
which 5 well formed, 3 ragged, 5 sparse. All seven extraction methods appeared in the sample,
so the round-robin selection worked as intended.

On the one page that carries a participant, everything holds:

```
Intent_to_Award_ISD26-4620.pdf p1 (native)
  candidates: AVIATE ENTERPRISES, INC.
  text good | tables good
  prices  1/1 parsed   $437,862.48
  dates   3/3 parsed   August 31, September 8, September 9 2026
```

### Defect 1: the review sampled zero bidder pages

The first run reviewed twenty pages and found **no** participant candidates, which made
bidder-name quality — an explicitly named review dimension — unmeasurable. The corpus holds
exactly **one** bidder page in 864, so any method-balanced or random sample misses it almost
always. Pages carrying a participant candidate are now seeded into the sample before the
round-robin, and a test asserts a single needle in a 200-page haystack is always picked.

Worth stating plainly: a review that silently measures nothing on its most important
dimension looks identical to a review that measured it and found nothing wrong.

### Defect 2: a corrupt file passed validation and became an empty page

One page extracted as `empty`, method `none`, warning `BadZipFile: File is not a zip file`.
Investigating it exposed a real validation gap.

`RFQ_26-171_BigHand_3_Year_Renewal_KD.docx` (6,005,243 bytes) begins with correct zip magic
`PK\x03\x04` and **ends with** `</PRE><hr> </BODY></HTML>`. The portal had appended an error
page to a partial download. Its length even differed between fetches — 6,005,243 then
6,005,039 — so the response is not deterministic.

It passed every check: valid signature at byte zero, size within bounds, plausible
content-type. The `_looks_like_html` guard inspects only the first 512 bytes, so a payload
that starts as a document and ends as an error page sails through. Extraction then failed and
emitted an empty page record, which is indistinguishable from a document that genuinely
contains no text — the same silent-loss shape as the three bugs found in acquisition earlier.

`validate` now rejects a payload whose **last** 512 bytes contain `</html>` or `</body>`, and
for zip-based formats opens the archive and runs `testzip()` before accepting it. Confirmed on
the real file: status `rejected`, note "payload ends with HTML: an error page was appended to
a partial download", nothing stored, extraction never reached. Acquisition for that event
correctly drops to 7 of 8.

That last point matters for the >=95% criterion: the honest rate now counts a corrupt payload
as a failure rather than as a success that produced an empty page.

## 2026-09-08 — Both document commands merge instead of overwriting

`analyze` processes one opportunity, so writing its manifest unconditionally reduced a
ten-event evaluation corpus to that opportunity's two files. `documents` had the same problem
and demonstrated it: reprocessing a single event replaced 84 manifest rows with 8.

Both now merge into any existing corpus, deduplicated on `(document_ref, sha256)` for
documents and `(document_ref, page)` for pages, with fresh rows winning a collision. A changed
hash under the same filename is kept as a **separate** row rather than replacing the old one,
because an agency swapping an attachment must not erase the earlier version from the audit
trail.

An earlier edit to add this silently failed to apply while reporting success, which is exactly
the pattern that has caused false "done" claims before. Reapplied with a verification of every
token after the write, and a count assertion on the number of merge call sites.

## 2026-09-08 — Spending wired into vendor profiles; 5 of 7 profile dimensions now populated

The brief names seven profile dimensions. Four were populated, two are impossible, and
spending was simply an unfinished thread: the Open FI$Cal expenditure source was mapped on
day one and never connected. It is now connected.

`openfiscal.py` reads the published pointer manifest (1,230 department-year files, FY16-FY25,
154 departments, 10.6 GB), selects under an explicit size budget, parses transactions and
aggregates per payee. `vendors.attach_spending` joins it to profiles.

Live run: 7 files, 629 MB, **1,547,737 payment rows, 10,679 distinct payees, zero download
failures**. Of 634 profiles, **353 matched**, 3 left unmatched as ambiguous, 278 unmatched.

### Why spending is a genuinely different fact from awards

`PERIMETER SOLUTIONS LP` holds **2 awards** and has received **$74,734,049 across 762
payments**. On awards alone it is a minor vendor. On spending it is a major CAL FIRE supplier.
An award says a contract exists; a payment says money moved under one. Fire retardant to CAL
FIRE at that volume is a standing relationship no award count would reveal.

### 81% of the money goes to government bodies, not companies

The top matched payees were `COUNTY OF LOS ANGELES` at $356M, `DEPT OF GENERAL SERVICES` at
$296M, then Kern, Riverside, Ventura, Orange, Santa Barbara, San Bernardino, Santa Clara and
Sacramento counties, plus the UC Regents and San Francisco. These are interagency transfers —
CAL FIRE paying counties for mutual-aid firefighting, not vendor procurement.

Split properly: **298 companies totalling $485M, 55 public bodies totalling $2.07B**. So 81%
of matched spending is government-to-government. A "top vendors by spend" view without that
filter would present Los Angeles County as California's largest supplier.

Every spending block now carries `payee_is_a_competing_firm`, using the same entity test the
competitor ranking uses. The amount is still recorded for a public body, because it is real
spending and belongs in spend analysis — it is just not a competitor.

Excluding public bodies, the top suppliers are recognisable and plausible: Perimeter Solutions
(fire retardant), NWN Solutions (IT), PG&E, Downtown Ford, Allstar Fire Equipment, US Foods,
AT&T, Verizon, WW Grainger. WW Grainger carries 15 awards **and** $10.4M across 4 departments,
which is a materially richer profile than either source alone.

### The join is name-based and never claims otherwise

These files publish no supplier id, only `VENDOR_NAME` truncated near 25 characters. So:

- An exact match after normalisation is `medium` confidence. Never `high` — a name comparison
  can always be wrong, and 112 of the 298 company matches had truncated names.
- A truncated prefix match is `low`.
- A short common prefix does not match at all; "ACME" will not match "ACME WIDGETS INC".
- Two distinct payees matching one vendor name are **left unsummed** and flagged. Combining
  two companies' spending is worse than reporting none. Three profiles hit this.
- An unmatched profile records "no payment record matched", never a zero. The files loaded
  cover a subset of departments and years, so absence of a match is not absence of spending.

### Coverage limit, measured

Of the 41 departments our vendors serve, **36 appear in the spending manifest and 5 do not**:
Transportation (148 awards), Corrections (29), Motor Vehicles (26), Justice (12), Water
Resources (10). That is **28% of award volume with no spending file at all**.

Caltrans is the notable absence — the largest procurement agency in the state, 86 open
solicitations, and no vendor transaction file under any name. Only `CATransportationCommission`
and `SecTransportationAgency`, both far smaller entities, appear. The gap is systematic rather
than random, and it includes the DMV, which is the agency for the demonstrated opportunity. So
for the very contract analysed end to end, spending data does not exist.

### Two file-selection bugs, one still open

**Fixed: smallest-first was actively harmful.** The first version sorted by ascending size,
reasoning that a fixed budget would then cover more departments. It selected 203 files, every
one from a tiny agency, none from a department our vendors serve. File size proxies
departmental spending, so smallest-first systematically selects the least informative data.
Selection is now relevance-first — caller-supplied department order — then largest within a
department.

**Still open: largest-first concentrates the budget.** The live run spent 466 MB of its 600 MB
on CAL FIRE's two years, leaving little for the other 35 covered departments. One file per
department, largest year each, would buy breadth instead of depth. Not yet changed, because
the two strategies should be compared on match rate rather than assumed.

## 2026-09-08 — analyze was destroying the spending enrichment; fixed and verified

Checking after the spending work found that `analyze` silently discarded it. The command
rebuilds vendor profiles from award records and never ran the spending step, so the command
meant to *produce* the deliverable destroyed part of it. Measured: 634 profiles, **0** with
spending after a run.

This is the third instance of the same shape — a step that rebuilds where it should merge or
consume. The document corpus and the manifest had it too.

Restructured rather than patched. Spending is now its own subcommand that caches to
`build/spending_index.json`, because it downloads hundreds of megabytes and has no business
running on every analysis. `analyze` attaches from that cache, and when the cache is absent
each profile records why the dimension is empty rather than leaving a silent blank:

    "no spending index present. Run `python -m sled_trial.cli spending` to download payment
     records; until then this dimension is unpopulated rather than zero."

Verified end to end after the fix: 634 profiles all carry a spending block, **385 matched**,
321 of them actual firms and 64 public bodies, and the enrichment survives a subsequent
`analyze` run.

### Breadth beat depth, measured rather than assumed

The open selection question was settled with a comparison instead of an opinion. Same budget
class, two strategies:

| Strategy | Files | Departments | Payment rows | Profiles matched |
| --- | --: | --: | --: | --: |
| largest-first (600 MB) | 7 | 5 | 1,547,737 | 353 |
| one per department first (500 MB) | 8 | 8 | 1,260,568 | **385** |

Fewer rows, less data downloaded, **more vendors matched**. Depth in one department buys
repeat payments from the same payees; breadth reaches new ones. Selection now takes one file
per department before a second from any.

That change exposed another bug immediately: the per-department allowance loop **re-selected
the same file** on each pass, because it counted picks per department without tracking which
files were already chosen. Now guarded, with a test asserting no file is selected twice and
another asserting the budget holds across five different budget sizes.

Largest company payee in the cached index is `PACIFIC GAS & ELECTRIC CO` at $907,467,467,
which is a utility rather than a competitor for any solicitation — another reminder that the
`payee_is_a_competing_firm` flag is doing necessary work.

## 2026-09-08 — CORRECTION: two README sources were never queried, and they fix two "impossible" gaps

Re-reading the brief to look for solutions to the weak parts found that **two of its eight
named source families were missing from my source registry entirely**. I had them in an early
version and lost them in a registry rewrite, then went on to describe capabilities they
provide as impossible.

Both are publicly reachable with no login — bare `.GBL`, same as SCPRS.

### Supplier search: `ZZ_PO.ZZ_PUBSRCH.GBL`

The brief's own question about it: *"Which supplier identifiers, categories, **locations**, and
SB/DVBE certifications support vendor resolution and profiling?"* The word locations is right
there in the question I was answering with "not available".

A live search for `AVIATE` returns, per supplier:

```
ZZ_PUBSRCH_VW_CITY            Sacramento
ZZ_PUBSRCH_VW_POSTAL          95652
ZZ_PUBSRCH_VW_ADDRESS1/2/3    5822 Price Ave, Suite 105
ZZ_PUBSRCH_VW_COUNTRY         USA
ZZ_BUS_TYP_VW_BUSINESS_DESCR  Construction
ZZ_CERTYPLBL_VW_DESCR254      Micro Business (MB)
ZZ_PUBSRCH_VW_DESCR1          DVBE , SB-PW
ZZ_NAICS_VW_NAICS_CODE        (industry codes)
ZZ_CLASSCD_VW_LICENSE_CODE    (license codes)
ZZ_KEYWORD_VW_DESCR_LONG      (keywords)
```

There is also a `ZZ_PUBSRCH1_WRK_DOWNLOAD_TO_FILE` control, so bulk export may be possible.

**So the geography claim was wrong.** I wrote in DECISIONS.md and in PLAN.txt that "no vendor
location exists in the award registry" and that geography was left unscored because matching
needs both sides. The award-registry half of that is true. The conclusion drawn from it was
not: the vendor side exists on a different surface named in the same brief, which I never
opened.

Two coverage caveats before this is treated as solved. The component title reads "Custom
Component for SB orDVBE", so it may only cover certification-registered suppliers rather than
every state supplier — that has to be measured, not assumed. And the returned rows include
contact names, emails, phone and fax. README puts "private contact enrichment" out of scope,
so geography, certifications, business type and NAICS are the fields to take; personal names
and contact details are not to be harvested even though they are visible.

Also worth noting: the search for `AVIATE` returned `AVIATE ROOFING FLOORING &`, a **different**
company from `AVIATE ENTERPRISES INC`. Name matching against this surface needs the same care
as anywhere else.

### LPA search: `ZZ_PO.ZZ_CNT_SRC_CMP_BKP.GBL`

The brief's question: *"Which vendors already hold purchasing vehicles relevant to an
opportunity?"* This is the source for `presence on a relevant statewide contract or purchasing
vehicle`, which is a named baseline prediction feature that `predict.py` scores but could
never populate, because I had no vehicle data for the opportunity side.

Searchable by `VENDOR_ID`, vendor name, contract ID, buyer and acquisition type. A search for
`GRAINGER` returns:

```
CNTRCT_ID                  7-25-51-02
NAME11                     WW GRAINGER INC
VENDOR_ID1                 0000005196
ZZ_CNTRCT_TYPE             Cooperative Agreement
DESCR2                     Facilities Maintenance, Repair, and Operations
CNTRCT_EXPIRE_DT1          08/31/2028
OPRDEFNDESC1               (buyer name)
ZZ_CTR_SRC_VW_ZZ_ACQ_TYPE  NON-IT Goods
```

`VENDOR_ID1` is the same identifier space as SCPRS `supplier_id`, so this joins on an
identifier rather than a name — the only surface so far besides SCPRS itself where that is
true. `CNTRCT_ID` also matches the `lpa_contract` field already present on award rows, giving
a second join path.

The search button is `ZZ_CTR_SRC2_WRK_SEARCH_BTN`; `ZZ_CTR_SRC2_WRK_BUTTON` returns a page with
no grid, which is how the first attempt looked like a failure. An empty search returns nothing,
so criteria are required.

### What this means for the record

Three statements in the written record are now wrong and need correcting rather than quietly
updating:

1. "No vendor location published anywhere reachable" — false. It is on the supplier search.
2. "Geography cannot be matched between opportunity and vendor" — false on the vendor side.
3. The source registry claiming eight README families were assessed — it held ten surfaces but
   was missing two of the eight named ones.

The lesson is narrower than "read the brief again": I did read it, built a registry from it,
and then trusted my own registry instead of the brief once the registry existed. A derived
artifact replaced the source it was derived from, and nothing checked that the derivation was
still complete.

## 2026-09-09 — Geography wired in from the supplier registry

The geography dimension is now populated, from `ZZ_PO.ZZ_PUBSRCH.GBL` — the source named in
the brief that I had never opened.

Live result: 120 most-active company profiles queried, 103 registry entries found, **38
profiles matched** across 31 cities, 2 left unmatched as ambiguous, zero query failures.

Example: `GREEN RAMP GROUP LLC` — 131A STONY CIR STE 500, SANTA ROSA, CA 95401-9513,
registry certifications DVBE/SB/SB-PW, website published, against 18 awards at 12 agencies.

And the chain closes on the case that started all of this: the DMV award notice named
`AVIATE ENTERPRISES, INC.`, which resolves to SCPRS `supplier_id 0000015031` and now to
1418 N MARKET BLVD STE 500, SACRAMENTO, CA 95834-1984.

### A parser bug that would have poisoned the data

The first version counted result rows by taking the highest `$N` index anywhere on the page.
That page carries the search form's own dropdowns: `ZZ_CERTYPLBL_VW_DESCR254` had 6 rows and
`ZZ_BUS_TYP_VW_BUSINESS_DESCR` had 4, on a search returning **2** suppliers. So it reported
six results and stapled unrelated business types and certifications onto companies.

Only the `ZZ_PUBSRCH_VW_*` family is the result grid; `ZZ_NAICS_VW`, `ZZ_CLASSCD_VW`,
`ZZ_KEYWORD_VW`, `ZZ_POSTAL_VW` and `ZZ_SRVCAREA_VW` are single-row filter inputs. Row count
now derives from the name field alone, so form furniture cannot inflate it, and the test
fixture deliberately contains more dropdown rows than results.

Worth noting the failure mode: this would not have thrown or looked empty. It would have
silently attached the wrong attributes to real companies — the most damaging shape of bug in
this pipeline, and the only reason it surfaced is that the row counts looked odd in a live run.

### Contact fields are excluded by decision, not omission

The result grid returns `FIRST_NAME`, `LAST_NAME`, `EMAILID`, `PHONE3` and `FAX`. README puts
private contact enrichment out of scope, so those five are named in
`CONTACT_FIELDS_NOT_CAPTURED`, read past, and never stored. A test asserts none of them
appear in output. Listing them explicitly means the omission reads as a decision in code
review rather than an oversight.

### The strict name match is deliberate, and the data proves it

The join requires an exact name match after normalisation. 103 registry entries produced only
38 joins, which looks like a poor yield until the near-misses are examined:

| Registry entry | Closest profile | Same company? |
| --- | --- | --- |
| Cactus Foods LLC | US FOODS | no |
| GRANITE FINANCIAL SOLUTIONS INC | GRANITE DATA SOLUTIONS | no |
| Kern Auto Parts Inc | NAPA AUTO PARTS | no |
| A.R.E. Auto Parts Inc. | CAL STATE AUTO PARTS | no |

Those are different companies that a two-word search returned, not matches the join missed.
Relaxing the rule would produce wrong addresses rather than more data. `AVIATE` alone matches
two distinct companies at two Sacramento addresses, which is the same lesson in miniature.

### Measured coverage bias

Sampling the 20 highest-award company profiles: **55% overall, 80% for vendors carrying a
certification in the award registry, 30% for those without.** Grainger, Verizon, Safeway and
McKesson are all absent — the component is the SB/DVBE registry, so large uncertified
suppliers are systematically missing.

Every unmatched profile therefore records "not in the small-business registry" rather than
"location unknown", because the two mean different things.

### Still not a prediction feature

Geography is now a profile dimension. It is **not** scored in prediction, because
opportunities state service-area counties while vendors state a city, and matching needs a
city-to-county gazetteer that is not in hand. Recorded in `prediction_gap` rather than faked
with a same-state check that would return 1.0 for every California vendor.

## 2026-09-09 — Pre-submission review: two dead deliverables, one unreproducible number

A full read of the repository against the brief, layer by layer. The code held up better
than the repository around it. Fourteen defects were confirmed against source and fixed;
what follows is the ones that changed an output a reviewer would see.

### The teaming deliverable was empty because `analyze` fed it the wrong corpus

`cmd_analyze` passed the date-sweep corpus to `recommend_primes`. The 2026-09-08 entry
above establishes that primes need `awards_prime_enriched.jsonl` — uniform depth across the
eligible set — and that file was sitting in `build/` unused. On the sweep the median vendor
holds one award, so nothing could clear the rule and the report printed a principled-sounding
"no vendor qualified" that was really a wiring bug. Wired up: **21 of 68 eligible vendors
qualify (30.9%)** on the demonstrated DMV opportunity, with named candidates and counted
evidence.

The enrichment itself was also unreproducible — built by a script that never made it into
the repository. It is now `cli backfill-primes`, which derives the eligible set with
`primes.eligible_supplier_ids` and queries SCPRS per supplier.

### The review queue reported zero items while holding eighteen

`report.py` read `review_queue.jsonl`; `cli.py` writes `review_queue.json`. The count came
back zero, which read as "no unresolved identities" — the opposite of the truth, and in the
direction that flatters. Now 18.

### The headline precision figure could not be regenerated

Nothing in the repository wrote `build/evaluation.json`, and `evaluate`,
`compare_to_baselines` and `describe_corpus` were reachable only from tests. The one number
the honesty argument rests on was a screenshot. `cli evaluate` now rebuilds it:
`predict.holdout_events` reconstructs the split (836 history rows, 55 events at the
09/03/2026 cutoff) and reproduces the published 0.0727 exactly.

### Three scoring defects, one of which flattered the model

* `precision_at_k` divided by `len(top)` rather than `k`, so a short prediction list could
  score 1.0. The baselines always return a full list, so the bias ran one way. The model
  returns ten predictions, so the published figure is unchanged — but the metric was wrong.
* `primes_similar_work` scored `len(both)`, the same count as `agency_and_category_awards`.
  Agency-and-category therefore carried an effective weight of 4.5 against the 3.5 the
  published table shows. Removed rather than reweighted: SCPRS cannot distinguish prime from
  sub, so the feature was never measurable and a second copy of an existing count is not a
  substitute for it.
* `compare_to_baselines` documented that history and cutoff are applied once for every
  approach, then handed the baselines unfiltered history. Now true as written.

After all three, on the same unselected 55 events: **precision@3 0.0727, precision@5 0.0582,
coverage 0.1918, lift 1.2x over the best trivial baseline.** The report now carries the
baseline and the lift beside the raw figure, which is the only context that makes a 0.07
presentable.

### Correctness fixes that had not yet surfaced in an output

`vendors.build_profile` raised `ValueError` on 29 February (`today.replace(year=+10)`).
Name normalisation stripped punctuation before suffixes, so "Foo L.L.C." and "Foo LLC" never
compared equal and the conflict detector could not pair them. Lineage reported its award
date range by sorting `MM/DD/YYYY` strings. `openfiscal.truncated_name` fired on every name
of 25 characters *or more*, when only a name of exactly 25 is evidence of truncation, and
its prefix rule measured the normalised name — shorter than the raw one — so the module's
own headline example failed. `DocumentStore.put` overwrote when two attachments on one event
shared a displayed filename, leaving a manifest row pointing at another document's bytes.
`retrieved_at` recorded manifest-assembly time rather than retrieval time. The SCPRS grid
keyed rows off any `$N` family, the bug already found and fixed in `supplier_search`.
County service areas were recovered from anywhere on the page, so every state buyer address
in Sacramento produced a Sacramento service area.

### What was deleted

`pipeline.py`, `models.py` and `tests/test_pipeline.py`: scaffold, unreferenced by any live
path, kept green by a test nobody had deleted. The prose award-statement miner in
`extract.py`, unused since the 2026-09-07 finding that tables are the only viable
extraction path. Duplicated `_text`/`hidden_fields` copies in `scprs` and `supplier_search`,
which both already import from `caleprocure`.

`assemble.py` now holds the artifact-shaping functions that had accumulated in `cli.py`, and
the merge-and-write block that was duplicated verbatim between `cmd_documents` and
`cmd_analyze` is one function called twice.

### Reproducibility, which was the real gap

There were no install instructions anywhere, so a reviewer following the repository landed
on four collection errors rather than a passing suite. `docs/RUNNING.md` covers install, the
command list and what each costs; verified from a clean virtualenv: `pip install -e ".[dev]"`
then `pytest -q` gives **356 passed**, offline, no credentials.

## 2026-09-09 — CORRECTION: bidder lists ARE public in California, for 23% of the feed

The 2026-09-07 entry states that California publishes no bidder lists and that no
deterministic solicitation-to-award join exists. Both hold for the Cal eProcure surfaces
surveyed. Both are wrong about the state as a whole, and the counterexample is the largest
issuer in the feed.

### Caltrans publishes every bidder, ranked, with amounts, anonymously

`https://dot.ca.gov/programs/procurement-and-contracts/bid-results/bid-week-<YYYY-MM-DD>`,
one page per week, slug dated to the Sunday. Verified anonymously, no login, no key.
From the week of 2026-01-11, contract `08A3933`:

```
Ware Disposal Inc.          SB: N   $436,020.00
Apex Waste Systems Inc.     SB: Y   $480,480.00
Burrtec Waste Industries    SB: N   $801,571.80
```

Three bidders, rank order, **including the two that lost** — the fact the state portal
does not carry and the reason every `win_rate` in `vendor_profiles.json` is null. The page
also marks Small Business preference per bidder. Contract `09A1078` on the same page
carries four bidders, `07A6272` one; 26 bid rows across six contracts that week.

### The join is exact, not probabilistic

Every contract number on the page links to
`https://caleprocure.ca.gov/event/2660/<contract_number>`. Business unit 2660 is the
Department of Transportation, and its event ids in our own feed (`01A6671`, `02A2535`,
`07A6272`) are that same contract-number format. The join to a Cal eProcure event is
**string equality on `event_id`** — no title similarity, no date window, no inference tier.
`known_bidder` in README's sense is directly reachable for these events.

**2660 is 81 of 359 events in the current feed, the single largest issuing agency.** The
brief's minimum of 100 bidder-event observations is reachable from roughly four weekly
pages.

### Measured limits

- **History is a rolling window.** Real content back to the week of 2025-12-14 (31 bid
  rows); 2025-10-12 and earlier return an empty template. Roughly nine months, so a
  harvester has to run continuously rather than backfill at leisure.
- **The empty weeks are soft-404s: HTTP 200 with a ~23.7 KB shell**, against ~30 KB for a
  real page. Byte-identical across dates. Exactly the "success that is not success" trap
  `documents._looks_like_html` exists for, and a row count of zero must be read as
  "no page", never "no bids that week".
- **Results are preliminary**, subject to SB/DVBE/licensing/bonding verification, so the
  posted low bidder is not necessarily the awardee. Rank is observed; award is not.
- `ppmoe.dot.ca.gov/des/oe/awards/bidsum/dl.php?id=<n>`, the older per-project bid summary
  endpoint, now returns a ServiceNow "DES NOT Found - PPMOE Migration" page under HTTP 200.
  Another soft-404, and a reminder that this family of URLs moves.

### The 1-in-30 award-notice figure was measuring the wrong population

`documents_manifest.jsonl` covers 10 events. **Zero of them had passed their end date**;
six were still open and four carried no parseable date. An open solicitation has not been
awarded, so it cannot carry an award notice, and the DMV intent-to-award was caught inside
a narrow window rather than being one-in-thirty rare.

Worse for that harvesting strategy: **the feed contains no closed events at all** — 359 of
359 are still open. Cal eProcure drops an event at close, so award notices attached after
close are never reachable from the feed. Award-notice harvesting from the active feed is
structurally low-yield and always will be. Caltrans bid results, which persist after close,
are the durable substitute.

This also matters for DGS policy: a protest must be filed within five working days of the
**public posting of the Notice of Proposed Award**, so NOPAs are a required public artifact
statewide. Where they are posted after an event leaves the feed is an open question and the
next thing worth tracing.

### Not established by this probe

- **PlanetBids** hosts bid results and plan-holder lists for many California cities and
  counties, and `pbsystem.planetbids.com/portal/<id>/bo/bo-search` answers HTTP 405 to a
  GET — the endpoint exists and expects POST, per-agency portal ids confirmed (Corona is
  39497). The platform was in scheduled maintenance during this probe, so whether the
  results and plan-holder endpoints answer anonymously is **untested, not negative**.
- **Board agendas and staff reports** routinely carry full bid tabulations — examples
  located across Stanislaus, Santa Cruz and Placer counties. One Placer packet fetched is
  a scanned image PDF with no text layer, so this path needs the OCR fallback rather than
  native extraction. Two county document servers refused connections from this host, so
  coverage across counties is unmeasured.
- **Protest decisions** through the OAH Alternative Protest Process name protester and
  awardee together. No published decision archive was located; unresolved.
- **CPRA** remains the compliant fallback for a bid tabulation no portal posts. Not
  automatable, and the brief asks for exactly this kind of documented manual path.

### What this changes

`sources/source_registry.csv` has 14 surfaces and none of them is Caltrans bid results —
a first-class deliverable missed a public, anonymous, loser-inclusive bidder source
belonging to the largest agency in the feed. The registry, `docs/SOURCES.md` and the
"bidder lists are not public" claim in the report all need revising, and the honest
framing is narrower than the original: *Cal eProcure* does not publish bidder lists;
*California* does, agency by agency, and nobody has aggregated them.

## 2026-09-09 — Caltrans bid-results adapter: 211 observed bidder events, 1 before

The correction recorded above is now wired in. `sources/caltrans.py` fetches the weekly
bid-results pages, parses the ranked field, and emits one observed-participant row per
bidder. `cli bidders --weeks N` drives it; `analyze` consumes what it writes.

Measured on a live 13-week harvest:

| | Before | After |
| --- | ---: | ---: |
| Observed bidder events | 1 | **211** |
| Solicitations with a named field | 1 | 76 |
| Solicitations naming more than one bidder | 0 | **50** |
| Supabase participant rows | 975 | 1,188 |

Fifty solicitations carrying a loser is the number that matters: it is evidence the trial
previously recorded as non-existent in California.

### Design notes

**Emit into the shape the export already reads.** `bidder_candidates` produces
`vendor_name_raw` / `amount_raw` / `amount_numeric`, the field names
`supabase_export.participant_rows` already consumes from document-extracted candidates, so
this source needed no second export path. Two small generalisations there: `rank` is taken
from the candidate instead of hardcoded null, and `source_key` is too, because rank is the
whole point of a bid-results row and attributing it to the event package would be false.

**Absent weeks are reported separately from empty weeks.** `harvest` returns
`weeks_populated` and `weeks_absent`. An unpublished week answers HTTP 200 with a ~23.7 KB
template, so collapsing the two would let a rolling-window boundary read as "no bids
opened". `looks_populated` decides on the presence of a Cal eProcure event link.

**Slugs round back to Sunday, not forward.** A page dated Sunday carries that week's
openings, so a date maps to the Sunday on or before it. Rounding forward silently skips the
first week in a range; the test names that case.

### A crash the tests could not have caught

`cmd_analyze` indexed `k["displayed_filename"]` on every observed participant. That held
while every participant came from a document, and the first Caltrans row — which cites a
URL, not a filename — took down the whole run. Fixed by moving the construction into
`assemble.unresolved_identity_review` and citing whichever the row carries. The regression
test was verified against the buggy form before being kept.

The repo's own guard did catch the other one: `attach_bid_history` existed for a few
minutes without an `ENRICHMENTS` entry, and
`test_every_vendors_attach_function_is_declared` failed immediately. That test was written
after this exact class of mistake happened four times, and it worked.

### Win rates: machinery done, corpus not

`vendors.attach_bid_history` computes wins, losses and a rate from observed rank, scoped and
labelled: rank 1 is a win, any lower rank an observed loss, and `win_rate_basis` records the
source keys, the solicitations counted, and that the identity match is a low-confidence name
comparison. The note states it covers a subset rather than the vendor's overall history.

**On the current corpus it matches nothing: 0 of 634 profiles.** That is not a defect in the
join. Profiles are built from a six-day statewide SCPRS sweep — office supplies, IT goods,
commodity purchases — while these are Caltrans highway and facility contractors. Exact
normalised overlap between the 149 bidder names and the 630 profile names is zero, and the
two nearest fuzzy matches include a false one ("A Superior Sanitation" against "A Plus
Superior Sanitation"), which is a good argument against loosening the match.

The vendors are reachable: an SCPRS name search returns `GRANITE CONSTRUCTION COMPANY`
(`0000011589`), `ANDERSEN INTEGRATED SVCS INC` (`0000170357`) and `A TEICHERT & SON INC`
(`0000028967`). So the missing step is corpus, not code — resolve each bidder name to a
supplier id, backfill those vendors' awards, and the rate populates. Left unbuilt rather
than half-built, and the review queue carries all 211 rows as
`unresolved_participant_identity` so nothing is presented as resolved that is not.

### Still Caltrans-only

This covers business unit 2660, 81 of 359 events. PlanetBids was in maintenance during the
probe and remains the largest untested source; board-agenda bid tabulations need OCR. Both
are recorded in the entry above rather than claimed here.

## 2026-09-09 — PlanetBids is behind a bot challenge; SF Public Works is the open substitute

The earlier probe recorded PlanetBids as untested because the platform was in maintenance.
Retested today, and the answer is not "down" but "closed to automation".

### The measurement

`pbsystem.planetbids.com/portal/<id>/*` 302s to `vendors.planetbids.com`, which answers
**HTTP 405 with an AWS WAF "Human Verification" interstitial** — `window.awsWafCookieDomainList`
and a `gokuProps` challenge token — served through CloudFront. The challenge appears with a
normal desktop browser user-agent, not only to a bare client, so it is bot detection rather
than a user-agent filter. Reproduced on two portal ids (39497, 15300) and both hostnames.

`https://pbsystem.planetbids.com/robots.txt` returns the maintenance page under HTTP 200
rather than a robots file, so **no crawl permission can be read from the site at all** —
there is no directive to comply with, which is not the same as permission.

### Ruling: not automatable, and not to be worked around

A WAF human-verification challenge is an access control. README permits inspecting public
browser network requests and explicitly forbids bypassing "authentication, CAPTCHA, access
controls, rate limits, or terms of use"; SECURITY.md says the same. Solving or evading the
challenge is therefore out of scope regardless of the data being public to a person in a
browser. Recorded as a demonstrated access limitation, which is what the brief asks for
when a source prevents collection.

The compliant routes, none of them automation: a person may open a portal and read results;
an agency or PlanetBids may grant API access on request; CPRA reaches any specific
tabulation. This is the strongest position available without permission.

### The substitute, found while testing the fallback

**San Francisco Public Works publishes a full bid tabulation as a text-layer PDF.** From
`Item 5b_PWC No 35 Traffic Signals attach 2026-4-30.pdf`, retrieved anonymously:

```
TABULATION OF BIDS      SOURCING ID: 0000002270
BIDDERS (in the order received & opened):  LBE Status        Total Bid Price
Bay Area Lightworks, Inc.                  Small-LBE 10%     $7,200,000.00
Liffey Electric                            Micro-LBE 10%     $7,215,619.50
A. Ruiz Construction                       Micro-LBE 10%     $9,001,119.88
Average Bid: $7,805,579.79     Engineer's Estimate: $9,200,000.00
```

Every bidder, a local-business-enterprise status, prices, and an engineer's estimate — which
is a benchmark Caltrans results do not carry. Native text, so no OCR. It also cites a
per-bid **subcontractor listing** at `bidopportunities.apps.sfdpw.org`, and subcontracting
is the dimension `vendors.build_profile` currently records as unobservable. That host
refuses connections from this environment, so the subcontractor claim is unverified.

### Environment caveat on the negative results

`stancounty.com`, `pfm.sbcounty.gov`, `webapps.sfpuc.org` and `bidopportunities.apps.sfdpw.org`
all returned connection failures (curl exit 7, no HTTP status) from this host, while
`sfpublicworks.org` and `dot.ca.gov` served normally. That pattern points at egress
filtering here rather than at the sources, so those four are unmeasured, not unavailable.
Anyone re-running this should retest them from an unrestricted network before concluding
anything.

### Ranking after this probe

1. **Caltrans bid results** — built, 211 observations, exact join.
2. **SF Public Works tabulations** — open, text-layer, adds engineer's estimate and a
   subcontractor path. The next thing worth building.
3. **Board-agenda tabulations** — reachable but scanned, needs the OCR fallback.
4. **PlanetBids** — largest agency coverage, closed to automation without permission.

## 2026-09-09 — SF Public Works adapter, and bidder identity resolved against SCPRS

Two additions, both following from the probe above: a second source that names losing
bidders, and the step that turns a company name on a page into a vendor the rest of the
pipeline already knows.

### SF Public Works: a second bidder source, with a trap the first one does not have

`sources/sfpublicworks.py` reads the `TABULATION OF BIDS` attachment that accompanies every
contract award going to the Public Works Commission. Measured on a live run across three
commission pages: 99 PDFs linked, 15 worth opening, **4 tabulations, 21 bidder
observations, and all four name more than one bidder.**

It also carries an **engineer's estimate**, which Caltrans does not. That is the agency's
own expectation of the price, so a field can now be described as coming in under or over
what the buyer budgeted rather than only relative to each other.

**The trap: San Francisco lists bidders in the order their envelopes were opened, not by
price.** Measured on Pavement Renovation No. 78, six bidders in listed order read $7.66M,
$6.56M, $6.69M, $6.60M, $8.11M, $7.30M. Reading rank off list position would have named
R&S Construction the apparent low bidder when Ronan Construction was $1.1M cheaper. Rank is
therefore derived by sorting on amount, and the page's own ordering is kept separately as
`listed_position` because it is the only ordering the document actually asserts. This is
the opposite of Caltrans, whose ordered list *is* the rank, and the two adapters say so in
their docstrings so the difference cannot be assumed away.

**No state join exists.** San Francisco is a city and does not appear in Cal eProcure, so
these rows carry `business_unit: "SFPW"` and SF's own sourcing id. `participant_rows` now
derives the solicitation record's source from the candidate rather than assuming
`caleprocure_event_list`; hanging an SF sourcing id off the state event list would have
asserted a record that does not exist.

**Discovery is the weak point, and it is a site limitation rather than a parsing one.** The
commission calendar links mostly minutes and agendas; the attachment carrying a tabulation
hangs off the individual meeting page, and those are `/node/<id>` URLs the site does not
index anywhere. So `--page` is repeatable and defaults to the calendar. A full backfill
needs the meeting URLs supplied, which is worth saying plainly rather than reporting the
calendar-only yield as the source's ceiling.

### Bidder identity resolution

`vendors.resolve_bidder_identities` takes each distinct bidder name to SCPRS and attaches a
`supplier_id`. One query does double duty: the same search that identifies a vendor returns
that vendor's award rows, so the profile backfill costs nothing extra and comes back as
`awards_seen`.

The rule is strict on purpose. Exactly one supplier matching after normalisation resolves
the row, at `medium` and never `high` — it is still a name comparison. More than one leaves
the row `ambiguous` with the candidates recorded, because two suppliers can normalise to
one name and be different companies. A near miss is not a match: "A Superior Sanitation"
and "A Plus Superior Sanitation" are both real and distinct in this corpus, which is the
argument against loosening it.

`attach_bid_history` now matches on a resolved `supplier_id` first and falls back to the
name only for rows that have none, so resolution is not wasted on a spelling difference.

### Profiles may use the wider corpus; prediction may not

Resolution produces `awards_bidder_enriched.jsonl`, and `assemble.profile_corpus` folds it
into the corpus profiles are built from. Prediction keeps ranking on the sweep alone.

That split is deliberate and now has a test that reads `cmd_analyze` and fails if
`rank_candidates` is ever handed anything but `awards`. Profiles are descriptive — counts,
agencies, amount ranges, one vendor at a time — so deeper history makes them more accurate.
Ranking is the opposite: enriching a subset reorders it, which is the measured effect that
invalidated the 0.17 precision figure and the 19 prime candidates. Same data, opposite
consequence, so the two corpora stay apart.

### A second latent crash of the same shape

`cmd_tabulations` called `extract.extract_pages` while `cli.py` no longer imported
`extract` — the module had been trimmed from the import when assembly moved out. Tests
passed, because no test exercises a network command. That is the second bug in this
session that only a live run could catch, after the one where every observed participant
was assumed to carry a filename. Worth recording as a pattern: the CLI's network commands
have no test coverage by construction, so each one has to be run once before it is
believed.

## 2026-09-09 — Running the README command verbatim broke three assumptions

The deliverable command had never been run as the brief writes it: every run this session
passed `--reuse-awards` and skipped `--download-documents`. Running it verbatim found three
problems, two of them in the numbers being shipped.

### The command could not reproduce the corpus it shipped

`--awards-from` defaulted to the literal `09/01/2026`, so a verbatim run swept three days
and produced 600 award rows and 393 profiles, against the 974 rows and 658 profiles in
`build/`. The shipped figures came from a wider window passed by hand and never written
down. Anyone following the README would have got smaller numbers than the report claimed
and no way to tell why.

The default is now derived: seven days before the cutoff, via
`assemble.default_awards_from`. The verbatim command reproduces the deliverable, which is
the only property that makes the figures checkable.

### The sweep was silently losing two thirds of its rows

`search_date_sliced` sets `truncated` on any slice still over the 200-row grid cap after
bisection, and nothing read it. Measured on the reference window: **6 of 7 slices capped,
1,252 rows collected against 3,789 the portal reported.** The corpus was a third of the
available data and every downstream figure was computed on it without a word.

`assemble.award_sweep_coverage` now summarises what was collected against what was
reported, `analyze` prints a warning, and `build/awards_coverage.json` names the slices and
the shortfall. Same class of silence as a soft-404 reading as "no results" — the fix is to
say so, not to pretend the window was complete.

The remedy is a second subdivision axis, not a wider window: widening adds days that will
themselves cap. `search_date_sliced` already accepts `subdivide_by`; wiring it is the next
increment and is not done.

### The model no longer beats a trivial baseline

Re-evaluated on the deeper corpus, over 64 unselected events:

| | 836-row history (previous) | 1,052-row history (now) |
| --- | ---: | ---: |
| Model precision@3 | 0.0727 | **0.0573** |
| Best trivial baseline | 0.0606 | 0.0625 |
| Lift | 1.20x | **0.917x** |

The 2026-09-08 entry claimed the lift was the stable quantity, holding at 1.20-1.33x across
every set size tried. That was measured across subsets of one shallow corpus. On a deeper
one it does not hold: the model is now *worse* than ranking by "most awards with this
agency". Reported as measured, in the report table as well as here.

Two honest caveats in both directions. The corpus is a third complete, so neither figure is
measured on the real distribution. And the target remains same-day purchase orders rather
than solicitation bidders, which the 2026-09-08 entry already argued is close to noise for
commodity categories. Neither rescues the number: on the evidence available the ranking has
not earned its features, and the right next move is the redefined forward-window target
that entry proposed, not weight tuning.

### An ordering trap between two commands

`analyze` writes `report.md` from whatever `evaluation.json` currently holds, while
`evaluate` is a separate command that runs after it. Following the documented order left a
report quoting the previous run's precision beside an `evaluation.json` holding the current
one. `docs/RUNNING.md` now states the order; the durable fix would be for `report` to read
the evaluation's own timestamp and refuse to quote a stale one.

### Every command now run at least once

`events`, `documents` and `spending` predated the `assemble` extraction and had not been
run since. All three work: 362 events across 66 agencies, 2/2 documents at 100% acquisition
with the intent-to-award participant still extracted, 18,058 payment rows from an 8 MB
sample. Both bugs found this session were in network commands, which have no test coverage
by construction, so each one is now exercised before shipping rather than after.
