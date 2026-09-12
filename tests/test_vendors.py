"""Offline tests for vendor identity resolution and profiles. No network."""
import datetime
import unittest
from unittest import mock

from sled_trial import vendors


def award(**over):
    base = {
        "purchase_doc": "26IT-0168", "department": "Department of Justice",
        "description": "Laptops", "start_date": "09/03/2026", "end_date": "09/02/2031",
        "awarded_amt": "$3,140.49", "supplier_id": "0000000269",
        "supplier_name": "TECHNOLOGY INTEGRATION GROUP", "category": "IT Goods",
        "acq_method": "Statewide Contracts", "cert_type": "SB|MB",
    }
    base.update(over)
    return base


class NormalizeTests(unittest.TestCase):
    def test_legal_suffixes_and_punctuation_are_ignored_for_comparison(self) -> None:
        self.assertEqual(vendors.normalize_name("ACME Widgets, Inc."),
                         vendors.normalize_name("acme widgets llc"))

    def test_distinct_companies_do_not_collide(self) -> None:
        self.assertNotEqual(vendors.normalize_name("ACME Widgets"),
                            vendors.normalize_name("ACME Services"))

    def test_empty_input_is_safe(self) -> None:
        self.assertEqual(vendors.normalize_name(""), "")
        self.assertEqual(vendors.normalize_name(None), "")

    def test_dotted_suffixes_normalise_with_undotted_ones(self) -> None:
        # Stripping punctuation before suffixes turned "L.L.C." into "l l c", which no
        # suffix alternative could match, so these two never compared equal.
        self.assertEqual(vendors.normalize_name("Foo L.L.C."),
                         vendors.normalize_name("Foo LLC"))
        self.assertEqual(vendors.normalize_name("Burketts Office Supplies"),
                         vendors.normalize_name("BURKETTS OFFICE SUPPLIES INC"))


class HorizonTests(unittest.TestCase):
    def test_profile_builds_on_a_leap_day(self) -> None:
        # date(2028, 2, 29).replace(year=2038) raises ValueError, which took the whole
        # profile build down one day in every four years.
        class LeapDay(datetime.date):
            @classmethod
            def today(cls):
                return datetime.date(2028, 2, 29)

        with mock.patch.object(vendors.dt, "date", LeapDay):
            profile = vendors.build_profile("0000000269", [award()])
        self.assertEqual(profile["awards_observed"], 1)


class ProfileTests(unittest.TestCase):
    def test_canonical_name_and_aliases(self) -> None:
        rows = [award(), award(), award(supplier_name="TECH INTEGRATION GRP")]
        p = vendors.build_profile("0000000269", rows)
        self.assertEqual(p["canonical_name"], "TECHNOLOGY INTEGRATION GROUP")
        self.assertEqual(p["aliases"], ["TECH INTEGRATION GRP"])
        self.assertEqual(p["identity_basis"], "scprs_supplier_id")

    def test_win_rate_is_never_invented(self) -> None:
        # California publishes no losing bidders, so a win rate cannot be computed and
        # must not be faked by equating bids with wins.
        p = vendors.build_profile("x", [award()])
        self.assertIsNone(p["win_rate"])
        self.assertIsNone(p["bids_observed"])
        self.assertIsNone(p["losses_observed"])
        self.assertIn("no losing-bidder data", p["win_rate_note"])

    def test_amount_stats_state_their_denominator(self) -> None:
        rows = [award(awarded_amt="$100.00"), award(awarded_amt="N/A"),
                award(awarded_amt="see contract"), award(awarded_amt="$300.00")]
        stats = vendors.build_profile("x", rows)["amount_stats"]
        self.assertEqual(stats["rows_with_parseable_amount"], 2)
        self.assertEqual(stats["rows_with_unparseable_amount"], 2)
        self.assertEqual(stats["total"], 400.0)
        self.assertEqual(stats["median"], 200.0)

    def test_missing_amounts_do_not_become_zero(self) -> None:
        stats = vendors.build_profile("x", [award(awarded_amt="N/A")])["amount_stats"]
        self.assertIsNone(stats["total"])
        self.assertIsNone(stats["median"])
        self.assertEqual(stats["rows_with_parseable_amount"], 0)

    def test_certifications_split_on_pipe_and_coverage_reported(self) -> None:
        rows = [award(cert_type="SB|MB"), award(cert_type=None), award(cert_type="DVBE")]
        p = vendors.build_profile("x", rows)
        self.assertEqual(p["certifications"], ["DVBE", "MB", "SB"])
        self.assertIn("/3 rows", p["certification_coverage"])

    def test_competitive_and_vehicle_awards_are_distinguished(self) -> None:
        rows = [award(acq_method="Formal - COMPETITIVE"),
                award(acq_method="Exempt by Policy - Other - NON-COMPETITIVELY BID"),
                award(acq_method="Statewide Contracts")]
        p = vendors.build_profile("x", rows)
        self.assertEqual(p["competitive_awards"], 1)
        self.assertEqual(p["non_competitive_awards"], 1)
        self.assertEqual(p["vehicle_awards"], 1)

    def test_agency_concentration_and_counts(self) -> None:
        rows = [award(), award(), award(department="CAL FIRE")]
        p = vendors.build_profile("x", rows)
        self.assertEqual(p["agency_count"], 2)
        self.assertAlmostEqual(p["agency_concentration"], 0.667, places=2)

    def test_dates_that_do_not_parse_are_excluded_not_guessed(self) -> None:
        rows = [award(start_date="09/03/2026"), award(start_date="N/A"),
                award(start_date="")]
        p = vendors.build_profile("x", rows)
        self.assertEqual(p["rows_with_parseable_date"], 1)
        self.assertEqual(p["first_award_date"], "2026-09-03")
        self.assertIsNone(p["activity_span_days"])

    def test_subcontractor_evidence_is_unknown_not_false(self) -> None:
        role = vendors.build_profile("x", [award()])["role_evidence"]
        self.assertIsNone(role["subcontractor_evidence"])
        self.assertIn("absence is unknown", role["subcontractor_note"])

    def test_evidence_refs_are_capped_and_the_cap_is_declared(self) -> None:
        rows = [award(purchase_doc=f"DOC-{i}") for i in range(40)]
        ev = vendors.build_profile("x", rows)["evidence"]
        self.assertEqual(len(ev["purchase_docs"]), vendors.MAX_EVIDENCE_REFS)
        self.assertEqual(ev["purchase_doc_count"], 40)
        self.assertTrue(ev["truncated_evidence"])


class GroupingTests(unittest.TestCase):
    def test_rows_group_by_supplier_id(self) -> None:
        rows = [award(), award(supplier_id="999", supplier_name="OTHER CO")]
        profiles, _ = vendors.build_profiles(rows)
        self.assertEqual({p["supplier_id"] for p in profiles}, {"0000000269", "999"})

    def test_rows_without_a_supplier_id_go_to_review_not_a_bucket(self) -> None:
        rows = [award(), award(supplier_id="", supplier_name="MYSTERY CO")]
        profiles, review = vendors.build_profiles(rows)
        self.assertEqual(len(profiles), 1)
        orphan = [r for r in review if r["type"] == "rows_without_supplier_id"]
        self.assertEqual(orphan[0]["count"], 1)


class ConflictTests(unittest.TestCase):
    def test_same_name_two_ids_is_flagged_and_left_unmerged(self) -> None:
        rows = [award(supplier_id="A", supplier_name="ACME WIDGETS INC"),
                award(supplier_id="B", supplier_name="Acme Widgets, LLC")]
        profiles, review = vendors.build_profiles(rows)
        self.assertEqual(len(profiles), 2)  # merging unrelated companies is the worse error
        conflict = [r for r in review if r["type"] == "possible_duplicate_vendor_identity"]
        self.assertEqual(len(conflict), 1)
        self.assertEqual(conflict[0]["supplier_ids"], ["A", "B"])
        self.assertEqual(conflict[0]["confidence"], "low")

    def test_different_names_are_not_flagged(self) -> None:
        rows = [award(supplier_id="A", supplier_name="ACME WIDGETS"),
                award(supplier_id="B", supplier_name="BETA SERVICES")]
        _, review = vendors.build_profiles(rows)
        self.assertEqual([r for r in review
                          if r["type"] == "possible_duplicate_vendor_identity"], [])

    def test_alias_collision_across_ids_is_also_caught(self) -> None:
        rows = [award(supplier_id="A", supplier_name="ALPHA CO"),
                award(supplier_id="A", supplier_name="SHARED NAME"),
                award(supplier_id="B", supplier_name="SHARED NAME")]
        _, review = vendors.build_profiles(rows)
        self.assertTrue(any(r["type"] == "possible_duplicate_vendor_identity"
                            for r in review))



class AttachSpendingScaleTests(unittest.TestCase):
    def test_the_matcher_is_not_called_per_pair(self) -> None:
        # 25,078 profiles x 12,612 payees = 316 million matcher calls on the real corpus.
        from unittest import mock

        from sled_trial import vendors
        from sled_trial.sources.ca import openfiscal as of
        profiles = [{"supplier_id": f"S{i}", "canonical_name": f"VENDOR {i} INC"}
                    for i in range(300)]
        spending = {f"PAYEE {j} INC": {"vendor_name_raw": f"PAYEE {j} INC",
                                       "truncated_name": False, "total": 1.0,
                                       "departments": [], "first_date": None,
                                       "last_date": None, "rows": 1}
                    for j in range(200)}
        with mock.patch.object(of, "match_confidence", wraps=of.match_confidence) as m:
            vendors.attach_spending(profiles, spending)
        self.assertLess(m.call_count, 300 * 10,
                        f"{m.call_count} matcher calls for 300 profiles x 200 payees")


class AttachLocationScaleTests(unittest.TestCase):
    def test_each_side_is_normalised_once_not_per_pair(self) -> None:
        # The location join normalised every registry name once per profile. 300 x 200
        # here; 25,078 x 152 on the real corpus.
        from unittest import mock

        from sled_trial import vendors
        profiles = [{"supplier_id": f"S{i}", "canonical_name": f"VENDOR {i}"}
                    for i in range(300)]
        locations = {f"OTHER {j}": {"has_location": True,
                                    "location": {"city": "X", "postal": "1"}}
                     for j in range(200)}
        with mock.patch.object(vendors, "normalize_name",
                               wraps=vendors.normalize_name) as m:
            vendors.attach_location(profiles, locations)
        self.assertLess(m.call_count, 300 + 200 + 10,
                        f"{m.call_count} normalisations for 300 profiles x 200 entries")

if __name__ == "__main__":
    unittest.main()


class DataQualityTests(unittest.TestCase):
    """Both cases below came from a real 200-row supplier history."""

    def test_certification_coverage_counts_rows_not_mentions(self) -> None:
        # 200 rows each carrying "DVBE|SB-PW" previously produced "400/200 rows".
        rows = [award(cert_type="DVBE|SB-PW"), award(cert_type="SB|DVBE")]
        p = vendors.build_profile("x", rows)
        self.assertEqual(p["certification_coverage"], "2/2 rows carried a cert_type")
        self.assertEqual(p["certification_mentions"], 4)

    def test_rows_without_certs_are_excluded_from_the_numerator(self) -> None:
        rows = [award(cert_type="SB"), award(cert_type=None), award(cert_type="")]
        self.assertEqual(vendors.build_profile("x", rows)["certification_coverage"],
                         "1/3 rows carried a cert_type")

    def test_far_future_date_is_flagged_and_excluded_from_the_span(self) -> None:
        # Real row: PO17-1119, start=end=02/14/2048. One typo must not make a vendor look
        # active for 22 years.
        rows = [award(start_date="09/03/2026", purchase_doc="GOOD"),
                award(start_date="02/14/2048", purchase_doc="PO17-1119")]
        p = vendors.build_profile("x", rows)
        self.assertEqual(p["rows_with_parseable_date"], 1)
        self.assertEqual(p["implausible_date_count"], 1)
        self.assertEqual(p["implausible_dates"][0]["purchase_doc"], "PO17-1119")
        self.assertEqual(p["last_award_date"], "2026-09-03")

    def test_pre_scprs_date_is_flagged(self) -> None:
        # SCPRS begins with state FY2010.
        p = vendors.build_profile("x", [award(start_date="01/01/1999")])
        self.assertEqual(p["implausible_date_count"], 1)
        self.assertIsNone(p["first_award_date"])

    def test_flagged_dates_are_retained_not_dropped(self) -> None:
        p = vendors.build_profile("x", [award(start_date="02/14/2048", purchase_doc="D1")])
        self.assertEqual(p["awards_observed"], 1)  # the award still counts
        self.assertEqual(p["implausible_dates"][0]["start_date"], "02/14/2048")

    def test_plausible_multi_year_future_date_is_kept(self) -> None:
        import datetime as dt
        soon = dt.date.today().replace(year=dt.date.today().year + 3).strftime("%m/%d/%Y")
        p = vendors.build_profile("x", [award(start_date=soon)])
        self.assertEqual(p["implausible_date_count"], 0)
        self.assertEqual(p["rows_with_parseable_date"], 1)


def bid(name="TECHNOLOGY INTEGRATION GROUP", event="08A3933", rank=1):
    return {"business_unit": "2660", "event_id": event, "vendor_name_raw": name,
            "rank": rank, "source_key": "caltrans_bid_results",
            "evidence_url": "https://dot.ca.gov/x"}


class BidHistoryTests(unittest.TestCase):
    """Observed wins and losses, which SCPRS alone cannot supply."""

    def _profile(self):
        return vendors.build_profile("0000000269", [award()])

    def test_win_rate_is_computed_from_observed_wins_and_losses(self) -> None:
        profile = self._profile()
        vendors.attach_bid_history([profile], [
            bid(event="A1", rank=1), bid(event="A2", rank=3), bid(event="A3", rank=2)])
        self.assertEqual(profile["bids_observed"], 3)
        self.assertEqual(profile["losses_observed"], 2)
        self.assertEqual(profile["win_rate"], 0.3333)

    def test_the_note_says_the_win_rate_covers_only_the_observed_subset(self) -> None:
        # A win rate over Caltrans solicitations is not this vendor's overall win rate,
        # and presenting it as one would be the exact overclaim the trial avoids.
        profile = self._profile()
        vendors.attach_bid_history([profile], [bid(event="A1", rank=1)])
        self.assertIn("caltrans_bid_results", profile["win_rate_basis"]["source_keys"])
        self.assertIn("subset", profile["win_rate_note"].lower())

    def test_identity_match_is_by_name_and_labelled_low_confidence(self) -> None:
        profile = self._profile()
        vendors.attach_bid_history([profile], [bid(name="Technology Integration Group.")])
        self.assertEqual(profile["bids_observed"], 1)
        self.assertEqual(profile["win_rate_basis"]["identity_confidence"], "low")

    def test_an_unmatched_vendor_keeps_the_not_computable_note(self) -> None:
        profile = self._profile()
        vendors.attach_bid_history([profile], [bid(name="SOME OTHER COMPANY INC")])
        self.assertIsNone(profile["win_rate"])
        self.assertIn("not computable", profile["win_rate_note"])

    def test_the_same_solicitation_counts_once_per_vendor(self) -> None:
        profile = self._profile()
        vendors.attach_bid_history([profile], [bid(event="A1"), bid(event="A1")])
        self.assertEqual(profile["bids_observed"], 1)

    def test_a_resolved_row_matches_on_supplier_id_not_on_spelling(self) -> None:
        # Resolution exists precisely so a differently-spelled name still lands on the
        # right vendor; falling back to the name here would waste it.
        profile = self._profile()
        vendors.attach_bid_history([profile], [
            dict(bid(name="TECH INTEGRATION GRP", event="A1", rank=1),
                 supplier_id="0000000269", identity_confidence="medium")])
        self.assertEqual(profile["bids_observed"], 1)
        self.assertEqual(profile["win_rate"], 1.0)
        self.assertEqual(profile["win_rate_basis"]["identity_confidence"], "medium")

    def test_a_resolved_row_for_another_vendor_does_not_attach(self) -> None:
        profile = self._profile()
        vendors.attach_bid_history([profile], [
            dict(bid(name="TECHNOLOGY INTEGRATION GROUP", event="A1"),
                 supplier_id="0000999999", identity_confidence="medium")])
        self.assertIsNone(profile["win_rate"])

    def test_the_weakest_identity_in_the_set_caps_the_confidence(self) -> None:
        # Ranked explicitly, not alphabetically: sorted() puts "unresolved" last and would
        # report the shakiest possible match as the strongest.
        profile = self._profile()
        vendors.attach_bid_history([profile], [
            dict(bid(event="A1"), identity_confidence="medium"),
            dict(bid(event="A2"), identity_confidence="unresolved"),
        ])
        self.assertEqual(profile["win_rate_basis"]["identity_confidence"], "unresolved")

    def test_a_rate_from_one_or_two_bids_is_flagged_as_a_small_sample(self) -> None:
        profile = self._profile()
        vendors.attach_bid_history([profile], [bid(event="A1", rank=1)])
        self.assertTrue(profile["win_rate_basis"]["small_sample"])

    def test_a_deeper_sample_is_not_flagged(self) -> None:
        profile = self._profile()
        vendors.attach_bid_history([profile], [
            bid(event=f"A{n}", rank=1 if n == 1 else 2) for n in range(1, 5)])
        self.assertFalse(profile["win_rate_basis"]["small_sample"])

    def test_the_join_reports_how_many_profiles_matched(self) -> None:
        profile = self._profile()
        summary = vendors.attach_bid_history([profile], [bid()])
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["profiles"], 1)
        self.assertEqual(summary["bid_rows"], 1)


class ResolveBidderIdentityTests(unittest.TestCase):
    """A company name from a bid-results page is not an identity until SCPRS confirms it."""

    def _lookup(self, table):
        def lookup(name):
            return table.get(vendors.normalize_name(name), [])
        return lookup

    def test_a_single_matching_supplier_resolves_the_row(self) -> None:
        rows = [{"vendor_name_raw": "Granite Construction Company"}]
        summary = vendors.resolve_bidder_identities(rows, self._lookup({
            "granite construction": [
                award(supplier_id="0000011589", supplier_name="GRANITE CONSTRUCTION COMPANY")],
        }))
        self.assertEqual(rows[0]["supplier_id"], "0000011589")
        self.assertEqual(rows[0]["identity_confidence"], "medium")
        self.assertEqual(summary["resolved"], 1)

    def test_two_suppliers_under_one_name_stay_unresolved(self) -> None:
        # Merging unrelated companies is worse than leaving a row unresolved -- the same
        # rule detect_identity_conflicts already applies.
        rows = [{"vendor_name_raw": "Granite Construction"}]
        summary = vendors.resolve_bidder_identities(rows, self._lookup({
            "granite construction": [
                award(supplier_id="0000011589", supplier_name="GRANITE CONSTRUCTION COMPANY"),
                award(supplier_id="0000116332", supplier_name="GRANITE CONSTRUCTION INC")],
        }))
        self.assertIsNone(rows[0]["supplier_id"])
        self.assertEqual(rows[0]["identity_confidence"], "ambiguous")
        self.assertEqual(sorted(rows[0]["candidate_supplier_ids"]),
                         ["0000011589", "0000116332"])
        self.assertEqual(summary["ambiguous"], 1)

    def test_a_name_absent_from_scprs_stays_unresolved(self) -> None:
        rows = [{"vendor_name_raw": "Nobody At All Inc"}]
        summary = vendors.resolve_bidder_identities(rows, self._lookup({}))
        self.assertIsNone(rows[0]["supplier_id"])
        self.assertEqual(rows[0]["identity_confidence"], "unresolved")
        self.assertEqual(summary["unresolved"], 1)

    def test_only_an_exact_normalised_match_counts(self) -> None:
        # "A Superior Sanitation" against "A Plus Superior Sanitation" is a real pair of
        # different companies observed in this data; a loose match would merge them.
        rows = [{"vendor_name_raw": "A Superior Sanitation"}]
        vendors.resolve_bidder_identities(rows, self._lookup({
            "a plus superior sanitation": [
                award(supplier_id="0000099999", supplier_name="A PLUS SUPERIOR SANITATION")],
        }))
        self.assertEqual(rows[0]["identity_confidence"], "unresolved")

    def test_each_distinct_name_is_looked_up_once(self) -> None:
        calls = []

        def lookup(name):
            calls.append(name)
            return [award(supplier_id="0000011589", supplier_name="GRANITE CONSTRUCTION")]

        rows = [{"vendor_name_raw": "Granite Construction"},
                {"vendor_name_raw": "GRANITE CONSTRUCTION"},
                {"vendor_name_raw": "Granite Construction"}]
        vendors.resolve_bidder_identities(rows, lookup)
        self.assertEqual(len(calls), 1)
        self.assertEqual({r["supplier_id"] for r in rows}, {"0000011589"})

    def test_the_awards_seen_during_resolution_are_returned_for_reuse(self) -> None:
        # The lookup that resolves a name also returns that vendor's award rows, so the
        # backfill is free rather than a second pass over the registry.
        rows = [{"vendor_name_raw": "Granite Construction"}]
        summary = vendors.resolve_bidder_identities(rows, self._lookup({
            "granite construction": [
                award(supplier_id="0000011589", supplier_name="GRANITE CONSTRUCTION",
                      purchase_doc="D1"),
                award(supplier_id="0000011589", supplier_name="GRANITE CONSTRUCTION",
                      purchase_doc="D2")],
        }))
        self.assertEqual(len(summary["awards_seen"]), 2)
