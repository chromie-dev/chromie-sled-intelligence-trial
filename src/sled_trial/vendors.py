"""Vendor identity resolution and profiles, built from SCPRS award history.

Identity is not guessed. SCPRS assigns each supplier a stable `supplier_id`, so aliases
collapse onto that key without fuzzy matching -- verified on a live search where 200 awards
across 39 departments all carried one id. Fuzzy matching is used only to *detect conflicts*
worth human review, never to merge records.

What this data can and cannot support:

* Awards are wins. SCPRS records what the state bought, so it evidences awards and
  incumbency. It carries no losing bidders, so a profile can never report a loss rate, and
  `bids_total` is deliberately absent rather than set equal to wins.
* SCPRS awards are contracts held directly with the state, which is evidence of acting as a
  prime. Subcontracting is invisible here, so the absence of sub evidence means unknown.
* `cert_type` and `lpa_contract` are sparse (67/200 and 24/200 on a live sample). Absent
  means unobserved, never "not certified".
"""
from __future__ import annotations

import collections
import datetime as dt
import re
import statistics
from typing import Any, Callable, Iterable

from .sources import scprs

MAX_EVIDENCE_REFS = 25
# SCPRS data begins with state fiscal year 2010 (from 2009-07-01), so anything earlier is
# suspect. Multi-year contracts legitimately carry future start dates, but not decades out.
# Measured case: purchase_doc PO17-1119 (Department of Justice) carries start=end=02/14/2048,
# a single outlier in 200 rows whose document number suggests 2017. Left in the record and
# flagged, never silently dropped -- but excluded from spans so one typo cannot claim a
# vendor has been active for 22 years.
EARLIEST_PLAUSIBLE = dt.date(2009, 7, 1)
FUTURE_YEARS_ALLOWED = 10
_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
# Suffixes and punctuation stripped only to compare names for conflict detection. The
# canonical name is never rewritten -- normalisation exists to raise questions, not answers.
# Dots are removed before this runs, so the pattern carries no punctuated alternatives:
# "l.l.c." arrives as "llc". Written the other way round, `l\.l\.c\.` could never match --
# the trailing \b cannot follow a period at end of string.
_LEGAL_SUFFIX = re.compile(
    r"\b(?:inc|incorporated|llc|ltd|limited|corp|corporation|co|company|"
    r"lp|llp|plc|dba|the)\b", re.I)
_PUNCT = re.compile(r"[^a-z0-9 ]+")
# openfiscal.match_confidence never returns "high": these files carry no supplier id.
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
# Weakest first. Ranked explicitly because alphabetical order puts "unresolved" last and
# would report the shakiest match in a set as the strongest.
_IDENTITY_ORDER = ("unresolved", "ambiguous", "low", "medium", "high")
# Below this a rate is arithmetic on a handful of events, not a track record.
MIN_BIDS_FOR_A_STABLE_RATE = 3
_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Comparison key for conflict detection only. Not a canonical name.

    Dots go first, then suffixes, then the rest of the punctuation. The previous order --
    all punctuation, then suffixes -- turned "L.L.C." into "l l c", which no suffix
    alternative could match, so "Foo L.L.C." and "Foo LLC" never normalised together.
    Suffix stripping runs again at the end because removing punctuation can expose one.
    """
    text = _LEGAL_SUFFIX.sub(" ", (name or "").lower().replace(".", ""))
    text = _PUNCT.sub(" ", text)
    text = _LEGAL_SUFFIX.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _parse_date(value: str | None) -> dt.date | None:
    if not value or not _DATE.match(value.strip()):
        return None
    try:
        return dt.datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _split_certs(value: str | None) -> list[str]:
    """cert_type arrives pipe-delimited, e.g. 'SB|MB'."""
    if not value:
        return []
    return sorted({part.strip() for part in value.split("|") if part.strip()})


def build_profile(supplier_id: str, rows: list[dict[str, str]], *,
                  observed_at: str | None = None) -> dict[str, Any]:
    """One vendor profile from that vendor's SCPRS award rows.

    Every aggregate states the denominator it was computed over, because amount and date
    coverage is partial and a mean over an unstated subset is a misleading number.
    """
    names = collections.Counter(r["supplier_name"] for r in rows if r.get("supplier_name"))
    canonical, _ = names.most_common(1)[0] if names else (None, 0)
    aliases = sorted(n for n in names if n != canonical)

    amounts: list[float] = []
    unparseable_amounts = 0
    for row in rows:
        numeric = scprs.amount_to_numeric(row.get("awarded_amt"))
        if numeric is None:
            if row.get("awarded_amt"):
                unparseable_amounts += 1
            continue
        amounts.append(float(numeric))

    # Not `today.replace(year=...)`: on 29 February that raises ValueError and takes the
    # whole profile build down one day in four years.
    horizon = dt.date.today() + dt.timedelta(days=round(365.25 * FUTURE_YEARS_ALLOWED))
    all_dates = [(r, d) for r, d in ((r, _parse_date(r.get("start_date"))) for r in rows) if d]
    dates = [d for _, d in all_dates if EARLIEST_PLAUSIBLE <= d <= horizon]
    implausible = [{"purchase_doc": r.get("purchase_doc"), "start_date": r.get("start_date"),
                    "department": r.get("department")}
                   for r, d in all_dates if not (EARLIEST_PLAUSIBLE <= d <= horizon)]
    agencies = collections.Counter(r["department"] for r in rows if r.get("department"))
    categories = collections.Counter(r["category"] for r in rows if r.get("category"))
    methods = collections.Counter(r["acq_method"] for r in rows if r.get("acq_method"))
    certs = collections.Counter(c for r in rows for c in _split_certs(r.get("cert_type")))
    # Count ROWS carrying any certification, not total certification mentions. A row reading
    # "DVBE|SB-PW" contributes two mentions, so summing mentions over rows produced the
    # impossible "400/200 rows" in an earlier run.
    rows_with_cert = sum(1 for r in rows if _split_certs(r.get("cert_type")))
    vehicles = sorted({r["lpa_contract"] for r in rows if r.get("lpa_contract")})

    competitive = sum(v for k, v in methods.items() if "COMPETITIVE" in k.upper()
                      and "NON-COMPETITIVE" not in k.upper())
    non_competitive = sum(v for k, v in methods.items() if "NON-COMPETITIVE" in k.upper())
    vehicle_awards = sum(v for k, v in methods.items()
                         if any(t in k for t in ("Statewide Contracts", "CMAS",
                                                 "Cooperative Agreements", "Leveraged")))

    years = collections.Counter(d.year for d in dates)
    span_days = (max(dates) - min(dates)).days if len(dates) > 1 else None

    return {
        "supplier_id": supplier_id,
        "canonical_name": canonical,
        "aliases": aliases,
        "alias_count": len(aliases),
        "identity_basis": "scprs_supplier_id",
        "identity_confidence": "high" if supplier_id else "unresolved",

        "awards_observed": len(rows),
        # Deliberately absent: SCPRS records awards only. There is no public losing-bidder
        # data in California, so bid totals and win rates are not computable and are not
        # invented. See DECISIONS.md 2026-09-07.
        "bids_observed": None,
        "losses_observed": None,
        "win_rate": None,
        "win_rate_note": "not computable: California publishes no losing-bidder data",

        "amount_stats": {
            "rows_with_parseable_amount": len(amounts),
            "rows_with_unparseable_amount": unparseable_amounts,
            "rows_without_amount": len(rows) - len(amounts) - unparseable_amounts,
            "total": round(sum(amounts), 2) if amounts else None,
            "min": round(min(amounts), 2) if amounts else None,
            "max": round(max(amounts), 2) if amounts else None,
            "median": round(statistics.median(amounts), 2) if amounts else None,
        },

        "agencies_served": [{"department": d, "awards": n} for d, n in agencies.most_common()],
        "agency_count": len(agencies),
        "agency_concentration": (round(agencies.most_common(1)[0][1] / len(rows), 3)
                                 if agencies and rows else None),
        "categories": [{"category": c, "awards": n} for c, n in categories.most_common()],
        "acquisition_methods": [{"method": m, "awards": n} for m, n in methods.most_common()],
        "competitive_awards": competitive,
        "non_competitive_awards": non_competitive,
        "vehicle_awards": vehicle_awards,

        "certifications": sorted(certs),
        "certification_coverage": f"{rows_with_cert}/{len(rows)} rows carried a cert_type",
        "certification_mentions": sum(certs.values()),
        "purchasing_vehicles": vehicles,

        "first_award_date": min(dates).isoformat() if dates else None,
        "last_award_date": max(dates).isoformat() if dates else None,
        "rows_with_parseable_date": len(dates),
        "implausible_dates": implausible,
        "implausible_date_count": len(implausible),
        "activity_span_days": span_days,
        "awards_by_year": dict(sorted(years.items())),

        "role_evidence": {
            "prime_awards_with_the_state": len(rows),
            "basis": "an SCPRS award is a contract held directly with the state",
            "subcontractor_evidence": None,
            "subcontractor_note": "not observable in SCPRS; absence is unknown, not negative",
        },

        "evidence": {
            "source_key": "caleprocure_scprs",
            "purchase_docs": [r["purchase_doc"] for r in rows if r.get("purchase_doc")][:MAX_EVIDENCE_REFS],
            "purchase_doc_count": sum(1 for r in rows if r.get("purchase_doc")),
            "truncated_evidence": sum(1 for r in rows if r.get("purchase_doc")) > MAX_EVIDENCE_REFS,
        },
        "evidence_class": "observed",
        "observed_at": observed_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def build_profiles(rows: Iterable[dict[str, str]], *, observed_at: str | None = None,
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group award rows by supplier_id and profile each.

    Returns (profiles, review_items). Rows without a supplier_id cannot be attributed to a
    vendor and become review items rather than being dropped or lumped together.
    """
    rows = list(rows)
    grouped: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    orphans: list[dict[str, str]] = []
    for row in rows:
        sid = (row.get("supplier_id") or "").strip()
        if sid:
            grouped[sid].append(row)
        else:
            orphans.append(row)

    profiles = [build_profile(sid, group, observed_at=observed_at)
                for sid, group in sorted(grouped.items())]
    review = detect_identity_conflicts(profiles)
    if orphans:
        review.append({
            "type": "rows_without_supplier_id",
            "count": len(orphans),
            "purchase_docs": [r.get("purchase_doc") for r in orphans][:MAX_EVIDENCE_REFS],
            "reason": "award row carries no supplier_id; cannot be attributed to a vendor",
            "action": "manual attribution required; not merged into any profile",
        })
    return profiles, review


def detect_identity_conflicts(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag distinct supplier_ids whose names normalise to the same string.

    These are *not* merged. Two ids sharing a normalised name may be one company recorded
    twice or two genuinely different firms, and README forbids merging unrelated companies.
    The pair goes to review with both ids and the evidence needed to decide.
    """
    by_key: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for profile in profiles:
        for name in [profile["canonical_name"], *profile["aliases"]]:
            if name:
                by_key[normalize_name(name)].append(profile)

    conflicts: list[dict[str, Any]] = []
    for key, matches in sorted(by_key.items()):
        ids = sorted({m["supplier_id"] for m in matches})
        if len(ids) < 2:
            continue
        conflicts.append({
            "type": "possible_duplicate_vendor_identity",
            "normalized_name": key,
            "supplier_ids": ids,
            "names": sorted({m["canonical_name"] for m in matches if m["canonical_name"]}),
            "awards_by_id": {m["supplier_id"]: m["awards_observed"] for m in matches},
            "reason": "different supplier_ids normalise to the same name",
            "action": "left unmerged pending review; merging unrelated companies is worse "
                      "than leaving two records",
            "confidence": "low",
        })
    return conflicts


# --- spending, from Open FI$Cal payment records ------------------------------------------
# The brief names spending as a profile dimension alongside awards. It is a different fact:
# an award says a contract exists, a payment says money actually moved under one. A vendor
# holding a contract it is never paid on is not an active supplier.
#
# The join is the weak part and stays visible. These records carry no supplier id, only a
# vendor name truncated near 25 characters, so attribution is a name comparison and is never
# recorded as high confidence. An unmatched profile gets an explicit "no spending matched"
# rather than a zero, because absence of a match is not absence of spending.

def attach_spending(profiles: list[dict[str, Any]],
                    spending: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Attach a spending block to each profile in place. Returns a summary of the join.

    `spending` is the output of `openfiscal.aggregate_by_vendor`, keyed by normalised name.
    """
    from .sources import openfiscal

    matched = ambiguous = 0
    for profile in profiles:
        canonical = profile.get("canonical_name") or ""
        candidates = []
        for key, entry in spending.items():
            ok, confidence, basis = openfiscal.match_confidence(canonical, key)
            if ok:
                candidates.append((confidence, basis, entry))
        if not candidates:
            profile["spending"] = {
                "matched": False,
                "evidence_class": None,
                "note": ("no payment record matched this vendor name. That is not evidence "
                         "of no spending: the files loaded cover a subset of departments "
                         "and fiscal years, and names in them are truncated."),
            }
            continue
        # More than one distinct payee matching one vendor name is a review item, not a sum.
        if len({c[2]["vendor_name_raw"] for c in candidates}) > 1:
            ambiguous += 1
            profile["spending"] = {
                "matched": False,
                "ambiguous": True,
                "candidate_names": sorted({c[2]["vendor_name_raw"] for c in candidates}),
                "note": ("several distinct payees match this vendor name; not summed, "
                         "because combining two companies' spending would be worse than "
                         "reporting none"),
            }
            continue
        # Highest confidence first, not input order: `candidates` arrives in dict order,
        # so taking [0] made the basis of a match depend on file ordering.
        confidence, basis, entry = max(
            candidates, key=lambda c: _CONFIDENCE_RANK.get(c[0], 0))
        matched += 1
        # Government and interagency payees dominate this data: 81% of matched spending on
        # the measured corpus went to counties, cities and university regents, because
        # departments pay each other for things like mutual-aid firefighting. Flagged here so
        # a "top vendors by spend" view cannot read a county as a competitor.
        from .predict import is_biddable_entity
        biddable, why = is_biddable_entity(profile.get("supplier_id") or "",
                                           profile.get("canonical_name"))
        profile["spending"] = {
            "matched": True,
            "payee_is_a_competing_firm": biddable,
            "payee_kind_note": (why if not biddable else
                                "payee looks like a company rather than a public body"),
            "match_confidence": confidence,
            "match_basis": basis,
            "payee_name_in_records": entry["vendor_name_raw"],
            "name_was_truncated": entry["truncated_name"],
            "payments": entry["payments"],
            "amount_total": entry["amount_total"],
            "amount_rows_unparseable": entry["amount_unparseable"],
            "departments_paying": entry["departments"],
            "fiscal_years": entry["fiscal_years"],
            "first_payment": entry["first_date"],
            "last_payment": entry["last_date"],
            "evidence_class": "derived",
            "source_key": "openfiscal_dept_vendor_tx",
            "note": ("payments evidence an active supplier relationship, which an award "
                     "alone does not. Attribution is by name, never by identifier."),
        }
    return {
        "profiles": len(profiles),
        "matched": matched,
        "ambiguous_left_unmatched": ambiguous,
        "unmatched": len(profiles) - matched - ambiguous,
        "payees_in_spending_data": len(spending),
        "join_basis": ("vendor name only. Open FI$Cal publishes no supplier id, so no match "
                       "here can be high confidence"),
    }


# --- location, from the Cal eProcure supplier registry ------------------------------------
# The brief names geography as a profile dimension. It is only available from the supplier
# search, which indexes the SB/DVBE registry, so coverage is skewed by construction.
# Measured on the 20 highest-award company profiles: 55% overall, 80% for vendors carrying a
# certification in the award registry, 30% for those without. Grainger, Verizon, Safeway and
# McKesson are all absent -- large uncertified suppliers are simply not in this registry.
#
# Absence therefore means "not in the small-business registry", never "no known location",
# and the attached block says which.

def attach_location(profiles: list[dict[str, Any]],
                    locations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Attach a location block to each profile in place. Returns a join summary.

    `locations` maps a normalised vendor name to a supplier-search row. The join is by name
    because the supplier search publishes no supplier_id -- unlike the LPA search, which
    does. So confidence is capped at medium and an exact-name requirement is enforced:
    prefix matching is not used here, because "AVIATE" alone matches two different companies
    at different Sacramento addresses.
    """
    matched = ambiguous = 0
    for profile in profiles:
        canonical = (profile.get("canonical_name") or "").strip()
        key = normalize_name(canonical)
        candidates = [row for name, row in locations.items()
                      if normalize_name(name) == key and row.get("has_location")]
        if not candidates:
            profile["location"] = {
                "matched": False,
                "evidence_class": None,
                "note": ("no entry in the Cal eProcure supplier registry. That registry "
                         "indexes SB/DVBE-certified suppliers, so this means 'not in the "
                         "small-business registry' rather than 'location unknown to the "
                         "state'. Large uncertified suppliers are systematically absent."),
            }
            continue
        distinct = {(r["location"].get("city"), r["location"].get("postal"))
                    for r in candidates}
        if len(distinct) > 1:
            ambiguous += 1
            profile["location"] = {
                "matched": False,
                "ambiguous": True,
                "candidates": sorted(f"{c} {p}" for c, p in distinct),
                "note": ("more than one registered supplier matches this name at different "
                         "addresses; not guessed"),
            }
            continue
        row = candidates[0]
        matched += 1
        profile["location"] = {
            "matched": True,
            "match_confidence": "medium",
            "match_basis": "exact vendor name after normalisation; registry publishes no "
                           "supplier_id, so this is a name match",
            "city": row["location"].get("city"),
            "state": row["location"].get("state"),
            "postal": row["location"].get("postal"),
            "street": row["location"].get("street"),
            "country": row["location"].get("country"),
            "website": row.get("website"),
            "registry_certifications": row.get("certifications") or [],
            "certification_id": row.get("certification_id"),
            "evidence_class": "observed",
            "source_key": "caleprocure_supplier_search",
            "note": ("published by the state supplier registry. Contact fields are present "
                     "in that registry and deliberately not captured."),
        }
    return {
        "profiles": len(profiles),
        "matched": matched,
        "ambiguous_left_unmatched": ambiguous,
        "unmatched": len(profiles) - matched - ambiguous,
        "join_basis": "vendor name only; the supplier registry publishes no supplier_id",
        "coverage_caveat": ("the supplier registry indexes SB/DVBE-certified suppliers. "
                            "Measured coverage on the 20 highest-award company profiles was "
                            "55% overall, 80% for vendors certified in the award registry "
                            "and 30% for those not. Geography is therefore systematically "
                            "better populated for small businesses."),
        "prediction_gap": ("scoring geographic fit against an opportunity needs a "
                           "city-to-county mapping, since opportunities state service-area "
                           "counties and vendors state a city. Not implemented, so the "
                           "geographic-activity prediction feature remains unscored."),
    }


def attach_bid_history(profiles: list[dict[str, Any]],
                       bid_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Attach observed wins and losses to profiles in place. Returns a join summary.

    SCPRS records who won and is silent on who lost, which is why `build_profile` leaves
    `win_rate` null. A bidder row that names the whole field -- currently only the Caltrans
    bid-results page -- supplies the missing half: rank 1 is a win, any lower rank is an
    observed loss against a named competitor.

    Two honest limits, both carried in `win_rate_basis` rather than left to the reader:

    * The rate covers **only the solicitations observed here**, not the vendor's whole
      history. A vendor bidding mostly outside Caltrans has a rate computed from a small
      and unrepresentative slice.
    * The join is by normalised name, because bid-results pages carry no supplier id. That
      is the same low-confidence comparison `attach_spending` makes, and it can be wrong.
    """
    # A row resolved to a supplier_id is indexed by it and by nothing else: resolution
    # exists so a different spelling still lands on the right vendor, and falling back to
    # the name for a resolved row would undo that and could attach it twice.
    by_id: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    by_name: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    rows = list(bid_rows)
    for row in rows:
        supplier_id = (row.get("supplier_id") or "").strip()
        if supplier_id:
            by_id[supplier_id].append(row)
            continue
        key = normalize_name(row.get("vendor_name_raw") or "")
        if key:
            by_name[key].append(row)

    matched = 0
    for profile in profiles:
        observed = (by_id.get((profile.get("supplier_id") or "").strip())
                    or by_name.get(normalize_name(profile.get("canonical_name") or "")))
        if not observed:
            continue
        matched += 1
        # One solicitation counts once even if the page lists a vendor twice.
        best: dict[tuple[Any, Any], int] = {}
        sources: set[str] = set()
        confidences: set[str] = set()
        for row in observed:
            confidences.add(row.get("identity_confidence") or "low")
            event = (row.get("business_unit"), row.get("event_id"))
            rank = row.get("rank")
            if rank is None:
                continue
            best[event] = min(best.get(event, rank), rank)
            sources.add(row.get("source_key") or "unknown")
        if not best:
            continue
        wins = sum(1 for rank in best.values() if rank == 1)
        profile["bids_observed"] = len(best)
        profile["wins_observed"] = wins
        profile["losses_observed"] = len(best) - wins
        profile["win_rate"] = round(wins / len(best), 4)
        profile["win_rate_note"] = (
            "computed over the subset of solicitations where a public source named the "
            "full bidder field; not this vendor's overall win rate"
            + (f". Only {len(best)} such solicitation(s) were observed, so this is a "
               f"small sample rather than a track record."
               if len(best) < MIN_BIDS_FOR_A_STABLE_RATE else ""))
        profile["win_rate_basis"] = {
            "source_keys": sorted(sources),
            "solicitations": [f"{bu}/{eid}" for bu, eid in sorted(best)],
            # The weakest link decides: one unresolved row in the set caps the whole rate.
            "identity_confidence": min(confidences or {"low"},
                                       key=lambda c: (_IDENTITY_ORDER.index(c)
                                                      if c in _IDENTITY_ORDER else 0)),
            "small_sample": len(best) < MIN_BIDS_FOR_A_STABLE_RATE,
            "identity_basis": ("matched on a resolved SCPRS supplier_id where one was "
                               "found, otherwise on a normalised company-name comparison, "
                               "which can attach the wrong company"),
            "evidence_class": "observed",
        }
    return {"matched": matched, "profiles": len(profiles),
            "bid_rows": len(rows), "vendors_in_bid_rows": len(by_name)}


def resolve_bidder_identities(rows: list[dict[str, Any]],
                              lookup: Callable[[str], list[dict[str, str]]],
                              ) -> dict[str, Any]:
    """Attach an SCPRS `supplier_id` to bidder rows in place. Returns a join summary.

    A bid-results page gives a company name and no identifier, so every row arrives
    unresolved. `lookup` takes a name and returns candidate SCPRS award rows -- the same
    query supplies both the identity and that vendor's award history, so `awards_seen`
    carries the rows back for reuse rather than making the caller sweep twice.

    Resolution is deliberately strict:

    * Exactly one supplier id whose name matches after normalisation -> resolved, at
      `medium`. Never `high`: this is still a name comparison, and the page carries nothing
      stronger to check it against.
    * More than one -> `ambiguous`, id left null, candidates recorded. Two suppliers can
      share a normalised name and be different companies, and merging them is worse than
      leaving the row unresolved.
    * A near miss is not a match. "A Superior Sanitation" and "A Plus Superior Sanitation"
      are both real and distinct in this data, so only exact normalised equality counts.
    """
    cache: dict[str, tuple[str | None, list[str], list[dict[str, str]]]] = {}
    awards_seen: list[dict[str, str]] = []
    counts = collections.Counter()

    for row in rows:
        raw = row.get("vendor_name_raw") or ""
        key = normalize_name(raw)
        if key not in cache:
            found = lookup(raw) if key else []
            matching = [r for r in found
                        if normalize_name(r.get("supplier_name") or "") == key]
            ids = sorted({r["supplier_id"] for r in matching if r.get("supplier_id")})
            cache[key] = (ids[0] if len(ids) == 1 else None, ids, matching)
            awards_seen.extend(matching)
        supplier_id, candidates, _ = cache[key]
        row["supplier_id"] = supplier_id
        row["candidate_supplier_ids"] = candidates
        if supplier_id:
            row["identity_confidence"] = "medium"
            row["identity_basis"] = ("exact normalised name match to a single SCPRS "
                                     "supplier_id; still a name comparison, never high")
        elif candidates:
            row["identity_confidence"] = "ambiguous"
            row["identity_basis"] = (f"{len(candidates)} SCPRS suppliers normalise to this "
                                     f"name; left unmerged pending review")
        else:
            row["identity_confidence"] = "unresolved"
            row["identity_basis"] = "no SCPRS supplier matches this name after normalisation"
        counts[row["identity_confidence"]] += 1

    return {
        "rows": len(rows),
        "distinct_names": len(cache),
        "resolved": counts["medium"],
        "ambiguous": counts["ambiguous"],
        "unresolved": counts["unresolved"],
        "awards_seen": awards_seen,
    }
