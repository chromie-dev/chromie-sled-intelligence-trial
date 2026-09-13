"""Offline tests for the predecessor search. No network."""
import unittest

from sled_trial import lineage

OPP = {"business_unit": "2740", "event_id": "0000040075",
       "solicitation_number": "ISD26-4620", "department": "Department of Motor Vehicles",
       "category": "IT Goods", "title": "Darktrace Software and Support Renewal"}


def page(text, **over):
    base = {"business_unit": "2740", "event_id": "0000040075", "text": text,
            "displayed_filename": "doc.pdf", "page": 1, "sha256": "abc"}
    base.update(over)
    return base


class SelfIdentifierTests(unittest.TestCase):
    def test_own_solicitation_number_is_not_a_predecessor(self) -> None:
        # Real false positive from the first live run: the DMV package restates its own
        # RFQ number on the title page and it was reported as a predecessor.
        out = lineage.find_predecessors(
            OPP, events=[], awards=[],
            pages=[page("OF THE Title: ISD26-4620 MILITARY AND VETERANS CODE.")])
        self.assertEqual(out["predecessor_matches"], [])
        self.assertEqual(out["trace"]["result"], "no_predecessor_found")

    def test_own_event_id_is_not_a_predecessor(self) -> None:
        out = lineage.find_predecessors(
            OPP, events=[], awards=[], pages=[page("Event 0000040075 closes soon.")])
        self.assertEqual(out["predecessor_matches"], [])

    def test_identifier_embedded_in_the_title_is_excluded(self) -> None:
        opp = {**OPP, "title": "04A7615 - A&E On-call Roadway services"}
        out = lineage.find_predecessors(
            opp, events=[], awards=[], pages=[page("Refer to 04A7615 for scope.")])
        self.assertEqual(out["predecessor_matches"], [])

    def test_excluded_identifiers_are_reported_in_the_trace(self) -> None:
        out = lineage.find_predecessors(OPP, events=[], awards=[], pages=[page("x")])
        query = next(q for q in out["trace"]["queries"]
                     if q["surface"] == "caleprocure_event_package")
        self.assertIn("ISD26-4620", query["self_identifiers_excluded"])


class PredecessorDetectionTests(unittest.TestCase):
    def test_a_different_number_with_predecessor_language_scores_medium(self) -> None:
        out = lineage.find_predecessors(
            OPP, events=[], awards=[],
            pages=[page("This replaces the previous solicitation 26C650001.")])
        self.assertEqual(len(out["predecessor_matches"]), 1)
        match = out["predecessor_matches"][0]
        self.assertEqual(match["referenced_identifier"], "26C650001")
        self.assertEqual(match["confidence"], "medium")
        self.assertEqual(match["evidence_class"], "inferred")

    def test_a_bare_different_number_scores_low(self) -> None:
        out = lineage.find_predecessors(
            OPP, events=[], awards=[], pages=[page("See attachment 26C650001.")])
        self.assertEqual(out["predecessor_matches"][0]["confidence"], "low")

    def test_rfi_language_is_detected(self) -> None:
        out = lineage.find_predecessors(
            OPP, events=[], awards=[],
            pages=[page("Following the request for information 26C650001, this RFP issues.")])
        self.assertTrue(out["predecessor_matches"][0]["evidence"]["predecessor_language"])

    def test_evidence_carries_document_page_and_sentence(self) -> None:
        out = lineage.find_predecessors(
            OPP, events=[], awards=[],
            pages=[page("Supersedes prior event 26C650001.", displayed_filename="a.pdf")])
        ev = out["predecessor_matches"][0]["evidence"]
        self.assertEqual(ev["document"], "a.pdf")
        self.assertEqual(ev["page"], 1)
        self.assertIn("26C650001", ev["evidence_sentence"])

    def test_pages_from_other_events_are_ignored(self) -> None:
        out = lineage.find_predecessors(
            OPP, events=[], awards=[],
            pages=[page("prior solicitation 26C650001", event_id="SOMETHING_ELSE")])
        self.assertEqual(out["predecessor_matches"], [])


class NoMatchTraceTests(unittest.TestCase):
    def test_no_match_produces_a_completed_trace(self) -> None:
        out = lineage.find_predecessors(OPP, events=[], awards=[], pages=[])
        trace = out["trace"]
        self.assertEqual(trace["result"], "no_predecessor_found")
        self.assertTrue(trace["queries"])
        self.assertIn("does not establish", trace["no_match_meaning"])

    def test_unavailable_surfaces_are_named_with_reasons(self) -> None:
        trace = lineage.find_predecessors(OPP, events=[], awards=[], pages=[])["trace"]
        surfaces = {s["surface"]: s["reason"] for s in trace["surfaces_not_available"]}
        self.assertIn("caleprocure_response_bid_inquiry", surfaces)
        reason = surfaces["caleprocure_response_bid_inquiry"]
        # Tested 2026-09-10 with a supplier login: no respondent fields either way.
        self.assertIn("login", reason)
        self.assertIn("respondent", reason)
        self.assertNotIn("not attempted", reason)

    def test_lineage_links_are_left_null_not_guessed(self) -> None:
        links = lineage.find_predecessors(OPP, events=[], awards=[], pages=[])["lineage_links"]
        self.assertIsNone(links["predecessor_record_id"])
        self.assertIn("no verified deterministic link", links["basis"])


class RelatedAndIncumbentTests(unittest.TestCase):
    def test_similar_title_same_buyer_is_low_confidence_only(self) -> None:
        events = [{"business_unit": "2740", "event_id": "OTHER",
                   "title": "Darktrace Software and Support Renewal Phase 2"}]
        out = lineage.find_predecessors(OPP, events=events, awards=[], pages=[])
        related = out["related_records"]
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["confidence"], "low")
        self.assertIn("insufficient", related[0]["confidence_basis"])

    def test_a_different_buyer_is_not_related(self) -> None:
        events = [{"business_unit": "9999", "event_id": "OTHER",
                   "title": "Darktrace Software and Support Renewal"}]
        out = lineage.find_predecessors(OPP, events=events, awards=[], pages=[])
        self.assertEqual(out["related_records"], [])

    def test_incumbent_context_counts_matching_awards(self) -> None:
        awards = [{"department": "Department of Motor Vehicles", "category": "IT Goods",
                   "supplier_id": "V1", "supplier_name": "ACME", "start_date": "01/01/2026"},
                  {"department": "Elsewhere", "category": "IT Goods", "supplier_id": "V2"}]
        out = lineage.find_predecessors(OPP, events=[], awards=awards, pages=[])
        ctx = out["incumbent_context"]
        self.assertEqual(ctx["awards_same_buyer_and_category"], 1)
        self.assertIn("cannot mean winning this specific solicitation", ctx["note"])


if __name__ == "__main__":
    unittest.main()


class DateRangeTests(unittest.TestCase):
    def test_incumbent_date_range_orders_by_date_not_by_string(self) -> None:
        # Lexicographic order over MM/DD/YYYY puts 01/02/2027 before 12/31/2026 and
        # reports a window that never happened.
        awards = [{"department": OPP["department"], "category": OPP["category"],
                   "supplier_id": "V1", "start_date": "12/31/2026"},
                  {"department": OPP["department"], "category": OPP["category"],
                   "supplier_id": "V2", "start_date": "01/02/2027"}]
        out = lineage.find_predecessors(OPP, events=[], awards=awards, pages=[])
        query = next(q for q in out["trace"]["queries"]
                     if q["surface"] == "caleprocure_scprs")
        self.assertEqual(query["date_range_present"], "2026-12-31..2027-01-02")
