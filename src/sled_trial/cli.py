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
import json
import pathlib
import sys
from typing import Any

from . import assemble, documents, extract, sources
from .assemble import (ENRICHMENTS, _opportunity_intelligence, _participants,
                       _read_jsonl, _source_coverage)
from .sources.ca import caleprocure as ca

DEFAULT_RAW = "data/raw/documents"


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
    session = ca.CalEProcureSession(delay_seconds=args.delay)
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
    session = ca.CalEProcureSession(delay_seconds=args.delay)
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
    session = ca.CalEProcureSession(delay_seconds=args.delay)

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

    session = ca.CalEProcureSession(delay_seconds=args.delay)
    result = caltrans.harvest(session, start, end)
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
        documents.write_jsonl(summary["awards_seen"],
                              outdir / "awards_bidder_enriched.jsonl")
        print(f"  resolved {summary['resolved']} rows, {summary['ambiguous']} ambiguous, "
              f"{summary['unresolved']} unresolved; "
              f"{len(summary['awards_seen'])} award rows collected for profiles")

    documents.write_jsonl(candidates, outdir / "caltrans_bidders.jsonl")
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
    session = ca.CalEProcureSession(delay_seconds=args.delay)

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
    documents.write_jsonl(result["candidates"], outdir / "sf_bidders.jsonl")
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

    session = ca.CalEProcureSession(delay_seconds=args.delay)
    merged = {(r.get("purchase_doc"), r.get("supplier_id")): r for r in awards}
    truncated: list[str] = []
    for n, sid in enumerate(eligible, 1):
        result = scprs.search(session, supplier_id=sid)
        for row in result["rows"]:
            merged.setdefault((row.get("purchase_doc"), row.get("supplier_id")), row)
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
    session = ca.CalEProcureSession(delay_seconds=args.delay)

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
        slices = []
        for result in scprs.search_date_sliced(session, window_from, cutoff):
            # A subdivided parent slice is yielded for its shortfall note and carries the
            # same rows its children already yielded. Taking them again double-counts.
            if result.get("subdivided"):
                continue
            slices.append(result)
            awards += result["rows"]
        coverage = assemble.award_sweep_coverage(slices)
        (outdir / "awards_coverage.json").write_text(
            json.dumps({**coverage, "window": {"from": window_from, "to": cutoff}},
                       indent=1, default=str))
        if not coverage["complete"]:
            print(f"        WARNING: {coverage['slices_truncated']} of "
                  f"{coverage['slices']} slices hit the grid cap; "
                  f"{coverage['rows_reported_by_portal'] - coverage['rows_collected']} "
                  f"reported rows not retrieved (see awards_coverage.json)")
        seen: set[tuple[Any, Any]] = set()
        deduped = []
        for row in awards:
            key = (row.get("purchase_doc"), row.get("supplier_id"))
            if key not in seen:
                seen.add(key)
                deduped.append(row)
        awards = deduped
        documents.write_jsonl(awards, cached)
        print(f"        {len(awards)} award rows")

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
    observed_ids = {p["supplier_id"] for p in profiles
                    if any(k["vendor_name_raw"].lower() in (p.get("canonical_name") or "").lower()
                           for k in known)}
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

    intelligence = _opportunity_intelligence(
        opportunity, known=known, prediction=prediction,
        lineage_result=lineage_result, documents_manifest=manifest)
    (outdir / "opportunity_intelligence.json").write_text(
        json.dumps(intelligence, indent=1, default=str))
    (outdir / "source_coverage.json").write_text(
        json.dumps(_source_coverage(), indent=1, default=str))

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
        "gov_procurement_records": (se.event_record_rows(events)
                                    + se.award_record_rows(awards)),
        "gov_procurement_participants": se.participant_rows(known, awards),
        "gov_procurement_documents": se.document_rows(manifest),
        "document_content_handoff": se.handoff_rows(pages),
        "gov_competitors": se.competitor_rows(profiles),
        "partner_match_payloads": se.partner_match_rows([prime]),
    }
    validation = se.write_exports(tables, outdir / "supabase")
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
    print(f"\nknown bidders {len(known)} | likely bidders "
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
            "tabulations": cmd_tabulations}[
        args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
