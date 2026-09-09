"""Offline tests for extraction-quality review. No network."""
import unittest

from sled_trial import page_review


def page(text="The Department of Motor Vehicles intends to award a contract.",
         method="native", tables=None, **over):
    base = {"displayed_filename": "doc.pdf", "page": 1, "method": method,
            "sha256": "abc", "text": text, "char_count": len(text),
            "table_count": len(tables or []), "tables": tables or [],
            "warnings": [], "ocr_confidence": None}
    base.update(over)
    return base


class TextQualityTests(unittest.TestCase):
    def test_well_formed_prose_is_good(self) -> None:
        out = page_review.review([page()])
        self.assertEqual(out["findings"][0]["text"]["verdict"], "good")

    def test_empty_text_is_reported_as_empty(self) -> None:
        out = page_review.review([page(text="")])
        self.assertEqual(out["findings"][0]["text"]["verdict"], "empty")

    def test_garbled_ocr_is_detected(self) -> None:
        # The failure mode that matters: OCR returning punctuation soup.
        out = page_review.review([page(text="~^~ |||| ### @@@ ,,,, ;;;; ~~~~ ////")])
        self.assertEqual(out["findings"][0]["text"]["verdict"], "garbled")

    def test_implausible_word_lengths_are_suspect(self) -> None:
        out = page_review.review([page(text="a b c d e f g h i j k l m n o p q r")])
        self.assertIn(out["findings"][0]["text"]["verdict"], {"garbled", "suspect"})


class TableQualityTests(unittest.TestCase):
    def test_a_well_formed_grid_is_good(self) -> None:
        out = page_review.review([page(tables=[[["Company Name", "Bid Amount"],
                                                ["ACME LLC", "$1,000.00"]]])])
        self.assertEqual(out["findings"][0]["tables"]["verdict"], "good")

    def test_ragged_rows_are_flagged_as_layout_artifacts(self) -> None:
        out = page_review.review([page(tables=[[["a", "b", "c"], ["x"]]])])
        self.assertEqual(out["findings"][0]["tables"]["verdict"], "ragged")

    def test_no_tables_is_not_a_defect(self) -> None:
        finding = page_review.review([page()])["findings"][0]["tables"]
        self.assertEqual(finding["verdict"], "none")
        self.assertIn("not a defect", finding["note"])


class FieldQualityTests(unittest.TestCase):
    def test_prices_are_found_and_parsed(self) -> None:
        out = page_review.review([page(text="Total award is $437,862.48 for the term.")])
        prices = out["findings"][0]["prices"]
        self.assertEqual(prices["matches"], 1)
        self.assertEqual(prices["parseable"], 1)

    def test_dates_are_found_and_parsed(self) -> None:
        out = page_review.review([page(text="Posted 08/31/2026 and closes September 8, 2026.")])
        dates = out["findings"][0]["dates"]
        self.assertEqual(dates["matches"], 2)
        self.assertEqual(dates["parseable"], 2)

    def test_bidder_names_come_from_tables(self) -> None:
        out = page_review.review([page(tables=[[["Company Name", "Bid Amount"],
                                                ["AVIATE ENTERPRISES, INC.", "$437,862.48"]]])])
        bidders = out["findings"][0]["bidder_names"]
        self.assertEqual(bidders["count"], 1)
        self.assertIn("AVIATE ENTERPRISES, INC.", bidders["candidates"])

    def test_absence_of_each_field_is_reported_not_scored_as_failure(self) -> None:
        f = page_review.review([page(text="Plain prose with nothing of interest.")])["findings"][0]
        self.assertEqual(f["prices"]["verdict"], "none")
        self.assertEqual(f["dates"]["verdict"], "none")
        self.assertEqual(f["bidder_names"]["verdict"], "none")


class SamplingTests(unittest.TestCase):
    def test_every_extraction_method_is_represented(self) -> None:
        # Taking the first N pages would miss OCR entirely.
        pages = ([page(method="native", page=i) for i in range(50)]
                 + [page(method="ocr", page=99)]
                 + [page(method="hybrid", page=98)])
        sample = page_review.sample_pages(pages, 20)
        methods = {p["method"] for p in sample}
        self.assertEqual(methods, {"native", "ocr", "hybrid"})

    def test_table_pages_are_prioritised(self) -> None:
        pages = [page(page=1), page(page=2, tables=[[["a", "b"], ["c", "d"]]])]
        self.assertEqual(page_review.sample_pages(pages, 1)[0]["page"], 2)

    def test_pages_without_a_page_number_are_skipped(self) -> None:
        pages = [page(page=None), page(page=1)]
        self.assertEqual(len(page_review.sample_pages(pages, 5)), 1)

    def test_the_minimum_of_twenty_is_reported_truthfully(self) -> None:
        few = page_review.review([page(page=i) for i in range(5)])
        self.assertFalse(few["meets_minimum_of_20"])
        many = page_review.review([page(page=i) for i in range(25)])
        self.assertTrue(many["meets_minimum_of_20"])


class HonestyTests(unittest.TestCase):
    def test_the_review_method_does_not_claim_a_human_read_the_pdfs(self) -> None:
        out = page_review.review([page()])
        self.assertIn("rather than by a person", out["review_method"])

    def test_limitations_state_that_recall_is_not_measured(self) -> None:
        out = page_review.review([page()])
        self.assertTrue(any("recall" in l for l in out["limitations"]))
        self.assertTrue(any("not whether it matches the source" in l
                            for l in out["limitations"]))


if __name__ == "__main__":
    unittest.main()


class BidderSeedingTests(unittest.TestCase):
    """Bidder-name quality cannot be measured if no bidder page is sampled.

    The first real run reviewed 20 pages and found zero bidders, because the corpus held
    exactly one bidder page in 864.
    """

    # A list of tables, each a list of rows -- the shape extract.participants_from_tables
    # expects. Passing one table's rows directly parses as several one-row tables.
    AWARD_TABLES = [[["Company Name", "Bid Amount"],
                     ["AVIATE ENTERPRISES, INC.", "$437,862.48"]]]

    def test_a_rare_bidder_page_is_always_sampled(self) -> None:
        haystack = [page(page=i, method="native") for i in range(200)]
        needle = page(page=999, method="native", tables=self.AWARD_TABLES,
                      displayed_filename="Intent_to_Award.pdf")
        sample = page_review.sample_pages(haystack + [needle], 20)
        self.assertIn(999, [p["page"] for p in sample])

    def test_the_review_then_reports_bidder_quality(self) -> None:
        pages = [page(page=i) for i in range(50)]
        pages.append(page(page=999, tables=self.AWARD_TABLES,
                          displayed_filename="Intent_to_Award.pdf"))
        out = page_review.review(pages, size=20)
        self.assertGreaterEqual(out["summary"]["pages_with_bidder_candidates"], 1)

    def test_method_coverage_survives_the_seeding(self) -> None:
        pages = ([page(page=i, method="native") for i in range(50)]
                 + [page(page=90, method="ocr"), page(page=91, method="hybrid")]
                 + [page(page=999, tables=self.AWARD_TABLES)])
        sample = page_review.sample_pages(pages, 20)
        self.assertTrue({"ocr", "hybrid"} <= {p["method"] for p in sample})

    def test_sampling_note_explains_the_seeding(self) -> None:
        out = page_review.review([page()], size=5)
        self.assertIn("seeded first", out["sampling"])
