# Data sources

Every California surface this pipeline touches, what it provides, and whether we can
actually use it. `sources/source_registry.csv` holds the full 18-field access research for
each one and is the source of truth; a test fails if a registry row is missing here.

Two links are given where they differ: the **human page** you can open in a browser,
and the **machine endpoint** the pipeline calls. They are not the same. The browser
pages are JavaScript shells that carry no data; the endpoints are the PeopleSoft
components underneath them, which serve complete data anonymously. That distinction
cost a day to find and is the single most useful thing in this document.

## In active use

### Active event list (PeopleSoft AUC_RESP_INQ_AUC)

- Browser page: https://caleprocure.ca.gov/pages/Events-BS3/event-search.aspx
- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL`
- Provides: solicitations
- Access: HTML (server-rendered PeopleSoft component)
- Login required: no
- When it becomes public: at advertisement
- History available: none - active-only feed
- Stable identifiers: (business_unit, event_id) - 375/375 unique; event_id format varies
- Verified: 2026-09-07
- **Gaps and caveats:** active-only, so disappearance is the ONLY closure signal - a failed run must record 'no signal', never 'all closed'. No attachments in this response

### Event detail (AUC_RESP_INQ_DTL)

- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_DTL.GBL?Page=AUC_RESP_INQ_DTL&Action=U&AUC_ID=<id>&AUC_ROUND=1&BIDDER_ID=BID0000001&BIDDER_LOC=1&BIDDER_SETID=STATE&BIDDER_TYPE=B&BUSINESS_UNIT=<bu>`
- Provides: solicitations
- Access: HTML (deterministic GET, no postback)
- Login required: no
- When it becomes public: at advertisement
- History available: current event only
- Stable identifiers: (business_unit, event_id); AUC_VERSION for change detection
- Verified: 2026-09-07
- **Gaps and caveats:** attachment filenames are NOT in this HTML; addendum history is free text needing parsing

### Event attachments (package postback + signed view URL)

- Endpoint we call: `POST .../AUC_RESP_INQ_DTL.GBL ICAction=RESP_INQ_DL0_WK_AUC_DOWNLOAD_PB then ICAction=PV_ATTACH_WRK_SCM_DOWNLOAD$N then GET the window.open URL`
- Provides: documents
- Access: HTML postback chain + signed GET (plain HTTP, no browser)
- Login required: no
- When it becomes public: at advertisement; addenda as issued
- History available: per event
- Stable identifiers: filename + SHA-256; CS_AUC_WRK_CS_VERSION per row
- Verified: 2026-09-07
- **Gaps and caveats:** signed view URL is per-request and not durable, so it cannot be cached as a permanent locator. Grid uses double-quoted attributes unlike the rest of the page - a single-quote regex returns zero rows and mimics 'no attachments'. Filename-prefix role convention unvalidated beyond one agency

### SCPRS award registry (ZZ_PO.ZZ_SCPRS1_CMP)

- Browser page: https://caleprocure.ca.gov/pages/SCPRSSearch/scprs-search.aspx
- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/ZZ_PO.ZZ_SCPRS1_CMP.GBL?FolderPath=PORTAL_ROOT_OBJECT.ZZ_FISCAL_SCPRS.ZZ_SCPRS1_CMP_GBL&IsFolder=false&IgnoreParamTempl=FolderPath%2cIsFolder`
- Provides: awards/contracts
- Access: HTML (GET then search POST with ICSID/ICStateNum)
- Login required: no
- When it becomes public: after award registration
- History available: SFY2010 onward per DGS
- Stable identifiers: purchase_doc; supplier_id (canonical vendor key)
- Verified: 2026-09-07
- **Gaps and caveats:** pagination past row 200 unresolved (NEXT control does not advance under automation); workaround is date/department slicing. No bidder set, only awardees

### Department vendor transactions (bulk CSV)

- Browser page: https://open.fiscal.ca.gov/dept_vendor_transaction.html
- Endpoint we call: `https://open.fiscal.ca.gov/dept_vendor_transaction.html`
- Provides: expenditures
- Access: download (direct CSV via published pointer manifest)
- Login required: no
- When it becomes public: after accounting period close
- History available: FY16-FY25 (10 years)
- Stable identifiers: business_unit; document_id
- Verified: 2026-09-07
- **Gaps and caveats:** payments only - no bidders, no solicitation ids. VENDOR_NAME truncated ~30 chars, so join to SCPRS supplier_id by name with low confidence. document_id is a FI$Cal voucher ref; join to SCPRS purchase_doc UNPROVEN. 10.6GB total, selective fetch required

### Weekly bid results (all bidders, ranked)

- Endpoint we call: `https://dot.ca.gov/programs/procurement-and-contracts/bid-results`
- Provides: bidders
- Access: HTML (one static page per week)
- Login required: no
- When it becomes public: within about 20 minutes of the public bid opening, held Tuesdays and Thursdays
- History available: rolling window; measured populated back to the week of 2025-12-14, empty at 2025-10-12
- Stable identifiers: contract number = Cal eProcure event_id under business_unit 2660; join is string equality, not inference
- Verified: 2026-09-09
- **Gaps and caveats:** Caltrans only, so no coverage of the other 278 events in the feed. Results are PRELIMINARY, pending SB/DVBE, licensing and bonding verification, so the low bidder is not necessarily the awardee. No supplier_id on the page, so identity resolution is a name match. Unpublished weeks answer HTTP 200 with an empty template rather than 404

### Bid tabulations attached to commission award items

- Endpoint we call: `https://sfpublicworks.org/about/public-works-commission-calendar`
- Provides: bidders
- Access: document (PDF attachment discovered from commission pages)
- Login required: no
- When it becomes public: when the award item is posted; the tabulation starts the five-working-day protest period
- History available: as far back as commission pages are linked; 29 meeting folders referenced from the calendar
- Stable identifiers: SF sourcing id (e.g. 0000007165). NOT a Cal eProcure event: SF is a city and absent from the state portal, so there is no state join
- Verified: 2026-09-09
- **Gaps and caveats:** Discovery is the weak point: the calendar links mostly minutes and agendas, so a full backfill needs meeting-page URLs supplied. Bidders are listed in the order opened, NOT by price, so rank is derived from amount. A tabulation precedes responsibility review, so the low bidder is not yet the awardee. SF vendors carry no state supplier_id, so identity cannot resolve against SCPRS

### Supplier search (ZZ_PO.ZZ_PUBSRCH)

- Browser page: https://caleprocure.ca.gov/pages/PublicSearch/supplier-search.aspx
- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/ZZ_PO.ZZ_PUBSRCH.GBL`
- Provides: suppliers/certifications/location
- Access: HTML (bare .GBL, then ICAction=ZZ_PUBSRCH1_WRK_BUTTON)
- Login required: no
- When it becomes public: on registration/certification
- History available: current state only
- Stable identifiers: supplier name; certification id (no supplier_id observed in results)
- Verified: 2026-09-09
- Wired in: `suppliers` command -> `supplier_locations.json` -> `vendors.attach_location`
- **Gaps and caveats:** ANSWERS THE GEOGRAPHY GAP - city, postal code and street address per supplier. Component is titled 'Custom Component for SB orDVBE' so coverage may be limited to certification-registered suppliers rather than all state suppliers; must be measured. No supplier_id in results, so the join to SCPRS is by name and inherits that weakness.

### Leveraged Procurement Agreement search (ZZ_PO.ZZ_CNT_SRC_CMP_BKP)

- Browser page: https://caleprocure.ca.gov/pages/LPASearch/lpa-search.aspx
- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/ZZ_PO.ZZ_CNT_SRC_CMP_BKP.GBL`
- Provides: contracts/purchasing vehicles
- Access: HTML (bare .GBL, then ICAction=ZZ_CTR_SRC2_WRK_SEARCH_BTN)
- Login required: no
- When it becomes public: on award of the vehicle
- History available: active vehicles with expiry dates
- Stable identifiers: CNTRCT_ID (matches SCPRS lpa_contract); VENDOR_ID1 (matches SCPRS supplier_id)
- Verified: 2026-09-09
- Wired in: `lpa` command -> `lpa_vehicles.json` -> `vendors.attach_vehicles`, which feeds the `vehicle_presence` prediction feature
- **Gaps and caveats:** POPULATES THE 'presence on a statewide contract or purchasing vehicle' PREDICTION FEATURE, which predict.py scores but has always evaluated to zero. Joins on identifier rather than name - the only surface besides SCPRS where that is true.


## Verified, not yet harvested

### Event vendor ads (Prime Seeking Sub / Sub Seeking Prime)

- Endpoint we call: `POST .../AUC_RESP_INQ_DTL.GBL with ICAction=ZZ_VNDR_AD_WRK_VENDOR_DETAILS_PB`
- Provides: declared interest
- Access: HTML via postback
- Login required: no
- When it becomes public: when the ad is placed
- History available: ad create/update timestamps
- Stable identifiers: joins on (ZZ_VNDR_AD_TBL_BUSINESS_UNIT, ZZ_VNDR_AD_TBL_AUC_ID)
- Verified: 2026-09-07
- **Gaps and caveats:** ONLY CA source tying a named company to a specific solicitation. But: contact is a person, no supplier_id, company name only in free text -> fuzzy match to SCPRS. Generic bid-assistance ads recur across unrelated events and must be discounted

### FI$Cal Payment Progress Search (ZZ_PO.ZZ_PMNTSRCH_PG)

- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/ZZ_PO.ZZ_PMNTSRCH_PG.GBL?PORTALPARAM_PTCNAV=ZZ_PMNTSRCH_PG_GBL&EOPP.SCNode=ERP&EOPP.SCPortal=SUPPLIER&EOPP.SCName=ADMN_PUBLIC_SEARCH&EOPP.SCPTcname=PT_PTPP_SCFNAV_BASEPAGE_SCR&FolderPath=PORTAL_ROOT_OBJECT.PORTAL_BASE_DATA.CO_NAVIGATION_COLLECTIONS.ADMN_PUBLIC_SEARCH.ADMN_S201504300556127137858824&IsFolder=false`
- Provides: payments
- Access: HTML
- Login required: no
- When it becomes public: after payment
- History available: unknown
- Stable identifiers: purchase order number; supplier name
- Verified: 2026-09-07
- **Gaps and caveats:** distinguishes holding a contract from being actively paid under it - real incumbency corroboration. Field extraction still to map


## Tested negatives and unreachable hosts

### Response Bid Inquiry (respondent fields)

- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL?page=AUC_RESP_INQ_AUC`
- Provides: solicitations (NOT respondents - see below)
- Access: HTML (bare .GBL and `?page=` form; both public)
- Login required: no - and signing in is actively worse
- History available: same active-only window as the main feed
- Verified: 2026-09-10, with a registered supplier login
- **The answer to the brief's central question, now tested rather than inferred.**
  Cal eProcure does not disclose other bidders' identities here, authenticated or not:
  - As a guest the grid columns are Department / Event ID / Event Name / Format / Type /
    End Date / Status / Buyer Name / Buyer Email. No respondent column, and no respondent
    field id anywhere in the page. It returns 356 events against the 375 the `.GBL` feed
    already gives, with the same field set - so it adds nothing the pipeline lacks.
  - Signed in as a registered supplier the landing page is unchanged.
  - Signing in **breaks** the event detail the pipeline depends on. That URL carries
    `BIDDER_ID=BID0000001`, the generic Default Bidder, and an authenticated session is
    rejected with `Invalid User Information BID0000001/B`. Dropping the bidder parameters
    yields PeopleSoft's component search dialog rather than the event.
  This is PeopleSoft Strategic Sourcing working as intended - a bidder inquires about its
  own responses, not anyone else's - so **the pipeline should stay anonymous**, and the
  earlier 302-to-login was not reproduced.
- **Where bidder identities actually come from:** `caltrans_bid_results` publishes the
  full ranked field, losers included, for business unit 2660; then bid-tabulation and
  intent-to-award PDFs posted as event attachments; then SCPRS awardees.

### Purchase Order Data (DGS) - historical inference corpus

- Endpoint we call: `https://data.ca.gov/dataset/purchase-order-data`
- Provides: awards/purchase orders
- Access: download (CKAN resource CSV; NOT the datastore API)
- Login required: no
- When it becomes public: published extract
- History available: FY2012-13 to FY2014-15 (~11 years stale)
- Stable identifiers: resource id bb82edc5-9c78-44e2-8947-68ece26197c5; Supplier Code; Purchase Order Number
- Verified: 2026-09-10
- **Access note:** `robots.txt` disallows `/api/` and `/datastore/*`, so the
  `datastore_search_sql` route stays off. `/dataset/*/resource/*/download/*` is not
  disallowed and is the route to use. `Crawl-delay: 10` applies, well above our default.
- **Gaps and caveats:** ~11 years stale - inference corpus only, never a current-incumbent source; age must enter confidence. Total Price is text with $ and padding so sums need cleaning

### PeopleSoft components on the backend host

- Endpoint we call: `https://suppliers.fiscal.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/ZZ_PO.ZZ_SCPRS1_CMP.GBL`
- Provides: contracts/payments
- Access: unreachable
- Login required: unknown
- When it becomes public: unknown
- History available: unknown
- Stable identifiers: unknown
- Verified: 2026-09-07
- **Gaps and caveats:** Not needed: caleprocure.ca.gov reverse-proxies the same application, so the backend host is redundant. Retained so the timeout is not re-investigated.


## Reachable, but only with a rendered page

Plain HTTP gets a shell or a refusal from these; a real browser gets the data. That is
being the client the site expects rather than defeating anything - see the anti-bot
clause in `SECURITY.md`.

### Public .aspx search pages (InFlight/NLX wrapper)

- Browser page: `https://caleprocure.ca.gov/pages/public-search.aspx`
- Provides: solicitations, suppliers
- Access: rendered page (SPA; plain HTTP returns a shell with no data)
- Login required: no
- Verified: 2026-09-10
- **Gaps and caveats:** previously recorded as a dead end, on the correct observation that
  plain HTTP returns 50KB of markup and no data. With a browser it renders 235 distinct
  events - but that is fewer than the 375 the `.GBL` feed returns, and every row on the
  first page reads `Posted`, so it neither replaces the feed nor supplies the closure
  signal the feed lacks. Wrapped components should still be targeted directly. Reading it
  needs a wait for an *attached* row node: `wait_until` alone races the XHR that fills the
  grid, and the unrendered template parses cleanly as a page with zero results.

### Per-agency vendor portal (bid opportunities, results, planholders)

- Browser page: https://pbsystem.planetbids.com/portal/<companyId>/bo/bo-search
- Provides: solicitations/bidders/awards
- Access: rendered page (SPA; plain HTTP returns 405)
- Login required: no for public stages; an account only for by-invite solicitations
- Verified: 2026-09-10
- **Why it matters:** the largest bidder-list corpus in California local government, and
  the one platform whose own vendor documentation says planholder lists and bid results
  are public without a login. Read end to end on Anaheim (`14424`): 136KB, 62 rows, with a
  stage filter exposing Planning / Bidding / Closed / Award Pending / Awarded / Canceled /
  Rejected.
- **Gaps and caveats:** decentralised - one portal per agency keyed by a numeric
  `companyId`, with no public master directory, so the agency list is curated rather than
  discovered. `vendors.planetbids.com` and `pbsystem.planetbids.com` serve the same app.
- **Terms, read 2026-09-10** at `home.planetbids.com/terms-and-conditions` (the
  `/terms-of-use/` path 302s to a host returning 405; the working link is in the portal
  footer). There is **no anti-scraping, robots, crawler or automated-access clause** — the
  method is not restricted. The constraint is on *purpose*, §6: *"Users may print and
  download portions of the materials solely in connection with the use of the Services
  provided on this website… User shall not reproduce, duplicate, copy, sell, resell or
  exploit for any commercial purpose the Services, website content or PlanetBids Tools."*
  A commercial intelligence product plausibly falls inside that, so a wide sweep is a
  business decision rather than an engineering one. The terms name their own remedy: a
  special-use request to `customerservice@planetbids.com`. Counterpoint for whoever
  decides: the underlying bid results are government public records held by the agencies
  and obtainable from them directly.

### CSU public bid portal

- Endpoint we call: https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=CalState
- Provides: solicitations across 23 campuses and the Chancellor's Office, since 2020
- Access: HTML, plain GET, one tab per lifecycle stage
- Login required: no to list; a supplier login for the event detail
- Verified: 2026-09-10
- **Gaps and caveats:** solicitations only. The Award tab marks a row `Awarded` but the
  awardee is named nowhere in the public listing, and the detail behind each row
  redirects to a JAGGAER supplier login. So this widens the education opportunity
  picture and adds nothing to the competitive one. Attribute quoting is mixed here as
  it is on the PeopleSoft surfaces: a single-quote-only pattern parses the live page to
  zero rows, which reads as "this tab has no solicitations".

### Master list of California licensed contractors

- Endpoint we call: https://www.cslb.ca.gov/onlineservices/dataportal/ContractorList
- Provides: vendor identity — the licence number is the one id that crosses the bidder
  sources, which otherwise publish names only or a platform id that stops at its edge
- Access: download, ASP.NET postback, chunked CSV. No charge, no login
- Verified: 2026-09-10
- **Gaps and caveats:** the transfer is cut short every run, and twelve attempts
  plateau at 48,000-65,000 rows and roughly 20MB against a register of about 290,000.
  That is a server-side ceiling rather than flakiness, and retrying harder was measured
  and does not help: best of four attempts was 64,767 rows, best of twelve was 59,873.
  The file is held under a `.PARTIAL` name and never promoted. The fragment is ordered by licence number, so it is a front slice biased to
  older licences rather than a sample. The portal also offers lists by classification
  (78 values, up to ten per download) and by county, which would give files small enough
  to complete; that form posts a multi-select listbox and the flow is not yet worked out.
  Cancelled and revoked licences are excluded throughout, so absence means "not currently
  licensed", not "never existed".

### LA County Public Works bid results and bid price history

- Endpoint we call: https://dpw.lacounty.gov/contracts/Opportunities.aspx?phase=AWARDED
- Provides: awarded solicitations; a per-project bid-results PDF naming the full field
- Access: plain HTML, then `BidResults.aspx?project_id=` which returns the PDF directly
- Verified: 2026-09-10
- **Deferred, on yield.** The chain works and needs no browser, and one PDF read cleanly:
  `NAME OF BIDDER`, lump-sum bid, alternates, LSBE/DVBE/SE preference, engineer's
  estimate, and a "Lowest Bidder" marker. But only 1 of 12 sampled awarded projects
  served a PDF at all — the rest return a ~950-byte stub — and the county has moved
  current work to Bid Express, so the self-hosted results are a shrinking tail. The
  layout is a wide landscape table that varies between projects, so a pattern tuned to
  one returns zero bidders on another. For comparison, PlanetBids returned 521 bidders
  from 120 solicitations as structured JSON.
- **Worth revisiting separately:** Bid Price History (`/general/bph/`) is a different and
  richer surface — number of bids received per project, and line-item engineer's estimate
  against low-bidder unit prices via `ProjectDetails.aspx?project_id=&bid_date=`.

### City of Sacramento Bid Activities Report

- Endpoint we call: https://services5.arcgis.com/54falWtcpty3V47Z/arcgis/rest/services/BidActivitiesReport/FeatureServer/0
- Provides: solicitations with competitive-intensity counts
- Access: ArcGIS FeatureServer query — typed JSON, no scraping and no browser
- Verified: 2026-09-10 — 395 of 395 collected, reconciled against the layer's own count
- **Counts, not names.** Each solicitation carries how many vendors were notified, how
  many became prospective bidders, and how many of those were local. Nothing here joins
  to a vendor. Only 34 rows carry an award amount.
- **Worth having anyway:** the local share is the only measure in the corpus of how much
  of a field an agency draws from its own city, and Sacramento publishes it directly
  rather than leaving it to be inferred from bidder addresses.

### University of California procurement

- Endpoint we call: none — https://procurement.ucop.edu/suppliers/how-become-uc-supplier
  is guidance, not a listing
- Verified: 2026-09-10 (systemwide, Berkeley, UCLA; UCSF and the UCOP supplier page
  refused the request)
- **No systemwide public bid portal exists.** This is the asymmetry worth recording: CSU
  runs one public Jaggaer portal covering all 23 campuses, and UC does not. Berkeley runs
  Jaggaer as BearBuy, but that is an internal purchasing tool rather than a public bid
  board. Covering UC would mean one adapter per campus, for solicitations only — none of
  the campus routes checked publishes bidders.

### San Bernardino County bid results

- Endpoint we call: https://res.sbcounty.gov/project-management/bid-results/
- Verified: 2026-09-11 — **unreachable, not unavailable.** Both county hosts refused the
  connection on every attempt, as several county hosts did in the earlier survey. That is
  a fact about this machine's route as much as about the county, so it is recorded as
  unmeasured rather than written off.
- **Why it is worth retrying from another network:** the county reportedly posts full
  scanned bid tabulations listing every bid received, within three business days of
  opening. That would be the highest-fidelity per-project bidder source surveyed. Scanned
  PDFs would need the OCR path rather than native extraction.

## Dead ends, recorded so they are not retried

### Planholder search, advertised projects and addenda

- Endpoint we call: https://ppmoe2.dot.ca.gov/des/oe/planholders/
- Provides: planholders/solicitations
- Access: unreachable (403)
- Verified: 2026-09-10
- **Gaps and caveats:** would be the highest-value state surface after the Caltrans weekly
  bid results, since planholders name companies against a named contract, and Caltrans
  contract numbers are Cal eProcure event ids under business unit 2660. Refuses with 403
  to plain HTTP, to a full browser header set, to local Chrome, and to a hosted browser
  from a different address - so the block is neither user-agent nor address shaped.
  Compliant routes left: ask Caltrans Office of Engineering directly, or a records request.

### SCPRS/CSCR historical contracts data

- Endpoint we call: `https://www.dgs.ca.gov/en/PD/Resources/Page-Content/Procurement-Division-Resources-List-Folder/SCPRS-CSCR-Historical-Contracts-Data`
- Provides: contracts/awards
- Access: manual-only (email request)
- Login required: no
- When it becomes public: n/a
- History available: pre-2015 on request
- Stable identifiers: n/a
- Verified: 2026-09-07
- **Gaps and caveats:** README treats this as a bulk seed; it is not one any more. Use SCPRS live search + data.ca.gov corpus instead



## How to reach the PeopleSoft endpoints

Three things are non-obvious and each one looked like a permission failure:

1. **Use the bare `.GBL` component.** The URL form given in the brief for the bid
   inquiry, `...AUC_RESP_INQ_AUC.GBL?page=AUC_RESP_INQ_AUC`, redirects to a login.
   The same component without that query string does not.
2. **Some components need `FolderPath` parameters to be public.** The award registry
   returns a login page without them and full data with them.
3. **Follow redirects and keep a cookie jar.** The first request establishes a session;
   without it a detail page returns a shell whose postback yields an empty grid, which
   is indistinguishable from a record that genuinely has no attachments.

A self-identifying crawler user-agent is required — the site returns 403 to a bare
non-browser agent — but no browser, API key or credential is needed anywhere.

