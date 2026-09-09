"""Offline tests for CLI argument handling and participant assembly. No network."""

import json
import pathlib
import tempfile
import unittest

from sled_trial import assemble, cli, sources


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

class CaltransBidderWiringTests(unittest.TestCase):
    """Harvested bidder rows must reach the observed-participant corpus."""

    def test_cached_caltrans_rows_are_merged_with_document_candidates(self) -> None:
        # Without this the harvest writes a file nobody reads, which is exactly how the
        # prime-enrichment corpus ended up sitting unused in build/.
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            (outdir / "caltrans_bidders.jsonl").write_text(json.dumps({
                "business_unit": "2660", "event_id": "08A3933",
                "vendor_name_raw": "Apex Waste Systems Inc.", "rank": 2}) + "\n")
            doc_candidate = {"business_unit": "2740", "event_id": "0000040075",
                             "vendor_name_raw": "AVIATE ENTERPRISES, INC."}
            merged = assemble.observed_participants([doc_candidate], outdir)
        self.assertEqual(len(merged), 2)
        self.assertIn("Apex Waste Systems Inc.",
                      [r["vendor_name_raw"] for r in merged])

    def test_sf_tabulation_rows_are_merged_too(self) -> None:
        # A second bidder source must not need a third merge path, or the next one gets
        # written and forgotten the way awards_prime_enriched.jsonl was.
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            (outdir / "caltrans_bidders.jsonl").write_text(json.dumps({
                "business_unit": "2660", "event_id": "08A3933",
                "vendor_name_raw": "Apex Waste Systems Inc."}) + "\n")
            (outdir / "sf_bidders.jsonl").write_text(json.dumps({
                "business_unit": "SFPW", "event_id": "0000007165",
                "vendor_name_raw": "Ronan Construction"}) + "\n")
            merged = assemble.observed_participants([], outdir)
        self.assertEqual(sorted(r["vendor_name_raw"] for r in merged),
                         ["Apex Waste Systems Inc.", "Ronan Construction"])

    def test_absent_cache_leaves_document_candidates_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc_candidate = {"business_unit": "2740", "event_id": "0000040075",
                             "vendor_name_raw": "AVIATE ENTERPRISES, INC."}
            merged = assemble.observed_participants([doc_candidate], pathlib.Path(tmp))
        self.assertEqual(merged, [doc_candidate])

    def test_the_same_bidder_is_not_counted_twice_across_reruns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            row = {"business_unit": "2660", "event_id": "08A3933",
                   "vendor_name_raw": "Apex Waste Systems Inc.", "rank": 2}
            (outdir / "caltrans_bidders.jsonl").write_text(
                json.dumps(row) + "\n" + json.dumps(row) + "\n")
            merged = assemble.observed_participants([], outdir)
        self.assertEqual(len(merged), 1)


class ReviewQueueShapeTests(unittest.TestCase):
    def test_a_bid_results_candidate_does_not_need_a_filename(self) -> None:
        # cmd_analyze indexed k["displayed_filename"] on every observed participant and
        # crashed the whole run when a Caltrans row, which cites a URL, reached it.
        rows = assemble.unresolved_identity_review([
            {"vendor_name_raw": "AVIATE ENTERPRISES, INC.",
             "displayed_filename": "Intent_to_Award.pdf", "page": 1},
            {"vendor_name_raw": "Apex Waste Systems Inc.",
             "source_key": "caltrans_bid_results",
             "evidence_url": "https://dot.ca.gov/x"},
        ])
        self.assertEqual([r["citation"] for r in rows],
                         ["Intent_to_Award.pdf", "https://dot.ca.gov/x"])
        self.assertEqual(rows[1]["source_key"], "caltrans_bid_results")


class ProfileCorpusTests(unittest.TestCase):
    """Profiles may see the bidder backfill. Prediction must not."""

    def _award(self, doc, sid="V1"):
        return {"purchase_doc": doc, "supplier_id": sid, "supplier_name": "ACME",
                "start_date": "09/01/2026"}

    def test_the_bidder_backfill_is_folded_into_the_profile_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            (outdir / "awards_bidder_enriched.jsonl").write_text(
                json.dumps(self._award("D2", "V2")) + "\n")
            corpus = assemble.profile_corpus([self._award("D1")], outdir)
        self.assertEqual(len(corpus), 2)

    def test_rows_already_in_the_sweep_are_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            (outdir / "awards_bidder_enriched.jsonl").write_text(
                json.dumps(self._award("D1")) + "\n")
            corpus = assemble.profile_corpus([self._award("D1")], outdir)
        self.assertEqual(len(corpus), 1)

    def test_an_absent_backfill_leaves_the_sweep_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            corpus = assemble.profile_corpus([self._award("D1")], pathlib.Path(tmp))
        self.assertEqual(len(corpus), 1)

    def test_analyze_ranks_on_the_sweep_not_on_the_profile_corpus(self) -> None:
        # Deepening a subset of vendors reorders a ranking -- measured, and it is why the
        # 0.17 figure was discarded. Profiles are descriptive and may use the wider
        # corpus; prediction may not, and this pins the two apart.
        source = pathlib.Path("src/sled_trial/cli.py").read_text()
        analyze = source[source.index("def cmd_analyze"):]
        rank_call = analyze[analyze.index("predict.rank_candidates("):]
        self.assertTrue(rank_call.startswith("predict.rank_candidates(awards,"),
                        f"prediction must rank on the sweep: {rank_call[:80]}")


class AwardSweepCoverageTests(unittest.TestCase):
    """A slice that hit the 200-row cap lost rows. Silence there is data loss."""

    def test_truncated_slices_are_counted_and_named(self) -> None:
        results = [
            {"slice": {"from": "09/01/2026", "to": "09/01/2026"}, "rows": [1] * 200,
             "truncated": True, "total_reported": 431},
            {"slice": {"from": "09/02/2026", "to": "09/02/2026"}, "rows": [1] * 12,
             "truncated": False, "total_reported": 12},
        ]
        out = assemble.award_sweep_coverage(results)
        self.assertEqual(out["slices"], 2)
        self.assertEqual(out["slices_truncated"], 1)
        self.assertEqual(out["rows_collected"], 212)
        self.assertEqual(out["rows_reported_by_portal"], 443)
        self.assertEqual(out["truncated_slices"][0]["from"], "09/01/2026")

    def test_a_complete_sweep_reports_no_shortfall(self) -> None:
        results = [{"slice": {"from": "09/02/2026", "to": "09/02/2026"}, "rows": [1] * 12,
                    "truncated": False, "total_reported": 12}]
        out = assemble.award_sweep_coverage(results)
        self.assertEqual(out["slices_truncated"], 0)
        self.assertTrue(out["complete"])

    def test_an_incomplete_sweep_says_so(self) -> None:
        results = [{"slice": {"from": "09/01/2026", "to": "09/01/2026"}, "rows": [1] * 200,
                    "truncated": True, "total_reported": 431}]
        out = assemble.award_sweep_coverage(results)
        self.assertFalse(out["complete"])
        self.assertIn("cap", out["note"].lower())


class AwardWindowTests(unittest.TestCase):
    def test_the_default_window_is_derived_from_the_cutoff_not_hardcoded(self) -> None:
        # A hardcoded start date meant the README command swept three days while the
        # shipped corpus came from seven, so the deliverable could not be reproduced by
        # the command the brief tells a reviewer to run.
        self.assertEqual(assemble.default_awards_from("09/03/2026"), "08/27/2026")

    def test_it_handles_a_month_boundary(self) -> None:
        self.assertEqual(assemble.default_awards_from("03/02/2026"), "02/23/2026")


class BidHistoryEnrichmentTests(unittest.TestCase):
    def test_win_rates_see_every_bidder_source_not_just_the_first(self) -> None:
        # Declaring one cache filename meant a second jurisdiction's bidders never reached
        # the win-rate join, silently.
        with tempfile.TemporaryDirectory() as tmp:
            outdir = pathlib.Path(tmp)
            (outdir / "caltrans_bidders.jsonl").write_text(json.dumps(
                {"vendor_name_raw": "A", "event_id": "1", "rank": 1}) + "\n")
            (outdir / "sf_bidders.jsonl").write_text(json.dumps(
                {"vendor_name_raw": "B", "event_id": "2", "rank": 1}) + "\n")
            payload = assemble.enrichment_payload(outdir, assemble.BIDDER_ROWS, None)
        self.assertEqual(sorted(r["vendor_name_raw"] for r in payload), ["A", "B"])

    def test_a_missing_cache_reads_as_absent_not_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = assemble.enrichment_payload(pathlib.Path(tmp), "spending_index.json",
                                                  "index")
        self.assertIsNone(payload)


class BidderSourceRegistryTests(unittest.TestCase):
    """Adding a jurisdiction should mean adding a registry row, not editing four files."""

    def test_every_declared_source_has_a_distinct_cache_and_key(self) -> None:
        keys = [s.key for s in sources.BIDDER_SOURCES]
        caches = [s.cache for s in sources.BIDDER_SOURCES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(caches), len(set(caches)))

    def test_the_merge_reads_every_declared_cache(self) -> None:
        # Not a hardcoded tuple of filenames: a source declared but unread is how the
        # prime-enrichment corpus sat in build/ unused.
        self.assertEqual(sorted(assemble.bidder_caches()),
                         sorted(s.cache for s in sources.BIDDER_SOURCES))

    def test_a_city_source_keeps_its_own_solicitation_registry(self) -> None:
        sf = sources.BY_KEY["sfpublicworks_bid_tabulation"]
        caltrans = sources.BY_KEY["caltrans_bid_results"]
        self.assertEqual(sf.record_source, "sfpublicworks_bid_tabulation")
        self.assertEqual(caltrans.record_source, "caleprocure_event_list")


if __name__ == "__main__":
    unittest.main()
