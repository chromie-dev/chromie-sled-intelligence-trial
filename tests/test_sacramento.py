"""Offline tests for the Sacramento Bid Activities layer. No network.

The payload is the shape the live ArcGIS FeatureServer returned on 2026-09-10.
"""
import unittest

from sled_trial.sources.ca import sacramento as sac

PAYLOAD = {
    "exceededTransferLimit": False,
    "features": [
        {"attributes": {
            "OBJECTID": 2, "Project_Title": "Citywide Multi-Function Copier Devices",
            "Invitation_Num": "P120100001",
            "Department": "City of Sacramento - City Manager",
            "Posted": 1333584000000, "Due_Date": 1337212800000,
            "Project_Stage": "Closed", "General": "X", "Public_Works": "",
            "Professional_Services": "", "Bid": "", "RFI": "", "RFP": "X",
            "RFQ": "", "RFQual": "", "Notified_Total": 6,
            "Prospective__Bidder_Total": 23, "Prospective_Bidders_Local": 11,
            "Award_Amount_Totaldollars": 0, "Award_Amount_Localdollars": 0}},
        {"attributes": {
            "OBJECTID": 3, "Project_Title": "Street Resurfacing",
            "Invitation_Num": "PW230000012", "Department": "Public Works",
            "Posted": 0, "Due_Date": None, "Project_Stage": "Awarded",
            "General": "", "Public_Works": "X", "Professional_Services": "",
            "Bid": "X", "RFI": "", "RFP": "", "RFQ": "", "RFQual": "",
            "Notified_Total": 0, "Prospective__Bidder_Total": 0,
            "Prospective_Bidders_Local": 0,
            "Award_Amount_Totaldollars": 1250000.0,
            "Award_Amount_Localdollars": 1250000.0}},
    ],
}


class ParseTests(unittest.TestCase):
    def test_solicitations_parse_with_identity(self) -> None:
        rows = sac.parse_features(PAYLOAD)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["event_id"], "P120100001")
        self.assertEqual(rows[0]["business_unit"], "SACCITY")

    def test_epoch_milliseconds_become_dates(self) -> None:
        self.assertEqual(sac.parse_features(PAYLOAD)[0]["posted"], "2012-04-05")

    def test_a_zero_or_null_date_is_none_rather_than_1970(self) -> None:
        row = sac.parse_features(PAYLOAD)[1]
        self.assertIsNone(row["posted"])
        self.assertIsNone(row["due_date"])

    def test_category_and_type_flags_become_lists(self) -> None:
        rows = sac.parse_features(PAYLOAD)
        self.assertEqual(rows[0]["categories"], ["General"])
        self.assertEqual(rows[0]["solicitation_types"], ["RFP"])
        self.assertEqual(rows[1]["categories"], ["Public_Works"])
        self.assertEqual(rows[1]["solicitation_types"], ["Bid"])


class CountTests(unittest.TestCase):
    """Counts, not names -- and zero is a real count while zero dollars is not."""

    def test_bidder_counts_are_captured(self) -> None:
        row = sac.parse_features(PAYLOAD)[0]
        self.assertEqual(row["vendors_notified"], 6)
        self.assertEqual(row["prospective_bidders"], 23)
        self.assertEqual(row["prospective_bidders_local"], 11)

    def test_a_zero_count_survives_as_zero(self) -> None:
        # Nobody bid is a finding; turning it into None loses it.
        self.assertEqual(sac.parse_features(PAYLOAD)[1]["prospective_bidders"], 0)

    def test_a_zero_award_amount_is_not_published_rather_than_free(self) -> None:
        rows = sac.parse_features(PAYLOAD)
        self.assertIsNone(rows[0]["award_amount"])
        self.assertEqual(rows[1]["award_amount"], 1250000.0)

    def test_local_share_is_derived_only_when_it_can_be(self) -> None:
        rows = sac.parse_features(PAYLOAD)
        self.assertEqual(rows[0]["local_share"], round(11 / 23, 3))
        self.assertIsNone(rows[1]["local_share"])   # no prospective bidders to divide by

    def test_rows_state_that_bidders_are_not_named(self) -> None:
        for row in sac.parse_features(PAYLOAD):
            self.assertFalse(row["names_bidders"])


class HarvestTests(unittest.TestCase):
    def test_the_layer_count_is_reconciled_against_what_arrived(self) -> None:
        def fetch(url):
            return {"count": 2} if "returnCountOnly" in url else PAYLOAD

        out = sac.harvest(fetch)
        self.assertEqual(out["collected"], 2)
        self.assertEqual(out["reported_by_layer"], 2)
        self.assertTrue(out["complete"])

    def test_a_short_harvest_is_visible_rather_than_looking_like_a_small_city(self) -> None:
        def fetch(url):
            return {"count": 395} if "returnCountOnly" in url else PAYLOAD

        out = sac.harvest(fetch)
        self.assertFalse(out["complete"])

    def test_a_failed_page_is_recorded(self) -> None:
        def fetch(url):
            if "returnCountOnly" in url:
                return {"count": 2}
            raise OSError("connection reset")

        out = sac.harvest(fetch)
        self.assertEqual(out["rows"], [])
        self.assertEqual(len(out["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
