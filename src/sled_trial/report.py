"""Generate build/report.md from the artifacts on disk.

Generated rather than hand-written so every number in the report traces to a file in
build/ and cannot drift away from what the pipeline actually produced.
"""
from __future__ import annotations

import collections
import json
import pathlib
from typing import Any

BUILD = pathlib.Path("build")


def _jsonl(name: str) -> list[dict[str, Any]]:
    path = BUILD / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _json(name: str) -> Any:
    path = BUILD / name
    return json.loads(path.read_text()) if path.exists() else None


def _money(value: Any) -> str:
    return "not stated" if value is None else f"${value:,.2f}"


def _gap(model: float | None, baseline: float | None) -> str:
    """The distance between model and baseline, for prose that must not go stale."""
    if model is None or baseline is None:
        return "gap"
    return f"{abs(float(model) - float(baseline)):.4f}"


def _fmt(value: Any) -> str:
    if value is None:
        return "not measured"
    if isinstance(value, float):
        # Never scientific notation for currency: "3.887e+04" is unreadable in a report a
        # reviewer is meant to act on.
        return f"{value:,.2f}" if abs(value) >= 1000 else f"{value:,.4g}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def generate() -> str:
    events = _jsonl("events.jsonl")
    awards = _jsonl("awards.jsonl")
    manifest = _jsonl("documents_manifest.jsonl")
    pages = _jsonl("document_pages.jsonl")
    profiles = _json("vendor_profiles.json") or []
    review = _json("review_queue.json") or []
    evaluation = _json("evaluation.json") or {}
    primes = _json("prime_candidates.json") or {}
    validation = _json("supabase/validation_report.json") or {}

    downloaded = [m for m in manifest if m.get("download_status") == "downloaded"]
    methods = collections.Counter(p.get("method") for p in pages)
    statuses = collections.Counter(m.get("download_status") for m in manifest)
    agencies = {e.get("agency") for e in events if e.get("agency")}
    chars = sum(p.get("char_count") or 0 for p in pages)
    profiled = [p for p in profiles if (p.get("awards_observed") or 0) > 0]
    acq = collections.Counter(a.get("acq_method") for a in awards)
    competitive = sum(v for k, v in acq.items()
                      if k and "COMPETITIVE" in k.upper() and "NON-COMPETITIVE" not in k.upper())

    lines: list[str] = []
    w = lines.append

    w("# California SLED Competitive Intelligence — Trial Report")
    w("")
    w("Generated from the artifacts in `build/`. Every figure below is computed from a file")
    w("in that directory. The closing recommendations and the next-source shortlist are")
    w("judgements, drawn from the access research recorded in `DECISIONS.md` and")
    w("`sources/source_registry.csv`, and are marked as such where they appear.")
    w("")
    w("## What was built")
    w("")
    w("A pipeline that takes a California solicitation and returns a competitive picture:")
    w("who is credibly in this market, who is likely to compete, which companies could")
    w("prime the work, and what evidence supports each claim. The state surfaces run over")
    w("plain HTTP with no login; the PlanetBids agency portals need a real browser session.")
    w("")
    w("| Stage | Result |")
    w("| --- | --- |")
    w(f"| Active solicitations parsed | {_fmt(len(events))} across {_fmt(len(agencies))} agencies |")
    w(f"| Award records ingested | {_fmt(len(awards))} |")
    w(f"| Documents enumerated | {_fmt(len(manifest))} |")
    w(f"| Documents retrieved | {_fmt(len(downloaded))} "
      f"({len(downloaded)/len(manifest)*100:.1f}%) |" if manifest else "| Documents retrieved | none |")
    w(f"| Pages extracted | {_fmt(len(pages))} ({_fmt(chars)} characters) |")
    w(f"| Vendor profiles | {_fmt(len(profiled))} |")
    w(f"| Review-queue items | {_fmt(len(review))} |")
    w("")

    w("## The competitive landscape, as the public record actually supports it")
    w("")
    w("Cal eProcure publishes a great deal about **who won** and almost nothing about **who")
    w("competed**. Individual agencies are a different matter, and that split shapes every")
    w("conclusion here.")
    w("")
    w("- Cal eProcure's bid-inquiry surface exposes no respondent fields, anonymously or")
    w("  signed in as a supplier: a bidder inquires about its own responses, not anyone")
    w("  else's. No planholder or bidder list exists on the state portal.")
    w("- **PlanetBids agency portals are the largest bidder source.** Cities, counties and")
    w("  districts publish every respondent with amount and certifications, plus the")
    w("  planholders who took out documents, keyed by a stable platform vendor id. It is a")
    w("  rendered single-page app, so it is the one surface read through a browser, and")
    w("  its terms restrict commercial reuse rather than automated access.")
    w("- **Caltrans is the exception, and it is a large one.** It posts every bidder on a")
    w("  solicitation, ranked, with amounts and Small Business preference, on a public")
    w("  weekly page within about twenty minutes of the bid opening. Losing bidders")
    w("  included. Its contract numbers are Cal eProcure event ids under business unit")
    w("  2660, so the join is exact rather than inferred, and 2660 is the largest single")
    w("  issuer in the active feed.")
    w("- **San Francisco publishes the same thing as a PDF**, attached to the commission")
    w("  item that awards each contract: every bidder, local-business status, price, and")
    w("  an engineer's estimate that the Caltrans pages do not carry. It lists companies")
    w("  in the order their envelopes were opened rather than by price, so rank there is")
    w("  derived from the amounts. San Francisco is a city and absent from Cal eProcure,")
    w("  so those bidders carry no state supplier id and no state join exists.")
    w("- The honest statement is therefore that *Cal eProcure* does not publish bidder")
    w("  lists, not that California does not. Agencies do, one at a time, in their own")
    w("  formats, and nobody has aggregated them.")
    w("- Award history, by contrast, is rich and queryable, and each supplier carries a")
    w("  stable identifier, so vendor identity is resolvable without guesswork.")
    w("- On the state portal itself, named participants come from **documents**, not from")
    w("  portal fields: intent-to-award notices attached to events state the winning")
    w("  company and its price.")
    w("")
    if awards:
        w(f"Of {_fmt(len(awards))} award records ingested, {_fmt(competitive)} were awarded through an")
        w("explicitly competitive method and the remainder through vehicles, cooperative")
        w("agreements or non-competitive exemptions. Competitive intensity in this market is")
        w("therefore not uniform: a large share of state spending never reaches an open")
        w("competition at all, which is itself a targeting signal.")
        w("")
        # Filter through the same entity test the ranking uses. Listing a county among
        # "most active suppliers" in a competitive-landscape section would contradict the
        # rule that excludes it from competitor ranking.
        from .predict import is_biddable_entity
        biddable, excluded = [], []
        for prof in sorted(profiled, key=lambda x: -(x.get("awards_observed") or 0)):
            ok, _ = is_biddable_entity(prof.get("supplier_id") or "",
                                       prof.get("canonical_name"))
            (biddable if ok else excluded).append(prof)
        w("Most active **competing firms** by observed award count. Government and")
        w("interagency sellers are excluded here by the same test the ranking uses:")
        w("")
        w("| Vendor | Awards | Agencies | Certifications |")
        w("| --- | ---: | ---: | --- |")
        for prof in biddable[:10]:
            w(f"| {prof.get('canonical_name')} | {_fmt(prof.get('awards_observed'))} | "
              f"{_fmt(prof.get('agency_count'))} | "
              f"{', '.join(prof.get('certifications') or []) or '—'} |")
        w("")
        if excluded:
            top_excluded = ", ".join(
                f"{e.get('canonical_name')} ({_fmt(e.get('awards_observed'))} awards)"
                for e in excluded[:3])
            w(f"{_fmt(len(excluded))} profiled sellers were excluded as non-competing")
            w(f"entities, the largest being {top_excluded}. They are real suppliers to the")
            w("state and belong in spend analysis, but they are not rival bidders.")
            w("")

    w("## Prediction quality, measured on held-out events")
    w("")
    if evaluation:
        w("| Metric | Value |")
        w("| --- | ---: |")
        w(f"| Events evaluated | {_fmt(evaluation.get('events_evaluated'))} |")
        w(f"| precision@3 | {_fmt(evaluation.get('precision_at_3'))} |")
        w(f"| precision@5 | {_fmt(evaluation.get('precision_at_5'))} |")
        w(f"| Coverage of actual awardees in top 10 | {_fmt(evaluation.get('coverage'))} |")
        comparison = evaluation.get("baseline_comparison") or {}
        if comparison:
            w(f"| Best trivial baseline precision@3 | "
              f"{_fmt(comparison.get('best_baseline_precision_at_3'))} |")
            w(f"| Model lift over that baseline | "
              f"{_fmt(comparison.get('lift_over_best_baseline'))}x |")
            w("")
            # Derived, never written down. Two lift figures used to be hardcoded here
            # from particular runs; they outlived the corpus that produced them and the
            # report went on quoting them next to numbers that disagreed.
            gap = _gap(evaluation.get("precision_at_3"),
                       comparison.get("best_baseline_precision_at_3"))
            w("**Read the lift as undetermined, not as a result.** Most events score exactly")
            w("zero, so the per-event spread swamps the mean: at this sample size the 95%")
            w("confidence interval on precision@3 is roughly plus or minus 0.03 to 0.04,")
            w(f"wider than the {gap} that separates the model from the baseline. The lift")
            w("has swung either side of 1.0 as the award window and the corpus changed,")
            w("with the ranking itself untouched. This evaluation is too small and too")
            w("zero-heavy to say whether the ranking beats counting past wins. Quoting")
            w("the lift without that caveat would be the misleading choice.")
        w("")
    w("These are weak numbers and are reported unadjusted. Two structural causes, both about")
    w("the data rather than the ranking:")
    w("")
    w("1. **History depth is capped.** The award search returns at most 200 rows and cannot")
    w("   be paged, so history has to be assembled by slicing dates. Most days exceed the")
    w("   cap, so each vendor carries only a handful of prior awards.")
    w("2. **The ground truth is purchase-level, not solicitation-level.** Award rows are")
    w("   often small commodity orders filled by whoever already holds a statewide vehicle.")
    w("   Predicting that is a materially different question from predicting who will bid on")
    w("   an RFP, and the two should not be conflated.")
    w("")
    w("A solicitation-level evaluation set is possible, but it has to be built from")
    w("award-notice documents, and its size is bounded by how many agencies post one.")
    w("")

    w("## Teaming recommendations")
    w("")
    cands = primes.get("prime_candidates") or []
    prov = primes.get("corpus_provenance") or {}
    eligible = prov.get("eligible_vendor_count")
    qualified = primes.get("candidates_qualified")

    # Counts, rule and corpus provenance print whether or not anything qualified. "0 of 75
    # eligible" tells a reader far more than a generic "nothing qualified", and the corpus
    # note is most needed precisely when the answer is empty.
    if primes:
        if eligible:
            # Quote the eligible denominator, not the whole corpus. Only vendors holding an
            # award at this agency or in this category can qualify at all, so "57 of 579"
            # reads as a 10% pass rate when the real figure is 76% -- understating in our
            # own favour, which is the wrong direction to be wrong in.
            pct = round((qualified or 0) / eligible * 100, 1)
            w(f"For the demonstrated opportunity, **{_fmt(qualified)} of {_fmt(eligible)}")
            w(f"eligible vendors** qualified as credible primes ({pct}%). Eligible means")
            w("holding at least one award with this agency or in this category; the wider")
            w(f"corpus held {_fmt(primes.get('vendors_considered'))} vendors, but the rest could")
            w("never qualify whatever their history.")
        else:
            w(f"For the demonstrated opportunity, {_fmt(qualified)} of")
            w(f"{_fmt(primes.get('vendors_considered'))} vendors qualified as credible primes.")
        w("")
        if primes.get("qualification_rule"):
            w(f"Rule: {primes['qualification_rule']}.")
            w("")
        if primes.get("qualification_note"):
            w(primes["qualification_note"])
            w("")
        if prov.get("why_this_corpus"):
            note = prov["why_this_corpus"]
            w(f"**Corpus note.** {note[:1].upper()}{note[1:]}.")
            w("")
        if prov.get("prior_invalid_run"):
            w(f"**Superseded result.** {prov['prior_invalid_run']}")
            w("")

    for c in cands[:5]:
        cc = c["credibility_case"]
        w(f"**{c['vendor_name']}** — score {c['prime_score']}, confidence {c['confidence']}"
          + ("  \n  *Also ranked as a likely competitor on this opportunity.*"
             if c.get("also_likely_competitor") else ""))
        w(f"  - Credible because: {cc['awards_at_or_above_value_floor']} awards at or above "
          f"the ${cc.get('value_floor') or 0:,.0f} value floor "
          f"({cc.get('value_floor_basis', 'basis not recorded')}), "
          f"{cc['awards_with_this_agency']} with this agency, "
          f"{cc['awards_in_this_category']} in this category; largest observed award "
          f"{_money(cc['largest_award'])} against an opportunity value of "
          f"{_money(cc.get('opportunity_value'))}.")
        if c["teaming_case"]["sufficient"]:
            for reason in c["teaming_case"]["reasons"]:
                w(f"  - Worth approaching because: {reason}.")
        else:
            # Credible as a prime but no articulable reason they would want the client.
            # Saying so is more useful than manufacturing a rationale.
            w("  - **No teaming rationale found.** Credible as a prime, but nothing in the "
              "client's profile fills a gap this company's record shows. Treat as a "
              "competitor to watch rather than an outreach target.")
        if c["disqualifiers"]:
            w(f"  - Against: {'; '.join(c['disqualifiers'])}.")
        w("")

    if not cands:
        w("No vendor qualified as a credible prime for the demonstrated opportunity. Reporting")
        w("an empty list is the correct outcome: a list of primes padded with vendors that have")
        w("never handled comparable work is worse than no list.")
        w("")
    elif primes.get("dual_role_candidates"):
        w(f"{_fmt(len(primes['dual_role_candidates']))} of the ranked primes are also predicted")
        w("competitors on this opportunity. That tension is surfaced rather than resolved:")
        w("whether to approach a rival is the client's call, not the model's.")
        w("")

    w("## Data quality and what is deliberately absent")
    w("")
    w("- **Win rates only where a full bidder field was observed.** A vendor seen on a")
    w("  Caltrans bid-results page has a real rate, computed over those solicitations and")
    w("  labelled as that subset rather than as an overall figure. Everywhere else a rate")
    w("  stays null with the reason attached, never faked by equating bids with wins.")
    w("- **No subcontracting history in the sources wired in.** An SCPRS award evidences")
    w("  priming; nothing here observes a subcontract, so its absence is recorded as")
    w("  unknown, never as negative. Not the same as unobtainable: SF Public Works cites a")
    w("  per-bid subcontractor listing alongside each tabulation, which is the obvious")
    w("  next source and is not yet retrieved.")
    w("- **Every aggregate states its denominator.** Amount statistics report parseable,")
    w("  unparseable and absent counts separately.")
    w("- **Government sellers are excluded from competitor ranking.** Counties and state")
    w("  authorities appear as suppliers in the award registry; ranking them as rival")
    w("  bidders would be a visible error.")
    w("- **Conflicting vendor identities are flagged, never merged.**")
    if statuses:
        w("")
        w(f"Document acquisition outcomes: {dict(statuses)}.")
    if methods:
        w(f"Extraction methods used: {dict(methods)}.")
    w("")

    w("## Chromie data-contract compatibility")
    w("")
    if validation:
        w("| Table | Rows | Valid |")
        w("| --- | ---: | --- |")
        for t in validation.get("tables", []):
            w(f"| `{t['table']}` | {_fmt(t['rows'])} | {'yes' if t['valid'] else 'NO'} |")
        w("")
        w("**Important caveat.** The frozen data-contract snapshot the brief describes was not")
        w("present in the repository. These schemas were authored locally from the pattern")
        w("table in the brief, so passing validation demonstrates internal consistency, not")
        w("compatibility with Chromie's real schema. Identifiers are deterministic local")
        w("UUIDs; no production identifier is assumed, and nothing writes to any Supabase")
        w("instance. `build/supabase/handoff.json` carries the import order, natural upsert")
        w("keys, conflict behaviour and the local-to-production remapping plan.")
        w("")

    w("## Recommended next actions")
    w("")
    w("*Judgement, not measurement: these follow from the access research in "
      "`DECISIONS.md` and `sources/source_registry.csv`.*")
    w("")
    w("1. **Harvest award notices systematically.** They are the only public source that")
    w("   names a participant against a specific solicitation. Sweeping every active event")
    w("   for one would build the first genuinely solicitation-level bidder dataset in this")
    w("   market.")
    w("2. **Mine the vendor-ad board.** A `Prime Seeking Sub` advertisement is a company")
    w("   publicly declaring intent to bid as prime on a named solicitation — the strongest")
    w("   forward-looking signal California exposes. It is reachable and not yet harvested.")
    w("3. **Deepen history per vendor, not per day.** The 200-row cap makes date-sliced")
    w("   backfill inefficient, while a per-supplier query returns that vendor's record")
    w("   directly. Once a candidate set exists, enrich it vendor by vendor.")
    w("4. **Classify supplier entity type.** Counties, interagency authorities and resellers")
    w("   behave differently from competing firms and should not share one model.")
    w("5. **Treat non-competitive awards as a targeting signal.** A department that buys")
    w("   repeatedly outside open competition is a different sales problem from one that runs")
    w("   formal solicitations, and the award method states which is which.")
    w("")

    w("## Next three sources to add")
    w("")
    w("*Judgement, from the surfaces surveyed during access research; the reasons below "
      "are what was observed on each portal, not figures computed from `build/`.*")
    w("")
    w("1. **Virginia eVA.** Its public endpoint is a pass-through onto a search index with a")
    w("   full historical corpus and explicit award and intent-posted statuses, including")
    w("   local agencies in the same feed. It is the densest evidence layer available and the")
    w("   right place to prototype confirmed-versus-inferred logic before applying it to")
    w("   California, where the public record is thinner.")
    w("2. **Georgia Procurement Registry.** The only surveyed portal where search, detail and")
    w("   attachment download are all confirmed anonymous end to end, and it carries an")
    w("   explicit state-versus-local discriminator, so local coverage arrives free.")
    w("3. **Texas ESBD.** A JSON endpoint with a last-modified timestamp on every record,")
    w("   which makes change detection exact rather than hash-based, plus a full agency")
    w("   lookup table to seed the buyer dimension.")
    w("")
    w("California should stay the reference market — it is the hardest of the four and forces")
    w("the evidence model to be honest — but the three above are where volume and confirmed")
    w("award history are cheapest to obtain.")
    w("")
    return "\n".join(lines) + "\n"


def write(path: str | pathlib.Path = "build/report.md") -> str:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate())
    return str(target)
