"""Explainable likely-bidder baseline.

Deliberately a transparent weighted sum, not a learned model. README requires feature
contributions and confidence rather than an opaque score, and the evaluation set is far too
small to justify anything that cannot be read off by hand.

Three disciplines are enforced structurally rather than by convention:

1. **No future leakage.** Every feature is computed from awards strictly before the
   opportunity's cutoff date. `rank_candidates` filters the corpus itself, so a caller
   cannot accidentally pass future rows.
2. **Predictions are never facts.** Output is labelled `predicted`, and a vendor already
   observed on the event is excluded from ranking and reported separately -- an observed
   participant is evidence, not a prediction, and scoring it would flatter the metrics.
3. **Eligibility is not intent.** Certification and vehicle presence contribute only
   *alongside* participation history, never alone. README forbids treating a certification
   or a registration as proof that a vendor will bid.
"""
from __future__ import annotations

import collections
import datetime as dt
import math
import re
import statistics
from typing import Any, Iterable

from .sources.ca import scprs
from .vendors import EARLIEST_PLAUSIBLE, normalize_name

# Weights are hand-set and published. Participation history dominates; eligibility signals
# are small multipliers on top of it. Tuning these against the evaluation set would make the
# reported precision meaningless, so they are fixed before evaluation and left alone.
WEIGHTS = {
    "same_agency_awards": 3.0,
    "same_category_awards": 2.0,
    "agency_and_category_awards": 3.5,
    "recency": 1.5,
    "frequency": 1.0,
    "size_similarity": 1.0,
    "competitive_history": 0.75,
    "cert_match": 0.5,
    "vehicle_presence": 0.5,
}
# `primes_similar_work` was removed: it scored `len(both)`, the same evidence as
# `agency_and_category_awards`, so agency-and-category carried an undisclosed effective
# weight of 4.5 rather than the 3.5 the table shows. Whether a vendor primes similar work
# is a real signal, but SCPRS cannot distinguish prime from sub, so it is not measurable
# here and a second copy of an existing count is not a substitute.
# Vendors that are not biddable competitors. Measured: Calaveras County and a state
# correctional authority both appear as SCPRS suppliers. Ranking a county as a rival bidder
# would be a visible correctness failure.
_NON_COMPETITOR = re.compile(
    r"\b(?:county|city of|state of|university of|regents|department|dept|"
    r"prison industry)\b", re.I)
# These read as government only in the absence of a corporate suffix. "PARTS AUTHORITY LLC"
# was ranked as a government entity and printed as one in the report, which is the same
# class of error in the opposite direction.
_WEAK_GOV = re.compile(r"\b(?:authority|district|board of)\b", re.I)
_CORPORATE_SUFFIX = re.compile(
    r"\b(?:inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|lp|llp|"
    r"plc)\b\.?", re.I)
_DEPT_SUPPLIER_ID = re.compile(r"^DEPT", re.I)


def is_biddable_entity(supplier_id: str, name: str | None) -> tuple[bool, str | None]:
    """Exclude government and interagency sellers from competitor ranking."""
    if _DEPT_SUPPLIER_ID.match(supplier_id or ""):
        return False, "supplier_id marks an interagency department seller"
    if name and _NON_COMPETITOR.search(name):
        return False, "name matches a government or interagency pattern"
    if name and _WEAK_GOV.search(name) and not _CORPORATE_SUFFIX.search(name):
        return False, "name reads as a public body and carries no corporate suffix"
    return True, None


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return None


def _amount(row: dict[str, str]) -> float | None:
    numeric = scprs.amount_to_numeric(row.get("awarded_amt"))
    return float(numeric) if numeric is not None else None


def _saturate(count: float, half: float) -> float:
    """Diminishing returns: the 40th award with an agency means less than the 4th.

    Bounded to [0, 1) so no single feature can dominate through sheer volume.
    """
    return count / (count + half) if count > 0 else 0.0


def features_for_vendor(
    history: list[dict[str, str]], opportunity: dict[str, Any], cutoff: dt.date,
) -> dict[str, Any]:
    """Per-feature values and contributions for one vendor against one opportunity.

    `history` must already be restricted to awards before `cutoff`; `rank_candidates` does
    that filtering.
    """
    agency = opportunity.get("department")
    category = opportunity.get("category")
    target_amount = opportunity.get("amount")
    required_certs = set(opportunity.get("required_certifications") or [])

    same_agency = [r for r in history if agency and r.get("department") == agency]
    same_category = [r for r in history if category and r.get("category") == category]
    both = [r for r in same_agency if category and r.get("category") == category]

    # Recency and frequency describe *relevant* participation. Scoring them over a vendor's
    # entire history meant anyone who sold anything to any agency recently was ranked as a
    # likely bidder here -- which is the "existence is not intent" failure in another guise.
    # Relevance is prior activity with this agency or in this category.
    relevant = {id(r): r for r in (*same_agency, *same_category)}.values()
    dates = [d for d in (_parse_date(r.get("start_date")) for r in relevant)
             if d and EARLIEST_PLAUSIBLE <= d <= cutoff]
    days_since = (cutoff - max(dates)).days if dates else None
    span_years = ((max(dates) - min(dates)).days / 365.25) if len(dates) > 1 else None
    frequency = (len(dates) / span_years) if span_years and span_years > 0.25 else None

    amounts = [a for a in (_amount(r) for r in relevant) if a is not None]
    median_amount = statistics.median(amounts) if amounts else None

    certs = {c for r in history for c in (r.get("cert_type") or "").split("|") if c.strip()}
    vehicles = {r["lpa_contract"] for r in history if r.get("lpa_contract")}
    competitive = sum(1 for r in relevant
                      if "COMPETITIVE" in (r.get("acq_method") or "").upper()
                      and "NON-COMPETITIVE" not in (r.get("acq_method") or "").upper())

    values: dict[str, float] = {
        "same_agency_awards": _saturate(len(same_agency), 4),
        "same_category_awards": _saturate(len(same_category), 6),
        "agency_and_category_awards": _saturate(len(both), 2),
        # Half-life of one year: participation two years stale counts a quarter as much.
        "recency": (0.5 ** (days_since / 365.25)) if days_since is not None else 0.0,
        "frequency": _saturate(frequency, 6) if frequency else 0.0,
        "size_similarity": _size_similarity(median_amount, target_amount),
        "competitive_history": _saturate(competitive, 5),
        "cert_match": (len(required_certs & certs) / len(required_certs)
                       if required_certs and certs else 0.0),
        "vehicle_presence": 1.0 if (opportunity.get("vehicle") in vehicles
                                    and opportunity.get("vehicle")) else 0.0,
    }

    # Eligibility signals may only amplify demonstrated participation. Without history they
    # contribute nothing, so a certified vendor that has never sold to this agency in this
    # category cannot be ranked as a likely bidder on eligibility alone.
    participation = max(values["same_agency_awards"], values["same_category_awards"])
    gated = {"cert_match", "vehicle_presence"}
    for key in gated:
        values[key] *= participation

    contributions = {k: round(WEIGHTS[k] * v, 4) for k, v in values.items()}
    score = round(sum(contributions.values()), 4)
    return {
        "score": score,
        "feature_values": {k: round(v, 4) for k, v in values.items()},
        "feature_contributions": contributions,
        "top_factors": [k for k, _ in sorted(contributions.items(), key=lambda kv: -kv[1])[:3]
                        if contributions[k] > 0],
        "weakening_factors": _weakening(values, opportunity),
        "relevant_awards": len(list(relevant)),
        "evidence_counts": {
            "awards_before_cutoff": len(history),
            "relevant_awards_before_cutoff": len(list(relevant)),
            "same_agency": len(same_agency),
            "same_category": len(same_category),
            "same_agency_and_category": len(both),
            "days_since_last_award": days_since,
        },
        "median_prior_amount": round(median_amount, 2) if median_amount else None,
    }


def _size_similarity(median_amount: float | None, target: float | None) -> float:
    """Closeness in order of magnitude. Unknown target contributes nothing, not a penalty."""
    if not median_amount or not target or median_amount <= 0 or target <= 0:
        return 0.0
    ratio = math.log10(median_amount / target)
    return max(0.0, 1.0 - abs(ratio) / 2.0)


def _weakening(values: dict[str, float], opportunity: dict[str, Any]) -> list[str]:
    """Factors arguing against the prediction. README requires these alongside support."""
    out: list[str] = []
    if values["same_agency_awards"] == 0:
        out.append("no prior award with this agency")
    if values["same_category_awards"] == 0:
        out.append("no prior award in this category")
    if values["recency"] < 0.25:
        out.append("last observed award is stale")
    if values["size_similarity"] == 0 and opportunity.get("amount"):
        out.append("typical award size differs by more than two orders of magnitude")
    if values["competitive_history"] == 0:
        out.append("no competitively awarded history observed")
    return out


def rank_candidates(
    corpus: Iterable[dict[str, str]], opportunity: dict[str, Any], *, cutoff: str,
    top_n: int = 10, observed_vendor_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Rank likely bidders for one opportunity from award history before `cutoff`.

    Returns predictions plus the excluded sets, so a reader can see what was filtered and
    why rather than inferring it from an absence.
    """
    cutoff_date = _parse_date(cutoff) or dt.datetime.strptime(cutoff, "%Y-%m-%d").date()
    observed = {v for v in observed_vendor_ids if v}

    by_vendor: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    leaked = 0
    for row in corpus:
        sid = (row.get("supplier_id") or "").strip()
        if not sid:
            continue
        date = _parse_date(row.get("start_date"))
        if date is None or date >= cutoff_date:
            leaked += date is not None
            continue
        by_vendor[sid].append(row)

    predictions: list[dict[str, Any]] = []
    excluded_entities: list[dict[str, Any]] = []
    no_relevance: list[dict[str, Any]] = []
    for sid, history in by_vendor.items():
        name = next((r.get("supplier_name") for r in reversed(history)
                     if r.get("supplier_name")), None)
        biddable, reason = is_biddable_entity(sid, name)
        if not biddable:
            excluded_entities.append({"supplier_id": sid, "name": name, "reason": reason})
            continue
        if sid in observed:
            continue
        scored = features_for_vendor(history, opportunity, cutoff_date)
        if scored["relevant_awards"] == 0:
            # No award with this agency and none in this category. Whatever else is true of
            # the vendor, nothing here evidences interest in this opportunity.
            no_relevance.append({"supplier_id": sid, "name": name,
                                 "awards_before_cutoff": len(history)})
            continue
        if scored["score"] <= 0:
            continue
        predictions.append({
            "supplier_id": sid,
            "vendor_name": name,
            "evidence_class": "predicted",
            "confidence": _confidence(scored),
            **scored,
        })

    predictions.sort(key=lambda p: (-p["score"], p["supplier_id"]))
    return {
        "opportunity": {k: v for k, v in opportunity.items() if k != "corpus"},
        "cutoff": cutoff_date.isoformat(),
        "predictions": predictions[:top_n],
        "candidates_scored": len(predictions),
        "vendors_in_corpus_before_cutoff": len(by_vendor),
        "rows_excluded_as_future": leaked,
        "excluded_non_competitor_entities": excluded_entities,
        "excluded_no_relevant_history": len(no_relevance),
        "observed_participants_excluded_from_ranking": sorted(observed),
        "note": "predictions are ranked likelihoods, never confirmed bidders",
    }


def _confidence(scored: dict[str, Any]) -> str:
    """Confidence tracks how much evidence sits behind the score, not the score itself."""
    counts = scored["evidence_counts"]
    if counts["same_agency_and_category"] >= 3 and scored["score"] >= 4:
        return "high"
    if counts["same_agency"] >= 2 or counts["same_category"] >= 3:
        return "medium"
    return "low"


def precision_at_k(predicted_ids: list[str], actual_ids: Iterable[str], k: int) -> float | None:
    """Fraction of the top k predictions that actually participated.

    Returns None when there is no ground truth, rather than 0.0 -- "we could not tell"
    must not be recorded as "the model was wrong".
    """
    actual = {a for a in actual_ids if a}
    if not actual:
        return None
    top = predicted_ids[:k]
    # Divided by k, not by len(top): a model returning one correct prediction has not
    # scored precision@3 of 1.0. The baselines always return a full list, so dividing by
    # the shorter length would have biased the comparison toward the model.
    return round(sum(1 for p in top if p in actual) / k, 4)


def coverage(predicted_ids: list[str], actual_ids: Iterable[str]) -> float | None:
    """Fraction of actual participants that appear anywhere in the prediction list."""
    actual = {a for a in actual_ids if a}
    if not actual:
        return None
    return round(sum(1 for a in actual if a in set(predicted_ids)) / len(actual), 4)


EVENT_SELECTION = (
    "every (agency, category) pair with a same-day awardee, unselected. An earlier "
    "evaluation used only the ten pairs with the deepest prior history, which are the most "
    "predictable, and reported precision@3 0.17-0.20. On the unselected set the figure is "
    "lower and is the one that should be quoted.")


def holdout_events(awards: list[dict[str, str]], *, cutoff: str,
                   ) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Split an award corpus into prior history and held-out events at `cutoff`.

    An event is one (agency, category) pair that received an award on the cutoff day; the
    suppliers it went to are the ground truth. Every such pair is kept -- selecting the
    pairs with the deepest history picks the most predictable events and flatters the
    score, which is exactly the bias that produced the discarded 0.17 figure.
    """
    cutoff_date = _parse_date(cutoff)
    if cutoff_date is None:
        raise ValueError(f"unparseable cutoff: {cutoff!r}")
    history, held_out = [], []
    for row in awards:
        date = _parse_date(row.get("start_date"))
        if date is None:
            continue
        if date == cutoff_date:
            held_out.append(row)
        elif date < cutoff_date:
            history.append(row)

    grouped: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for row in held_out:
        grouped[(row.get("department") or "", row.get("category") or "")].append(row)

    events = [{
        "opportunity": {
            "department": agency,
            "category": category,
            # Truncated agency plus category: short enough to read in a per-event table,
            # unique enough to identify the pair.
            "event_ref": f"{agency[:22]}|{category[:18]}",
            "amount": None,
        },
        "actual_participant_ids": sorted({(r.get("supplier_id") or "").strip()
                                          for r in rows if r.get("supplier_id")}),
    } for (agency, category), rows in sorted(grouped.items())]
    return history, events


def evaluate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate precision@3, precision@5 and coverage over held-out events.

    Events without ground truth are counted and excluded from the means rather than
    silently scored as failures.
    """
    p3, p5, cov, scored, unusable = [], [], [], 0, 0
    for result in results:
        predicted = [p["supplier_id"] for p in result["predictions"]]
        actual = result.get("actual_participant_ids") or []
        if not actual:
            unusable += 1
            continue
        scored += 1
        p3.append(precision_at_k(predicted, actual, 3))
        p5.append(precision_at_k(predicted, actual, 5))
        cov.append(coverage(predicted, actual))
    mean = lambda xs: round(statistics.mean(xs), 4) if xs else None  # noqa: E731
    return {
        "events_evaluated": scored,
        "events_without_ground_truth": unusable,
        "precision_at_3": mean(p3),
        "precision_at_5": mean(p5),
        "coverage": mean(cov),
        "per_event": [
            {"event": r.get("opportunity", {}).get("event_ref"),
             "precision_at_3": precision_at_k([p["supplier_id"] for p in r["predictions"]],
                                              r.get("actual_participant_ids") or [], 3),
             "coverage": coverage([p["supplier_id"] for p in r["predictions"]],
                                  r.get("actual_participant_ids") or [])}
            for r in results
        ],
    }


# --- baselines --------------------------------------------------------------------------
# A precision figure alone cannot be judged. On a task where hundreds of eligible commodity
# suppliers compete for a handful of same-day purchase orders, a low absolute precision may
# still be the best obtainable result -- or it may be no better than counting who is busiest.
# Measured on the unselected 55-event set, the best trivial baseline below scores p@3 0.0606
# against the model's 0.0727 -- a lift of 1.2x. That lift held between 1.20x and 1.33x at
# every set size tried, so the ranking carries signal beyond "who wins most often":
# consistently, and consistently modestly. Reporting the comparison is the honest way to
# present a weak absolute number. Figures regenerate with `cli evaluate`.

def _biddable_counter(history: Iterable[dict[str, str]],
                      keep: Any = lambda row: True) -> list[str]:
    counts: collections.Counter[str] = collections.Counter()
    for row in history:
        sid = (row.get("supplier_id") or "").strip()
        if not sid or not keep(row):
            continue
        if not is_biddable_entity(sid, row.get("supplier_name"))[0]:
            continue
        counts[sid] += 1
    return [sid for sid, _ in counts.most_common()]


BASELINES: dict[str, Any] = {
    # Deliberately ignores the opportunity: pure popularity.
    "most_awards_overall": lambda history, opp: _biddable_counter(history),
    "most_awards_in_category": lambda history, opp: _biddable_counter(
        history, lambda r: r.get("category") == opp.get("category")),
    "most_awards_with_agency": lambda history, opp: _biddable_counter(
        history, lambda r: r.get("department") == opp.get("department")),
}


def compare_to_baselines(
    history: list[dict[str, str]], events: list[dict[str, Any]], *, cutoff: str,
) -> dict[str, Any]:
    """Score the model and every baseline over the same events, history and metrics.

    `events` are `{"opportunity": {...}, "actual_participant_ids": [...]}` mappings. The
    comparison is only meaningful when every approach sees identical inputs, so history and
    cutoff are applied once here rather than per approach.
    """
    # The baselines count rows directly and would otherwise see history the model is
    # forbidden to use. Filtering once here is what makes the claim above true.
    cutoff_date = _parse_date(cutoff)
    if cutoff_date is None:
        raise ValueError(f"unparseable cutoff: {cutoff!r}")
    history = [r for r in history
               if (d := _parse_date(r.get("start_date"))) and d < cutoff_date]

    def measure(ranked_for: Any) -> dict[str, Any]:
        p3, p5, cov = [], [], []
        for event in events:
            ranked = ranked_for(event)
            actual = event.get("actual_participant_ids") or []
            p3.append(precision_at_k(ranked, actual, 3))
            p5.append(precision_at_k(ranked, actual, 5))
            cov.append(coverage(ranked[:10], actual))
        clean = lambda xs: [x for x in xs if x is not None]  # noqa: E731
        mean = lambda xs: round(statistics.mean(xs), 4) if xs else None  # noqa: E731
        return {"precision_at_3": mean(clean(p3)), "precision_at_5": mean(clean(p5)),
                "coverage_at_10": mean(clean(cov))}

    results = {
        name: measure(lambda e, fn=fn: fn(history, e["opportunity"]))
        for name, fn in BASELINES.items()
    }
    results["model"] = measure(lambda e: [
        p["supplier_id"] for p in rank_candidates(
            history, e["opportunity"], cutoff=cutoff, top_n=10)["predictions"]])

    best_baseline = max(
        (r["precision_at_3"] or 0.0 for name, r in results.items() if name != "model"),
        default=0.0)
    model_p3 = results["model"]["precision_at_3"] or 0.0
    return {
        "events": len(events),
        "cutoff": cutoff,
        "history_rows": len(history),
        "results": results,
        "best_baseline_precision_at_3": round(best_baseline, 4),
        "model_precision_at_3": round(model_p3, 4),
        "lift_over_best_baseline": (round(model_p3 / best_baseline, 3)
                                    if best_baseline else None),
        "interpretation": (
            "A low absolute precision is expected on this task: the ground truth is which "
            "few of hundreds of eligible suppliers received a purchase order on one day, "
            "not which firms bid on a solicitation. The comparison is what carries meaning "
            "-- the model must beat popularity to have earned its features."),
    }


# --- corpus provenance ------------------------------------------------------------------
# Selectively deepening some vendors' histories silently wrecks a ranking: enriching 25 of
# 279 vendors dropped precision@3 from 0.233 to 0.100 and coverage from 0.552 to 0.183,
# because the enriched few carried two hundred awards each against one or two for everyone
# else and dominated on evidence volume alone. Nothing in the output revealed it.
#
# Two dead ends before the right answer. Award-count skew cannot detect it: on a genuinely
# uniform six-day window one national supplier legitimately held 36 awards against a median
# of 1. Per-vendor date coverage cannot reliably detect it either, because a short sweep
# gives almost every vendor a zero-day span, so the statistic has no baseline to compare
# against.
#
# How a corpus was assembled is not a property to be inferred from the rows -- it is known
# at the moment of assembly. So it is declared, not guessed. `describe_corpus` reports the
# shape for a reader; `SWEEP` and `PER_VENDOR` say how it was built, and `MIXED` is the
# combination that invalidates a ranking.

SWEEP = "date_sweep"                 # one date window applied to every vendor
PER_VENDOR = "per_vendor_backfill"   # every candidate in a defined eligible set, uniformly
MIXED = "mixed"                      # a sweep plus an arbitrary subset: not rankable


def describe_corpus(corpus: Iterable[dict[str, str]], *,
                    build_method: str = SWEEP) -> dict[str, Any]:
    """Shape of an award corpus, plus the declared way it was assembled.

    `rankable` is False for `MIXED`, because a ranking over a sweep blended with a targeted
    subset measures which vendors were fetched rather than which are likely. Descriptive
    statistics are reported either way; they inform a reader but do not decide the question.
    """
    counts: collections.Counter[str] = collections.Counter()
    spans: dict[str, tuple[dt.date, dt.date]] = {}
    for row in corpus:
        sid = (row.get("supplier_id") or "").strip()
        if not sid:
            continue
        counts[sid] += 1
        date = _parse_date(row.get("start_date"))
        if date is None or not (EARLIEST_PLAUSIBLE <= date <= dt.date(2039, 12, 31)):
            continue
        lo, hi = spans.get(sid, (date, date))
        spans[sid] = (min(lo, date), max(hi, date))
    if not counts:
        return {"vendors": 0, "build_method": build_method, "rankable": True,
                "reason": "empty corpus"}
    values = sorted(counts.values())
    day_spans = sorted((hi - lo).days for lo, hi in spans.values())
    rankable = build_method != MIXED
    return {
        "vendors": len(counts),
        "awards_total": sum(values),
        "awards_per_vendor_median": statistics.median(values),
        "awards_per_vendor_max": values[-1],
        "observation_span_days_median": statistics.median(day_spans) if day_spans else 0,
        "observation_span_days_max": day_spans[-1] if day_spans else 0,
        "build_method": build_method,
        "rankable": rankable,
        "reason": ({
            SWEEP: "one date window applied to every vendor, so history depth is not an "
                   "artifact of which vendors were fetched",
            PER_VENDOR: "every candidate in a defined eligible set was backfilled, so depth "
                        "is uniform within the set that can qualify",
            MIXED: "a date sweep blended with an arbitrary per-vendor subset: the enriched "
                   "vendors dominate on evidence volume, so any ranking over this corpus "
                   "reflects which vendors were fetched rather than which are likely",
        }).get(build_method, f"unrecognised build method {build_method!r}"),
        "guidance": ("assemble history as one date window across all vendors, or backfill "
                     "every member of a defined eligible set -- never an arbitrary subset"),
        "note": ("award-count skew is not evidence of this problem: genuine market "
                 "concentration produces large count ratios on a perfectly uniform window"),
    }
