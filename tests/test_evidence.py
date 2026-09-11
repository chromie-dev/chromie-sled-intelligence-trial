"""Tests for the evidence audit.

The audit answers a question schema validation cannot: if a reviewer follows a citation,
do they arrive anywhere? It exists because a dangling reference is invisible in the row
that carries it -- the row is well formed, the id looks like an id, and nothing complains
until someone tries to resolve it.
"""
import unittest

from sled_trial import evidence


def tables(**kwargs):
    return {k: v for k, v in kwargs.items()}


RECORD = {"id": "rec-1", "source_key": "caltrans_bid_results"}
COMPETITOR = {"id": "comp-1", "legal_name": "WARE DISPOSAL INC"}
DOCUMENT = {"id": "doc-1", "record_id": "rec-1"}
PAGE = {"id": "page-1", "document_id": "doc-1", "page": 3}
SOURCE = {"id": "src-1", "source_key": "caltrans_bid_results"}


def participant(**over):
    row = {"id": "part-1", "record_id": "rec-1", "competitor_id": "comp-1",
           "role": "known_bidder",
           "evidence": {"source_key": "caltrans_bid_results",
                        "evidence_row": "Ware Disposal Inc. | $436,020.00"}}
    row.update(over)
    return row


class ForeignKeyTests(unittest.TestCase):
    def test_a_sound_export_has_no_dangling_references(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[COMPETITOR],
            gov_procurement_participants=[participant()],
            gov_procurement_documents=[DOCUMENT], document_content_handoff=[PAGE]))
        self.assertTrue(report["sound"])
        self.assertEqual(report["defect_count"], 0)

    def test_a_participant_pointing_at_a_missing_competitor_is_caught(self) -> None:
        # The real defect this found: every observed bidder that could not be matched to
        # a state supplier id referenced a competitor row nothing emitted. 2,703 of them.
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[],
            gov_procurement_participants=[participant()]))
        self.assertFalse(report["sound"])
        self.assertEqual(report["dangling_references"], 1)
        self.assertEqual(report["defects"][0]["field"], "competitor_id")
        self.assertEqual(report["defects"][0]["expected_in"], "gov_competitors")

    def test_a_participant_pointing_at_a_missing_record_is_caught(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_records=[], gov_competitors=[COMPETITOR],
            gov_procurement_participants=[participant()]))
        self.assertEqual(report["dangling_references"], 1)

    def test_a_document_pointing_at_a_missing_record_is_caught(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_records=[], gov_procurement_documents=[DOCUMENT]))
        self.assertEqual(report["dangling_references"], 1)

    def test_extracted_text_pointing_at_a_missing_document_is_caught(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_documents=[], document_content_handoff=[PAGE]))
        self.assertEqual(report["dangling_references"], 1)

    def test_a_null_reference_is_not_treated_as_dangling(self) -> None:
        # Absent and wrong are different. A participant with no competitor yet is
        # unresolved, not broken.
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[],
            gov_procurement_participants=[participant(competitor_id=None)]))
        self.assertTrue(report["sound"])


class PageCitationTests(unittest.TestCase):
    """Citing page 12 of an eight-page document lands the reader nowhere."""

    def _cite(self, page):
        return participant(evidence={"source_key": "caleprocure_event_package",
                                     "document_id": "doc-1", "page": page})

    def test_a_page_that_exists_is_accepted(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[COMPETITOR],
            gov_procurement_documents=[DOCUMENT], document_content_handoff=[PAGE],
            gov_procurement_participants=[self._cite(3)]))
        self.assertTrue(report["sound"])

    def test_a_page_past_the_end_of_the_document_is_caught(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[COMPETITOR],
            gov_procurement_documents=[DOCUMENT], document_content_handoff=[PAGE],
            gov_procurement_participants=[self._cite(12)]))
        self.assertFalse(report["sound"])
        self.assertEqual(report["page_citations_out_of_range"], 1)

    def test_citing_a_document_with_no_extracted_text_is_caught(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[COMPETITOR],
            gov_procurement_documents=[DOCUMENT], document_content_handoff=[],
            gov_procurement_participants=[self._cite(1)]))
        self.assertEqual(report["dangling_references"], 1)


class CitationClassTests(unittest.TestCase):
    """Cited, uncited and externally-cited are three different states."""

    def test_a_row_with_no_evidence_is_uncited(self) -> None:
        self.assertEqual(evidence.classify_citation(None), "uncited")
        self.assertEqual(evidence.classify_citation({}), "uncited")

    def test_a_source_key_alone_is_not_a_citation(self) -> None:
        # It names the surface, not the record on it, so it cannot be followed.
        self.assertEqual(
            evidence.classify_citation({"source_key": "caltrans_bid_results"}),
            "uncited")

    def test_a_url_alone_is_external_and_unverified(self) -> None:
        # Nothing here fetches, so claiming it is checked would be a lie a reviewer
        # cannot see through.
        self.assertEqual(
            evidence.classify_citation({"url": "https://example.gov/x"}),
            "external_only")

    def test_a_document_and_page_is_a_real_citation(self) -> None:
        self.assertEqual(
            evidence.classify_citation({"document_id": "doc-1", "page": 2}), "cited")

    def test_a_purchase_document_is_a_real_citation(self) -> None:
        self.assertEqual(
            evidence.classify_citation({"purchase_doc": "PO-261012700356"}), "cited")

    def test_coverage_is_reported_per_role(self) -> None:
        # Roles cite differently and legitimately: an awardee cites a purchase document,
        # a bidder cites the page it was read from.
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[COMPETITOR],
            gov_procurement_participants=[
                participant(),
                participant(id="p2", role="awardee",
                            evidence={"purchase_doc": "PO-1"}),
                participant(id="p3", role="known_bidder", evidence={}),
            ]))
        self.assertEqual(report["citation_coverage"]["awardee"], {"cited": 1})
        self.assertEqual(report["uncited_claims"], 1)


class SourceRegistryTests(unittest.TestCase):
    def test_a_source_key_not_in_the_registry_is_reported(self) -> None:
        # A harvester emitting rows under an undocumented name is how an unrecorded
        # source reaches a reviewer.
        report = evidence.audit(tables(
            gov_procurement_sources=[SOURCE],
            gov_procurement_records=[{"id": "r", "source_key": "mystery_portal"}]))
        self.assertEqual(report["unregistered_sources"][0]["source_key"],
                         "mystery_portal")

    def test_a_known_source_key_is_accepted(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_sources=[SOURCE], gov_procurement_records=[RECORD]))
        self.assertEqual(report["unregistered_sources"], [])

    def test_no_registry_means_no_claim_either_way(self) -> None:
        # Without a registry to compare against, silence beats inventing a verdict.
        report = evidence.audit(tables(
            gov_procurement_records=[{"id": "r", "source_key": "anything"}]))
        self.assertEqual(report["unregistered_sources"], [])


class HonestyTests(unittest.TestCase):
    def test_sound_does_not_claim_external_citations_were_followed(self) -> None:
        report = evidence.audit(tables(
            gov_procurement_records=[RECORD], gov_competitors=[COMPETITOR],
            gov_procurement_participants=[participant(
                evidence={"url": "https://example.gov/never-fetched"})]))
        self.assertTrue(report["sound"])
        self.assertIn("not followed", report["note"])


if __name__ == "__main__":
    unittest.main()
