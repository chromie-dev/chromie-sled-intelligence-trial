# Trial data boundary

Allowed: repository fixtures, generated outputs, and publicly accessible procurement
sources documented in `sources/source_registry.csv`.

Forbidden: Chromie production/staging databases, Supabase projects, internal APIs,
customer files, customer prompts, secrets, production schemas, copied database dumps, and
Chromie employee credentials for Chromie systems.

Do not request production access. Do not add secrets to git. A public-source adapter must
be optional and must store its raw response outside git.

## Portal access

Updated 2026-09-10. Coverage beyond Cal eProcure was authorised by the reviewer, who
supplied a Browserbase key and a read-only PlanetBids account and asked that bot
detection not be treated as a stopping point. The earlier rule — stop if a source
requires a login — is replaced by the four below. The other three clauses stand unchanged.

**Login: allowed.** Prefer an account we register ourselves under our own identity, which
is free on most procurement portals. Use a supplied third-party account only where
self-registration is not available. Credentials live in `.env` and nowhere else.

**Payment: stop and document.** Unchanged. This currently excludes California Secretary
of State bulk entity data ($100) and paid depth tiers on aggregator platforms.

**Anti-bot controls: read as a real browser, do not defeat the check.** Most blocks we hit
were a site refusing a non-browser client, not a challenge — a fuller header set or a real
Chrome session resolves them, and that is being the expected client rather than evading
anything. Where a human-verification challenge does appear, a person may complete it once
through a live browser session. Do not add CAPTCHA-solving services, or stealth and
fingerprint-spoofing plugins whose purpose is to make automation read as human. If a
source cannot be read without one, that is a finding to report, not a control to work
around.

**Terms-violating automation: stop and document.** Unchanged. Check each portal's terms
before pointing an adapter at it and record the finding in the `terms_access_constraints`
column of `sources/source_registry.csv`, whether or not an adapter gets built. `robots.txt`
is a stated crawl policy rather than a bot-detection measure, so nothing above overrides
it.

## Operating rules

**Read-only.** Adapters retrieve and parse. Nothing submits a bid or a form, uploads,
registers, or changes state on a portal. The browser transport exposes retrieval only.

**Credentials stay in `.env`.** Never in git, fixtures, logs, screenshots, generated
outputs under `build/`, or the source registry. Browser session recording is disabled for
authenticated sessions, since a login replay captures a password field. A test asserts no
secret name or value appears in generated output.

**Rate limits are respected.** The default inter-request delay applies to every transport,
browser sessions included.
