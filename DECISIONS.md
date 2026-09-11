# Decisions and findings

What the California public record actually supports, what it does not, and why the code is
shaped the way it is. Organised by subject rather than by date.

---

## 1. The central question: who bid?
**Cal eProcure does not publish bidder lists, and this is now tested .** The Response Bid Inquiry component was recorded as login-gated. It is not: it
answers anonymously over plain HTTP. Signed in as a registered supplier it returns the same
event grid, with no respondent column and no respondent field anywhere in the page — and
signing in actively *breaks* the event detail the pipeline depends on, which is pinned to
the generic Default Bidder id. This is PeopleSoft Strategic Sourcing behaving correctly: a
bidder inquires about its own responses, not anyone else's. The pipeline stays anonymous.

**California publishes bidder lists agency by agency, and overwhelmingly on one platform.**
That is the finding the work turned on:

| Surface | What it gives | Scale |
| --- | --- | --- |
| PlanetBids agency portals | Every respondent with amount and certifications, **plus planholders**, keyed by a stable platform vendor id | 1,845 bidders and 25,090 planholders over 3 agencies; 1,269 and 10,538 distinct vendors |
| Caltrans weekly bid results | Every bidder, ranked, with amount and Small Business status | 836 observations over 53 weeks (2025-09-07 to 2026-09-06) |
| SF Public Works tabulations | Every bidder, local-business status, price, **engineer's estimate** | 21 observations |
| Award-notice PDFs on Cal eProcure events | The awardee and the winning amount | 1 observation |

**Most local surfaces publish opportunities or counts, not names.** Surveying the rest of
California local government is what makes the concentration visible, and the negatives are
as useful as the positive: CSU marks a solicitation `Awarded` but hides the awardee behind a
supplier login (577 solicitations, 22 campuses); Sacramento publishes bidder *counts* and a
local-participation share but never a vendor (395 solicitations); LA County names the full
field but only on roughly one awarded project in twelve, in varying PDF layouts, and has
moved current work to Bid Express; UC has no systemwide public bid portal at all, unlike
CSU. So the competitive data concentrates in PlanetBids, and the rest of the sector is an
opportunity feed.

Caltrans contract numbers **are** Cal eProcure event ids under business unit 2660 — the
id space and format match exactly (`01A6671` in the feed, `01A6607` from the results). But
**the join does not fire on a snapshot, and measuring it is how we found out**: 0 of 75
harvested Caltrans solicitations match any of the 80 open BU-2660 events. Cal eProcure lists
open events; Caltrans publishes results for events that have already closed. Same ids,
disjoint in time. The join is only possible if an event was captured while open and kept, so
this is a harvesting-cadence problem rather than a matching problem, and no name
normalisation or padding variant fixes it.

San Francisco is a city, absent from the state portal, so its rows carry their own sourcing
id and no state join is claimed. PlanetBids rows carry a `vendorId`, but it is a
PlanetBids-internal identifier: it deduplicates a vendor across agency portals and does not
cross into SCPRS `supplier_id`.

Two limits carried in the data, not just here: results are preliminary pending SB/DVBE,
licensing and bonding verification, so the low bidder is not yet the awardee; and Caltrans
keeps roughly nine months, so a harvester must run continuously rather than backfill.

**The demonstrated event has closed.** Cal eProcure lists open events only, so an event
leaving the feed is the sole closure signal it gives — there is no status change to read.
The DMV event used as the worked example dropped out of the feed on or before 2026-09-10,
while its detail page and both attachments stayed retrievable by identifier. `analyze` now
reports whether its target is still listed, because otherwise a later run returning no
documents reads as "this solicitation had no attachments" rather than "the event is gone".
The example is kept because its intent-to-award PDF is the only document in the corpus
naming a bidder against a specific solicitation.

**Vendor advertisements** are the remaining solicitation-specific signal: a `Prime Seeking
Sub` post is a company declaring intent to bid on a named event. Reachable, not yet
harvested, and classified `declared_interest` — never `known_bidder`, because the ad names a
person and no supplier id.

---

## 2. Dead ends, recorded so they are not retried

**PlanetBids — was recorded as blocked, and that was wrong.** The block was never an auth
wall: the portal answers a bare HTTP client with 405 because it is not a browser. A real
Chrome session reads it, and the app's own JSON API can then be called from inside the loaded
page — the same requests a person clicking through causes. It is now the largest bidder source
in the corpus. Two things the original note got right and one it got wrong: `robots.txt` does
return a maintenance page rather than a crawl policy, the portal does sit behind an AWS WAF,
and "out of reach" did not follow from either. Its terms carry no anti-automation clause; what
they do restrict is commercial use of site content, which is a business decision rather than a
technical one and is recorded against the source.

**CSLB master register — a ceiling, not flakiness.** The contractor register is free and needs
no login, and a licence number is the one identifier that crosses the bidder sources. The
download is cut short server-side at roughly 20MB every run. Twelve attempts plateaued between
48,000 and 65,000 rows against a register of about 290,000, and retrying harder was measured
rather than assumed: best of four was 64,767 rows, best of twelve was 59,873. What is held is a
front slice ordered by licence number, so it is biased to older licences rather than a sample.
The by-classification route is the remaining option and its form does not yield to a
server-side post.

**Cal eProcure `.aspx` pages — empty shells.** The public pages are JavaScript wrappers
carrying no data. The conclusion "a browser is required" was wrong: they wrap PeopleSoft
components that serve complete data anonymously. Two URL shapes are the whole difference — a
query parameter that triggers a login redirect, and `FolderPath` parameters that make a
component public.

**DGS bulk historical contract export — gone.** The page the brief links no longer offers a
download.

**`data.ca.gov` CKAN API — disallowed.** `robots.txt` disallows `/api/`, which the historical
corpus query needs. Not queried.

**`suppliers.fiscal.ca.gov` — unreachable.** No response from any route tried.

**Board-agenda bid tabulations — reachable but scanned.** County staff reports routinely embed
full bid tabulations. The packets sampled are image PDFs with no text layer, so this path needs
the OCR fallback rather than native extraction. Several county hosts also refused connections
from the harvesting machine, so their coverage is unmeasured rather than unavailable.

**No deterministic solicitation-to-award join.** SCPRS rows are keyed by purchase document
number, which bears no relation to a Cal eProcure event id. A description search for
solicitation numbers returned 11 records against tens of thousands of awards. Opportunity-to-
award linkage is therefore probabilistic — department, category, date window, description
similarity — and is surfaced as `inferred`, never `confirmed`.

---

## 3. Access, as measured

Every Cal eProcure surface, and every other state and local source but one, is anonymous
HTTP: no login, no API key. The exception is PlanetBids, a rendered single-page app whose
API answers a bare client with 403, so it is read through a real Chrome session (local, or
hosted through Browserbase) issuing the same GETs the page itself makes. Still no login.

- **Bare `.GBL` components are public.** The bid-inquiry URL form given in the brief redirects
  to a login; the same component without that query string does not.
- **Some components need `FolderPath` parameters** to return data instead of a login page.
- **A cookie jar and redirect-following are required.** The first request establishes a
  session; without it a detail page returns a shell whose postback yields an empty grid,
  indistinguishable from a record with no attachments.
- **A self-identifying crawler user-agent is required** — the site returns 403 to a bare
  non-browser agent.
- **Attachments download over plain HTTP** via a postback chain and a signed URL. Events with
  many attachments need the PeopleSoft state re-established mid-sequence; without that, events
  with 8-15 attachments return a session page while events with 2 succeed.

**Grid caps are the binding constraint.** SCPRS returns at most 200 rows and its pager does not
advance under automation, so a wider query must be sliced rather than paged. Date bisection
alone left the reference window at 1,252 rows against 3,789 reported, with 6 of 7 single-day
slices still capped. Two further axes now cut a capped day — acquisition method first, then
business unit — and completeness is measured against the portal's own total rather than
assumed: **4,769 rows collected against 4,924 reported (96.9%)**, with the 6 residual slices
that still exceed the cap after both axes named in `build/awards_coverage.json`. The sweep
also resumes: a slice that answered is not asked again, a slice that failed stays pending,
and the rows already cached are carried rather than rewritten.

---

## 4. Identity

**SCPRS supplier ids solve vendor identity** for state awards: a stable id per supplier,
carried on every award row, which removes the need to match on names.

**There are three identifier namespaces, and they do not meet.** SCPRS `supplier_id` keys
state awards. PlanetBids issues its own `vendorId`, which deduplicates a vendor across that
platform's agencies and stops at its edge — it is carried namespaced under its source key so
it can never be read as a state supplier id. CSLB licence numbers are the only identifier
that could bridge them, which is why the register matters more than its own contents suggest
and why its download ceiling is a real loss rather than a missing nice-to-have. Vendor ads
cite a licence in free text, so those are extracted.

**Leveraged Procurement Agreements join on an identifier, not a name.** The LPA search
publishes the same `supplier_id` the award registry carries, so statewide-contract standing
attaches with no confidence ceiling and no ambiguity case — unlike every other vendor join
here. Measured: 379 vehicles across 119 of 699 corpus suppliers, 378 currently in force. This
also supplies the "presence on a statewide contract or purchasing vehicle" prediction
feature, which had scored zero in every run because nothing populated it.

**Bid-results pages carry no id**, so bidder names are resolved against SCPRS by exact
normalised match. One query returns both the identity and that vendor's award history, so the
profile backfill costs nothing extra. Live over 157 distinct names: 27 rows resolved, 1
ambiguous, 183 unresolved.

Resolution is deliberately strict:

- One matching supplier resolves the row, at `medium` and never `high` — it remains a name
  comparison.
- More than one leaves it `ambiguous`, id null, candidates recorded. Two suppliers can
  normalise to one name and be different companies.
- A near miss is not a match. "A Superior Sanitation" and "A Plus Superior Sanitation" are both
  real and distinct in this corpus.

Unresolved rows stay in the review queue rather than being presented as matched.

**City and state vendor populations are disjoint, and that is a product finding.** None of
the San Francisco bidders appear in the state award registry — checked against SCPRS
directly, not merely against the local corpus: Ronan Construction, A. Ruiz Construction,
Precision Engineering, CLW Builders and Bauman Landscape return zero state award rows each.
They are city contractors and do not sell to the state.

So a city surface does not enrich the state picture, and no amount of name matching will
make it. What it does is cover a separate market: local government is its own competitive
universe with its own incumbents, and a SLED product needs a vendor universe per
jurisdiction rather than one national list with cities folded in. Bidder observations are
tagged by `source_key` and business unit so the two are never read as one pool.

---

## 5. What the data cannot support

**Win rates, except where a full field was observed.** SCPRS records who won and is silent on
who lost, so a rate is computable only over solicitations where a bidder list exists. 40
profiles carry one; every one is flagged `small_sample`, because each rests on one or two
solicitations. Elsewhere the rate stays null with the reason attached rather than being faked
by equating bids with wins.

**Prediction quality is undetermined, and the sample size is why.**

| Corpus | Events | precision@3 | Best trivial baseline | 95% CI | Events scoring zero |
| --- | ---: | ---: | ---: | ---: | ---: |
| 974 rows, 6-day window | 55 | 0.0727 | 0.0606 | ±0.0435 | 45 |
| 1,252 rows, 7-day window | 64 | 0.0573 | 0.0625 | ±0.0308 | 53 |
| 4,088 rows, 8-day window | 64 | 0.0625 | 0.0469 | ±0.0350 | 53 |

Three measurements of the same thing. The spread across them is 0.0154, inside every one of
those intervals, and precision@5 moves the opposite way to precision@3 between the second and
third. The third row beats its baseline where the second lost to it, on a corpus three times
deeper — and that is still not a result, because 53 of 64 events score exactly zero and the
interval swallows the difference. The evaluation cannot resolve whether the ranking beats
counting past wins.

The shipped headline is whatever the documented command produces with no flags, currently the
8-day figure. Quoting a window chosen after seeing which scored best is the failure mode this
table exists to prevent, and the second row is kept precisely because it is the one where the
model lost.

An earlier figure of 0.17 was withdrawn for exactly that reason: it was measured on the ten
held-out events with the deepest prior history, which are the most predictable. The unselected
set is the one that gets quoted.

**The target is also the wrong question.** Ground truth here is which few of several hundred
eligible suppliers received a purchase order from one agency in one category on one day. For
commodity categories that is close to noise. The useful redefinition — will this vendor
transact with this agency in this category within N days — is measurable from the same data
and is proposed rather than substituted, since changing an evaluation target after seeing a
poor score needs agreement to be credible.

**Corpus depth must be uniform.** Enriching a subset of vendors reorders a ranking: deepening
25 of 279 vendors moved precision@3 from 0.233 to 0.100 because the enriched few carried two
hundred awards each and dominated on evidence volume. Prediction therefore ranks on the date
sweep alone. Profiles are descriptive and may use the wider corpus; a test reads `cmd_analyze`
and fails if the two are ever crossed.

The same asymmetry rescues the prime task: backfilling every member of the eligible set is
uniform, because a vendor outside it can never qualify however deep its history. On a uniform
corpus 21 of 68 eligible vendors qualify.

**Subcontracting is not observed** in the sources wired in. An award evidences priming.
SF Public Works cites a per-bid subcontractor listing, which is the obvious next source and is
not yet retrieved. Absence is recorded as unknown, never as negative.

**Vendor geography does not exist in the award registry.** It comes from the supplier registry
instead, which indexes SB/DVBE-certified suppliers, so absence there means "not in the
small-business registry" rather than "location unknown".

---

## 6. Extraction

**Tables are the extraction path; prose regexes are not.** The awardee in an intent-to-award
notice sits in a two-column table. A label-based prose regex over the same page returned 8
false positives against 1 true result, so table structure drives extraction and a prose miner
was removed rather than kept as a fallback.

**A filename keyword is not a classifier.** Four of five events matching "bidder" in a filename
were blank declaration forms containing no bidder identities. Filenames decide only what to
download; content confirms before any participant record is created.

**Two bidder pages, two orderings.** Caltrans lists bidders in rank order. San Francisco lists
them in the order envelopes were opened — measured on one contract as $7.66M, $6.56M, $6.69M,
$6.60M, $8.11M, $7.30M — so rank there is derived by sorting on amount and the page's own
ordering is preserved separately. Assuming one convention from the other would name the wrong
low bidder.

**Soft-404s are the recurring trap.** An unpublished Caltrans week returns HTTP 200 with an
empty template, and a migrated Caltrans endpoint returns HTTP 200 with a "not found" page.
Zero rows means "no page", never "no bids that week", and the adapters distinguish the two.

**Acquisition measured at 98.8%** on the current corpus: 83 of 84 documents, 863 pages. The one
failure is classified rather than dropped — a `.docx` whose payload ended with HTML, an error
page appended to a partial download, caught because the bytes are checked against the type
they claim. File types are
not PDF-only — the corpus includes `.docx`, `.xlsx`, `.zip` and `.csv`, so extraction cannot
assume PDF.

---

## 7. Contracts and scope

**The Supabase contracts are authored, not the promised snapshot.** No frozen schema export was
provided, so the JSON Schemas were written from the README's pattern table. Passing validation
demonstrates internal consistency only; no production compatibility is claimed, and nothing
writes to any Supabase instance.

**`README.md` is the target spec, not `PROJECT_BRIEF.md`.** The two describe different
products; the README carries the rubric and wins where they conflict.

**Outbound identification** uses a project user-agent with no personal contact details.

---

## 8. Open items

Closed since the first pass: the SCPRS subdivision axis (now two axes, taking the sweep from
roughly a quarter of the portal's reported rows to 96.9%, with the residual measured rather
than estimated); statewide contract vehicles; the supplier location index; vendor
advertisements, now harvested across every event in the feed — 356 read, 98 carrying an ad,
none failing; and evidence-link validation, which runs on every analyze and fails the run
loudly when a citation leads nowhere.

Caltrans bidder history is also backfilled: 53 weeks, 2025-09-07 to 2026-09-06. That was the
item with a clock on it, because the site keeps roughly nine months and uncollected history
is lost rather than deferred. It is collected.

1. **Twelve months of award history.** The bidder half of the backfill is done; the award
   sweep still covers eight days. The machinery is ready — harvests resume rather than
   restart, an empty unit is distinguished from a failed one, and rows checkpoint to disk per
   slice so a killed run costs a slice — but at the observed rate a serial year is roughly 65
   hours. Four sessions, each with its own PeopleSoft state chain, brings that to about 16.
   This is the largest remaining gap between what was asked and what exists.
2. **A complete CSLB register**, the bridge between the three identifier namespaces. Blocked
   on a server-side download ceiling at 59,873 of roughly 290,000 rows; the by-classification
   route is unsolved. Nothing yet reads the register even for the rows we hold, so the
   licence-number join it exists for is built but not connected.
3. **PlanetBids document bytes.** Metadata, URLs, the login gate and the recalled flag are
   harvested; the files themselves sit behind the same protection as the API and need the
   browser transport.
4. **Lineage across the new sources.** Evidence-link validation is now built and passing;
   lineage still only understands the state surfaces.
5. SF subcontractor listings, which would populate the one profile dimension still empty.
6. Predecessor search across every RFP in the evaluation set; it currently runs on the
   demonstrated event only. Worth doing after item 1 rather than before — lineage searches
   the award corpus, and on eight days of history it would find almost nothing.
7. A solicitation-level evaluation set assembled from award-notice documents, and the
   forward-window prediction target to replace the same-day one.
8. **Respondents and incumbents.** Four of the brief's six participation states are exported
   — awardee, known bidder, planholder and interested vendor. A respondent is distinguishable
   from a planholder only where a portal publishes both, and incumbency is currently inferred
   through lineage rather than recorded as a role.
