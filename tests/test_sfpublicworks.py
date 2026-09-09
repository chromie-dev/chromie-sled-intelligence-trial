"""Offline tests for the SF Public Works bid-tabulation adapter. No network.

The text below is the shape `extract_pages` returns for a real tabulation page. Note the
bidder order: San Francisco lists companies "in the order received & opened", which is not
price order, so rank has to be derived rather than read off the page.
"""
import unittest

from sled_trial.sources.ca import sfpublicworks

TABULATION = """City and County of San Francisco
Department of Public Works
TABULATION OF BIDS
SOURCING ID: 0000007165
CONTRACT TITLE: PW VL PAVE RENOV NO.78 & SWR
FULL TITLE: Various Locations Pavement Renovation No. 78 and Sewer Replacement
BIDS RECEIVED: September 24, 2025
BIDDERS (in the order received & opened): LBE Status Claimed Total Bid Price
R&S Construction Management Inc. Micro-LBE 10% $7,660,061.00
Ronan Construction Micro-LBE 10% $6,563,340.00
Esquivel Grading & Paving, Inc. Small-LBE 10% $6,695,491.00
A. Ruiz Construction Company Micro-LBE 10% $6,604,539.52
Precision Engineering Small-LBE 10% $8,112,813.00
Bauman Landscape & Construction Inc. Small-LBE 10% $7,309,710.00
Average Bid: $7,157,659.09
Engineer's Estimate: $7,830,000.00
% of Engineer's Estimate: 91%
cc: Someone Else
"""

NO_LBE = """TABULATION OF BIDS
SOURCING ID: 0000002270
BIDS RECEIVED: February 18, 2026
BIDDERS (in the order received & opened): LBE Status Total Bid Price
Plain Contractor Inc. $1,000.00
Average Bid: $1,000.00
"""


class ParseTests(unittest.TestCase):
    def test_every_bidder_is_captured(self) -> None:
        tab = sfpublicworks.parse_tabulation(TABULATION)
        self.assertEqual(len(tab["bidders"]), 6)
        self.assertIn("Ronan Construction", [b["vendor_name"] for b in tab["bidders"]])

    def test_rank_is_derived_from_price_not_from_listed_order(self) -> None:
        # The page lists bidders in the order their envelopes were opened. Ronan is
        # cheapest at $6,563,340 but appears second, so trusting position would name the
        # wrong apparent low bidder.
        tab = sfpublicworks.parse_tabulation(TABULATION)
        by_rank = {b["rank"]: b["vendor_name"] for b in tab["bidders"]}
        self.assertEqual(by_rank[1], "Ronan Construction")
        self.assertEqual(by_rank[6], "Precision Engineering")

    def test_the_listed_order_is_preserved_separately(self) -> None:
        # It is the one fact the page actually asserts, so it is kept rather than
        # discarded in favour of the derived rank.
        tab = sfpublicworks.parse_tabulation(TABULATION)
        first = next(b for b in tab["bidders"] if b["listed_position"] == 1)
        self.assertEqual(first["vendor_name"], "R&S Construction Management Inc.")

    def test_amounts_keep_the_raw_string_and_a_numeric_form(self) -> None:
        tab = sfpublicworks.parse_tabulation(TABULATION)
        ronan = next(b for b in tab["bidders"] if b["vendor_name"] == "Ronan Construction")
        self.assertEqual(ronan["bid_amount_raw"], "$6,563,340.00")
        self.assertEqual(ronan["bid_amount"], 6563340.0)

    def test_local_business_status_is_captured(self) -> None:
        tab = sfpublicworks.parse_tabulation(TABULATION)
        ronan = next(b for b in tab["bidders"] if b["vendor_name"] == "Ronan Construction")
        self.assertEqual(ronan["lbe_status"], "Micro-LBE 10%")

    def test_a_bidder_without_an_lbe_status_still_parses(self) -> None:
        tab = sfpublicworks.parse_tabulation(NO_LBE)
        self.assertEqual(len(tab["bidders"]), 1)
        self.assertEqual(tab["bidders"][0]["vendor_name"], "Plain Contractor Inc.")
        self.assertIsNone(tab["bidders"][0]["lbe_status"])

    def test_the_solicitation_is_identified(self) -> None:
        tab = sfpublicworks.parse_tabulation(TABULATION)
        self.assertEqual(tab["sourcing_id"], "0000007165")
        self.assertEqual(tab["contract_title"], "PW VL PAVE RENOV NO.78 & SWR")
        self.assertEqual(tab["bids_received"], "September 24, 2025")

    def test_the_engineers_estimate_is_captured(self) -> None:
        # A benchmark Caltrans results do not carry: it says whether the field came in
        # under or over what the agency expected to pay.
        tab = sfpublicworks.parse_tabulation(TABULATION)
        self.assertEqual(tab["engineers_estimate"], 7830000.0)

    def test_summary_lines_are_not_mistaken_for_bidders(self) -> None:
        tab = sfpublicworks.parse_tabulation(TABULATION)
        names = [b["vendor_name"] for b in tab["bidders"]]
        for noise in ("Average Bid:", "Engineer's Estimate:", "cc:"):
            self.assertNotIn(noise, names)

    def test_text_without_a_tabulation_yields_nothing(self) -> None:
        self.assertIsNone(sfpublicworks.parse_tabulation(
            "Attachment 2: Contract Monitoring Division 14B Waiver"))


class DiscoveryTests(unittest.TestCase):
    PAGE = """
    <a href="/sites/default/files/Commissions/Nov%2013%202025/Item%204d_award.pdf">award</a>
    <a href="https://sfpublicworks.org/sites/default/files/Commissions/Nov%2013%202025/Item%204d_Attachments.pdf">attach</a>
    <a href="/sites/default/files/other/newsletter.pdf">unrelated</a>
    <a href="/about/commission">not a pdf</a>
    """

    def test_only_commission_pdfs_are_returned_absolute(self) -> None:
        links = sfpublicworks.commission_pdf_links(self.PAGE)
        self.assertEqual(links, [
            "https://sfpublicworks.org/sites/default/files/Commissions/Nov%2013%202025/Item%204d_Attachments.pdf",
            "https://sfpublicworks.org/sites/default/files/Commissions/Nov%2013%202025/Item%204d_award.pdf",
        ])

    def test_links_are_deduplicated(self) -> None:
        page = self.PAGE + self.PAGE
        self.assertEqual(len(sfpublicworks.commission_pdf_links(page)), 2)


class CandidateTests(unittest.TestCase):
    def test_rows_use_the_field_names_the_participant_export_reads(self) -> None:
        tab = sfpublicworks.parse_tabulation(TABULATION)
        rows = sfpublicworks.bidder_candidates(tab, source_url="https://x/y.pdf")
        low = next(r for r in rows if r["vendor_name_raw"] == "Ronan Construction")
        self.assertEqual(low["amount_numeric"], 6563340.0)
        self.assertEqual(low["rank"], 1)
        self.assertEqual(low["source_key"], "sfpublicworks_bid_tabulation")
        self.assertEqual(low["evidence_url"], "https://x/y.pdf")

    def test_the_event_identity_is_the_sourcing_id_not_a_cal_eprocure_event(self) -> None:
        # San Francisco is a city, absent from Cal eProcure entirely, so inventing a
        # business_unit for it would fabricate a join that does not exist.
        tab = sfpublicworks.parse_tabulation(TABULATION)
        row = sfpublicworks.bidder_candidates(tab, source_url="https://x/y.pdf")[0]
        self.assertEqual(row["business_unit"], "SFPW")
        self.assertEqual(row["event_id"], "0000007165")


class PrefilterTests(unittest.TestCase):
    def test_attachment_and_award_files_are_worth_opening(self) -> None:
        for name in ["Item%204d_Attachments%202025.pdf", "Item 4c_elevator award.pdf",
                     "PWC No 35 attach 2026-4-30.pdf", "Bid Tabulation.pdf"]:
            with self.subTest(name=name):
                self.assertTrue(sfpublicworks.likely_tabulation(f"https://x/{name}"))

    def test_minutes_and_agendas_are_skipped(self) -> None:
        # Not a classifier -- it only decides what to download. Content still confirms.
        for name in ["2025-11-13 PWC Minutes.pdf", "PW Commission Agenda v44.pdf",
                     "Item 1_PWC Correspondence Log.pdf"]:
            with self.subTest(name=name):
                self.assertFalse(sfpublicworks.likely_tabulation(f"https://x/{name}"))


class HarvestTests(unittest.TestCase):
    def _read_pages(self, mapping):
        def read_pages(url):
            return mapping.get(url, ["nothing here"])
        return read_pages

    def test_a_tabulation_is_found_and_attributed_to_its_url(self) -> None:
        out = sfpublicworks.harvest(
            ["https://x/a.pdf", "https://x/b.pdf"],
            self._read_pages({"https://x/b.pdf": ["cover page", TABULATION]}))
        self.assertEqual(len(out["tabulations"]), 1)
        self.assertEqual(out["tabulations"][0]["source_url"], "https://x/b.pdf")
        self.assertEqual(len(out["candidates"]), 6)

    def test_documents_without_a_tabulation_are_counted_not_dropped(self) -> None:
        out = sfpublicworks.harvest(["https://x/a.pdf"], self._read_pages({}))
        self.assertEqual(out["documents_read"], 1)
        self.assertEqual(out["documents_without_tabulation"], 1)

    def test_a_document_that_fails_to_read_is_recorded_as_a_failure(self) -> None:
        # README requires an inaccessible document to be an explicit failure rather than a
        # silent omission.
        def boom(url):
            raise OSError("connection reset")

        out = sfpublicworks.harvest(["https://x/a.pdf"], boom)
        self.assertEqual(out["failures"], [{"url": "https://x/a.pdf",
                                            "error": "OSError: connection reset"}])
        self.assertEqual(out["tabulations"], [])

    def test_only_the_first_pages_are_searched(self) -> None:
        # A tabulation sits at the front of its attachment; one real file runs to 221
        # pages and scanning all of them for every document is waste.
        pages = ["filler"] * 40 + [TABULATION]
        out = sfpublicworks.harvest(["https://x/a.pdf"],
                                    self._read_pages({"https://x/a.pdf": pages}),
                                    max_pages=5)
        self.assertEqual(out["tabulations"], [])


if __name__ == "__main__":
    unittest.main()
