"""Offline tests for report generation."""
import json
import re
import pathlib
import tempfile
import unittest
from unittest import mock

from sled_trial import report


class GenerateTests(unittest.TestCase):
    def test_generates_without_any_artifacts(self) -> None:
        # A report must be producible before a full run; missing inputs read as
        # "not measured" rather than crashing or inventing figures.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report, "BUILD", pathlib.Path(tmp)):
                text = report.generate()
        self.assertIn("Trial Report", text)
        self.assertIn("Next three sources", text)

    def test_the_landscape_reflects_the_sources_actually_wired_in(self) -> None:
        # The bid-inquiry surface was tested with a login and exposes no respondents; the
        # browser-only PlanetBids portals are the largest bidder source. Prose written
        # before either finding must not survive in a generated report.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report, "BUILD", pathlib.Path(tmp)):
                text = report.generate()
        self.assertIn("PlanetBids", text)
        self.assertNotIn("out of bounds", text)
        self.assertNotIn("no browser, no API key", text)

    def test_non_competing_entities_are_excluded_from_the_landscape_table(self) -> None:
        # Listing a county among "most active suppliers" would contradict the rule that
        # excludes it from competitor ranking.
        profiles = [
            {"supplier_id": "0000004178", "canonical_name": "CALAVERAS COUNTY",
             "awards_observed": 99, "agency_count": 5, "certifications": []},
            {"supplier_id": "0000015031", "canonical_name": "AVIATE ENTERPRISES INC",
             "awards_observed": 7, "agency_count": 3, "certifications": ["DVBE"]},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "vendor_profiles.json").write_text(json.dumps(profiles))
            (root / "awards.jsonl").write_text(json.dumps(
                {"purchase_doc": "D1", "acq_method": "Formal - COMPETITIVE"}) + "\n")
            with mock.patch.object(report, "BUILD", root):
                text = report.generate()
        landscape = text.split("Most active")[1].split("## ")[0]
        self.assertIn("AVIATE ENTERPRISES INC", landscape)
        self.assertNotIn("| CALAVERAS COUNTY |", landscape)
        self.assertIn("excluded as non-competing", text)

    def test_proposed_contract_caveat_survives_into_the_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "supabase").mkdir()
            (root / "supabase" / "validation_report.json").write_text(json.dumps(
                {"tables": [{"table": "gov_competitors", "rows": 1, "valid": True}]}))
            with mock.patch.object(report, "BUILD", root):
                text = report.generate()
        self.assertIn("was not", text)
        # Whitespace-normalised: the report hard-wraps, and asserting on the literal
        # newline made this a test of where the line happened to break.
        flat = re.sub(r"\s+", " ", text)
        self.assertIn("not compatibility with Chromie's real schema", flat)

    def test_empty_prime_list_is_stated_not_padded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "prime_candidates.json").write_text(json.dumps({"prime_candidates": []}))
            with mock.patch.object(report, "BUILD", root):
                text = report.generate()
        self.assertIn("No vendor qualified", text)

    def test_write_creates_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report, "BUILD", pathlib.Path(tmp)):
                path = report.write(pathlib.Path(tmp) / "report.md")
            self.assertTrue(pathlib.Path(path).exists())



class GeneratedProseTests(unittest.TestCase):
    """Prose in a generated report must come from the run, not from a past one.

    Two lift figures were hardcoded into the caveat paragraph and outlived the corpus
    that produced them, so the report quoted 0.92x next to a table saying 1.333x.
    """

    def _report(self, precision, baseline):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            (out / "evaluation.json").write_text(json.dumps({
                "precision_at_3": precision, "precision_at_5": 0.05, "coverage": 0.1,
                "baseline_comparison": {
                    "best_baseline_precision_at_3": baseline,
                    "lift_over_best_baseline": precision / baseline}}))
            with mock.patch.object(report, "BUILD", out):
                return report.generate()

    def _report_with_corpus(self, median, span, rows, backfill):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            (out / "evaluation.json").write_text(json.dumps({
                "precision_at_3": 0.17, "precision_at_5": 0.12, "coverage": 0.28,
                "corpus": {"awards_per_vendor_median": median,
                           "observation_span_days_max": span},
                "baseline_comparison": {"history_rows": rows,
                                        "best_baseline_precision_at_3": 0.09,
                                        "lift_over_best_baseline": 1.8}}))
            (out / "awards_backfill_coverage.jsonl").write_text(
                "".join(json.dumps(b) + "\n" for b in backfill))
            with mock.patch.object(report, "BUILD", out):
                return report.generate()

    def test_history_depth_is_computed_from_the_corpus(self) -> None:
        # Said the cap left vendors "a handful of prior awards". On twelve months the
        # cap costs under a tenth of rows and the median vendor still holds one.
        text = self._report_with_corpus(1, 356, 250986, [
            {"measured_this_run": {"collected": 100, "reported": 110}},
            {"measured_this_run": {"collected": 900, "reported": 990}}])
        self.assertIn("356-day window of 250,986 awards", text)
        self.assertIn("median vendor", text)
        self.assertIn("holds 1;", text)
        self.assertIn("costs 9.1%", text)

    def test_the_old_cap_explanation_is_gone(self) -> None:
        text = self._report_with_corpus(1, 356, 250986, [])
        for stale in ("handful of prior awards", "Most days exceed the", "History depth is capped"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)

    def test_no_corpus_yet_still_renders_without_inventing_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(report, "BUILD", pathlib.Path(tmp)):
                text = report.generate()
        self.assertIn("Per-vendor history is thin", text)
        self.assertNotIn("-day window of", text)

    def test_the_caveat_states_the_gap_this_run_measured(self) -> None:
        text = self._report(0.0625, 0.0469)
        self.assertIn("0.0156", text)

    def test_no_lift_figure_from_an_earlier_run_survives(self) -> None:
        text = self._report(0.0625, 0.0469)
        for stale in ("0.92x", "1.20x", "seven-day", "six-day"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)

if __name__ == "__main__":
    unittest.main()


class TeamingRationaleTests(unittest.TestCase):
    def test_a_prime_without_a_teaming_rationale_is_labelled_not_padded(self) -> None:
        # Manufacturing a rationale would be worse than admitting there isn't one.
        prime = {"prime_candidates": [{
            "vendor_name": "STRATO COMMUNICATIONS INC", "prime_score": 8.5,
            "confidence": "high", "also_likely_competitor": False,
            "credibility_case": {"awards_at_or_above_value_floor": 161, "value_floor": 3390,
                                 "awards_with_this_agency": 4, "awards_in_this_category": 1,
                                 "largest_award": 106546388.0, "opportunity_value": 33900.0},
            "teaming_case": {"reasons": [], "sufficient": False},
            "disqualifiers": []}],
            "candidates_qualified": 1, "vendors_considered": 10,
            "qualification_rule": "test rule"}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "prime_candidates.json").write_text(json.dumps(prime))
            with mock.patch.object(report, "BUILD", root):
                text = report.generate()
        self.assertIn("No teaming rationale found", text)
        self.assertIn("competitor to watch rather than an outreach target", text)

    def test_a_prime_with_a_rationale_states_it(self) -> None:
        prime = {"prime_candidates": [{
            "vendor_name": "ALLEN ALARM SYSTEMS INC", "prime_score": 9.8,
            "confidence": "high", "also_likely_competitor": True,
            "credibility_case": {"awards_at_or_above_value_floor": 79, "value_floor": 3390,
                                 "awards_with_this_agency": 21, "awards_in_this_category": 146,
                                 "largest_award": 199146.0, "opportunity_value": 33900.0},
            "teaming_case": {"reasons": ["client covers IT Services"], "sufficient": True},
            "disqualifiers": []}],
            "candidates_qualified": 1, "vendors_considered": 10,
            "qualification_rule": "test rule"}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "prime_candidates.json").write_text(json.dumps(prime))
            with mock.patch.object(report, "BUILD", root):
                text = report.generate()
        self.assertIn("Worth approaching because: client covers IT Services", text)
        self.assertNotIn("No teaming rationale found", text)


class PrimeDenominatorTests(unittest.TestCase):
    def test_the_eligible_denominator_is_quoted_not_the_whole_corpus(self) -> None:
        # "57 of 579" implies a 10% pass rate when only 75 vendors could ever qualify and
        # the real figure is 76%. Understating in our own favour is still misreporting.
        prime = {
            "prime_candidates": [], "candidates_qualified": 57, "vendors_considered": 579,
            "qualification_rule": "test rule",
            "corpus_provenance": {"eligible_vendor_count": 75,
                                  "why_this_corpus": "because reasons",
                                  "prior_invalid_run": "an earlier run reported 19"},
            "qualification_note": "qualification is a weak filter here",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "prime_candidates.json").write_text(json.dumps(prime))
            with mock.patch.object(report, "BUILD", root):
                text = report.generate()
        self.assertIn("57 of 75", text)
        self.assertIn("76.0%", text)
        self.assertIn("could\nnever qualify", text)

    def test_the_superseded_result_is_disclosed(self) -> None:
        prime = {"prime_candidates": [], "candidates_qualified": 1,
                 "vendors_considered": 10, "qualification_rule": "r",
                 "corpus_provenance": {"eligible_vendor_count": 2,
                                       "why_this_corpus": "w",
                                       "prior_invalid_run": "19 were artifacts"}}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "prime_candidates.json").write_text(json.dumps(prime))
            with mock.patch.object(report, "BUILD", root):
                text = report.generate()
        self.assertIn("Superseded result", text)
        self.assertIn("19 were artifacts", text)


class ReviewQueueTests(unittest.TestCase):
    def test_review_queue_count_reads_the_file_the_pipeline_writes(self) -> None:
        # The report read review_queue.jsonl while analyze wrote review_queue.json, so a
        # queue holding real identity conflicts was reported as zero items.
        queue = [{"type": "possible_duplicate_vendor_identity"},
                 {"type": "low_confidence_prediction"}]
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "review_queue.json").write_text(json.dumps(queue))
            with mock.patch.object(report, "BUILD", pathlib.Path(tmp)):
                text = report.generate()
        self.assertIn("| Review-queue items | 2 |", text)
