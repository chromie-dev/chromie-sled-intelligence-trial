"""Offline tests for the Cal eProcure vendor-ad boards. No network.

The markup is the shape the "View Vendor Ad" postback returned live for two real
events: 7760/0000039865 (a genuine sub seeking a prime) and 8940/0000039727 (a
bid-assistance firm advertising to bidders).
"""
import unittest

from sled_trial.sources.ca import vendor_ads as va

GENUINE = """
<span id='ZZ_VNDR_AD_TBL_BUSINESS_UNIT'>7760</span>
<span id='ZZ_VNDR_AD_TBL_AUC_ID'>0000039865</span>
<span id='ZZ_VNDR_AD_WRK_ZZ_AUC_NAME'>CR25-300826.FMD.UPS Services</span>
<span id='ZZ_VNDR_AD_WRK_DESCR254'>No Ad for Prime Seeking Sub</span>
<span id='ZZ_VNDR_SUB_VW_NAME1$0' >Jackie, Integrity Technology</span>
<textarea id='ZZ_VNDR_SUB_VW_DESCRLONG$0'>Integrity Technology is a value-added
reseller for IT products and services. We welcome the opportunity to partner with you
on this opportunity. We are certified as a CA small/micro/woman-owned business.</textarea>
<span id='ZZ_VNDR_SUB_VW_LAST_ENTRY_DATE$0'>08/26/2026</span>
<span id='ZZ_VNDR_SUB_VW_CREATE_DTTM$0'>08/26/2026  7:28PM</span>
<span id='ZZ_VNDR_SUB_VW_EMAILID_VNDR$0'>jackie@example.com</span>
<span id='ZZ_VNDR_SUB_VW_PHONE$0'>555-0100</span>
"""

BID_ASSISTANCE = """
<span id='ZZ_VNDR_AD_TBL_BUSINESS_UNIT'>8940</span>
<span id='ZZ_VNDR_AD_TBL_AUC_ID'>0000039727</span>
<span id='ZZ_VNDR_AD_WRK_DESCR254'>No Ad for Prime Seeking Sub</span>
<span id='ZZ_VNDR_SUB_VW_NAME1$0' >Robert L. Klein</span>
<textarea id='ZZ_VNDR_SUB_VW_DESCRLONG$0'>We are, Klein &amp; Associates, a SDVBE and SB
State certified business. We can help you search and bid on opportunities. Additionally,
if you select us to use our research and recruiting abilities after you win a bid.</textarea>
<span id='ZZ_VNDR_SUB_VW_LAST_ENTRY_DATE$0'>09/02/2026</span>
<span id='ZZ_VNDR_SUB_VW_CREATE_DTTM$0'>07/24/2026 10:47AM</span>
"""

NO_ADS = """
<span id='ZZ_VNDR_AD_TBL_BUSINESS_UNIT'>3790</span>
<span id='ZZ_VNDR_AD_TBL_AUC_ID'>0000039530</span>
<span id='ZZ_VNDR_AD_WRK_DESCR254'>No Ad for Prime Seeking Sub</span>
<span>No Ad for Sub Seeking Prime</span>
"""


class ParseTests(unittest.TestCase):
    def test_a_row_id_ending_in_a_dollar_index_is_read(self) -> None:
        # `$` is an end-of-line anchor. Unescaped, every field read as None and the ad
        # was silently dropped as empty -- while the index lookup still found the row,
        # so the failure looked like "this board has no ads".
        parsed = va.parse_ad_page(GENUINE)
        self.assertEqual(parsed["ad_count"], 1)
        ad = parsed["boards"]["sub_seeking_prime"]["ads"][0]
        self.assertEqual(ad["vendor_name"], "Jackie, Integrity Technology")

    def test_the_event_identity_is_captured(self) -> None:
        parsed = va.parse_ad_page(GENUINE)
        self.assertEqual(parsed["business_unit"], "7760")
        self.assertEqual(parsed["event_id"], "0000039865")

    def test_dates_are_captured(self) -> None:
        ad = va.parse_ad_page(GENUINE)["boards"]["sub_seeking_prime"]["ads"][0]
        self.assertEqual(ad["response_deadline"], "08/26/2026")
        self.assertEqual(ad["created"], "08/26/2026  7:28PM")

    def test_contact_fields_are_present_on_the_page_and_never_stored(self) -> None:
        # README puts private contact enrichment out of scope, and these boards are the
        # one surface where a named individual's email and phone sit in the open.
        ad = va.parse_ad_page(GENUINE)["boards"]["sub_seeking_prime"]["ads"][0]
        self.assertNotIn("email", " ".join(ad).lower())
        for value in ad.values():
            self.assertNotIn("jackie@example.com", str(value))
            self.assertNotIn("555-0100", str(value))


class StatedAbsenceTests(unittest.TestCase):
    """The page says "No Ad for X". That is a fact, not a failed read."""

    def test_an_empty_board_is_recorded_as_stated_absent(self) -> None:
        parsed = va.parse_ad_page(NO_ADS)
        self.assertTrue(parsed["boards"]["prime_seeking_sub"]["stated_absent"])
        self.assertTrue(parsed["boards"]["sub_seeking_prime"]["stated_absent"])
        self.assertEqual(parsed["ad_count"], 0)

    def test_one_board_can_be_absent_while_the_other_has_ads(self) -> None:
        parsed = va.parse_ad_page(GENUINE)
        self.assertTrue(parsed["boards"]["prime_seeking_sub"]["stated_absent"])
        self.assertFalse(parsed["boards"]["sub_seeking_prime"]["stated_absent"])


class GenericAdTests(unittest.TestCase):
    """Bid-assistance firms post against events they have no intention of bidding."""

    def test_a_bid_assistance_ad_is_flagged(self) -> None:
        parsed = va.parse_ad_page(BID_ASSISTANCE)
        self.assertEqual(parsed["generic_count"], 1)

    def test_a_genuine_ad_is_not_flagged(self) -> None:
        # The discount has to be narrow, or it eats the signal it is protecting.
        self.assertEqual(va.parse_ad_page(GENUINE)["generic_count"], 0)

    def test_flagged_rather_than_dropped(self) -> None:
        # Dropping would hide a judgement call inside the parser.
        rows = va.declared_interest_rows(va.parse_ad_page(BID_ASSISTANCE))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["generic_bid_assistance"])


class ClassificationTests(unittest.TestCase):
    def test_an_ad_is_declared_interest_and_never_a_bid(self) -> None:
        for page in (GENUINE, BID_ASSISTANCE):
            for row in va.declared_interest_rows(va.parse_ad_page(page)):
                self.assertEqual(row["participation"], "declared_interest")
                self.assertIsNone(row["supplier_id"])
                self.assertEqual(row["identity_confidence"], "unresolved")

    def test_only_a_prime_seeking_a_sub_is_declaring_intent_to_bid(self) -> None:
        rows = va.declared_interest_rows(va.parse_ad_page(GENUINE))
        self.assertFalse(rows[0]["intends_to_bid"])

    def test_the_name_field_is_not_reliably_a_company(self) -> None:
        # Observed: "Robert L. Klein" is a person, with the company only in the free
        # text. Any later match against a supplier registry inherits that.
        rows = va.declared_interest_rows(va.parse_ad_page(BID_ASSISTANCE))
        self.assertEqual(rows[0]["vendor_name_raw"], "Robert L. Klein")
        self.assertIn("Klein & Associates", rows[0]["description"])


class HarvestTests(unittest.TestCase):
    def test_events_with_no_ads_are_kept_apart_from_events_that_failed(self) -> None:
        pages = {("7760", "0000039865"): GENUINE, ("3790", "0000039530"): NO_ADS}

        def fetch(bu, eid):
            if (bu, eid) == ("9999", "x"):
                raise OSError("connection reset")
            return pages[(bu, eid)]

        out = va.harvest(fetch, [
            {"business_unit": "7760", "event_id": "0000039865"},
            {"business_unit": "3790", "event_id": "0000039530"},
            {"business_unit": "9999", "event_id": "x"},
        ])
        self.assertEqual(out["events_checked"], 2)
        self.assertEqual(out["events_with_ads"], 1)
        self.assertEqual(len(out["events_stating_no_ads"]), 1)
        self.assertEqual(len(out["failures"]), 1)

    def test_generic_ads_are_counted_in_the_summary(self) -> None:
        out = va.harvest(lambda bu, eid: BID_ASSISTANCE,
                         [{"business_unit": "8940", "event_id": "0000039727"}])
        self.assertEqual(out["generic_bid_assistance"], 1)


PRIME = """
<span id='ZZ_VNDR_AD_TBL_BUSINESS_UNIT'>2660</span>
<span id='ZZ_VNDR_AD_TBL_AUC_ID'>12A2401</span>
<span>No Ad for Sub Seeking Prime</span>
<span id='ZZ_VNDR_PRIM_VW_NAME1$0' >AI FENCE &amp; RESTORATION</span>
<textarea id='ZZ_VNDR_PRIM_VW_DESCRLONG$0'>AI FENCE &amp; RESTORATION is a California
-based fencing contractors, licensed by the CSLB #1155122 under C-13 Fencing. We
specialize in quality fencing and exterior construction services.</textarea>
<span id='ZZ_VNDR_PRIM_VW_LAST_ENTRY_DATE$0'>09/15/2026</span>
<span id='ZZ_VNDR_PRIM_VW_CREATE_DTTM$0'>09/01/2026 10:00AM</span>
"""


class PrimeBoardTests(unittest.TestCase):
    """The board that matters: a prime seeking subs is declaring it will bid."""

    def test_the_prime_board_uses_its_own_field_family(self) -> None:
        # PRIM, not PRM. Guessed wrong first and the board silently parsed as empty,
        # which is indistinguishable from an event with no prime ad.
        parsed = va.parse_ad_page(PRIME)
        self.assertEqual(parsed["ad_count"], 1)
        self.assertFalse(parsed["boards"]["prime_seeking_sub"]["stated_absent"])

    def test_a_prime_ad_is_marked_as_intending_to_bid(self) -> None:
        row = va.declared_interest_rows(va.parse_ad_page(PRIME))[0]
        self.assertTrue(row["intends_to_bid"])
        self.assertEqual(row["interest_direction"], "prime_seeking_sub")

    def test_it_is_still_declared_interest_not_a_bid(self) -> None:
        # Saying you will bid is not bidding.
        row = va.declared_interest_rows(va.parse_ad_page(PRIME))[0]
        self.assertEqual(row["participation"], "declared_interest")

    def test_the_prime_name_field_is_a_company(self) -> None:
        row = va.declared_interest_rows(va.parse_ad_page(PRIME))[0]
        self.assertEqual(row["vendor_name_raw"], "AI FENCE & RESTORATION")


class LicenceTests(unittest.TestCase):
    """Contractors cite their state licence in the copy, and it is the one identifier
    that crosses sources -- these ads carry no supplier id."""

    def test_a_cited_cslb_number_is_extracted(self) -> None:
        self.assertEqual(va.licence_numbers(
            "licensed by the CSLB #1155122 under C-13 Fencing"), ["1155122"])

    def test_other_phrasings_are_caught(self) -> None:
        self.assertEqual(va.licence_numbers("CA License # 987654"), ["987654"])
        self.assertEqual(va.licence_numbers("Lic. 1023456"), ["1023456"])

    def test_a_bare_number_is_not_treated_as_a_licence(self) -> None:
        # "We have completed 250000 square feet" is not a licence number.
        self.assertEqual(va.licence_numbers("we completed 250000 square feet"), [])

    def test_ads_without_a_licence_yield_none(self) -> None:
        self.assertEqual(va.licence_numbers("We resell IT products."), [])

    def test_the_licence_reaches_the_declared_interest_row(self) -> None:
        row = va.declared_interest_rows(va.parse_ad_page(PRIME))[0]
        self.assertEqual(row["cslb_licences"], ["1155122"])


if __name__ == "__main__":
    unittest.main()
