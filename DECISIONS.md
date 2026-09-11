# Decisions and findings

What the California public record actually supports, what it does not, and why the code is
shaped the way it is. Organised by subject rather than by date.

---

## 1. The central question: who bid?

**Cal eProcure does not publish bidder lists.** The Response Bid Inquiry component — the one
surface that would name respondents — redirects to a login. No planholder lists, no bid
results, no pre-bid attendance records are public there.

**California does publish them, agency by agency.** That is the finding the trial turned on,
and it is narrower and more useful than the negative:

| Surface | What it gives | Scale |
| --- | --- | --- |
| Caltrans weekly bid results | Every bidder, ranked, with amount and Small Business status | 81 of 359 active events; 211 observations over 13 weeks |
| SF Public Works tabulations | Every bidder, local-business status, price, **engineer's estimate** | 21 observations; 4 of 4 named more than one bidder |
| Award-notice PDFs on Cal eProcure events | The awardee and the winning amount | 1 observation |

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

**PlanetBids — blocked.** Hundreds of California cities and counties use it, and it exposes
bid results and plan-holder lists. Every portal URL redirects to an AWS WAF human-verification
challenge, which appears with an ordinary desktop browser user-agent, and `robots.txt` returns
a maintenance page rather than a robots file, so no crawl permission can be read from the site
at all. A CAPTCHA-class control is one the brief and `SECURITY.md` both forbid working around.
Compliant routes: a person reading a portal, an agency granting access on request, or a public
records request. This is the largest source that remains out of reach.

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

Everything the pipeline uses is anonymous HTTP. No browser, no API key, no credential.

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
advance under automation, so a wider query must be sliced rather than paged. On the reference
window 6 of 7 date slices still hit the cap: **1,252 rows collected against 3,789 the portal
reported.** `build/awards_coverage.json` records which slices fell short and by how much. The
remedy is a second subdivision axis, not a wider window — widening only adds days that cap in
turn. Not yet implemented.

---

## 4. Identity

**SCPRS supplier ids solve vendor identity** for state awards: a stable id per supplier,
carried on every award row, which removes the need to match on names.

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
who lost, so a rate is computable only over solicitations where a bidder list exists. 24
profiles carry one; every one is flagged `small_sample`, because each rests on one or two
solicitations. Elsewhere the rate stays null with the reason attached rather than being faked
by equating bids with wins.

**Prediction quality is undetermined, and the sample size is why.**

| Corpus | Events | precision@3 | Best trivial baseline | 95% CI | Events scoring zero |
| --- | ---: | ---: | ---: | ---: | ---: |
| 974 rows, 6-day window | 55 | 0.0727 | 0.0606 | ±0.0435 | 45 |
| 1,252 rows, 7-day window | 64 | 0.0573 | 0.0625 | ±0.0308 | 53 |

The gap between the two is 0.0154, inside either interval, and precision@5 moves the other
way. These are the same measurement twice. At this size, with four fifths of events scoring
zero, the evaluation cannot resolve whether the ranking beats counting past wins. The shipped
headline is the 7-day figure because that is what the documented command produces with no
flags; quoting the other would mean choosing a window after seeing which scored better.

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

**Acquisition measured at 100%** on the current corpus: 84 documents, 863 pages. File types are
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

1. A second SCPRS subdivision axis, so the award sweep stops losing two thirds of its rows.
2. Vendor advertisements — the strongest forward-looking signal California exposes.
3. SF subcontractor listings, which would populate the one profile dimension still empty.
4. Predecessor search across every RFP in the evaluation set; it currently runs on the
   demonstrated event only.
5. A solicitation-level evaluation set assembled from award-notice documents, and the
   forward-window prediction target to replace the same-day one.
