"""Offline tests for PDF extraction and participant mining. No network."""
import pathlib
import unittest

from sled_trial import extract

FIX = pathlib.Path(__file__).parent / "fixtures"

# The real shape observed on DMV event 2740/0000040075, Intent_to_Award_ISD26-4620.pdf.
AWARD_TABLE = [["Company Name", "Bid Amount"], ["AVIATE ENTERPRISES, INC.", "$437,862.48"]]


class ParticipantTableTests(unittest.TestCase):
    def test_extracts_vendor_and_amount(self) -> None:
        got = extract.participants_from_tables([AWARD_TABLE])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["vendor_name_raw"], "AVIATE ENTERPRISES, INC.")
        self.assertEqual(got[0]["amount_raw"], "$437,862.48")
        self.assertEqual(got[0]["amount_numeric"], "437862.48")

    def test_evidence_row_is_retained(self) -> None:
        got = extract.participants_from_tables([AWARD_TABLE])
        self.assertEqual(got[0]["evidence_row"], AWARD_TABLE[1])
        self.assertEqual(got[0]["header"], AWARD_TABLE[0])

    def test_header_row_is_not_mistaken_for_a_vendor(self) -> None:
        got = extract.participants_from_tables([[["Company Name"], ["Company Name"]]])
        self.assertEqual(got, [])

    def test_table_without_a_vendor_column_is_ignored(self) -> None:
        self.assertEqual(extract.participants_from_tables(
            [[["Item", "Quantity"], ["Widget", "5"]]]), [])

    def test_unparseable_amount_is_rejected_not_reported_as_a_participant(self) -> None:
        # Deliberate precision-over-recall choice. On a real 6-event corpus the permissive
        # version returned 1 true awardee and 8 false positives. A fabricated known_bidder
        # is the worst error this pipeline can make, so a row whose value cell does not
        # parse as money or a rank is not treated as participation evidence. Near-misses
        # belong in the review queue rather than in the participant set.
        got = extract.participants_from_tables(
            [[["Vendor", "Bid Amount"], ["ACME LLC", "see attachment"]]])
        self.assertEqual(got, [])

    def test_rank_column_is_captured_when_present(self) -> None:
        got = extract.participants_from_tables(
            [[["Rank", "Bidder", "Total Price"], ["2", "ACME LLC", "$10,000.00"]]])
        self.assertEqual(got[0]["rank_raw"], "2")
        self.assertEqual(got[0]["vendor_name_raw"], "ACME LLC")

    def test_multi_bidder_table_yields_every_row(self) -> None:
        got = extract.participants_from_tables(
            [[["Bidder", "Bid Amount"], ["A CO", "$1.00"], ["B CO", "$2.00"], ["", "$3.00"]]])
        self.assertEqual([g["vendor_name_raw"] for g in got], ["A CO", "B CO"])

    def test_empty_and_short_tables_are_safe(self) -> None:
        self.assertEqual(extract.participants_from_tables([]), [])
        self.assertEqual(extract.participants_from_tables([[]]), [])
        self.assertEqual(extract.participants_from_tables([[["Vendor"]]]), [])


class ExtractPagesTests(unittest.TestCase):
    def test_native_text_extraction(self) -> None:
        data = (FIX / "tiny_text.pdf").read_bytes()
        pages = list(extract.extract_pages(data, document_ref="fixture", sha256="deadbeef"))
        self.assertEqual(len(pages), 1)
        page = pages[0]
        self.assertEqual(page["method"], "native")
        self.assertEqual(page["page"], 1)
        self.assertIn("Intent to Award", page["text"])
        self.assertEqual(page["warnings"], [])
        self.assertEqual(page["sha256"], "deadbeef")

    def test_unreadable_pdf_yields_a_record_rather_than_raising(self) -> None:
        # A document must never silently vanish; failure is a typed record.
        pages = list(extract.extract_pages(b"not a pdf at all",
                                           document_ref="bad", sha256="x"))
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["method"], "none")
        self.assertIsNone(pages[0]["page"])
        self.assertTrue(pages[0]["warnings"])

    def test_ocr_availability_is_reported_not_assumed(self) -> None:
        ok, note = extract.ocr_available()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(note, str)

    def test_sparse_page_warns_when_ocr_is_disabled(self) -> None:
        data = (FIX / "tiny_text.pdf").read_bytes()
        pages = list(extract.extract_pages(data, document_ref="f", sha256="x", allow_ocr=False))
        self.assertEqual(pages[0]["method"], "native")  # this fixture has real text


if __name__ == "__main__":
    unittest.main()


class ParticipantPrecisionTests(unittest.TestCase):
    """Regressions built from real false positives on a 6-event corpus.

    pdfplumber reports prose blocks in solicitation documents as tables, and words like
    "bidder" and "bid" pervade RFQ boilerplate, so a loose header match fires on
    requirement text. Each case below was actually emitted by the first implementation.
    """

    def test_prose_heading_is_not_a_vendor(self) -> None:
        got = extract.participants_from_tables(
            [[["Confirmed DVBE Participation of:"], ["Confirmed DVBE Participation of:"]]])
        self.assertEqual(got, [])

    def test_percentage_band_is_not_a_vendor(self) -> None:
        got = extract.participants_from_tables(
            [[["Bidder", "Bid Amount"], ["5% and Over", "5% and Over"]]])
        self.assertEqual(got, [])

    def test_requirement_paragraph_is_not_a_vendor(self) -> None:
        got = extract.participants_from_tables([[
            ["Bidder Requirements"],
            ["RECYCLED CONTENT REQUIREMENTS The State shall require the following"]]])
        self.assertEqual(got, [])

    def test_executive_order_heading_is_not_a_vendor(self) -> None:
        got = extract.participants_from_tables(
            [[["Bidder", "Total"], ["EXECUTIVE ORDER N-6-22 - RUSSIAN SANCTIONS", "n/a"]]])
        self.assertEqual(got, [])

    def test_long_header_means_not_a_tabulation(self) -> None:
        long_header = "Attachments The following documents are incorporated by reference"
        got = extract.participants_from_tables(
            [[[long_header, "Bid Amount"], ["ACME LLC", "$1.00"]]])
        self.assertEqual(got, [])

    def test_vendor_column_alone_is_not_participation_evidence(self) -> None:
        got = extract.participants_from_tables(
            [[["Company Name"], ["ACME LLC"]]])
        self.assertEqual(got, [])

    def test_same_cell_resolved_twice_is_rejected(self) -> None:
        got = extract.participants_from_tables(
            [[["Bidder", "Bid"], ["ACME LLC", "ACME LLC"]]])
        self.assertEqual(got, [])

    def test_non_numeric_rank_is_not_a_rank(self) -> None:
        got = extract.participants_from_tables(
            [[["Bidder", "Rank"], ["ACME LLC", "see notes"]]])
        self.assertEqual(got, [])

    def test_the_real_awardee_still_survives_every_guard(self) -> None:
        # The one true positive from the corpus must not be lost to the tightening.
        got = extract.participants_from_tables(
            [[["Company Name", "Bid Amount"], ["AVIATE ENTERPRISES, INC.", "$437,862.48"]]])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["vendor_name_raw"], "AVIATE ENTERPRISES, INC.")
        self.assertEqual(got[0]["amount_numeric"], "437862.48")

    def test_a_multi_bidder_tabulation_with_ranks_survives(self) -> None:
        got = extract.participants_from_tables([[
            ["Rank", "Bidder", "Total Price"],
            ["1", "ALPHA CONSTRUCTION INC.", "$1,250,000.00"],
            ["2", "BETA BUILDERS LLC", "$1,340,500.00"]]])
        self.assertEqual([g["vendor_name_raw"] for g in got],
                         ["ALPHA CONSTRUCTION INC.", "BETA BUILDERS LLC"])
        self.assertEqual([g["rank_raw"] for g in got], ["1", "2"])
