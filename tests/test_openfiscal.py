"""Offline tests for the Open FI$Cal spending adapter and the spending join. No network."""
import unittest

from sled_trial import vendors
from sled_trial.sources.ca import openfiscal as of

MANIFEST_CSV = (
    b"FileName,UploadDate,FileSize,Download\n"
    b'"Vendor_2740_MotorVehicles_FY25.csv","2026-09-07","75 MB","https://x/a.csv"\n'
    b'"Vendor_7120_WorkforceBoard_FY24.csv","2026-09-07","1,018 KB","https://x/b.csv"\n'
    b'"Vendor_2740_MotorVehicles_FY24.csv","2026-09-07","2 GB","https://x/c.csv"\n')

TX_CSV = (
    b"business_unit,department_name,accounting_date,fiscal_year_begin,VENDOR_NAME,monetary_amount\n"
    b'"2740","Department of Motor Vehicles","2026-01-15","2025","AVIATE ENTERPRISES INC","1000.50"\n'
    b'"2740","Department of Motor Vehicles","2026-03-20","2025","AVIATE ENTERPRISES INC","2000.00"\n'
    b'"2740","Department of Motor Vehicles","2026-02-01","2025","WESTERN STATES COUNCIL OF","500.00"\n'
    b'"2740","Department of Motor Vehicles","2026-02-02","2025","BAD AMOUNT CO","not-a-number"\n')


class SizeTests(unittest.TestCase):
    def test_units_are_converted(self) -> None:
        self.assertEqual(of.size_mb("75 MB"), 75.0)
        self.assertEqual(of.size_mb("2 GB"), 2048.0)
        self.assertAlmostEqual(of.size_mb("1,018 KB"), 0.994, places=2)

    def test_unparseable_size_is_zero_not_a_guess(self) -> None:
        for bad in ["", None, "unknown", "big"]:
            self.assertEqual(of.size_mb(bad), 0.0)


class ManifestTests(unittest.TestCase):
    class FakeSession:
        def get(self, url, referer=None, timeout=120):
            return MANIFEST_CSV, {}

    def test_manifest_rows_are_parsed(self) -> None:
        rows = of.fetch_manifest(self.FakeSession())
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["business_unit"], "2740")
        self.assertEqual(rows[0]["fiscal_year"], "FY25")
        self.assertEqual(rows[0]["department"], "MotorVehicles")

    def test_selection_respects_the_size_budget(self) -> None:
        # Largest-first: the 2 GB file exceeds the budget and is skipped, the 75 MB and
        # 1 MB files both fit.
        rows = of.fetch_manifest(self.FakeSession())
        chosen = of.select_files(rows, max_total_mb=80)
        self.assertEqual([c["size_mb"] > 1 for c in chosen], [True, False])
        self.assertLessEqual(sum(c["size_mb"] for c in chosen), 80)
        self.assertEqual(len(chosen), 2)

    def test_largest_year_first_within_a_department(self) -> None:
        # File size proxies departmental spending. A smallest-first version selected 203
        # files from tiny agencies with no relevance to the vendors under analysis.
        rows = of.fetch_manifest(self.FakeSession())
        chosen = of.select_files(rows, business_units=["2740"], max_total_mb=3000)
        self.assertEqual([c["fiscal_year"] for c in chosen], ["FY24", "FY25"])  # 2 GB then 75 MB

    def test_one_file_per_department_before_a_second_from_any(self) -> None:
        # Breadth over depth: largest-first outright spent 466 MB of a 600 MB budget on one
        # department's two years and left 35 relevant departments uncovered.
        rows = of.fetch_manifest(self.FakeSession())
        chosen = of.select_files(rows, business_units=["2740", "7120"], max_total_mb=100)
        first_two = [c["business_unit"] for c in chosen[:2]]
        self.assertEqual(sorted(first_two), ["2740", "7120"])

    def test_caller_unit_order_is_preserved(self) -> None:
        rows = of.fetch_manifest(self.FakeSession())
        chosen = of.select_files(rows, business_units=["7120", "2740"], max_total_mb=100)
        self.assertEqual(chosen[0]["business_unit"], "7120")

    def test_filters_by_business_unit_and_year(self) -> None:
        rows = of.fetch_manifest(self.FakeSession())
        self.assertEqual(len(of.select_files(rows, business_units=["7120"])), 1)
        self.assertEqual(len(of.select_files(rows, fiscal_years=["FY25"])), 1)


class AggregateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agg = of.aggregate_by_vendor(of.parse_transactions(TX_CSV))

    def test_payments_are_summed_per_vendor(self) -> None:
        entry = self.agg["AVIATE ENTERPRISES INC"]
        self.assertEqual(entry["payments"], 2)
        self.assertEqual(entry["amount_total"], 3000.50)

    def test_unparseable_amounts_are_counted_not_zeroed(self) -> None:
        entry = self.agg["BAD AMOUNT CO"]
        self.assertEqual(entry["amount_unparseable"], 1)
        self.assertEqual(entry["amount_total"], 0.0)
        self.assertEqual(entry["payments"], 1)  # the payment still happened

    def test_truncated_names_are_flagged(self) -> None:
        self.assertTrue(self.agg["WESTERN STATES COUNCIL OF"]["truncated_name"])
        self.assertFalse(self.agg["BAD AMOUNT CO"]["truncated_name"])

    def test_paying_departments_and_dates_are_captured(self) -> None:
        entry = self.agg["AVIATE ENTERPRISES INC"]
        self.assertIn("Department of Motor Vehicles", entry["departments"])
        self.assertEqual(entry["first_payment" if False else "first_date"], "2026-01-15")
        self.assertEqual(entry["last_date"], "2026-03-20")


class MatchTests(unittest.TestCase):
    def test_an_exact_match_is_medium_never_high(self) -> None:
        # These files carry no supplier id, so no name match can be high confidence.
        ok, conf, _ = of.match_confidence("AVIATE ENTERPRISES INC", "AVIATE ENTERPRISES INC")
        self.assertTrue(ok)
        self.assertEqual(conf, "medium")

    def test_a_truncated_prefix_matches_at_low_confidence(self) -> None:
        ok, conf, basis = of.match_confidence(
            "WESTERN STATES COUNCIL OF CARPENTERS", "WESTERN STATES COUNCIL OF")
        self.assertTrue(ok)
        self.assertEqual(conf, "low")
        self.assertIn("truncated", basis)

    def test_unrelated_names_do_not_match(self) -> None:
        self.assertFalse(of.match_confidence("ACME WIDGETS", "BETA SERVICES")[0])

    def test_a_short_common_prefix_does_not_match(self) -> None:
        # "ACME" is well under the truncation length, so a prefix match would be reckless.
        self.assertFalse(of.match_confidence("ACME WIDGETS INC", "ACME")[0])

    def test_empty_names_never_match(self) -> None:
        self.assertFalse(of.match_confidence("", "ACME")[0])
        self.assertFalse(of.match_confidence("ACME", "")[0])


class AttachTests(unittest.TestCase):
    def _profiles(self, *names):
        return [{"supplier_id": str(i), "canonical_name": n} for i, n in enumerate(names)]

    @staticmethod
    def _entry(raw, total):
        return {"vendor_name_raw": raw, "payments": 1, "amount_total": total,
                "amount_unparseable": 0, "departments": {}, "fiscal_years": {},
                "first_date": None, "last_date": None, "truncated_name": True}

    def test_a_matched_profile_gains_a_spending_block(self) -> None:
        profiles = self._profiles("AVIATE ENTERPRISES INC")
        summary = vendors.attach_spending(
            profiles, of.aggregate_by_vendor(of.parse_transactions(TX_CSV)))
        block = profiles[0]["spending"]
        self.assertTrue(block["matched"])
        self.assertEqual(block["amount_total"], 3000.50)
        self.assertEqual(block["evidence_class"], "derived")
        self.assertEqual(summary["matched"], 1)

    def test_an_unmatched_profile_says_so_rather_than_reporting_zero(self) -> None:
        profiles = self._profiles("NOBODY LTD")
        vendors.attach_spending(
            profiles, of.aggregate_by_vendor(of.parse_transactions(TX_CSV)))
        block = profiles[0]["spending"]
        self.assertFalse(block["matched"])
        self.assertNotIn("amount_total", block)
        self.assertIn("not evidence of no spending", block["note"])

    def test_a_non_prefix_similar_name_is_correctly_rejected(self) -> None:
        # "ACME WIDGETS INCORPORATED" is not a prefix of the profile name, so it must not
        # match however similar it looks. Only the genuine truncation matches.
        spending = {
            "ACME WIDGETS INCORPORATED": self._entry("ACME WIDGETS INCORPORATED", 1.0),
            "ACME WIDGETS INTERNATIONA": self._entry("ACME WIDGETS INTERNATIONA", 99.0),
        }
        profiles = self._profiles("ACME WIDGETS INTERNATIONAL HOLDINGS")
        vendors.attach_spending(profiles, spending)
        block = profiles[0]["spending"]
        self.assertTrue(block["matched"])
        self.assertEqual(block["amount_total"], 99.0)
        self.assertEqual(block["payee_name_in_records"], "ACME WIDGETS INTERNATIONA")

    def test_several_payees_matching_one_name_are_left_unsummed(self) -> None:
        # A real ambiguity: the profile name matches one payee exactly and is also a prefix
        # of a longer payee name. Combining two companies' spending would be worse than
        # reporting none, so it reports none and flags it.
        spending = {
            "ACME WIDGETS INTERNATIONA": self._entry("ACME WIDGETS INTERNATIONA", 1.0),
            "ACME WIDGETS INTERNATIONA LIMITED":
                self._entry("ACME WIDGETS INTERNATIONA LIMITED", 99.0),
        }
        profiles = self._profiles("ACME WIDGETS INTERNATIONA")
        summary = vendors.attach_spending(profiles, spending)
        block = profiles[0]["spending"]
        self.assertFalse(block["matched"])
        self.assertTrue(block["ambiguous"])
        self.assertEqual(len(block["candidate_names"]), 2)
        self.assertEqual(summary["ambiguous_left_unmatched"], 1)

    def test_the_join_basis_is_declared(self) -> None:
        summary = vendors.attach_spending(self._profiles("X"), {})
        self.assertIn("no match here can be high confidence", summary["join_basis"])



class SpendingLookupTests(unittest.TestCase):
    """The index narrows; match_confidence still decides. Brute force is the oracle."""

    NAMES = [
        "AVIATE ENTERPRISES INC", "AVIATE ENTERPRISES, INC.", "ACME WIDGETS INC", "ACME",
        "WESTERN STATES COUNCIL OF", "WESTERN STATES COUNCIL OF CARPENTERS",
        "STATE BLDG & CONST TRADES COUNCIL OF CALIFORNIA", "STATE BLDG & CONST TRADES",
        "BETA SERVICES", "", "   ", "ALBERTSONS", "ALBERTSONS LLC",
        "PACIFIC GAS AND ELECTRIC COMPANY", "PACIFIC GAS AND ELECTRIC",
    ]

    def _spending(self):
        return {n: {"vendor_name_raw": n, "i": i} for i, n in enumerate(self.NAMES) if n.strip()}

    def _brute(self, spending, scprs_name):
        out = []
        for key, entry in spending.items():
            ok, conf, basis = of.match_confidence(scprs_name, key)
            if ok:
                out.append((conf, basis, entry))
        return out

    def test_matches_brute_force_on_every_tier_including_order(self) -> None:
        # Exact, payee-truncated prefix, our-name-truncated prefix, empty, and misses.
        spending = self._spending()
        lookup = of.SpendingLookup(spending)
        for query in self.NAMES + ["WESTERN STATES COUNCIL OF CARPENTERS AND JOINERS",
                                    "PACIFIC GAS", "AVIATE", "STATE BLDG & CONST TRADES CO"]:
            with self.subTest(query=query):
                self.assertEqual(lookup.candidates(query), self._brute(spending, query))

    def test_the_matcher_is_asked_about_a_handful_not_everyone(self) -> None:
        # The bug this replaces: 25,078 profiles x 12,612 payees = 316 million calls.
        from unittest import mock
        spending = {f"PAYEE NUMBER {i:05d} INCORPORATED": {"vendor_name_raw": f"P{i}"}
                    for i in range(5000)}
        spending["ACME WIDGETS INC"] = {"vendor_name_raw": "ACME WIDGETS INC"}
        lookup = of.SpendingLookup(spending)
        with mock.patch.object(of, "match_confidence", wraps=of.match_confidence) as m:
            found = lookup.candidates("ACME WIDGETS INC")
        self.assertEqual(len(found), 1)
        self.assertLess(m.call_count, 50,
                        f"asked the matcher {m.call_count} times to place one name")

if __name__ == "__main__":
    unittest.main()


class PayeeKindTests(unittest.TestCase):
    """81% of matched spending on the real corpus went to counties, not companies."""

    def _spending(self, name):
        return {of.normalize_vendor(name): {
            "vendor_name_raw": name, "payments": 1, "amount_total": 100.0,
            "amount_unparseable": 0, "departments": {}, "fiscal_years": {},
            "first_date": None, "last_date": None, "truncated_name": False}}

    def test_a_company_payee_is_marked_as_a_competing_firm(self) -> None:
        profiles = [{"supplier_id": "1", "canonical_name": "WW GRAINGER INC"}]
        vendors.attach_spending(profiles, self._spending("WW GRAINGER INC"))
        self.assertTrue(profiles[0]["spending"]["payee_is_a_competing_firm"])

    def test_a_county_payee_is_marked_as_not_a_competing_firm(self) -> None:
        profiles = [{"supplier_id": "2", "canonical_name": "COUNTY OF LOS ANGELES"}]
        vendors.attach_spending(profiles, self._spending("COUNTY OF LOS ANGELES"))
        block = profiles[0]["spending"]
        self.assertFalse(block["payee_is_a_competing_firm"])
        self.assertIn("government", block["payee_kind_note"])

    def test_the_spending_total_is_still_recorded_for_a_public_body(self) -> None:
        # It is real spending and belongs in spend analysis; it is just not a competitor.
        profiles = [{"supplier_id": "3", "canonical_name": "REGENTS OF UNIV OF CA DAVIS"}]
        vendors.attach_spending(profiles, self._spending("REGENTS OF UNIV OF CA DAVIS"))
        self.assertEqual(profiles[0]["spending"]["amount_total"], 100.0)


class SelectionSafetyTests(unittest.TestCase):
    class FakeSession:
        def get(self, url, referer=None, timeout=120):
            return MANIFEST_CSV, {}

    def test_no_file_is_selected_twice(self) -> None:
        # The per-department allowance loop re-selected the same file on each pass until it
        # tracked chosen filenames, not just per-department counts.
        rows = of.fetch_manifest(self.FakeSession())
        chosen = of.select_files(rows, business_units=["2740", "7120"], max_total_mb=5000)
        names = [c["filename"] for c in chosen]
        self.assertEqual(len(names), len(set(names)))

    def test_the_budget_is_never_exceeded(self) -> None:
        rows = of.fetch_manifest(self.FakeSession())
        for budget in (1, 5, 80, 500, 5000):
            with self.subTest(budget=budget):
                chosen = of.select_files(rows, max_total_mb=budget)
                self.assertLessEqual(sum(c["size_mb"] for c in chosen), budget)


class TruncationTests(unittest.TestCase):
    def test_only_a_name_at_the_cut_length_is_flagged_as_truncated(self) -> None:
        # A 41-character name is proof the file did NOT truncate it. `>=` flagged every
        # long name, so the flag said "possibly cut off" about complete names.
        rows = [{"VENDOR_NAME": "A" * of.TRUNCATION_LENGTH, "monetary_amount": "1"},
                {"VENDOR_NAME": "B" * 41, "monetary_amount": "1"}]
        out = of.aggregate_by_vendor(rows)
        self.assertTrue(out[of.normalize_vendor("A" * of.TRUNCATION_LENGTH)]["truncated_name"])
        self.assertFalse(out[of.normalize_vendor("B" * 41)]["truncated_name"])

    def test_prefix_rule_measures_the_raw_name_not_the_normalised_one(self) -> None:
        # Normalisation strips punctuation and so shortens the name below the cut length;
        # measured there, a genuinely truncated name never looked truncated.
        matched, confidence, _ = of.match_confidence(
            "WESTERN STATES COUNCIL OF CARPENTERS", "WESTERN STATES COUNCIL OF")
        self.assertTrue(matched)
        self.assertEqual(confidence, "low")

    def test_unknown_file_size_is_charged_against_the_budget(self) -> None:
        # Charging zero let a manifest of malformed rows through for free.
        manifest = [{"filename": f"f{i}.csv", "business_unit": str(i), "fiscal_year": "FY25",
                     "size_mb": 0.0, "url": "u"} for i in range(5)]
        chosen = of.select_files(manifest, business_units=[], fiscal_years=["FY25"],
                                 max_total_mb=of.UNKNOWN_SIZE_MB * 2)
        self.assertEqual(len(chosen), 2)
