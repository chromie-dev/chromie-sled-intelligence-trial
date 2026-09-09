"""Offline tests for CLI argument handling and participant assembly. No network."""

import pathlib
import unittest

from sled_trial import assemble, cli


class EventPairTests(unittest.TestCase):
    def test_parses_pairs(self) -> None:
        self.assertEqual(cli._event_pairs(["2660/04A7615"]), [("2660", "04A7615")])

    def test_dedupes_while_preserving_order(self) -> None:
        got = cli._event_pairs(["2660/04A7615", "2740/0000040075", "2660/04A7615"])
        self.assertEqual(got, [("2660", "04A7615"), ("2740", "0000040075")])

    def test_same_event_id_at_two_agencies_is_two_events(self) -> None:
        # event_id is not globally unique; the pair is the identity.
        got = cli._event_pairs(["2660/0000040001", "2740/0000040001"])
        self.assertEqual(len(got), 2)

    def test_malformed_values_are_rejected(self) -> None:
        for bad in ["2660", "/04A7615", "2660/", ""]:
            with self.subTest(bad=bad):
                with self.assertRaises(Exception):
                    cli._event_pairs([bad])


class ParticipantAssemblyTests(unittest.TestCase):
    def _page(self, tables):
        return {
            "tables": tables, "business_unit": "2740", "event_id": "0000040075",
            "displayed_filename": "Intent_to_Award.pdf", "document_ref": "ref",
            "sha256": "abc", "page": 1, "method": "native",
        }

    def test_candidate_carries_its_evidence(self) -> None:
        page = self._page([[["Company Name", "Bid Amount"],
                            ["AVIATE ENTERPRISES, INC.", "$437,862.48"]]])
        got = assemble._participants([page])
        self.assertEqual(len(got), 1)
        c = got[0]
        self.assertEqual(c["vendor_name_raw"], "AVIATE ENTERPRISES, INC.")
        self.assertEqual(c["event_id"], "0000040075")
        self.assertEqual(c["page"], 1)
        self.assertEqual(c["sha256"], "abc")
        self.assertEqual(c["evidence_class"], "observed")

    def test_identity_is_flagged_unresolved(self) -> None:
        # An extracted name is not a resolved vendor until it matches an SCPRS supplier_id.
        page = self._page([[["Vendor", "Bid Amount"], ["ACME", "$1.00"]]])
        self.assertIn("unresolved", assemble._participants([page])[0]["confidence_note"])

    def test_pages_without_tables_yield_nothing(self) -> None:
        self.assertEqual(assemble._participants([self._page([])]), [])
        self.assertEqual(assemble._participants([{"tables": None}]), [])


class ParserTests(unittest.TestCase):
    def test_subcommand_is_required(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])

    def test_documents_requires_an_event(self) -> None:
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["documents"])

    def test_analyze_flags(self) -> None:
        args = cli.build_parser().parse_args(
            ["analyze", "--opportunity", "x.json", "--download-documents"])
        self.assertTrue(args.download_documents)
        self.assertEqual(args.output, "build")

    def test_delay_is_configurable_and_defaults_conservative(self) -> None:
        self.assertEqual(cli.build_parser().parse_args(["events"]).delay, 1.5)
        self.assertEqual(
            cli.build_parser().parse_args(["events", "--delay", "3"]).delay, 3.0)

    def test_shared_flags_are_accepted_after_the_subcommand(self) -> None:
        # The README deliverable command writes --output after `analyze`; that ordering is
        # the contract, so it must parse.
        args = cli.build_parser().parse_args([
            "analyze", "--opportunity", "data/examples/active_opportunity.json",
            "--download-documents", "--output", "build"])
        self.assertEqual(args.output, "build")
        self.assertTrue(args.download_documents)

    def test_readme_command_parses_verbatim(self) -> None:
        argv = ["analyze", "--opportunity", "data/examples/active_opportunity.json",
                "--download-documents", "--output", "build"]
        args = cli.build_parser().parse_args(argv)
        self.assertEqual(args.command, "analyze")
        self.assertEqual(args.opportunity, "data/examples/active_opportunity.json")

    def test_missing_opportunity_file_returns_nonzero(self) -> None:
        args = cli.build_parser().parse_args(
            ["analyze", "--opportunity", "/nonexistent/nope.json"])
        self.assertEqual(cli.main(
            ["analyze", "--opportunity", "/nonexistent/nope.json"]), 1)



class CorpusMergeTests(unittest.TestCase):
    """Analysing one opportunity must not shrink a multi-event evaluation corpus."""

    def test_fresh_rows_are_added_to_existing_ones(self) -> None:
        existing = [{"document_ref": "a", "sha256": "1"}]
        fresh = [{"document_ref": "b", "sha256": "2"}]
        out = assemble._merge_rows(existing, fresh,
                              key=lambda r: (r["document_ref"], r["sha256"]))
        self.assertEqual(len(out), 2)

    def test_a_fresh_row_replaces_the_same_key(self) -> None:
        existing = [{"document_ref": "a", "sha256": "1", "v": "old"}]
        fresh = [{"document_ref": "a", "sha256": "1", "v": "new"}]
        out = assemble._merge_rows(existing, fresh,
                              key=lambda r: (r["document_ref"], r["sha256"]))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["v"], "new")

    def test_a_changed_hash_is_kept_as_a_separate_row(self) -> None:
        # An agency replacing an attachment under the same filename must not erase the
        # earlier version from the audit trail.
        existing = [{"document_ref": "a", "sha256": "1"}]
        fresh = [{"document_ref": "a", "sha256": "2"}]
        out = assemble._merge_rows(existing, fresh,
                              key=lambda r: (r["document_ref"], r["sha256"]))
        self.assertEqual(len(out), 2)

    def test_reading_a_missing_file_is_empty_not_an_error(self) -> None:
        self.assertEqual(assemble._read_jsonl(pathlib.Path("/nonexistent/x.jsonl")), [])


class EnrichmentWiringTests(unittest.TestCase):
    """Every declared profile enrichment must actually be applied by `analyze`.

    `analyze` rebuilds profiles from award records each run, destroying anything attached
    afterwards. That was fixed for the document manifest, the page corpus and the spending
    index, then reintroduced a fourth time by adding the location enrichment without wiring
    it in. These tests make forgetting one a test failure rather than silent data loss.
    """

    def test_every_enrichment_names_a_real_attach_function(self) -> None:
        from sled_trial import vendors
        for filename, _key, attach_name in cli.ENRICHMENTS:
            with self.subTest(enrichment=attach_name):
                self.assertTrue(hasattr(vendors, attach_name),
                                f"{filename} names {attach_name}, which does not exist")
                self.assertTrue(callable(getattr(vendors, attach_name)))

    def test_every_vendors_attach_function_is_declared(self) -> None:
        # The direction that actually caused the bug: a new attach_* function existed but
        # nothing wired it into analyze.
        from sled_trial import vendors
        declared = {name for _f, _k, name in cli.ENRICHMENTS}
        available = {n for n in dir(vendors)
                     if n.startswith("attach_") and callable(getattr(vendors, n))}
        self.assertEqual(available, declared,
                         f"undeclared enrichment(s): {sorted(available - declared)}")

    def test_each_enrichment_has_a_distinct_cache_file(self) -> None:
        files = [f for f, _k, _n in cli.ENRICHMENTS]
        self.assertEqual(len(files), len(set(files)))

    def test_the_spending_cache_reads_from_its_index_key(self) -> None:
        # The spending cache wraps its payload; the location cache does not. Getting this
        # wrong attaches an empty dict and reports zero matches.
        by_file = {f: k for f, k, _n in cli.ENRICHMENTS}
        self.assertEqual(by_file["spending_index.json"], "index")
        self.assertIsNone(by_file["supplier_locations.json"])

if __name__ == "__main__":
    unittest.main()
