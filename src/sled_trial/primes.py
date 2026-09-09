"""Prime-contractor recommendations for subcontracting outreach.

The question is not "who is big" but "who could credibly prime this, and why would they
want what the client offers". README requires both halves to be explained, so every
recommendation carries a credibility case and a separate teaming case, each grounded in
counted evidence.

Two rules that shape the output:

* A recommendation requires evidence of **prime awards at comparable value**. Reach alone
  does not qualify a company; a vendor with a hundred tiny commodity orders is not a
  credible prime for a million-dollar services contract.
* A likely competitor can also be a viable partner, and that tension is surfaced rather
  than resolved. README asks for exactly this case to be identified.
"""
from __future__ import annotations

import collections
import datetime as dt
import statistics
from typing import Any, Iterable

from . import predict
from .vendors import EARLIEST_PLAUSIBLE

WEIGHTS = {
    "prime_award_evidence": 3.0,
    "agency_relationship": 2.5,
    "value_comparability": 2.0,
    "scope_coverage": 1.5,
    "vehicle_access": 1.0,
    "certification_fit": 0.75,
    "recency": 1.25,
}
# A prime candidate must clear this on prime-award evidence alone before anything else is
# considered. Without it the remaining signals describe a supplier, not a prime.
MIN_PRIME_AWARDS = 2
# A prime candidate must show awards at or above one decade below the opportunity value.
# This is deliberately a FLOOR and not a two-sided band: a company whose awards dwarf the
# opportunity is still a credible prime for it, whereas one that has only ever handled work
# an order of magnitude smaller is not. Set to one decade after reading real output -- at
# 1.5 decades a vendor whose largest award was $38,870 qualified to prime $437,862.
VALUE_ORDERS_TOLERANCE = 1.0


def _amounts(rows: Iterable[dict[str, str]]) -> list[float]:
    return [a for a in (predict._amount(r) for r in rows) if a is not None]


def _is_eligible(history: Iterable[dict[str, str]], opportunity: dict[str, Any]) -> bool:
    """Could this vendor qualify at all?

    `assess_prime` rejects any vendor with no award at this agency and none in this
    category, so that pair is the ceiling on who can ever qualify. It is the honest
    denominator for a pass rate, and the set worth backfilling history for.
    """
    agency, category = opportunity.get("department"), opportunity.get("category")
    return any((agency and r.get("department") == agency)
               or (category and r.get("category") == category) for r in history)


def eligible_supplier_ids(corpus: Iterable[dict[str, str]],
                          opportunity: dict[str, Any]) -> list[str]:
    """Supplier ids worth deepening before ranking primes.

    Backfilling exactly this set is uniform rather than biasing: a vendor outside it can
    never qualify however deep its history, so nobody's relative standing inside the set
    changes. Prediction cannot be rescued the same way -- its candidate pool is every
    vendor with any relevant award, so deepening a subset reorders the ranking.
    """
    by_vendor: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in corpus:
        sid = (row.get("supplier_id") or "").strip()
        if sid:
            by_vendor[sid].append(row)
    return sorted(sid for sid, history in by_vendor.items()
                  if _is_eligible(history, opportunity))


def assess_prime(
    supplier_id: str, name: str | None, history: list[dict[str, str]],
    opportunity: dict[str, Any], client: dict[str, Any], cutoff: dt.date,
) -> dict[str, Any] | None:
    """Assess one vendor as a prime candidate. Returns None when it does not qualify.

    Returning None rather than a low score keeps unqualified companies out of the ranked
    output entirely: a list of "primes" that includes non-primes is worse than a short list.
    """
    biddable, _ = predict.is_biddable_entity(supplier_id, name)
    if not biddable:
        return None

    agency = opportunity.get("department")
    category = opportunity.get("category")
    target = opportunity.get("amount")
    client_categories = set(client.get("categories") or [])
    client_certs = set(client.get("certifications") or [])
    required_certs = set(opportunity.get("required_certifications") or [])

    dated = [(r, d) for r, d in ((r, predict._parse_date(r.get("start_date"))) for r in history)
             if d and EARLIEST_PLAUSIBLE <= d <= cutoff]
    history = [r for r, _ in dated]
    if not history:
        return None

    amounts = _amounts(history)
    # Prime evidence: awards at a value comparable to the opportunity. Where the
    # opportunity has no stated value, fall back to the vendor's own upper range so the
    # test still means "has handled work of this weight".
    if target:
        floor = target / (10 ** VALUE_ORDERS_TOLERANCE)
    elif amounts:
        # No stated value: the vendor's own median stands in, so the test still reads as
        # "has handled work of this weight". Note this is a weak floor by construction --
        # roughly half of any vendor's awards clear it.
        floor = statistics.median(amounts)
    else:
        return None
    comparable = [a for a in amounts if a >= floor]
    if len(comparable) < MIN_PRIME_AWARDS:
        return None

    same_agency = [r for r in history if agency and r.get("department") == agency]
    same_category = [r for r in history if category and r.get("category") == category]
    # README requires a prime candidate to have won work from this agency or jurisdiction,
    # or to cover the required scope. A vendor with neither is not a recommendation, it is
    # noise -- an earlier run surfaced one with 0 agency and 0 category awards.
    if not same_agency and not same_category:
        return None
    categories = collections.Counter(r["category"] for r in history if r.get("category"))
    vehicles = {r["lpa_contract"] for r in history if r.get("lpa_contract")}
    certs = {c for r in history for c in (r.get("cert_type") or "").split("|") if c.strip()}
    last = max(d for _, d in dated)
    days_since = (cutoff - last).days

    values = {
        "prime_award_evidence": predict._saturate(len(comparable), 4),
        "agency_relationship": predict._saturate(len(same_agency), 3),
        "value_comparability": predict._size_similarity(
            statistics.median(comparable) if comparable else None, target),
        "scope_coverage": predict._saturate(len(same_category), 4),
        "vehicle_access": 1.0 if opportunity.get("vehicle") in vehicles
                          and opportunity.get("vehicle") else 0.0,
        "certification_fit": (len(required_certs & certs) / len(required_certs)
                              if required_certs else 0.0),
        "recency": 0.5 ** (days_since / 365.25),
    }
    contributions = {k: round(WEIGHTS[k] * v, 4) for k, v in values.items()}
    score = round(sum(contributions.values()), 4)

    # The teaming case. A prime is worth approaching when the client covers scope the prime
    # demonstrably does not, or brings a certification the prime lacks and the solicitation
    # wants. Both are stated as rationale, never as a claim about the prime's intentions.
    prime_categories = set(categories)
    gap_categories = sorted(client_categories - prime_categories)
    cert_advantage = sorted(client_certs - certs)
    required_cert_gap = sorted((required_certs - certs) & client_certs)

    teaming_reasons: list[str] = []
    if gap_categories:
        teaming_reasons.append(
            f"client covers categories absent from this prime's observed record: "
            f"{', '.join(gap_categories)}")
    if required_cert_gap:
        teaming_reasons.append(
            f"solicitation seeks {', '.join(required_cert_gap)} which the client holds and "
            f"this prime's record does not show")
    elif cert_advantage:
        teaming_reasons.append(
            f"client holds certifications not observed on this prime: "
            f"{', '.join(cert_advantage)}")
    if same_agency and not same_category:
        teaming_reasons.append(
            f"strong relationship with {agency} but no observed award in {category}, so "
            f"scope depth is the plausible gap")

    # No "neither agency nor category" entry here: that case returned None above, so a
    # candidate reaching this point always has one of them.
    disqualifiers: list[str] = []
    if values["value_comparability"] == 0 and target:
        disqualifiers.append("typical comparable award differs sharply from opportunity value")
    if days_since > 730:
        disqualifiers.append("no observed award in the last two years")

    return {
        "supplier_id": supplier_id,
        "vendor_name": name,
        "prime_score": score,
        "confidence": "high" if len(comparable) >= 5 and same_agency else
                      "medium" if len(comparable) >= 3 or same_agency else "low",
        "feature_contributions": contributions,
        "credibility_case": {
            # Named for what it measures: awards at or above the value floor, not awards
            # of similar size. `value_comparability` below is the two-sided similarity, and
            # a candidate can clear the floor while scoring low on similarity.
            "awards_at_or_above_value_floor": len(comparable),
            "value_floor": round(floor, 2),
            "value_floor_basis": ("one decade below the stated opportunity value" if target
                                  else "this vendor's own median award: the opportunity "
                                       "states no value"),
            "median_award_above_floor": round(statistics.median(comparable), 2) if comparable else None,
            "largest_award": round(max(amounts), 2) if amounts else None,
            "opportunity_value": target,
            "largest_award_to_opportunity_ratio": (round(max(amounts) / target, 3)
                                                   if amounts and target else None),
            "awards_with_this_agency": len(same_agency),
            "awards_in_this_category": len(same_category),
            "categories_observed": [c for c, _ in categories.most_common(5)],
            "purchasing_vehicles": sorted(vehicles)[:5],
            "certifications_observed": sorted(certs),
            "last_award_days_before_cutoff": days_since,
            "basis": "an SCPRS award is a contract held directly with the state, "
                     "which evidences acting as a prime",
        },
        "teaming_case": {
            "reasons": teaming_reasons,
            "client_scope_gap_filled": gap_categories,
            "client_certification_advantage": cert_advantage,
            "sufficient": bool(teaming_reasons),
        },
        "disqualifiers": disqualifiers,
        "evidence": {
            "source_key": "caleprocure_scprs",
            "purchase_docs": [r["purchase_doc"] for r in history if r.get("purchase_doc")][:15],
            "awards_considered": len(history),
        },
        "evidence_class": "derived",
        "note": "credibility is evidence-backed; willingness to team is not observable",
    }


def recommend_primes(
    corpus: Iterable[dict[str, str]], opportunity: dict[str, Any], client: dict[str, Any],
    *, cutoff: str, top_n: int = 10, likely_bidder_ids: Iterable[str] = (),
    build_method: str = predict.SWEEP,
) -> dict[str, Any]:
    """Rank credible primes, flagging any that are also likely competitors.

    `build_method` declares how `corpus` was assembled and is reported unchanged, because a
    prime ranking over a sweep blended with an arbitrary subset measures which vendors were
    fetched. Primes need uniform depth within the eligible set, so `PER_VENDOR` over that
    set is the corpus this is meant to run on; a sweep will usually qualify nobody.
    """
    corpus = list(corpus)
    cutoff_date = (predict._parse_date(cutoff)
                   or dt.datetime.strptime(cutoff, "%Y-%m-%d").date())
    competitors = {c for c in likely_bidder_ids if c}

    by_vendor: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in corpus:
        sid = (row.get("supplier_id") or "").strip()
        date = predict._parse_date(row.get("start_date"))
        if sid and date and date < cutoff_date:
            by_vendor[sid].append(row)

    candidates: list[dict[str, Any]] = []
    for sid, history in by_vendor.items():
        name = next((r.get("supplier_name") for r in reversed(history)
                     if r.get("supplier_name")), None)
        assessed = assess_prime(sid, name, history, opportunity, client, cutoff_date)
        if assessed is None:
            continue
        if sid in competitors:
            # README asks for this case explicitly: the same company can be the strongest
            # partner and the strongest rival. Surfaced, not resolved.
            assessed["also_likely_competitor"] = True
            assessed["dual_role_note"] = (
                "ranked as a likely bidder on this opportunity as well; approaching them "
                "means approaching a competitor, which is a judgement call for the client")
        else:
            assessed["also_likely_competitor"] = False
        candidates.append(assessed)

    candidates.sort(key=lambda c: (-c["prime_score"], c["supplier_id"]))
    ranked = candidates[:top_n]

    # Only a vendor holding an award with this agency or in this category can ever qualify,
    # so it is the honest denominator. Quoting the whole corpus instead reads as a 10% pass
    # rate where the real figure is 76% -- understating in our own favour.
    eligible = sum(1 for history in by_vendor.values()
                   if _is_eligible(history, opportunity))
    provenance = predict.describe_corpus(corpus, build_method=build_method)
    provenance["eligible_vendor_count"] = eligible
    provenance["why_this_corpus"] = provenance["reason"]

    return {
        "opportunity": opportunity,
        "client": client,
        "cutoff": cutoff_date.isoformat(),
        "prime_candidates": ranked,
        "candidates_qualified": len(candidates),
        "vendors_considered": len(by_vendor),
        "corpus_provenance": provenance,
        "qualification_note": (
            "Qualification is a weak filter rather than a selective one: the value floor is "
            "easy to clear once a vendor has substantial award history, so the discriminating "
            "power lives in the ranking score, not in the qualified/unqualified split."
            if eligible else
            "No vendor in this corpus holds an award with this agency or in this category, so "
            "nothing could qualify whatever the rule. That is a corpus limit, not a finding "
            "about the market."),
        "qualification_rule": (
            f"at least {MIN_PRIME_AWARDS} awards at or above one decade below the "
            f"opportunity value, plus at least one award with this agency or in this "
            f"category; unqualified vendors are omitted entirely"),
        "dual_role_candidates": [c["supplier_id"] for c in ranked
                                 if c["also_likely_competitor"]],
    }
