"""Offline tests for the supplier registry adapter and the location join. No network."""
import unittest

from sled_trial import vendors
from sled_trial.sources.ca import supplier_search as ss

# Shaped like the real response: one result grid plus form dropdowns with MORE rows than
# results. A first version keyed rows off the highest index anywhere on the page, reported
# 6 results for a 2-result search, and stapled unrelated attributes onto suppliers.
GRID = """
<span id="ZZ_PUBSRCH_VW_ZZ_NAME1$0">AVIATE ENTERPRISES INC</span>
<span id="ZZ_PUBSRCH_VW_CITY$0">SACRAMENTO</span>
<span id="ZZ_PUBSRCH_VW_STATE$0">CA</span>
<span id="ZZ_PUBSRCH_VW_POSTAL$0">95834-1984</span>
<span id="ZZ_PUBSRCH_VW_COUNTRY$0">USA</span>
<span id="ZZ_PUBSRCH_VW_ADDRESS1$0">1418 N MARKET BLVD</span>
<span id="ZZ_PUBSRCH_VW_ADDRESS2$0">STE 500</span>
<span id="ZZ_PUBSRCH_VW_DESCR1$0">DVBE , SB-PW</span>
<span id="ZZ_PUBSRCH_VW_ZZ_CERT_ID$0">1792472</span>
<span id="ZZ_PUBSRCH_VW_URL$0">www.aviateinc.com</span>
<span id="ZZ_PUBSRCH_VW_EMAILID$0">someone@example.com</span>
<span id="ZZ_PUBSRCH_VW_FIRST_NAME$0">Jane</span>
<span id="ZZ_PUBSRCH_VW_PHONE3$0">916.000.0000</span>
<span id="ZZ_PUBSRCH_VW_ZZ_NAME1$1">AVIATE ROOFING, FLOORING &amp; CONSTRUCTION</span>
<span id="ZZ_PUBSRCH_VW_CITY$1">Sacramento</span>
<span id="ZZ_PUBSRCH_VW_POSTAL$1">95652</span>
<span id="ZZ_CERTYPLBL_VW_DESCR254$0">Small Business (SB)</span>
<span id="ZZ_CERTYPLBL_VW_DESCR254$1">Micro Business (MB)</span>
<span id="ZZ_CERTYPLBL_VW_DESCR254$5">DVBE</span>
<span id="ZZ_BUS_TYP_VW_BUSINESS_DESCR$0">Manufacturer</span>
<span id="ZZ_BUS_TYP_VW_BUSINESS_DESCR$3">Construction</span>
<span id="ZZ_NAICS_VW_NAICS_CODE$0">238160</span>
"""


class ParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = ss.parse_results(GRID)

    def test_form_dropdowns_do_not_inflate_the_result_count(self) -> None:
        # 6 certification options and 4 business types are on the page; 2 suppliers matched.
        self.assertEqual(len(self.rows), 2)

    def test_location_is_parsed(self) -> None:
        loc = self.rows[0]["location"]
        self.assertEqual(loc["city"], "SACRAMENTO")
        self.assertEqual(loc["state"], "CA")
        self.assertEqual(loc["postal"], "95834-1984")
        self.assertEqual(loc["street"], "1418 N MARKET BLVD STE 500")
        self.assertTrue(self.rows[0]["has_location"])

    def test_certifications_come_from_the_result_row_not_the_dropdown(self) -> None:
        # "Micro Business (MB)" is a dropdown option and must not attach to this supplier.
        self.assertEqual(self.rows[0]["certifications"], ["DVBE", "SB-PW"])

    def test_contact_fields_are_never_captured(self) -> None:
        blob = repr(self.rows)
        for value in ("someone@example.com", "Jane", "916.000.0000"):
            with self.subTest(value=value):
                self.assertNotIn(value, blob)

    def test_the_omission_is_recorded(self) -> None:
        self.assertEqual(len(self.rows[0]["contact_fields_omitted"]), 5)

    def test_entities_are_decoded_and_kept_distinct(self) -> None:
        self.assertIn("&", self.rows[1]["supplier_name"])
        self.assertNotEqual(self.rows[0]["supplier_name"], self.rows[1]["supplier_name"])

    def test_a_row_with_no_name_is_dropped(self) -> None:
        self.assertEqual(ss.parse_results('<span id="ZZ_PUBSRCH_VW_CITY$0">Nowhere</span>'), [])

    def test_coverage_caveat_travels_with_every_row(self) -> None:
        for row in self.rows:
            self.assertIn("may not index every state supplier", row["coverage_note"])


class CriteriaTests(unittest.TestCase):
    def test_a_blank_search_is_refused(self) -> None:
        # It returns the empty form, which parses as zero results and reads exactly like
        # "this vendor is not registered".
        with self.assertRaises(ValueError):
            ss.search(None)

    def test_unknown_criteria_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ss.search(None, city="Sacramento")


class LocationJoinTests(unittest.TestCase):
    def _index(self):
        return {r["supplier_name"]: r for r in ss.parse_results(GRID)}

    def test_an_exact_name_match_attaches_location(self) -> None:
        profiles = [{"supplier_id": "1", "canonical_name": "AVIATE ENTERPRISES INC"}]
        summary = vendors.attach_location(profiles, self._index())
        block = profiles[0]["location"]
        self.assertTrue(block["matched"])
        self.assertEqual(block["city"], "SACRAMENTO")
        self.assertEqual(block["evidence_class"], "observed")
        self.assertEqual(summary["matched"], 1)

    def test_confidence_is_capped_at_medium(self) -> None:
        # The registry publishes no supplier_id, so this can only ever be a name match.
        profiles = [{"supplier_id": "1", "canonical_name": "AVIATE ENTERPRISES INC"}]
        vendors.attach_location(profiles, self._index())
        self.assertEqual(profiles[0]["location"]["match_confidence"], "medium")

    def test_an_unmatched_vendor_says_why_rather_than_claiming_no_location(self) -> None:
        profiles = [{"supplier_id": "9", "canonical_name": "WW GRAINGER INC"}]
        vendors.attach_location(profiles, self._index())
        block = profiles[0]["location"]
        self.assertFalse(block["matched"])
        self.assertIn("not in the small-business registry", block["note"])

    def test_prefix_matching_is_not_used(self) -> None:
        # "AVIATE" alone matches two different companies at different addresses.
        profiles = [{"supplier_id": "1", "canonical_name": "AVIATE"}]
        vendors.attach_location(profiles, self._index())
        self.assertFalse(profiles[0]["location"]["matched"])

    def test_the_summary_states_the_measured_coverage_bias(self) -> None:
        summary = vendors.attach_location([], {})
        self.assertIn("80% for vendors certified", summary["coverage_caveat"])
        self.assertIn("city-to-county mapping", summary["prediction_gap"])


if __name__ == "__main__":
    unittest.main()
