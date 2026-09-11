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


class TargetStillActiveTests(unittest.TestCase):
    """The feed is active-only, so an absent target is a fact worth stating."""

    OPP = {"business_unit": "2740", "event_id": "0000040075"}

    def test_a_listed_target_is_reported_active(self) -> None:
        events = [{"business_unit": "2740", "event_id": "0000040075"}]
        state = assemble.target_listing_state(self.OPP, events)
        self.assertTrue(state["listed_in_active_feed"])

    def test_an_absent_target_is_flagged_with_what_it_does_and_does_not_mean(self) -> None:
        # Cal eProcure drops an event at close, so "not listed" means closed or withdrawn,
        # not that the documents are gone. Zero documents afterwards must not read as
        # "this solicitation had no attachments".
        state = assemble.target_listing_state(self.OPP, [{"business_unit": "2740",
                                                          "event_id": "0000040001"}])
        self.assertFalse(state["listed_in_active_feed"])
        self.assertIn("no longer listed", state["note"].lower())
        self.assertIn("documents may still", state["note"].lower())

    def test_an_empty_feed_is_unknown_rather_than_absent(self) -> None:
        # A failed feed fetch is not evidence the event closed.
        state = assemble.target_listing_state(self.OPP, [])
        self.assertIsNone(state["listed_in_active_feed"])


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


class ObservedOnThisEventTests(unittest.TestCase):
    """Only bidders on the target solicitation count as already observed on it."""

    OPP = {"business_unit": "2740", "event_id": "0000040075"}

    def test_a_bidder_from_another_solicitation_is_not_excluded(self) -> None:
        # `known` now holds every harvested bidder from every event. Treating all of them
        # as observed here drops legitimate candidates from this opportunity's ranking.
        known = [{"business_unit": "2660", "event_id": "08A3933",
                  "vendor_name_raw": "Apex Waste Systems Inc.", "supplier_id": "V1"}]
        profiles = [{"supplier_id": "V1", "canonical_name": "APEX WASTE SYSTEMS INC"}]
        self.assertEqual(assemble.observed_vendor_ids(self.OPP, known, profiles), set())

    def test_a_bidder_on_this_event_is_excluded(self) -> None:
        known = [{"business_unit": "2740", "event_id": "0000040075",
                  "vendor_name_raw": "AVIATE ENTERPRISES, INC.", "supplier_id": "V2"}]
        profiles = [{"supplier_id": "V2", "canonical_name": "AVIATE ENTERPRISES INC"}]
        self.assertEqual(assemble.observed_vendor_ids(self.OPP, known, profiles), {"V2"})

    def test_a_resolved_id_is_used_directly(self) -> None:
        known = [{"business_unit": "2740", "event_id": "0000040075",
                  "vendor_name_raw": "spelled differently", "supplier_id": "V3"}]
        profiles = [{"supplier_id": "V3", "canonical_name": "SOMETHING ELSE"}]
        self.assertEqual(assemble.observed_vendor_ids(self.OPP, known, profiles), {"V3"})

    def test_an_unresolved_name_matches_on_normalised_equality_not_substring(self) -> None:
        # "ACME" inside "ACME WIDGETS OF NEVADA" is not the same company.
        known = [{"business_unit": "2740", "event_id": "0000040075",
                  "vendor_name_raw": "ACME"}]
        profiles = [{"supplier_id": "V4", "canonical_name": "ACME WIDGETS OF NEVADA"},
                    {"supplier_id": "V5", "canonical_name": "Acme, Inc."}]
        self.assertEqual(assemble.observed_vendor_ids(self.OPP, known, profiles), {"V5"})


class ReviewQueueResolutionTests(unittest.TestCase):
    def test_a_resolved_participant_is_not_queued_as_unresolved(self) -> None:
        rows = assemble.unresolved_identity_review([
            {"vendor_name_raw": "A", "supplier_id": "0000011589",
             "identity_confidence": "medium"},
            {"vendor_name_raw": "B"},
        ])
        self.assertEqual([r["vendor_name_raw"] for r in rows], ["B"])

    def test_an_ambiguous_participant_is_still_queued(self) -> None:
        rows = assemble.unresolved_identity_review([
            {"vendor_name_raw": "C", "identity_confidence": "ambiguous",
             "candidate_supplier_ids": ["1", "2"]}])
        self.assertEqual(len(rows), 1)


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

class PlanetBidsCoverageTests(unittest.TestCase):
    def test_a_later_agency_run_does_not_drop_earlier_portals(self) -> None:
        # The cache-wipe shape again, this time in the file that proves coverage: a
        # --agency run replaced the whole report with the one portal it touched.
        import argparse
        from unittest import mock

        from sled_trial.net import browser as browser_mod
        from sled_trial.sources.ca import planetbids as pb

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            (out / "planetbids_coverage.json").write_text(json.dumps({"agencies": [
                {"company_id": "14424", "bids_collected": 1025, "complete": True}]}))
            harvest = lambda fetch, cid, **kw: {
                "bids": [], "candidates": [], "declared_interest": [], "documents": [],
                "company_id": cid, "bids_collected": 463, "complete": True}
            with mock.patch.object(cli, "_session", lambda a: object()), \
                    mock.patch.object(pb, "harvest_agency", harvest), \
                    mock.patch.object(browser_mod, "PortalJsonReader", _StubReader):
                cli.cmd_planetbids(argparse.Namespace(
                    output=tmp, delay=0, browser_headers=False, agency=["39497"],
                    max_bids=1, local_browser=False, documents=False))
            agencies = json.loads(
                (out / "planetbids_coverage.json").read_text())["agencies"]
        ids = {str(a["company_id"]) for a in agencies}
        self.assertEqual(ids, {"14424", "39497"},
                         "a later run dropped the portals an earlier one measured")


class _StubReader:
    """Stands in for the hosted browser. Records what it was constructed with."""

    last_kwargs: dict = {}

    def __init__(self, entry, **kwargs):
        type(self).last_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_json(self, url):
        return {}


class SavedContextTests(unittest.TestCase):
    def test_planetbids_reuses_the_context_auth_saved(self) -> None:
        # `auth` stores a context id and tells the operator later runs reuse it. No
        # harvest read the store, so every run opened a fresh anonymous browser.
        import argparse
        from unittest import mock

        from sled_trial.net import browser as browser_mod
        from sled_trial.sources.ca import planetbids as pb

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            (out / "contexts.json").write_text(json.dumps({"planetbids": "ctx-abc123"}))
            harvest = lambda fetch, cid, **kw: {
                "bids": [], "candidates": [], "declared_interest": [], "documents": [],
                "company_id": cid, "bids_collected": 0, "complete": True}
            with mock.patch.object(cli, "_session", lambda a: object()), \
                    mock.patch.object(pb, "harvest_agency", harvest), \
                    mock.patch.object(browser_mod, "PortalJsonReader", _StubReader):
                cli.cmd_planetbids(argparse.Namespace(
                    output=tmp, delay=0, browser_headers=False, agency=["14424"],
                    max_bids=1, local_browser=False, documents=False))
        self.assertEqual(_StubReader.last_kwargs.get("context_id"), "ctx-abc123")


class MonthWindowTests(unittest.TestCase):
    """A backfill is walked in calendar months so a stopped run is still describable."""

    def test_a_year_splits_into_calendar_months_newest_first(self) -> None:
        # Newest first because recency dominates the features: stop early and the
        # months you kept are the ones worth having.
        w = cli.month_windows("09/11/2025", "09/10/2026")
        self.assertEqual(w[0], ("09/01/2026", "09/10/2026"))
        self.assertEqual(w[-1], ("09/11/2025", "09/30/2025"))
        self.assertEqual(len(w), 13)

    def test_windows_are_contiguous_and_never_overlap(self) -> None:
        import datetime as dt
        w = list(reversed(cli.month_windows("01/15/2026", "05/03/2026")))
        for (_, end), (nxt, _) in zip(w, w[1:]):
            self.assertEqual(
                dt.datetime.strptime(nxt, "%m/%d/%Y").date()
                - dt.datetime.strptime(end, "%m/%d/%Y").date(),
                dt.timedelta(days=1), f"gap or overlap at {end} -> {nxt}")

    def test_the_range_ends_are_respected_not_rounded_out(self) -> None:
        # Rounding to whole months would collect days the caller did not ask for.
        w = cli.month_windows("02/10/2026", "02/20/2026")
        self.assertEqual(w, [("02/10/2026", "02/20/2026")])

    def test_february_in_a_leap_year(self) -> None:
        w = cli.month_windows("02/01/2024", "03/01/2024")
        self.assertEqual(w[-1], ("02/01/2024", "02/29/2024"))

    def test_a_backwards_range_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            cli.month_windows("09/10/2026", "09/11/2025")

    def test_a_single_day_is_one_window(self) -> None:
        self.assertEqual(cli.month_windows("09/03/2026", "09/03/2026"),
                         [("09/03/2026", "09/03/2026")])


class BackfillAwardsTests(unittest.TestCase):
    """One month failing must not cost the months after it."""

    def _args(self, tmp, **over):
        import argparse
        base = dict(output=tmp, delay=0, browser_headers=False,
                    since="07/01/2026", until="09/30/2026", months=0)
        base.update(over)
        return argparse.Namespace(**base)

    def test_every_month_is_swept_and_logged(self) -> None:
        from unittest import mock
        swept = []

        def fake(session, outdir, start, end, *, say=print):
            swept.append((start, end))
            return [], {"rows_collected": 1, "rows_reported_by_portal": 1,
                        "complete": True, "slices": 1}

        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "awards.jsonl").write_text("")
            with mock.patch.object(cli, "_session", lambda a: object()), \
                    mock.patch.object(cli, "sweep_awards", fake):
                self.assertEqual(cli.cmd_backfill_awards(self._args(tmp)), 0)
            log = [json.loads(l) for l
                   in (pathlib.Path(tmp) / "awards_backfill_coverage.jsonl").read_text()
                   .splitlines() if l.strip()]
        self.assertEqual(swept[0], ("09/01/2026", "09/30/2026"), "not newest first")
        self.assertEqual(len(swept), 3)
        self.assertEqual(len(log), 3, "a per-window verdict is the only way to say "
                                      "which months are actually complete")

    def test_a_failing_month_does_not_stop_the_rest(self) -> None:
        from unittest import mock
        seen = []

        def fake(session, outdir, start, end, *, say=print):
            seen.append(start)
            if start == "08/01/2026":
                raise RuntimeError("portal timed out")
            return [], {"rows_collected": 1, "complete": True}

        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "awards.jsonl").write_text("")
            with mock.patch.object(cli, "_session", lambda a: object()), \
                    mock.patch.object(cli, "sweep_awards", fake):
                code = cli.cmd_backfill_awards(self._args(tmp))
            log = (pathlib.Path(tmp) / "awards_backfill_coverage.jsonl").read_text()
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 3, "a failed month took the later months with it")
        self.assertNotIn("08/01/2026", log, "a failed month must not log a verdict")

    def test_months_caps_how_much_is_attempted(self) -> None:
        from unittest import mock
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "awards.jsonl").write_text("")
            with mock.patch.object(cli, "_session", lambda a: object()), \
                    mock.patch.object(cli, "sweep_awards",
                                      lambda s, o, a, b, say=print: (
                                          seen.append(a), ([], {"complete": True}))[1]):
                cli.cmd_backfill_awards(self._args(tmp, months=2))
        self.assertEqual(seen, ["09/01/2026", "08/01/2026"])


class CoverageVerdictTests(unittest.TestCase):
    """A coverage verdict must never describe a corpus that is not on disk."""

    WINDOW = {"from": "08/27/2026", "to": "09/03/2026"}

    def test_a_fresh_measurement_is_published_as_its_own(self) -> None:
        v = assemble.award_coverage_verdict(
            {"slices": 559, "rows_collected": 4769, "complete": False, "note": "capped"},
            None, rows_on_disk=4769, held=0, window=self.WINDOW)
        self.assertTrue(v["measured_this_run"])
        self.assertEqual(v["rows_on_disk"], 4769)

    def test_a_fully_resumed_run_carries_the_earlier_verdict_and_says_so(self) -> None:
        # Found live: the file claimed 4,769 collected while awards.jsonl held 4,288,
        # because the sweep that measured 4,769 died before writing its rows.
        earlier = {"slices": 559, "rows_collected": 4769,
                   "rows_reported_by_portal": 4924, "complete": False, "note": "capped"}
        v = assemble.award_coverage_verdict(
            {"slices": 0, "rows_collected": 0, "complete": True, "note": ""},
            earlier, rows_on_disk=4288, held=17, window=self.WINDOW)
        self.assertEqual(v["rows_collected"], 4769, "threw away the real measurement")
        self.assertEqual(v["rows_on_disk"], 4288)
        self.assertFalse(v["measured_this_run"])
        self.assertIn("predates", v["note"])
        self.assertFalse(v["complete"], "a resumed run must not report the window clean")

    def test_a_resumed_run_that_did_measure_keeps_its_own_numbers(self) -> None:
        v = assemble.award_coverage_verdict(
            {"slices": 12, "rows_collected": 300, "complete": True, "note": ""},
            {"slices": 559, "rows_collected": 4769, "complete": False, "note": "old"},
            rows_on_disk=4588, held=17, window=self.WINDOW)
        self.assertEqual(v["rows_collected"], 300)
        self.assertEqual(v["slices_held_from_earlier_runs"], 17)
        self.assertIn("not re-measured", v["note"])

    def test_a_first_run_with_no_earlier_file_still_publishes(self) -> None:
        v = assemble.award_coverage_verdict(
            {"slices": 0, "rows_collected": 0, "complete": True, "note": ""},
            None, rows_on_disk=0, held=0, window=self.WINDOW)
        self.assertEqual(v["rows_on_disk"], 0)
        self.assertEqual(v["window"], self.WINDOW)


class SweepMemoryTests(unittest.TestCase):
    """The sweep must not hold the corpus in memory while it collects it.

    Every row used to be retained twice -- once in `awards`, once inside the slice
    record kept for coverage, which only ever needed the count. That is what killed
    three real runs; a twelve-month window would not have fit at all.
    """

    def _award(self, n):
        return {"purchase_doc": f"D{n}", "supplier_id": f"V{n}",
                "supplier_name": f"VENDOR {n}", "department": "Department of Motor Vehicles",
                "category": "IT Goods", "start_date": "09/01/2026",
                "awarded_amt": "$100.00", "acq_method": "Fair and Reasonable - COMPETITIVE"}

    def _run(self, tmp, sweep, seen):
        import argparse
        from unittest import mock

        from sled_trial import assemble as _a, report
        from sled_trial.sources.ca import scprs

        out = pathlib.Path(tmp)
        opp = {"business_unit": "2740", "event_id": "0000040075",
               "department": "Department of Motor Vehicles", "category": "IT Goods",
               "amount": 1000.0, "analysis_cutoff": "09/03/2026"}
        (out / "opportunity.json").write_text(json.dumps(opp))
        real_coverage = _a.award_sweep_coverage

        def spy(results):
            seen.extend(results)
            return real_coverage(results)

        previous_build = report.BUILD
        try:
            with mock.patch.object(cli, "_session", lambda args: _NeverFetch()), \
                    mock.patch.object(cli.ca, "fetch_event_list", lambda session: ""), \
                    mock.patch.object(scprs, "search_date_sliced", sweep), \
                    mock.patch.object(cli.assemble, "award_sweep_coverage", spy):
                return cli.cmd_analyze(argparse.Namespace(
                    opportunity=str(out / "opportunity.json"), output=tmp,
                    download_documents=False, raw_root=str(out / "raw"), no_ocr=True,
                    delay=0, browser_headers=False, awards_from=None,
                    reuse_awards=False, review_pages=20))
        finally:
            report.BUILD = previous_build

    def test_a_slice_record_keeps_its_tally_and_drops_its_rows(self) -> None:
        def sweep(session, window_from, cutoff, *, subdivide_by=None, skip=(),
                  on_slice=None):
            on_slice("s1", "ok", 2)
            yield {"rows": [self._award(0), self._award(1)], "total_reported": 2,
                   "truncated": False, "slice": {"from": "09/01/2026"}}

        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run(tmp, sweep, seen), 0)
        self.assertNotIn("rows", seen[0], "the slice record still carries its rows")
        self.assertEqual(seen[0]["rows_collected"], 2)

    def test_every_slice_reaches_the_cache_exactly_once(self) -> None:
        # Rows are appended per slice and deduped by reading the file back, so a row
        # repeated across slices must not appear twice on disk.
        def sweep(session, window_from, cutoff, *, subdivide_by=None, skip=(),
                  on_slice=None):
            for i, rows in enumerate([[self._award(0), self._award(1)],
                                      [self._award(1), self._award(2)]]):
                on_slice(f"s{i}", "ok", len(rows))
                yield {"rows": rows, "total_reported": len(rows), "truncated": False,
                       "slice": {"from": "09/01/2026"}}

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run(tmp, sweep, []), 0)
            rows = [json.loads(l) for l in
                    (pathlib.Path(tmp) / "awards.jsonl").read_text().splitlines()
                    if l.strip()]
        self.assertEqual(sorted(r["purchase_doc"] for r in rows), ["D0", "D1", "D2"])


class VendorAdsCommandTests(unittest.TestCase):
    """The vendor-ads command: a corpus built over runs, never a snapshot."""

    def _events(self, out, n=1):
        from sled_trial import documents
        documents.write_jsonl(
            [{"business_unit": "7760", "event_id": f"000003986{i}"} for i in range(n)],
            out / "events.jsonl")

    def test_no_event_feed_is_an_error_not_an_empty_harvest(self) -> None:
        import argparse
        with tempfile.TemporaryDirectory() as tmp:
            code = cli.cmd_vendor_ads(argparse.Namespace(
                output=tmp, delay=0, browser_headers=False, limit=0))
            self.assertEqual(code, 1)
            self.assertFalse(
                (pathlib.Path(tmp) / "vendor_ads_declared_interest.jsonl").exists(),
                "wrote an empty cache over a missing feed")

    def test_a_second_run_adds_to_the_cache_rather_than_replacing_it(self) -> None:
        # Same shape that emptied caltrans_bidders.jsonl: writing only this run's rows.
        import argparse
        from unittest import mock

        from sled_trial import documents
        from sled_trial.sources.ca import vendor_ads

        held = [{"business_unit": "7760", "event_id": "0000039999",
                 "vendor_name_raw": "EARLIER CO", "interest_direction": "sub_seeking_prime",
                 "intends_to_bid": False}]
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            self._events(out)
            documents.write_jsonl(held, out / "vendor_ads_declared_interest.jsonl")
            with mock.patch.object(cli, "_session", lambda args: object()), \
                    mock.patch.object(vendor_ads, "read_ad_page",
                                      lambda session, bu, eid: "<html>no ads</html>"):
                code = cli.cmd_vendor_ads(argparse.Namespace(
                    output=tmp, delay=0, browser_headers=False, limit=0))
            self.assertEqual(code, 0)
            rows = [json.loads(l) for l in
                    (out / "vendor_ads_declared_interest.jsonl").read_text().splitlines()
                    if l.strip()]
            self.assertEqual([r["vendor_name_raw"] for r in rows], ["EARLIER CO"])

    def test_an_ad_is_declared_interest_and_never_a_bidder(self) -> None:
        import argparse
        from unittest import mock

        from sled_trial.sources.ca import vendor_ads

        page = ("<span id='ZZ_VNDR_AD_TBL_BUSINESS_UNIT'>7760</span>"
                "<span id='ZZ_VNDR_AD_TBL_AUC_ID'>0000039860</span>"
                "<span id='ZZ_VNDR_PRIM_VW_NAME1$0' >BIG PRIME INC</span>"
                "<textarea id='ZZ_VNDR_PRIM_VW_DESCRLONG$0'>Seeking subs.</textarea>")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            self._events(out)
            with mock.patch.object(cli, "_session", lambda args: object()), \
                    mock.patch.object(vendor_ads, "read_ad_page",
                                      lambda session, bu, eid: page):
                cli.cmd_vendor_ads(argparse.Namespace(
                    output=tmp, delay=0, browser_headers=False, limit=0))
            rows = [json.loads(l) for l in
                    (out / "vendor_ads_declared_interest.jsonl").read_text().splitlines()
                    if l.strip()]
            self.assertEqual([r["participation"] for r in rows], ["declared_interest"])
            self.assertTrue(rows[0]["intends_to_bid"], "prime seeking sub means it bids")


class TestSuiteHygieneTests(unittest.TestCase):
    """A test file must not define the same class name twice.

    Python keeps the second and drops the first without a word, so the suite quietly
    stops running tests that still look present in the file. Caught live: a new
    `HarvestTests` in test_vendor_ads.py shadowed an existing one -- 27 tests defined,
    25 collected, all green. A guard for the shape, not for that one name.
    """

    def test_no_test_file_defines_a_class_name_twice(self) -> None:
        import ast
        import collections as _c

        offenders = []
        for path in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
            names = [n.name for n in ast.parse(path.read_text()).body
                     if isinstance(n, ast.ClassDef)]
            offenders += [f"{path.name}:{name}"
                          for name, count in _c.Counter(names).items() if count > 1]
        self.assertEqual(offenders, [],
                         "shadowed test classes; the earlier one never runs")


class PathVariableTests(unittest.TestCase):
    """A name holding an output path must not be rebound to something else.

    This exists because it happened: `cached` held `outdir / "awards.jsonl"`, was reused
    a few lines later for the cached award *list*, and the sweep then died writing its
    own results. It only fired on the full-sweep branch, so every --reuse-awards run
    passed and two real runs lost ninety minutes each.

    Checked with the AST rather than by grepping, so it catches the shape of the mistake
    rather than one spelling of it.
    """

    def _path_names(self, func):
        """Names assigned from an `outdir / ...` expression, i.e. holding a Path."""
        import ast

        names = set()
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div)
                    and isinstance(value.left, ast.Name)
                    and value.left.id in ("outdir", "directory", "dest")):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        return names

    def _rebinds(self, func, names):
        """Those same names later assigned something that is not a path expression."""
        import ast

        bad = []
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            is_path = (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Div))
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names and not is_path:
                    bad.append((target.id, getattr(node, "lineno", None)))
        return bad

    def _functions(self):
        import ast

        tree = ast.parse(pathlib.Path(cli.__file__).read_text())
        return [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name.startswith("cmd_")]

    def test_no_command_rebinds_a_path_variable_to_a_non_path(self) -> None:
        offenders = []
        for func in self._functions():
            names = self._path_names(func)
            if names:
                offenders += [(func.name, n, line)
                              for n, line in self._rebinds(func, names)]
        self.assertEqual(offenders, [],
                         f"a path variable is reused for something else: {offenders}")

    def test_the_check_would_have_caught_the_real_bug(self) -> None:
        # Guards the guard: if the AST walk stops finding path assignments, the test
        # above passes vacuously.
        import ast

        source = ("def cmd_x(args):\n"
                  "    cached = outdir / 'awards.jsonl'\n"
                  "    cached = read_rows('awards.jsonl')\n")
        func = ast.parse(source).body[0]
        names = self._path_names(func)
        self.assertIn("cached", names)
        self.assertTrue(self._rebinds(func, names))



class MergeCacheTests(unittest.TestCase):
    """A harvester's cache is a corpus built up over runs, not a snapshot of the last one."""

    def _rows(self, path):
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_fresh_rows_are_added_to_the_rows_already_held(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            (out / "c.jsonl").write_text(json.dumps({"k": 1, "v": "old"}) + "\n")
            merged = assemble.merge_cache(out, "c.jsonl", [{"k": 2, "v": "new"}],
                                          key=lambda r: r["k"])
            self.assertEqual({r["k"] for r in merged}, {1, 2})
            self.assertEqual({r["k"] for r in self._rows(out / "c.jsonl")}, {1, 2})

    def test_a_fresh_row_replaces_the_held_row_with_the_same_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            (out / "c.jsonl").write_text(json.dumps({"k": 1, "v": "old"}) + "\n")
            merged = assemble.merge_cache(out, "c.jsonl", [{"k": 1, "v": "new"}],
                                          key=lambda r: r["k"])
            self.assertEqual(merged, [{"k": 1, "v": "new"}])

    def test_an_absent_cache_is_created_from_the_fresh_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            merged = assemble.merge_cache(out, "c.jsonl", [{"k": 1}], key=lambda r: r["k"])
            self.assertEqual(merged, [{"k": 1}])
            self.assertTrue((out / "c.jsonl").exists())


class _NeverFetch:
    """A session that must not be used: a fully-resumed run has nothing to fetch."""

    def get(self, *args, **kwargs):
        raise AssertionError("network touched on a fully-resumed run")


class ResumeKeepsTheCacheTests(unittest.TestCase):
    """Resuming skips units already held. It must not also forget their rows.

    Reproduced before the fix: a `bidders` run whose every week was already held rewrote
    caltrans_bidders.jsonl from 3 rows to 0. The same shape emptied awards.jsonl on a
    second plain run of the README command.
    """

    def _rows(self, path):
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_a_fully_held_bidders_run_keeps_the_rows_it_already_had(self) -> None:
        import argparse
        import datetime as dt
        from unittest import mock

        from sled_trial import documents, harvest_state
        from sled_trial.sources.ca import caltrans

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            end = dt.date.today()
            weeks = list(caltrans.week_slugs(end - dt.timedelta(weeks=2), end))
            state = harvest_state.load(out)
            for week in weeks:
                harvest_state.record(state, "caltrans_bid_results", week, outcome="ok", rows=1)
            harvest_state.save(out, state)
            held = [{"business_unit": "2660", "event_id": f"E{i}", "vendor_name_raw": f"V{i}"}
                    for i in range(3)]
            documents.write_jsonl(held, out / "caltrans_bidders.jsonl")

            with mock.patch.object(cli, "_session", lambda args: _NeverFetch()):
                code = cli.cmd_bidders(argparse.Namespace(
                    output=tmp, delay=0, browser_headers=False, weeks=2, resolve=False))
            self.assertEqual(code, 0)
            self.assertEqual(len(self._rows(out / "caltrans_bidders.jsonl")), 3)

    def test_a_fully_held_award_sweep_keeps_the_awards_it_already_had(self) -> None:
        import argparse
        from unittest import mock

        from sled_trial import documents, harvest_state, report
        from sled_trial.sources.ca import scprs

        awards = [{"purchase_doc": f"D{i}", "supplier_id": f"V{i}", "supplier_name": f"VENDOR {i}",
                   "department": "Department of Motor Vehicles", "category": "IT Goods",
                   "start_date": "09/01/2026", "awarded_amt": "$100.00",
                   "acq_method": "Fair and Reasonable - COMPETITIVE"} for i in range(3)]
        opportunity = {"business_unit": "2740", "event_id": "0000040075",
                       "department": "Department of Motor Vehicles", "category": "IT Goods",
                       "amount": 1000.0, "analysis_cutoff": "09/03/2026"}
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            documents.write_jsonl(awards, out / "awards.jsonl")
            opp_path = out / "opportunity.json"
            opp_path.write_text(json.dumps(opportunity))
            # The whole default window was swept by an earlier run.
            state = harvest_state.load(out)
            key = scprs.slice_key({"from": assemble.default_awards_from("09/03/2026"),
                                   "to": "09/03/2026"})
            harvest_state.record(state, "caleprocure_scprs", key, outcome="ok", rows=3)
            harvest_state.save(out, state)

            previous_build = report.BUILD
            try:
                with mock.patch.object(cli, "_session", lambda args: _NeverFetch()), \
                        mock.patch.object(cli.ca, "fetch_event_list", lambda session: ""):
                    code = cli.cmd_analyze(argparse.Namespace(
                        opportunity=str(opp_path), output=tmp, download_documents=False,
                        raw_root=str(out / "raw"), no_ocr=True, delay=0,
                        browser_headers=False, awards_from=None, reuse_awards=False,
                        review_pages=20))
            finally:
                report.BUILD = previous_build
            self.assertEqual(code, 0)
            self.assertEqual({r["purchase_doc"] for r in self._rows(out / "awards.jsonl")},
                             {"D0", "D1", "D2"})


class InterruptedSweepTests(unittest.TestCase):
    """Resume has to survive the kill it was built for.

    The state file was saved once, after the sweep loop finished. So a run killed
    part-way -- the memory kill named in harvest_state's own docstring -- held nothing
    and the next run refetched every slice. Resumable only across a run that did not
    need resuming.
    """

    def test_a_sweep_killed_part_way_keeps_the_slices_it_finished(self) -> None:
        import argparse
        from unittest import mock

        from sled_trial import harvest_state, report
        from sled_trial.sources.ca import scprs

        row = {"purchase_doc": "D0", "supplier_id": "V0", "supplier_name": "VENDOR 0",
               "department": "Department of Motor Vehicles", "category": "IT Goods",
               "start_date": "09/01/2026", "awarded_amt": "$100.00",
               "acq_method": "Fair and Reasonable - COMPETITIVE"}
        opportunity = {"business_unit": "2740", "event_id": "0000040075",
                       "department": "Department of Motor Vehicles", "category": "IT Goods",
                       "amount": 1000.0, "analysis_cutoff": "09/03/2026"}

        def torn(session, window_from, cutoff, *, subdivide_by=None, skip=(),
                 on_slice=None):
            on_slice("2026-09-01..2026-09-01", harvest_state.OK, 1)
            yield {"rows": [row], "from": "09/01/2026", "to": "09/01/2026",
                   "reported": 1, "truncated": False}
            raise MemoryError("killed part-way, exactly as before")

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            opp_path = out / "opportunity.json"
            opp_path.write_text(json.dumps(opportunity))
            previous_build = report.BUILD
            try:
                with mock.patch.object(cli, "_session", lambda args: _NeverFetch()), \
                        mock.patch.object(cli.ca, "fetch_event_list", lambda session: ""), \
                        mock.patch.object(scprs, "search_date_sliced", torn):
                    with self.assertRaises(MemoryError):
                        cli.cmd_analyze(argparse.Namespace(
                            opportunity=str(opp_path), output=tmp,
                            download_documents=False, raw_root=str(out / "raw"),
                            no_ocr=True, delay=0, browser_headers=False,
                            awards_from=None, reuse_awards=False, review_pages=20))
            finally:
                report.BUILD = previous_build

            state = harvest_state.load(out)
            self.assertTrue(harvest_state.is_done(
                state, "caleprocure_scprs", "2026-09-01..2026-09-01"),
                "the finished slice was not held; the next run refetches it")
            rows = [json.loads(l) for l
                    in (out / "awards.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual([r["purchase_doc"] for r in rows], ["D0"],
                             "the slice was held but its rows never reached disk")


class OpportunityIntelligenceScopeTests(unittest.TestCase):
    """The debrief is about one solicitation. Its known bidders are that solicitation's."""

    def _intel(self, known):
        return assemble._opportunity_intelligence(
            {"business_unit": "2740", "event_id": "X"}, known=known,
            prediction={}, lineage_result={}, documents_manifest=[])

    def test_known_bidders_count_only_the_target_event(self) -> None:
        known = [{"business_unit": "2740", "event_id": "X", "vendor_name_raw": "A"},
                 {"business_unit": "2740", "event_id": "X", "vendor_name_raw": "B"},
                 {"business_unit": "PB14424", "event_id": "9", "vendor_name_raw": "C"}]
        out = self._intel(known)["known_bidders"]
        self.assertEqual(out["count"], 2)
        self.assertEqual({p["vendor_name_raw"] for p in out["participants"]}, {"A", "B"})

    def test_the_debrief_does_not_repeat_claims_the_research_overturned(self) -> None:
        text = json.dumps(self._intel([]))
        self.assertNotIn("requires a login", text)
        self.assertNotIn("publishes no bidder lists", text)
        self.assertNotIn("no public bidder or planholder list", text)


if __name__ == "__main__":
    unittest.main()
