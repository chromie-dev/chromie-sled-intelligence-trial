"""Command line entry point.

    python -m sled_trial.cli events    --output build
    python -m sled_trial.cli documents --event 2740/0000040075 --output build
    python -m sled_trial.cli analyze   --opportunity data/examples/active_opportunity.json \
                                       --download-documents --output build

`analyze` is the deliverable command named in the project README. It is assembled from the
subcommands above as each stage lands, so partial output is real output rather than a stub.
"""
from __future__ import annotations

import argparse
import collections
import functools
import json
import pathlib
import sys
from typing import Any

from . import (assemble, documents, evidence, extract, harvest_state,
               sources)
from .assemble import (ENRICHMENTS, _opportunity_intelligence, _participants,
                       _read_jsonl, _source_coverage)
from .sources.ca import caleprocure as ca

DEFAULT_RAW = "data/raw/documents"


def _session(args: argparse.Namespace) -> ca.CalEProcureSession:
    """The Cal eProcure transport for every state command.

    Not swappable for a browser: these components are driven by PeopleSoft postbacks that
    carry an ICStateNum chain, which `CalEProcureSession` maintains and a page-navigation
    transport cannot. Sources that only need to read a rendered page take a fetcher from
    `sled_trial.net.build_fetcher` instead.
    """
    return ca.CalEProcureSession(delay_seconds=args.delay,
                                 browser_headers=args.browser_headers)


def _event_pairs(values: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        if "/" not in value:
            raise argparse.ArgumentTypeError(
                f"--event expects BUSINESS_UNIT/EVENT_ID, got {value!r}")
        bu, _, eid = value.partition("/")
        if not bu or not eid:
            raise argparse.ArgumentTypeError(f"--event malformed: {value!r}")
        pairs.append((bu, eid))
    # identity is the pair, and the same event id can recur across agencies
    return list(dict.fromkeys(pairs))


def cmd_events(args: argparse.Namespace) -> int:
    session = _session(args)
    rows = ca.parse_event_list(ca.fetch_event_list(session))
    if not rows:
        print("no events parsed -- refusing to write an empty feed", file=sys.stderr)
        return 1
    out = pathlib.Path(args.output) / "events.jsonl"
    written = documents.write_jsonl(rows, out)
    incomplete = [r for r in rows if len(r) != len(ca.EVENT_FIELDS)]
    keys = {(r["business_unit"], r["event_id"]) for r in rows}
    print(f"events: {written} -> {out}")
    print(f"  agencies: {len({r['agency'] for r in rows})}")
    print(f"  unique (business_unit, event_id): {len(keys)}/{len(rows)}")
    print(f"  rows missing a field: {len(incomplete)}")
    return 0


def cmd_documents(args: argparse.Namespace) -> int:
    pairs = _event_pairs(args.event)
    session = _session(args)
    store = documents.DocumentStore(args.raw_root)
    manifest: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    for bu, eid in pairs:
        try:
            docs = ca.fetch_attachments(session, bu, eid)
        except Exception as exc:  # a portal shape change must not abort the whole run
            manifest.append(assemble.enumeration_failure_row(bu, eid, exc))
            print(f"  {bu}/{eid}: enumeration failed ({type(exc).__name__})", file=sys.stderr)
            continue
        rows, page_rows = documents.process_event_documents(
            docs, store=store, allow_ocr=not args.no_ocr)
        manifest += rows
        pages += page_rows
        ok = sum(1 for r in rows if r["download_status"] == "downloaded")
        print(f"  {bu}/{eid}: {len(rows)} documents, {ok} downloaded, {len(page_rows)} pages")

    outdir = pathlib.Path(args.output)
    manifest, pages = assemble.merge_document_corpus(outdir, manifest, pages)
    print(f"\ndocuments_manifest.jsonl: {len(manifest)}")
    print(f"document_pages.jsonl:     {len(pages)}")

    statuses = collections.Counter(r["download_status"] for r in manifest)
    print("status:", dict(statuses))
    print(f"acquisition rate: {statuses.get('downloaded', 0)}/{len(manifest)} "
          f"= {statuses.get('downloaded', 0) / max(len(manifest), 1) * 100:.1f}% "
          f"(README target >=95% of publicly downloadable documents)")
    methods = collections.Counter(p["method"] for p in pages)
    print("extraction:", dict(methods))

    candidates = _participants(pages)
    n = documents.write_jsonl(candidates, outdir / "participant_candidates.jsonl")
    print(f"participant_candidates.jsonl: {n}")
    named = [c for c in candidates if c["amount_numeric"] or c["rank_raw"]]
    for c in named[:10]:
        print(f"  {c['vendor_name_raw'][:44]:<44} {str(c['amount_raw'])[:14]:<14} "
              f"<- {c['displayed_filename'][:38]} p{c['page']}")
    return 0


def cmd_spending(args: argparse.Namespace) -> int:
    """Download and cache Open FI$Cal payment records as a reusable index.

    Kept separate from `analyze` because it downloads hundreds of megabytes. `analyze`
    attaches from the cache this writes, so the expensive step runs when asked for and the
    deliverable command stays fast.
    """
    from . import vendors
    from .sources.ca import openfiscal as of

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    session = _session(args)

    # Departments our own vendor profiles actually serve, in award-volume order, mapped to
    # business-unit codes through the event feed. Spending files are keyed by code, profiles
    # carry display names, so the feed is the only bridge.
    units: list[str] = []
    profiles_path = outdir / "vendor_profiles.json"
    events = _read_jsonl(outdir / "events.jsonl")
    if profiles_path.exists() and events:
        name_to_unit: dict[str, str] = {}
        for event in events:
            name_to_unit.setdefault((event.get("agency") or "").strip(),
                                    event.get("business_unit"))
        served: collections.Counter[str] = collections.Counter()
        for profile in json.loads(profiles_path.read_text()):
            for agency in profile.get("agencies_served") or []:
                served[(agency.get("department") or "").strip()] += agency.get("awards", 0)
        for name, _ in served.most_common():
            unit = name_to_unit.get(name)
            if unit and unit not in units:
                units.append(unit)
        print(f"targeting {len(units)} departments our vendors serve")
    else:
        print("no profiles or event feed yet; selecting across all departments")

    manifest = of.fetch_manifest(session)
    chosen = of.select_files(manifest, business_units=units,
                             fiscal_years=args.fiscal_years or ["FY25", "FY24"],
                             max_total_mb=args.max_mb)
    print(f"manifest: {len(manifest)} files, {sum(m['size_mb'] for m in manifest)/1024:.1f} GB")
    print(f"selected {len(chosen)} files, {sum(c['size_mb'] for c in chosen):.0f} MB "
          f"across {len({c['business_unit'] for c in chosen})} departments")

    rows: list[dict[str, Any]] = []
    failures = 0
    for n, entry in enumerate(chosen, 1):
        try:
            data, _ = session.get(entry["url"], timeout=600)
        except Exception as exc:
            failures += 1
            print(f"  [{n}/{len(chosen)}] FAILED {entry['filename']}: "
                  f"{type(exc).__name__}", file=sys.stderr)
            continue
        rows.extend(of.parse_transactions(data))
        print(f"  [{n}/{len(chosen)}] {entry['department'][:30]:<30} "
              f"{entry['fiscal_year']} -> {len(rows):,} rows")

    index = of.aggregate_by_vendor(rows)
    payload = {
        "generated_at": documents.utc_now(),
        "files_selected": len(chosen), "files_failed": failures,
        "payment_rows": len(rows), "payees": len(index),
        "departments_covered": sorted({c["business_unit"] for c in chosen}),
        "fiscal_years": sorted({c["fiscal_year"] for c in chosen if c["fiscal_year"]}),
        "budget_mb": args.max_mb,
        "coverage_note": ("this index covers the selected departments and years only. A "
                          "vendor absent from it has no matched payment record, which is "
                          "not the same as having received no payments."),
        "index": index,
    }
    target = outdir / "spending_index.json"
    target.write_text(json.dumps(payload, indent=1, default=str))
    print(f"\n{len(rows):,} payment rows, {len(index):,} payees, {failures} failures")
    print(f"wrote {target}")

    if profiles_path.exists():
        profiles = json.loads(profiles_path.read_text())
        summary = vendors.attach_spending(profiles, index)
        profiles_path.write_text(json.dumps(profiles, indent=1, default=str))
        (outdir / "spending_join.json").write_text(json.dumps(summary, indent=1, default=str))
        print(f"attached to profiles: {summary['matched']} matched, "
              f"{summary['ambiguous_left_unmatched']} ambiguous, {summary['unmatched']} unmatched")
    return 0


def cmd_bidders(args: argparse.Namespace) -> int:
    """Harvest Caltrans weekly bid results: the one California source naming losing bidders.

    Separate from `analyze` because it walks a page per week and its useful range is the
    rolling window the site keeps, not one opportunity. `analyze` picks up what this
    writes.
    """
    import datetime as dt

    from .sources.ca import caltrans, scprs

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    end = dt.date.today()
    start = end - dt.timedelta(weeks=args.weeks)
    print(f"harvesting Caltrans bid results, {start} to {end}")

    session = _session(args)
    # Resume rather than restart. Caltrans keeps roughly nine months, so a long backfill
    # has to survive interruption -- and one run really was killed mid-sweep for memory,
    # taking an hour of throttled requests with it.
    state = harvest_state.load(outdir)
    weeks = [s for s in caltrans.week_slugs(start, end)]
    todo = harvest_state.pending(state, "caltrans_bid_results", weeks)
    if len(todo) < len(weeks):
        print(f"  {len(weeks) - len(todo)} of {len(weeks)} weeks already held; "
              f"fetching {len(todo)}")

    def note(slug: str, outcome: str, rows: int) -> None:
        harvest_state.record(state, "caltrans_bid_results", slug,
                             outcome=outcome, rows=rows)

    result = caltrans.harvest(session, start, end,
                              skip=set(weeks) - set(todo), on_week=note)
    harvest_state.save(outdir, state)
    if result["weeks_failed"]:
        print(f"  WARNING: {len(result['weeks_failed'])} week(s) failed and will be "
              f"retried on the next run")
    candidates = caltrans.bidder_candidates(result["solicitations"])

    if args.resolve:
        # One SCPRS name query returns both the supplier_id and that vendor's awards, so
        # resolution and the profile backfill come out of the same pass.
        from . import vendors

        print(f"  resolving {len({c['vendor_name_raw'] for c in candidates})} distinct "
              f"names against SCPRS")

        def lookup(name: str) -> list[dict[str, str]]:
            try:
                return scprs.search(session, supplier_name=name)["rows"]
            except Exception as exc:  # one bad name must not lose the harvest
                print(f"    {name[:40]}: {type(exc).__name__}", file=sys.stderr)
                return []

        summary = vendors.resolve_bidder_identities(candidates, lookup)
        assemble.merge_cache(outdir, "awards_bidder_enriched.jsonl",
                             summary["awards_seen"], key=assemble.award_key)
        print(f"  resolved {summary['resolved']} rows, {summary['ambiguous']} ambiguous, "
              f"{summary['unresolved']} unresolved; "
              f"{len(summary['awards_seen'])} award rows collected for profiles")

    # The cache accumulates across runs; the results file describes this run only.
    assemble.merge_cache(outdir, "caltrans_bidders.jsonl", candidates,
                         key=assemble.bidder_key)
    (outdir / "caltrans_bid_results.json").write_text(
        json.dumps(result, indent=1, default=str))

    solicitations = result["solicitations"]
    multi = [s for s in solicitations if s["bidder_count"] > 1]
    print(f"  weeks with a page: {len(result['weeks_populated'])} | "
          f"weeks never published: {len(result['weeks_absent'])}")
    print(f"  {len(solicitations)} solicitations, {len(candidates)} bidder observations")
    print(f"  {len(multi)} solicitations name more than one bidder, i.e. carry losers")
    return 0


def cmd_tabulations(args: argparse.Namespace) -> int:
    """Harvest SF Public Works bid tabulations: a second source that names losing bidders.

    San Francisco posts the whole field as a PDF attachment to the commission item that
    awards the contract, with an engineer's estimate the Caltrans pages do not carry.
    """
    from .sources.ca import sfpublicworks as sfpw

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    session = _session(args)

    # The calendar links only a slice of each meeting's papers; the attachment carrying a
    # tabulation usually hangs off the meeting's own page, and those are /node/<id> URLs
    # the site does not index in one place. So pages are an argument: default to the
    # calendar, and let a caller point at meeting pages to go deeper.
    pages = args.page or [sfpw.CALENDAR_URL]
    links: list[str] = []
    for page_url in pages:
        body, _ = session.get(page_url)
        links += sfpw.commission_pdf_links(body.decode("utf-8", "replace"))
    links = sorted(set(links))
    worth = [u for u in links if sfpw.likely_tabulation(u)][:args.limit]
    print(f"{len(pages)} page(s), {len(links)} commission PDFs linked, "
          f"{len(worth)} worth opening")

    def read_pages(url: str) -> list[str]:
        data, _ = session.get(url)
        return [p.get("text") or "" for p in extract.extract_pages(
            data, document_ref=url, sha256="", allow_ocr=not args.no_ocr)]

    result = sfpw.harvest(worth, read_pages, max_pages=args.max_pages)
    assemble.merge_cache(outdir, "sf_bidders.jsonl", result["candidates"],
                         key=assemble.bidder_key)
    (outdir / "sf_tabulations.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "candidates"},
                   indent=1, default=str))

    multi = [t for t in result["tabulations"] if t["bidder_count"] > 1]
    print(f"  read {result['documents_read']} documents, "
          f"{result['documents_without_tabulation']} carried no tabulation, "
          f"{len(result['failures'])} failed")
    print(f"  {len(result['tabulations'])} tabulations, "
          f"{len(result['candidates'])} bidder observations")
    print(f"  {len(multi)} tabulations name more than one bidder, i.e. carry losers")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Regenerate build/evaluation.json from the cached award corpus.

    Kept out of `analyze` because it ranks every held-out event and is the one number a
    reviewer must be able to reproduce independently of a live crawl.
    """
    from . import predict

    outdir = pathlib.Path(args.output)
    awards_path = outdir / "awards.jsonl"
    if not awards_path.exists():
        print(f"no award corpus at {awards_path}; run analyze first", file=sys.stderr)
        return 1
    awards = _read_jsonl(awards_path)
    history, events = predict.holdout_events(awards, cutoff=args.cutoff)
    if not events:
        print(f"no awards dated {args.cutoff}; nothing to hold out", file=sys.stderr)
        return 1
    print(f"history {len(history)} rows, {len(events)} held-out events at {args.cutoff}")

    results = [{**event,
                "predictions": predict.rank_candidates(
                    history, event["opportunity"], cutoff=args.cutoff,
                    top_n=10)["predictions"]}
               for event in events]
    summary = predict.evaluate(results)
    summary["baseline_comparison"] = predict.compare_to_baselines(
        history, events, cutoff=args.cutoff)
    summary["event_selection"] = predict.EVENT_SELECTION
    summary["corpus"] = predict.describe_corpus(history)
    summary["corpus_note"] = summary["corpus"]["reason"]
    (outdir / "evaluation.json").write_text(json.dumps(summary, indent=1, default=str))
    print(f"precision@3 {summary['precision_at_3']} | precision@5 "
          f"{summary['precision_at_5']} | coverage {summary['coverage']} | lift "
          f"{summary['baseline_comparison']['lift_over_best_baseline']}x")
    return 0


def cmd_backfill_primes(args: argparse.Namespace) -> int:
    """Deepen award history for exactly the vendors that could qualify as primes.

    A date sweep leaves the median vendor holding one award, so almost nobody clears the
    prime rule and the deliverable ships an empty list. Backfilling every member of the
    eligible set is uniform rather than biasing -- a vendor outside it can never qualify
    however deep its history -- so relative standing inside the set is unchanged.
    """
    from . import primes
    from .sources.ca import scprs

    outdir = pathlib.Path(args.output)
    awards_path = outdir / "awards.jsonl"
    path = pathlib.Path(args.opportunity)
    if not awards_path.exists() or not path.exists():
        print("need both --opportunity and a cached build/awards.jsonl", file=sys.stderr)
        return 1
    opportunity = json.loads(path.read_text())
    awards = _read_jsonl(awards_path)
    eligible = primes.eligible_supplier_ids(awards, opportunity)
    print(f"{len(eligible)} of {len({a.get('supplier_id') for a in awards})} vendors are "
          f"eligible to prime this opportunity")

    session = _session(args)
    merged = {assemble.award_key(r): r for r in awards}
    truncated: list[str] = []
    for n, sid in enumerate(eligible, 1):
        result = scprs.search(session, supplier_id=sid)
        for row in result["rows"]:
            merged.setdefault(assemble.award_key(row), row)
        if result["truncated"]:
            # The grid caps at 200 rows and cannot be paged, so a deeper vendor is
            # under-represented. Recorded, because silent shortfall is what biases a corpus.
            truncated.append(sid)
        print(f"  [{n}/{len(eligible)}] {sid}: +{len(result['rows'])} rows"
              f"{' (capped)' if result['truncated'] else ''}")

    rows = list(merged.values())
    out = outdir / "awards_prime_enriched.jsonl"
    documents.write_jsonl(rows, out)
    print(f"{len(awards)} -> {len(rows)} rows written to {out}")
    if truncated:
        print(f"{len(truncated)} vendors hit the {scprs.PAGE_LIMIT}-row cap: "
              f"{', '.join(truncated[:10])}")
    return 0


def _context_store(outdir: pathlib.Path) -> pathlib.Path:
    return outdir / "contexts.json"


def cmd_auth(args: argparse.Namespace) -> int:
    """Sign in to a portal once, by hand, and keep the session for later runs.

    A saved Browserbase context holds the cookies. A person opens the printed live-view
    URL, signs in with credentials from `.env`, and clears any one-time verification the
    portal shows. Every later harvest reuses the context read-only and arrives already
    authenticated, so this is run once per portal rather than once per run.

    Deliberately interactive. Automating the sign-in form would make the harvester a
    thing that submits forms, and `SECURITY.md` says it retrieves and parses only.
    """
    from .net import browser

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    store_path = _context_store(outdir)
    store = json.loads(store_path.read_text()) if store_path.exists() else {}

    context_id = store.get(args.source)
    if context_id and not args.new:
        print(f"reusing saved context for {args.source}")
    else:
        context_id = browser.create_context(f"sled-trial-{args.source}")
        print(f"created a new context for {args.source}")

    session = browser.create_session(context_id=context_id, persist=True)
    print(f"\n  open this and sign in:\n    {browser.live_view_url(session['id'])}")
    print(f"\n  session replay: https://www.browserbase.com/sessions/{session['id']}")
    print(f"\n  credentials are in .env under the keys for {args.source};"
          "\n  do not paste them anywhere else, and do not screenshot the signed-in page.")
    try:
        input("\n  press enter here once you are signed in (or ctrl-c to abandon) ")
    except (KeyboardInterrupt, EOFError):
        print("\nabandoned; nothing saved")
        return 1

    store[args.source] = context_id
    store_path.write_text(json.dumps(store, indent=1))
    print(f"\nsaved. later runs reuse this context read-only.\n  {store_path}")
    return 0


def cmd_limits(args: argparse.Namespace) -> int:
    """What the Browserbase key is allowed to do. Recorded so a quota is not read as a bug."""
    from .net import browser

    limits = browser.account_limits()
    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "browserbase_limits.json").write_text(json.dumps(limits, indent=1))
    for project in limits["projects"]:
        tier = {3: "free", 25: "developer"}.get(project["concurrency"], "unknown")
        print(f"  {project['name']}: concurrency {project['concurrency']} ({tier} tier), "
              f"session cap {project['session_timeout_seconds']}s, "
              f"{project.get('browser_minutes_used')} browser-minutes used")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    """One reconciled account of what the pipeline holds, across every source.

    Joins the static research in the source registry to what each harvester reported on
    its last run and when that run last wrote anything.
    """
    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    cov = assemble.unified_coverage(outdir)
    (outdir / "coverage.json").write_text(json.dumps(cov, indent=1, default=str))

    print(f"  {cov['sources_harvested']} of {cov['sources_tracked']} sources harvested, "
          f"{cov['total_failures']} failures\n")
    print(f"  {'source':<32}{'rows':>8}{'of portal':>11}  last sync")
    for e in cov["sources"]:
        target = ("-" if e["reported_by_portal"] is None
                  or not e["reported_is_portal_total"]
                  else str(e["reported_by_portal"]))
        flag = "" if not e["shortfall"] else f"  SHORT {e['shortfall']}"
        print(f"  {e['source_key']:<32}{e['rows_on_disk']:>8}{target:>11}  "
              f"{(e['last_sync'] or 'never')[:10]}{flag}")
    if cov["sources_never_harvested"]:
        print(f"\n  never harvested: {', '.join(cov['sources_never_harvested'])}")
    return 0


def cmd_sacramento(args: argparse.Namespace) -> int:
    """Harvest the City of Sacramento Bid Activities layer (ArcGIS open data).

    Counts, not names: vendors notified, prospective bidders, and how many were local.
    """
    from .sources.ca import sacramento as sac

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    session = _session(args)

    def fetch(url: str):
        return json.loads(session.get(url, timeout=90)[0])

    out = sac.harvest(fetch, on_progress=lambda m: print(f"        {m}"))
    documents.write_jsonl(out["rows"], outdir / "sacramento_solicitations.jsonl")
    (outdir / "sacramento_coverage.json").write_text(json.dumps(
        {k: v for k, v in out.items() if k != "rows"}, indent=1, default=str))
    if not out["complete"]:
        print(f"        WARNING: collected {out['collected']} of "
              f"{out['reported_by_layer']} the layer reported")
    print(f"\n{out['collected']} solicitations "
          f"({out['with_bidder_counts']} with a bidder count)")
    return 0


def cmd_csu(args: argparse.Namespace) -> int:
    """Harvest the CSU public bid portal: 23 campuses on one endpoint.

    Solicitations only. The Award tab marks status but never names the awardee, and
    the detail behind each row needs a supplier login.
    """
    from .sources.ca import csu

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    session = _session(args)

    def fetch(url: str) -> str:
        return session.get(url, timeout=90)[0].decode("utf-8", "replace")

    out = csu.harvest(fetch, on_progress=lambda m: print(f"        {m}"))
    documents.write_jsonl(out["rows"], outdir / "csu_solicitations.jsonl")
    (outdir / "csu_coverage.json").write_text(json.dumps(
        {k: v for k, v in out.items() if k != "rows"}, indent=1, default=str))
    print(f"\n{len(out['rows'])} solicitations across "
          f"{len(out['campuses'])} campuses -> csu_solicitations.jsonl")
    return 0


def cmd_cslb(args: argparse.Namespace) -> int:
    """Download the CSLB contractor register.

    Free, no login, and the one identifier that crosses the bidder sources: Caltrans
    and SF publish names only, PlanetBids ids stop at its own edge, and vendor ads cite
    a licence number in free text.
    """
    from .sources.ca import cslb

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    session = _session(args)
    reports = []
    for which in (args.file or ["license_master"]):
        report = cslb.download(session, which, dest=args.raw_root_registries,
                               attempts=args.attempts,
                               on_progress=lambda m: print(f"        {m}"))
        reports.append(report)
        if not report["complete"]:
            print(f"        WARNING: {which} is incomplete and was NOT promoted to its "
                  f"real name; {report['rows']} rows retrieved")
    (outdir / "cslb_coverage.json").write_text(
        json.dumps({"files": reports}, indent=1, default=str))
    return 0 if all(r["complete"] for r in reports) else 1


def cmd_suppliers(args: argparse.Namespace) -> int:
    """Build the supplier location/certification index the vendor profiles read.

    Regenerates `supplier_locations.json`, which previously existed in the build
    directory with nothing able to rebuild it.
    """
    from .sources.ca import supplier_search

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    awards = assemble._read_jsonl(outdir / "awards.jsonl")
    names = [r.get("supplier_name") for r in awards]
    if args.limit:
        names = names[:args.limit]
    if not names:
        print("  no supplier names in awards.jsonl; run the award sweep first")
        return 1

    session = _session(args)
    out = supplier_search.location_index(
        session, names, on_progress=lambda m: print(f"        {m}"))
    (outdir / "supplier_locations.json").write_text(
        json.dumps(out["index"], indent=1, default=str))
    (outdir / "supplier_locations_coverage.json").write_text(json.dumps(
        {k: v for k, v in out.items() if k != "index"}, indent=1, default=str))
    with_loc = sum(1 for v in out["index"].values() if v.get("has_location"))
    print(f"\n{out['suppliers_indexed']} suppliers indexed ({with_loc} with a location) "
          f"from {out['names_searched']} names; {len(out['failures'])} lookups failed")
    return 0


def cmd_vendor_ads(args: argparse.Namespace) -> int:
    """Read the vendor-ad board on each event in the cached feed.

    These are never bidders. A prime seeking a sub says it means to bid *this* event,
    which is the only forward-looking declared signal Cal eProcure publishes; a sub
    seeking a prime is offering itself to whoever bids. Both land as declared_interest
    and there is no path that promotes either to a bidder.
    """
    from .sources.ca import vendor_ads

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    events = assemble._read_jsonl(outdir / "events.jsonl")
    if not events:
        print("  no events.jsonl; run analyze or events first")
        return 1
    if args.limit:
        events = events[:args.limit]
    print(f"  reading the ad board on {len(events)} events")

    session = _session(args)
    out = vendor_ads.harvest(
        functools.partial(vendor_ads.read_ad_page, session), events,
        on_progress=lambda m: print(f"        {m}"))
    rows = assemble.merge_cache(outdir, "vendor_ads_declared_interest.jsonl",
                                out["rows"], key=assemble.declared_interest_key)
    (outdir / "vendor_ads_coverage.json").write_text(json.dumps(
        {k: v for k, v in out.items() if k != "rows"}, indent=1, default=str))
    intending = sum(1 for r in rows if r["intends_to_bid"])
    print(f"\n{len(rows)} ads across {out['events_with_ads']} events "
          f"({intending} prime-seeking-sub, i.e. stating an intent to bid; "
          f"{out['generic_bid_assistance']} generic bid-assistance); "
          f"{len(out['events_stating_no_ads'])} events stated no ads, "
          f"{len(out['failures'])} failed")
    return 0


def cmd_lpa(args: argparse.Namespace) -> int:
    """Look up the statewide contract vehicles held by suppliers in the award corpus.

    Keyed by supplier id, which is what the LPA search publishes and what the award rows
    already carry, so this joins on an identifier rather than a name.
    """
    from .sources.ca import lpa

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    awards = assemble._read_jsonl(outdir / "awards.jsonl")
    supplier_ids = [s for s in dict.fromkeys(
        (r.get("supplier_id") or "").strip() for r in awards) if s]
    if args.limit:
        supplier_ids = supplier_ids[:args.limit]
    if not supplier_ids:
        print("  no supplier ids in awards.jsonl; run the award sweep first")
        return 1
    print(f"  checking {len(supplier_ids)} suppliers for statewide vehicles")

    session = _session(args)
    out = lpa.vehicles_by_supplier(session, supplier_ids,
                                   on_progress=lambda m: print(f"        {m}"))
    rows = lpa.vehicle_rows(out["by_supplier"])
    (outdir / "lpa_vehicles.json").write_text(json.dumps(rows, indent=1, default=str))
    (outdir / "lpa_coverage.json").write_text(json.dumps(
        {k: v for k, v in out.items() if k != "by_supplier"}, indent=1, default=str))
    live = sum(1 for r in rows if r["current"] is True)
    print(f"\n{len(rows)} vehicles across {out['suppliers_with_vehicles']} suppliers "
          f"({live} currently in force); {len(out['failures'])} lookups failed")
    return 0


def cmd_planetbids(args: argparse.Namespace) -> int:
    """Harvest PlanetBids agency portals: who bid, and who took out the documents.

    One portal per agency, keyed by the numeric companyId in its URL. The API answers
    403 to a bare client, so calls go through the loaded page -- the same GETs the app
    itself issues.
    """
    from .net.browser import PortalJsonReader
    from .sources.ca import planetbids as pb

    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    registry = {r["company_id"]: r.get("agency_name") or "" for r in pb.curated_agencies()}
    agencies = ([a.strip() for a in args.agency if a.strip()] if args.agency
                else list(registry))
    if not agencies:
        print("  no agencies: pass --agency or populate sources/planetbids/agencies.csv")
        return 1
    candidates, interest, summaries = [], [], []

    for cid in agencies:
        print(f"  agency {cid} {registry.get(cid, '')}")
        entry = pb.PORTAL.format(cid=cid)
        try:
            # Three GETs per solicitation plus latency, so ask for a session long
            # enough to finish. The default 600s expires mid-loop and surfaces as a
            # navigation error rather than as an expiry.
            budget = 900 if args.max_bids is None else max(600, int(args.max_bids * 8))
            with PortalJsonReader(entry, delay_seconds=args.delay,
                                  remote=not args.local_browser,
                                  session_seconds=min(budget, 21600)) as reader:
                out = pb.harvest_agency(reader.fetch_json, cid,
                                        max_bids=args.max_bids,
                                        on_progress=lambda m: print(f"        {m}"))
        except Exception as exc:
            print(f"        FAILED: {type(exc).__name__}: {exc}")
            summaries.append({"company_id": cid, "error":
                              f"{type(exc).__name__}: {exc}"})
            continue
        candidates += out["candidates"]
        interest += out["declared_interest"]
        summaries.append({k: v for k, v in out.items()
                          if k not in ("bids", "candidates", "declared_interest",
                                       "documents")})
        if not out["complete"]:
            print(f"        WARNING: collected {out['bids_collected']} of "
                  f"{out['bids_reported_by_portal']} solicitations the portal reported")

    assemble.merge_cache(outdir, "planetbids_bidders.jsonl", candidates,
                         key=assemble.bidder_key)
    assemble.merge_cache(outdir, "planetbids_declared_interest.jsonl", interest,
                         key=assemble.bidder_key)
    (outdir / "planetbids_coverage.json").write_text(
        json.dumps({"agencies": summaries}, indent=1, default=str))
    print(f"\n{len(candidates)} bidder rows | {len(interest)} planholder rows "
          f"across {len(agencies)} agency portal(s)")
    return 0


def month_windows(from_date: str, to_date: str) -> list[tuple[str, str]]:
    """Split a range into calendar months, newest first.

    Newest first because recency dominates the features: if a backfill is stopped
    early, the months that were collected are the ones worth having. Calendar months
    rather than 30-day blocks so a window is nameable -- "September is complete" is a
    claim a reviewer can check against the portal.
    """
    import datetime as dt

    start, end = dt.datetime.strptime(from_date, "%m/%d/%Y").date(), \
        dt.datetime.strptime(to_date, "%m/%d/%Y").date()
    if start > end:
        raise ValueError(f"--from {from_date} is after --to {to_date}")
    out, cursor = [], start
    while cursor <= end:
        last = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1) \
            - dt.timedelta(days=1)
        out.append((cursor.strftime("%m/%d/%Y"), min(last, end).strftime("%m/%d/%Y")))
        cursor = last + dt.timedelta(days=1)
    return list(reversed(out))


def cmd_backfill_awards(args: argparse.Namespace) -> int:
    """Deepen the award corpus a month at a time.

    The sweep itself is `sweep_awards`, unchanged -- this walks calendar months and
    calls it, which is what makes a long backfill stoppable. Twelve months serially
    costs the same as one twelve-month range; what months buy is a corpus you can
    describe. "The last five months, complete" is checkable against portal totals per
    window, where a ragged partial year is not.

    Slice keys carry no notion of which run produced them, so months never collide and
    a re-run skips whatever is already held.
    """
    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    windows = month_windows(args.since, args.until)
    if args.months:
        windows = windows[:args.months]
    print(f"backfilling {len(windows)} month(s), newest first: "
          f"{windows[-1][0]} .. {windows[0][1]}")

    session = _session(args)
    log = outdir / "awards_backfill_coverage.jsonl"
    done = 0
    for index, (start, end) in enumerate(windows, 1):
        print(f"\n  [{index}/{len(windows)}] {start} .. {end}")
        try:
            _, coverage = sweep_awards(session, outdir, start, end,
                                       say=lambda m: print(f"        {m}"))
        except KeyboardInterrupt:
            # Everything up to here is on disk and recorded. Stopping is a supported
            # way to run this, not a failure.
            print(f"\n  stopped after {done} of {len(windows)} months; "
                  f"rerun to continue from here")
            return 0
        except Exception as exc:
            # One month failing must not cost the months after it. Its slices stay
            # unheld, so a rerun re-asks exactly that window.
            print(f"        FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        done += 1
        # Appended, never overwritten: a per-window verdict is the only way to say
        # which months are actually complete.
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"window": {"from": start, "to": end},
                                 "collected": coverage.get("rows_collected"),
                                 "reported": coverage.get("rows_reported_by_portal"),
                                 "complete": coverage.get("complete"),
                                 "slices": coverage.get("slices"),
                                 "collected_at": documents.utc_now()},
                                default=str) + "\n")
    total = sum(1 for _ in (outdir / "awards.jsonl").open())
    print(f"\n{done} of {len(windows)} month(s) swept; {total} award rows on disk "
          f"(per-window verdicts in {log.name})")
    return 0


def sweep_awards(session, outdir: pathlib.Path, window_from: str, window_to: str,
                 *, say=print) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect SCPRS awards over one date window, resumably.

    Shared by `analyze`, which sweeps a single opportunity's context window, and
    `backfill-awards`, which walks a month at a time. One implementation because the
    hard parts -- subdivision, per-slice checkpointing, dedupe on read-back -- are
    exactly the parts that must not diverge between the two.
    """
    from .sources.ca import scprs

    cached = outdir / "awards.jsonl"
    slices = []
    # Subdivide a still-capped day by acquisition method. The value list is a lower
    # bound read off whatever is already cached, so the sweep measures what the
    # subdivision actually recovered rather than assuming the list is exhaustive.
    # Two axes, tried in order. Acquisition method first because it comes free from
    # rows already collected; business unit second because one method dominates --
    # `Fair and Reasonable - COMPETITIVE` was over the cap on every day of the
    # reference window even pinned, so a single axis cannot finish. Both lists are
    # lower bounds, which is why the sweep measures what it recovered.
    axes = []
    # Named distinctly from `cached`, which is the output *path* set above. Reusing
    # that name here clobbered it and the sweep died writing its own results -- on
    # the full-sweep branch only, so every --reuse-awards run passed and every real
    # one lost ninety minutes of throttled requests.
    previous_awards = assemble._read_jsonl(outdir / "awards.jsonl")
    if previous_awards:
        methods = scprs.observed_acq_methods(previous_awards)
        if methods:
            axes.append(("acq_method", methods))
    units = scprs.observed_business_units(assemble._read_jsonl(outdir / "events.jsonl"))
    if units:
        axes.append(("business_unit", units))
    # Resume rather than restart. This sweep is the longest transaction in the
    # pipeline and has lost about ninety minutes twice: once to memory pressure,
    # once to a crash writing its own output. A slice that answered is not asked
    # again; a slice that failed stays pending.
    sweep_state = harvest_state.load(outdir)
    done = {u for u, e in (sweep_state.get("sources", {})
                           .get("caleprocure_scprs", {})
                           .get("units", {})).items()
            if e.get("outcome") in harvest_state.DONE}

    def note_slice(key: str, outcome: str, rows: int) -> None:
        harvest_state.record(sweep_state, "caleprocure_scprs", key,
                             outcome=outcome, rows=rows)

    for result in scprs.search_date_sliced(
            session, window_from, window_to, subdivide_by=axes or None,
            skip=done, on_slice=note_slice):
        # A subdivided parent slice is yielded for its shortfall note and carries the
        # same rows its children already yielded. Taking them again double-counts.
        if result.get("subdivided"):
            continue
        # Checkpoint per slice. The save below only runs if the whole sweep
        # finishes, so a run killed part-way -- the memory kill this resume was
        # built for -- held nothing and refetched all of it. Rows before state:
        # a crash between the two costs one refetch, whereas marking a slice
        # done whose rows never reached disk would leave a hole nothing reports.
        documents.write_jsonl(result["rows"], cached, append=True)
        harvest_state.save(outdir, sweep_state)
        # Keep the slice's tally, drop its rows. They are on disk a line above,
        # and coverage only ever asks how many there were. Holding them here as
        # well retained every row twice for the length of the sweep, which is
        # what killed this run three times; twelve months would not have fit at
        # all. Peak memory is now one slice, not the whole window.
        slices.append({k: v for k, v in result.items() if k != "rows"}
                      | {"rows_collected": len(result["rows"])})
    harvest_state.save(outdir, sweep_state)
    if done:
        print(f"        resumed: {len(done)} slice(s) already held, "
              f"{len(previous_awards)} cached rows carried")
    coverage = assemble.award_sweep_coverage(slices)
    coverage_path = outdir / "awards_coverage.json"
    existing_coverage = (json.loads(coverage_path.read_text())
                         if coverage_path.exists() else None)
    if not coverage["complete"]:
        print(f"        WARNING: {coverage['slices_truncated']} of "
              f"{coverage['slices']} slices hit the grid cap; "
              f"{coverage['rows_reported_by_portal'] - coverage['rows_collected']} "
              f"reported rows not retrieved (see awards_coverage.json)")
    # Read back what the sweep checkpointed instead of carrying it in memory: the
    # file already holds this run's slices appended to whatever an earlier run left,
    # so this is both the dedupe and the resume carry-over in one pass. Last wins,
    # so a row fetched now replaces the cached copy of the same award.
    # ponytail: reads the whole corpus once at the end. If the window ever outgrows
    # memory at that point, stream it through a temp file keyed on award_key.
    awards = list({assemble.award_key(r): r
                   for r in assemble._read_jsonl(cached)}.values())
    documents.write_jsonl(awards, cached)
    # Written after the rows, and always -- a verdict is only worth publishing next
    # to the corpus it describes.
    coverage_path.write_text(json.dumps(assemble.award_coverage_verdict(
        coverage, existing_coverage, rows_on_disk=len(awards), held=len(done),
        window={"from": window_from, "to": window_to}), indent=1, default=str))
    say(f"{len(awards)} award rows on disk")
    return awards, coverage


def cmd_analyze(args: argparse.Namespace) -> int:
    """The README deliverable command. Produces every required build/ artifact."""
    from . import lineage as lineage_mod
    from . import page_review
    from . import predict, primes, report as report_mod, supabase_export as se, vendors
    from .sources.ca import scprs

    path = pathlib.Path(args.opportunity)
    if not path.exists():
        print(f"opportunity file not found: {path}", file=sys.stderr)
        return 1
    opportunity = json.loads(path.read_text())
    bu, eid = opportunity.get("business_unit"), opportunity.get("event_id")
    if not bu or not eid:
        print("opportunity must carry business_unit and event_id", file=sys.stderr)
        return 1
    cutoff = opportunity.get("analysis_cutoff") or "09/03/2026"
    client = opportunity.get("client_profile") or {}
    outdir = pathlib.Path(args.output)
    outdir.mkdir(parents=True, exist_ok=True)
    session = _session(args)

    print(f"analyze {bu}/{eid}  cutoff={cutoff}  output={outdir}")

    # 1. Active event feed -- context for lineage and for resolving references.
    print("  [1/9] event feed")
    events = ca.parse_event_list(ca.fetch_event_list(session))
    documents.write_jsonl(events, outdir / "events.jsonl")

    # 2. Documents for this opportunity.
    manifest: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    if args.download_documents:
        print("  [2/9] documents")
        store = documents.DocumentStore(args.raw_root)
        try:
            docs = ca.fetch_attachments(session, bu, eid)
            manifest, pages = documents.process_event_documents(
                docs, store=store, allow_ocr=not args.no_ocr)
        except Exception as exc:
            manifest = [assemble.enumeration_failure_row(bu, eid, exc)]
            print(f"        enumeration failed: {type(exc).__name__}", file=sys.stderr)
    else:
        print("  [2/9] documents skipped (--download-documents not set)")
    manifest, pages = assemble.merge_document_corpus(outdir, manifest, pages)
    print(f"        corpus now {len(manifest)} documents, {len(pages)} pages")

    # 3. Observed participants, from document tables only.
    listing = assemble.target_listing_state(opportunity, events)
    if listing["listed_in_active_feed"] is not True:
        print(f"        NOTE: {listing['note']}")

    print("  [3/9] observed participants")
    known = assemble.observed_participants(_participants(pages), outdir)
    documents.write_jsonl(known, outdir / "participant_candidates.jsonl")
    by_source = collections.Counter(k.get("source_key") for k in known)
    named = ", ".join(f"{by_source[s.key]} from {s.label}"
                      for s in sources.BIDDER_SOURCES if by_source[s.key])
    if named:
        print(f"        {len(known)} candidates ({named})")

    # 4. Award history for this buyer and category, plus a dated window for context.
    print("  [4/9] award history")
    awards: list[dict[str, Any]] = []
    cached = outdir / "awards.jsonl"
    if args.reuse_awards and cached.exists():
        awards = [json.loads(l) for l in cached.read_text().splitlines() if l.strip()]
        print(f"        reused {len(awards)} cached award rows")
    else:
        window_from = args.awards_from or assemble.default_awards_from(cutoff)
        awards, _ = sweep_awards(session, outdir, window_from, cutoff,
                                 say=lambda m: print(f"        {m}"))

    # 5. Lineage -- always emits a trace, including an explicit no-match.
    print("  [5/9] predecessor search")
    lineage_result = lineage_mod.find_predecessors(
        opportunity, events=events, awards=awards, pages=pages)
    (outdir / "procurement_lineage.json").write_text(
        json.dumps(lineage_result, indent=1, default=str))
    print(f"        {lineage_result['trace']['result']}")

    # 6. Vendor profiles and prediction.
    print("  [6/9] vendor profiles and prediction")
    # Profiles see the bidder backfill; prediction below keeps ranking on the sweep.
    profile_awards = assemble.profile_corpus(awards, outdir)
    if len(profile_awards) != len(awards):
        print(f"        profile corpus {len(awards)} -> {len(profile_awards)} rows "
              f"with the bidder backfill; prediction still ranks on the sweep")
    profiles, review = vendors.build_profiles(profile_awards)
    # Attach cached spending. Rebuilding profiles from awards previously discarded the
    # spending enrichment entirely, so the command meant to produce the deliverable destroyed
    # part of it. The download lives in the `spending` subcommand; this only consumes it.
    for filename, key, attach_name in ENRICHMENTS:
        attach = getattr(vendors, attach_name)
        payload = assemble.enrichment_payload(outdir, filename, key)
        if payload is None:
            print(f"        {attach_name}: no {filename} cached, dimension left unpopulated")
            continue
        joined = attach(profiles, payload)
        print(f"        {attach_name}: {joined['matched']} of {joined['profiles']} profiles")
    (outdir / "vendor_profiles.json").write_text(json.dumps(profiles, indent=1, default=str))
    observed_ids = assemble.observed_vendor_ids(opportunity, known, profiles)
    prediction = predict.rank_candidates(awards, opportunity, cutoff=cutoff, top_n=10,
                                         observed_vendor_ids=observed_ids)

    # 7. Primes. The date sweep gives the median vendor one award, so almost nobody clears
    # the prime rule on it -- `backfill-primes` deepens exactly the eligible set, and that
    # corpus is used when it exists. Uniform depth within the eligible set is what makes
    # the ranking meaningful; see DECISIONS.md 2026-09-08.
    print("  [7/9] prime candidates")
    prime_corpus, prime_build = awards, predict.SWEEP
    enriched_path = outdir / "awards_prime_enriched.jsonl"
    if enriched_path.exists():
        prime_corpus = [json.loads(l) for l in enriched_path.read_text().splitlines()
                        if l.strip()]
        prime_build = predict.PER_VENDOR
        print(f"        prime corpus: {len(prime_corpus)} rows from {enriched_path.name}")
    else:
        print(f"        prime corpus: date sweep only ({len(awards)} rows); run "
              f"`backfill-primes` for uniform depth over the eligible set")
    prime = primes.recommend_primes(
        prime_corpus, opportunity, client, cutoff=cutoff, top_n=10,
        likely_bidder_ids=[p["supplier_id"] for p in prediction["predictions"]],
        build_method=prime_build)
    (outdir / "prime_candidates.json").write_text(json.dumps(prime, indent=1, default=str))

    # Planholders and vendor ads: interest, never bids. Read from every surface that
    # publishes it so a new one reaches the export by being harvested, not by editing
    # this line.
    declared = [row for cache in assemble.DECLARED_INTEREST_CACHES
                for row in assemble._read_jsonl(outdir / cache)]

    intelligence = _opportunity_intelligence(
        opportunity, known=known, prediction=prediction,
        lineage_result=lineage_result, documents_manifest=manifest)
    intelligence["target_listing"] = listing
    (outdir / "opportunity_intelligence.json").write_text(
        json.dumps(intelligence, indent=1, default=str))
    (outdir / "source_coverage.json").write_text(
        json.dumps(_source_coverage(), indent=1, default=str))
    # Reconciled coverage across every source, not just the ones this run touched.
    unified = assemble.unified_coverage(outdir)
    (outdir / "coverage.json").write_text(json.dumps(unified, indent=1, default=str))
    if unified["sources_short_of_portal_total"]:
        print("        coverage: short of the portal total on "
              + ", ".join(unified["sources_short_of_portal_total"]))

    # Review queue: identity conflicts, plus every low-confidence prediction, so nothing
    # weak is presented without a route to human review.
    review = list(review) + vendors.detect_identity_conflicts(profiles)
    review += [{"type": "low_confidence_prediction", "supplier_id": p["supplier_id"],
                "vendor_name": p["vendor_name"], "score": p["score"],
                "confidence": p["confidence"],
                "weakening_factors": p["weakening_factors"],
                "action": "confirm or discard before presenting to a client"}
               for p in prediction["predictions"] if p["confidence"] == "low"]
    review += assemble.unresolved_identity_review(known)
    (outdir / "review_queue.json").write_text(json.dumps(review, indent=1, default=str))

    # 8. Extraction-quality review over a representative page sample.
    print("  [8/9] page extraction review")
    review_result = page_review.review(pages, size=args.review_pages)
    (outdir / "page_review.json").write_text(
        json.dumps(review_result, indent=1, default=str))
    print(f"        {review_result['pages_reviewed']} pages reviewed "
          f"(minimum 20 met: {review_result['meets_minimum_of_20']})")

    # 9. Supabase-shaped fixtures and the generated report.
    print("  [9/9] supabase fixtures and report")
    tables = {
        "gov_procurement_sources": se.source_rows(),
        "gov_procurement_records": (se.event_record_rows(events, target=opportunity,
                                                         participants=known + declared,
                                                         documents=manifest)
                                    + se.award_record_rows(awards)),
        # Four participation states, not two. Planholders and advertisers were being
        # collected and never exported -- 25,090 rows of the strongest pre-close signal
        # the portals publish, sitting on disk while the export claimed to distinguish
        # interested vendors from bidders.
        "gov_procurement_participants": (se.participant_rows(known, awards)
                                         + se.declared_interest_rows(declared)),
        "gov_procurement_documents": se.document_rows(manifest),
        "document_content_handoff": se.handoff_rows(pages),
        # Two sources, and both are needed. Award history covers vendors that have won
        # something; the observed side covers everyone we watched bid without matching
        # them to a state supplier id. Emitting only the first left 2,703 participants
        # pointing at 1,786 competitor records that did not exist.
        "gov_competitors": (se.competitor_rows(profiles)
                            + se.observed_competitor_rows(known + declared)),
        "partner_match_payloads": se.partner_match_rows([prime]),
    }
    validation = se.write_exports(tables, outdir / "supabase")
    # Does a reviewer following a citation arrive anywhere? Schema validation cannot
    # answer that, and a dangling reference is invisible in the row that carries it.
    audit = evidence.audit(tables)
    (outdir / "evidence_audit.json").write_text(
        json.dumps(audit, indent=1, default=str))
    if not audit["sound"]:
        print(f"        WARNING: {audit['defect_count']} evidence defect(s) — "
              f"{audit['dangling_references']} dangling, "
              f"{audit['page_citations_out_of_range']} page citations out of range "
              f"(see evidence_audit.json)")
    report_mod.BUILD = outdir
    report_mod.write(outdir / "report.md")

    required = ["opportunity_intelligence.json", "procurement_lineage.json",
                "documents_manifest.jsonl", "document_pages.jsonl",
                "vendor_profiles.json", "prime_candidates.json",
                "source_coverage.json", "review_queue.json", "report.md",
                "page_review.json"]
    print("\noutputs:")
    missing = []
    for name in required:
        target = outdir / name
        if target.exists():
            print(f"  {name:<34} {target.stat().st_size:>9,} bytes")
        else:
            missing.append(name)
            print(f"  {name:<34} MISSING")
    print(f"  supabase/                          "
          f"{sum(t['rows'] for t in validation['tables']):>9,} rows across "
          f"{len(validation['tables'])} tables, all_valid={validation['all_valid']}")
    if missing:
        print(f"\nincomplete: {missing}", file=sys.stderr)
        return 1
    print(f"\nknown bidders {intelligence['known_bidders']['count']} | likely bidders "
          f"{len(prediction['predictions'])} | primes {prime['candidates_qualified']} | "
          f"lineage {lineage_result['trace']['result']} | review items {len(review)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Shared flags live on a parent parser attached to each subcommand, so they may be
    # written *after* the subcommand name. The README's deliverable command is
    # `analyze --opportunity ... --download-documents --output build`, and that ordering
    # is the contract; a top-level-only flag would reject it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--output", default="build")
    common.add_argument("--delay", type=float, default=1.5,
                        help="per-request delay, seconds (voluntary rate limit)")
    common.add_argument("--raw-root", default=DEFAULT_RAW)
    common.add_argument("--no-ocr", action="store_true", help="skip OCR fallback")
    common.add_argument("--browser-headers", action="store_true",
                        help="send a full browser header set; some hosts 403 a bare "
                             "crawler UA without running an actual challenge")

    parser = argparse.ArgumentParser(prog="sled_trial")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("events", parents=[common],
                   help="fetch and parse the active event feed")
    docs = sub.add_parser("documents", parents=[common],
                          help="download and extract one or more events")
    docs.add_argument("--event", action="append", required=True,
                      metavar="BUSINESS_UNIT/EVENT_ID")
    sp = sub.add_parser("spending", parents=[common],
                        help="download and cache Open FI$Cal payment records")
    sp.add_argument("--max-mb", type=float, default=600.0,
                    help="download budget in MB (the full set is ~10.6 GB)")
    sp.add_argument("--fiscal-years", action="append",
                    help="e.g. --fiscal-years FY25 --fiscal-years FY24")

    an = sub.add_parser("analyze", parents=[common],
                        help="the README deliverable command")
    an.add_argument("--opportunity", required=True)
    an.add_argument("--download-documents", action="store_true")
    an.add_argument("--awards-from", default=None,
                    help="start of the award-history window, MM/DD/YYYY; defaults to "
                         f"{assemble.DEFAULT_AWARD_WINDOW_DAYS} days before the cutoff")
    an.add_argument("--reuse-awards", action="store_true",
                    help="reuse build/awards.jsonl instead of re-querying")
    an.add_argument("--review-pages", type=int, default=20,
                    help="pages to sample for the extraction-quality review (brief: >=20)")

    ev = sub.add_parser("evaluate", parents=[common],
                        help="regenerate build/evaluation.json from the cached corpus")
    ev.add_argument("--cutoff", default="09/03/2026",
                    help="held-out day, MM/DD/YYYY; history is everything before it")

    bp = sub.add_parser("backfill-primes", parents=[common],
                        help="deepen award history for the prime-eligible vendor set")
    bp.add_argument("--opportunity", required=True)

    ba = sub.add_parser("backfill-awards", parents=[common],
                        help="deepen award history a calendar month at a time, "
                             "newest first")
    ba.add_argument("--since", required=True,
                    help="earliest date to collect, MM/DD/YYYY")
    ba.add_argument("--until", required=True, help="latest date, MM/DD/YYYY")
    ba.add_argument("--months", type=int, default=0,
                    help="stop after this many months; 0 walks the whole range")

    va = sub.add_parser("vendor-ads", parents=[common],
                        help="harvest Cal eProcure vendor ads (declared interest, "
                             "never bidders)")
    va.add_argument("--limit", type=int, default=0,
                    help="most events to read; 0 reads every event in the cached feed")

    bd = sub.add_parser("bidders", parents=[common],
                        help="harvest Caltrans weekly bid results (names losing bidders)")
    bd.add_argument("--weeks", type=int, default=12,
                    help="how many weeks back to walk; the site keeps roughly nine months")
    tb = sub.add_parser("tabulations", parents=[common],
                        help="harvest SF Public Works bid tabulations (names losing bidders)")
    tb.add_argument("--limit", type=int, default=40,
                    help="most commission PDFs to open in one run")
    tb.add_argument("--page", action="append",
                    help="page to discover PDFs from; repeatable, defaults to the "
                         "commission calendar")
    sub.add_parser("coverage", parents=[common],
                   help="reconcile what every source collected against what it reported")

    sac_p = sub.add_parser("sacramento", parents=[common],
                           help="harvest the Sacramento bid activities open dataset")

    cu = sub.add_parser("csu", parents=[common],
                        help="harvest the CSU public bid portal (23 campuses)")

    cs = sub.add_parser("cslb", parents=[common],
                        help="download the CSLB contractor register")
    cs.add_argument("--file", action="append",
                    choices=["license_master", "workers_comp", "personnel"],
                    help="which register file; repeatable (default: license_master)")
    cs.add_argument("--attempts", type=int, default=4,
                    help="how many times to retry a torn transfer; the longest "
                         "attempt is kept")
    cs.add_argument("--raw-root-registries", default="data/raw/registries",
                    help="where the register files are written")

    su = sub.add_parser("suppliers", parents=[common],
                        help="rebuild the supplier location/certification index")
    su.add_argument("--limit", type=int, default=None,
                    help="cap how many names are searched")

    lp = sub.add_parser("lpa", parents=[common],
                        help="statewide contract vehicles held by corpus suppliers")
    lp.add_argument("--limit", type=int, default=None,
                    help="cap how many suppliers are checked")

    pbx = sub.add_parser("planetbids", parents=[common],
                         help="harvest PlanetBids agency portals (names losing bidders)")
    pbx.add_argument("--agency", action="append",
                     help="numeric companyId; repeatable. Default: every agency in "
                          "sources/planetbids/agencies.csv")
    pbx.add_argument("--max-bids", type=int, default=None,
                     help="cap solicitations per agency (default: all closed ones)")
    pbx.add_argument("--local-browser", action="store_true",
                     help="use local Chrome instead of a hosted session")

    au = sub.add_parser("auth", parents=[common],
                        help="sign in to a portal once and save the session")
    au.add_argument("--source", required=True,
                    help="portal key, e.g. planetbids")
    au.add_argument("--new", action="store_true",
                    help="force a fresh context instead of reusing the saved one")
    sub.add_parser("limits", parents=[common],
                   help="report what the Browserbase key is allowed to do")

    tb.add_argument("--max-pages", type=int, default=5,
                    help="pages to search per document; a tabulation is front matter")

    bd.add_argument("--resolve", action="store_true",
                    help="resolve bidder names to SCPRS supplier ids and collect their "
                         "awards, which is what populates win rates")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"events": cmd_events, "documents": cmd_documents, "analyze": cmd_analyze,
            "spending": cmd_spending, "evaluate": cmd_evaluate,
            "backfill-primes": cmd_backfill_primes, "bidders": cmd_bidders,
            "tabulations": cmd_tabulations, "auth": cmd_auth, "limits": cmd_limits,
            "planetbids": cmd_planetbids,
            "lpa": cmd_lpa, "suppliers": cmd_suppliers, "cslb": cmd_cslb, "csu": cmd_csu, "sacramento": cmd_sacramento,
            "vendor-ads": cmd_vendor_ads, "backfill-awards": cmd_backfill_awards,
            "coverage": cmd_coverage}[
        args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
