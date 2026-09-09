# Data sources

Two links are given where they differ: the **human page** you can open in a browser,
and the **machine endpoint** the pipeline calls. They are not the same. The browser
pages are JavaScript shells that carry no data; the endpoints are the PeopleSoft
components underneath them, which serve complete data anonymously. That distinction
took the most time and is the most important thing in the document below.

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


## Verified, not yet wired in

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
- **Gaps and caveats:** POPULATES THE 'presence on a statewide contract or purchasing vehicle' PREDICTION FEATURE, which predict.py scores but has always evaluated to zero. Joins on identifier rather than name - the only surface besides SCPRS where that is true.

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


## Blocked or unresolved

### Response Bid Inquiry (respondent fields)

- Endpoint we call: `https://caleprocure.ca.gov/psc/psfpd1/SUPPLIER/ERP/c/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL?page=AUC_RESP_INQ_AUC`
- Provides: responses/bidders
- Access: manual-only
- Login required: YES - 302 to ?cmd=login&errorPg=ckreq
- When it becomes public: not publicly disclosed anonymously
- History available: unknown
- Stable identifiers: unknown
- Verified: 2026-09-07
- **Gaps and caveats:** This is the answer to the brief's central question: California does not publicly disclose bidder identities here. Fallback is bid-tabulation and intent-to-award PDFs posted as event attachments, then SCPRS awardees, then expenditure-derived participation.

### Purchase Order Data (DGS) - historical inference corpus

- Endpoint we call: `https://data.ca.gov/dataset/purchase-order-data`
- Provides: awards/purchase orders
- Access: API (datastore_search_sql) - ROBOTS CONFLICT, see constraints
- Login required: no
- When it becomes public: published extract
- History available: FY2012-13 to FY2014-15 (~11 years stale)
- Stable identifiers: resource id bb82edc5-9c78-44e2-8947-68ece26197c5; Supplier Code; Purchase Order Number
- Verified: 2026-09-07
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


## Dead ends, recorded so they are not retried

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

### Public .aspx search pages (InFlight/NLX wrapper) - DO NOT USE

- Endpoint we call: `https://caleprocure.ca.gov/pages/public-search.aspx`
- Provides: n/a
- Access: browser-only
- Login required: no
- When it becomes public: n/a
- History available: n/a
- Stable identifiers: n/a
- Verified: 2026-09-07
- **Gaps and caveats:** RECORDED AS A DEAD END so it is not retried. These wrap the PeopleSoft components above - always target the .GBL component directly


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

