"""Offline tests for the PlanetBids adapter. No network.

The payloads below are the shapes the portal's own API returned for a real awarded
solicitation (City of Anaheim, bid 124517), trimmed. The distinction the whole source
turns on is visible in them: 57 prospective bidders against 6 actual responses.
"""
import unittest

from sled_trial.sources.ca import planetbids as pb

BIDS = {
    "meta": {"totalBids": 1025, "totalPages": 35},
    "data": [
        {"type": "bids", "id": "124517", "attributes": {
            "bidId": 124517, "companyId": 14424, "stageId": 6, "stageStr": "Awarded",
            "title": "RFP for Energy Efficiency Consulting Services",
            "invitationNum": "20241209-01", "issueDate": "2024-12-06 14:24:00.000",
            "bidDueDate": "2025-01-10 17:00:00.000", "bidTypeId": 4,
            "byInvitation": False, "categoryIds": "91016, 91841"}},
        {"type": "bids", "id": "124600", "attributes": {
            "bidId": 124600, "companyId": 14424, "stageId": 2, "stageStr": "Bidding",
            "title": "STILL OPEN", "invitationNum": "X", "issueDate": None,
            "bidDueDate": None, "bidTypeId": 1, "byInvitation": False,
            "categoryIds": ""}},
    ],
}

PROSPECTIVE = {"data": [
    {"type": "bid-prospective-bidders", "id": "2784016", "attributes": {
        "bidderId": 2784016, "companyId": 14424, "vendorName": "2RS Consultants, LLC",
        "dbeStatus": "OSB", "address1": "PO Box 541", "city": "Palmaya",
        "zipCode": "22963", "contactName": "Laurie Johnson", "phone": "434-500-9600",
        "vendorEmail": "l*****j@2rsconsulting.com", "classification": 1, "status": 0,
        "preBidMtgAttendee": False, "bidId": 124517, "vendorId": 1116354}},
    {"type": "bid-prospective-bidders", "id": "2786573", "attributes": {
        "bidderId": 2786573, "companyId": 14424, "vendorName": "6893449 Canada Inc",
        "dbeStatus": "", "city": "", "contactName": "", "phone": "",
        "classification": 2, "status": 0, "preBidMtgAttendee": True,
        "bidId": 124517, "vendorId": 998877}},
]}

RESPONSES = {"data": [
    {"type": "bid-responses", "id": "409469", "attributes": {
        "responseId": 409469, "companyId": 14424, "ranking": 0, "amount": 0.0,
        "responsive": 0, "status": 1, "bidId": 124517, "vendorId": 803192,
        "bidderId": 2785006, "vendorName": "alliancePROJECT, Inc.", "city": "",
        "dbeStatus": "OSB, CADIR, WBE"}},
    {"type": "bid-responses", "id": "409604", "attributes": {
        "responseId": 409604, "companyId": 14424, "ranking": 1, "amount": 246500.0,
        "responsive": 1, "status": 1, "bidId": 124517, "vendorId": 771122,
        "bidderId": 2785100, "vendorName": "Lincus, Inc.", "city": "Tustin",
        "dbeStatus": "WBE"}},
    {"type": "bid-responses", "id": "409700", "attributes": {
        "responseId": 409700, "companyId": 14424, "ranking": 2, "amount": 310000.0,
        "responsive": 2, "status": 1, "bidId": 124517, "vendorId": 660011,
        "bidderId": 2785200, "vendorName": "EXP US Services", "city": "Irvine",
        "dbeStatus": ""}},
]}


class BidListTests(unittest.TestCase):
    def test_solicitations_parse_with_their_stage(self) -> None:
        bids = pb.parse_bids(BIDS)
        self.assertEqual(len(bids), 2)
        self.assertEqual(bids[0]["stage"], "Awarded")
        self.assertEqual(bids[0]["invitation_number"], "20241209-01")

    def test_categories_become_a_list_not_a_joined_string(self) -> None:
        self.assertEqual(pb.parse_bids(BIDS)[0]["category_ids"], ["91016", "91841"])
        self.assertEqual(pb.parse_bids(BIDS)[1]["category_ids"], [])

    def test_the_portal_reports_its_own_totals(self) -> None:
        # Needed to tell a complete harvest from one that stopped early.
        self.assertEqual(pb.total_bids(BIDS), 1025)
        self.assertEqual(pb.total_pages(BIDS), 35)

    def test_page_size_is_pinned_because_the_api_rejects_others(self) -> None:
        # per_page=50 returns HTTP 400. Discovered live; pinned so nobody "optimises" it.
        self.assertEqual(pb.PAGE_SIZE, 30)
        self.assertIn("per_page=30", pb.bids_url(14424))

    def test_stage_filter_defaults_to_every_stage(self) -> None:
        self.assertIn("stage_id=0", pb.bids_url(14424))
        self.assertIn("stage_id=6", pb.bids_url(14424, stage_id=6))


class ProspectiveBidderTests(unittest.TestCase):
    def test_planholders_carry_a_stable_vendor_id(self) -> None:
        # The reason this source beats the PDF ones: identity without name matching.
        rows = pb.parse_prospective_bidders(PROSPECTIVE)
        self.assertEqual(rows[0]["vendor_id"], 1116354)

    def test_certifications_are_split_into_a_list(self) -> None:
        rows = pb.parse_prospective_bidders(PROSPECTIVE)
        self.assertEqual(rows[0]["classifications"], ["OSB"])
        self.assertEqual(rows[1]["classifications"], [])

    def test_pre_bid_attendance_is_captured(self) -> None:
        rows = pb.parse_prospective_bidders(PROSPECTIVE)
        self.assertFalse(rows[0]["pre_bid_meeting_attendee"])
        self.assertTrue(rows[1]["pre_bid_meeting_attendee"])

    def test_prime_versus_sub_is_read_from_the_classification_code(self) -> None:
        rows = pb.parse_prospective_bidders(PROSPECTIVE)
        self.assertTrue(rows[0]["is_prime"])
        self.assertFalse(rows[1]["is_prime"])

    def test_empty_contact_fields_become_none_not_empty_strings(self) -> None:
        self.assertIsNone(pb.parse_prospective_bidders(PROSPECTIVE)[1]["contact_name"])


class ResponseTests(unittest.TestCase):
    def test_an_unranked_field_yields_null_rank_not_zero(self) -> None:
        # The portal writes 0 when it has not ranked. Storing 0 would invent a low bidder.
        rows = pb.parse_responses(RESPONSES)
        self.assertIsNone(rows[0]["rank"])
        self.assertEqual(rows[1]["rank"], 1)

    def test_an_unpublished_amount_is_null_not_zero(self) -> None:
        rows = pb.parse_responses(RESPONSES)
        self.assertIsNone(rows[0]["amount"])
        self.assertEqual(rows[1]["amount"], 246500.0)

    def test_responsive_is_tri_state(self) -> None:
        # 0 is "not yet judged", not "non-responsive". Collapsing them would record a
        # responsive bidder as rejected.
        rows = pb.parse_responses(RESPONSES)
        self.assertIsNone(rows[0]["responsive"])
        self.assertTrue(rows[1]["responsive"])
        self.assertFalse(rows[2]["responsive"])


class SeparationTests(unittest.TestCase):
    """A planholder is not a bidder, and conflating them inflates every field."""

    def test_planholders_and_bidders_stay_in_separate_buckets(self) -> None:
        bid = pb.parse_bids(BIDS)[0]
        bidders = pb.bidder_candidates(bid, pb.parse_responses(RESPONSES), cid=14424)
        interest = pb.declared_interest_rows(
            bid, pb.parse_prospective_bidders(PROSPECTIVE), cid=14424)
        self.assertEqual(len(bidders), 3)
        self.assertEqual(len(interest), 2)
        self.assertTrue(all(r["participation"] == "declared_interest" for r in interest))
        self.assertFalse(any("participation" in r for r in bidders))

    def test_bidder_rows_use_the_field_names_the_participant_export_reads(self) -> None:
        bid = pb.parse_bids(BIDS)[0]
        row = pb.bidder_candidates(bid, pb.parse_responses(RESPONSES),
                                   cid=14424)[1]
        self.assertEqual(row["vendor_name_raw"], "Lincus, Inc.")
        self.assertEqual(row["amount_numeric"], 246500.0)
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["source_key"], "planetbids_agency_portal")
        self.assertEqual(row["business_unit"], "PB14424")
        self.assertEqual(row["event_id"], "124517")

    def test_the_evidence_url_points_at_the_page_a_person_can_open(self) -> None:
        bid = pb.parse_bids(BIDS)[0]
        row = pb.bidder_candidates(bid, pb.parse_responses(RESPONSES), cid=14424)[0]
        self.assertEqual(row["evidence_url"],
                         "https://pbsystem.planetbids.com/portal/14424/bo/bo-detail/124517")

    def test_the_identity_is_not_a_cal_eprocure_business_unit(self) -> None:
        # A city bid id is not a state event id; inventing one would fabricate a join.
        bid = pb.parse_bids(BIDS)[0]
        row = pb.bidder_candidates(bid, pb.parse_responses(RESPONSES), cid=14424)[0]
        self.assertTrue(row["business_unit"].startswith("PB"))


class HarvestTests(unittest.TestCase):
    def _fetch(self, extra=None, fail_on=None):
        def fetch_json(url):
            if fail_on and fail_on in url:
                raise OSError("connection reset")
            if "/bids?" in url:
                return BIDS
            if "bid-prospective-bidders" in url:
                return PROSPECTIVE
            if "bid-responses" in url:
                return RESPONSES
            return (extra or {}).get("files", {"data": []})
        return fetch_json

    def test_only_closed_solicitations_are_asked_for_a_bidder_field(self) -> None:
        # An open bid has no respondents yet; harvesting it would record "no bidders"
        # for a solicitation that simply has not closed.
        out = pb.harvest_agency(self._fetch(), 14424)
        self.assertEqual({r["event_id"] for r in out["candidates"]}, {"124517"})

    def test_portal_totals_are_carried_so_a_short_harvest_is_visible(self) -> None:
        out = pb.harvest_agency(self._fetch(), 14424)
        self.assertEqual(out["bids_reported_by_portal"], 1025)
        self.assertEqual(out["bids_collected"], 2)
        self.assertFalse(out["complete"])

    def test_a_bid_that_fails_is_recorded_not_dropped(self) -> None:
        out = pb.harvest_agency(self._fetch(fail_on="bid-responses"), 14424)
        self.assertEqual(out["candidates"], [])
        self.assertEqual(len(out["failures"]), 1)
        self.assertIn("OSError", out["failures"][0]["detail"])

    def test_one_dead_endpoint_does_not_cost_the_others(self) -> None:
        # Measured live: 17 of 60 Anaheim solicitations answer bid-responses with 400
        # while still serving their planholders. Failing the whole bid threw those away.
        out = pb.harvest_agency(self._fetch(fail_on="bid-responses"), 14424)
        self.assertEqual(out["candidates"], [])
        self.assertEqual(len(out["declared_interest"]), 2)

    def test_a_set_the_portal_says_is_absent_is_not_called_a_failure(self) -> None:
        # 400 here means "no response set exists", not "the request broke". Filing it
        # under failures would make a real outage indistinguishable from an empty bid.
        def fetch(url):
            if "bid-responses" in url:
                raise RuntimeError("HTTP 400 for .../bid-responses: could not process")
            if "/bids?" in url:
                return BIDS
            if "bid-prospective-bidders" in url:
                return PROSPECTIVE
            return {"data": []}

        out = pb.harvest_agency(fetch, 14424)
        self.assertEqual(out["failures"], [])
        self.assertEqual(len(out["absent"]), 1)
        self.assertEqual(out["absent"][0]["endpoint"], "bid-responses")
        self.assertEqual(len(out["declared_interest"]), 2)

    def test_max_bids_bounds_a_run(self) -> None:
        out = pb.harvest_agency(self._fetch(), 14424, max_bids=0)
        self.assertEqual(out["candidates"], [])
        self.assertEqual(out["failures"], [])



class CommandTests(unittest.TestCase):
    """The command body must actually run. A missing helper here is a NameError that
    only a live run finds -- which is exactly how a previous command shipped broken."""

    def _fake_reader(self):
        def fetch_json(url):
            if "/bids?" in url:
                return BIDS
            if "bid-prospective-bidders" in url:
                return PROSPECTIVE
            if "bid-responses" in url:
                return RESPONSES
            return {"data": []}

        class FakeReader:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                self.fetch_json = fetch_json
                return self

            def __exit__(self, *a):
                return False

        return FakeReader

    def test_the_command_writes_the_files_it_promises(self) -> None:
        import argparse
        import pathlib
        import tempfile
        from unittest import mock

        from sled_trial import cli

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("sled_trial.net.browser.PortalJsonReader",
                            self._fake_reader()):
                code = cli.cmd_planetbids(argparse.Namespace(
                    output=tmp, agency=["14424"], max_bids=None, delay=0,
                    local_browser=False))
            self.assertEqual(code, 0)
            written = {p.name for p in pathlib.Path(tmp).iterdir()}
            self.assertEqual(written, {"planetbids_bidders.jsonl",
                                       "planetbids_declared_interest.jsonl",
                                       "planetbids_coverage.json"})

    def test_the_source_is_registered_so_the_pipeline_can_find_it(self) -> None:
        from sled_trial import sources

        self.assertIn("planetbids_agency_portal", sources.BY_KEY)
        self.assertEqual(sources.BY_KEY["planetbids_agency_portal"].cache,
                         "planetbids_bidders.jsonl")


class DerivedRankTests(unittest.TestCase):
    """Most agencies publish every amount but leave `ranking` at 0."""

    def test_rank_is_derived_from_amount_when_the_portal_does_not_rank(self) -> None:
        rows = pb.with_derived_rank(pb.parse_responses(RESPONSES))
        by_name = {r["vendor_name"]: r for r in rows}
        self.assertEqual(by_name["Lincus, Inc."]["derived_rank"], 1)      # 246,500
        self.assertEqual(by_name["EXP US Services"]["derived_rank"], 2)   # 310,000

    def test_a_bidder_with_no_published_amount_gets_no_derived_rank(self) -> None:
        # Ranking it would invent a position the data does not support.
        rows = pb.with_derived_rank(pb.parse_responses(RESPONSES))
        unpriced = next(r for r in rows if r["vendor_name"] == "alliancePROJECT, Inc.")
        self.assertIsNone(unpriced["derived_rank"])

    def test_the_portals_own_rank_is_never_overwritten(self) -> None:
        # `rank` stays null so a caller can tell a stated rank from an inferred one.
        row = pb.bidder_candidates(pb.parse_bids(BIDS)[0],
                                   pb.parse_responses(RESPONSES), cid=14424)[0]
        self.assertIsNone(row["rank"])
        self.assertIn("derived_rank", row)

DOCUMENTS = {"data": [
    {"type": "bid-downloadable-files", "id": "527484", "attributes": {
        "downloadableFileId": 527484, "fileTitle": "RFP Energy Efficiency Consulting",
        "filename": "CAO-153605-v1-RFP_-_Energy_Efficiency_Consultant.pdf",
        "fileSize": 323368, "serverFullPath": "files-prod01.planetbids.com/Anaheim/BMfiles/",
        "serverFilename": "20241206132307123 CAO-153605-v1-RFP_-_Energy_Efficiency_Consultant.pdf",
        "sortLabel": "1", "recalled": False, "publiclyVisible": False,
        "uploadedDate": "2024-12-06 13:23:07.123", "bidId": 124517}},
    {"type": "bid-downloadable-files", "id": "527500", "attributes": {
        "downloadableFileId": 527500, "fileTitle": "Addendum 1", "filename": "add1.pdf",
        "fileSize": 1024, "serverFullPath": "", "serverFilename": "",
        "recalled": True, "publiclyVisible": True, "bidId": 124517}},
]}


class DocumentTests(unittest.TestCase):
    """Field names verified against a live response, not guessed.

    An earlier version looked for `fileId`, `fileName` and `requiresLogin`, none of
    which exist -- so every filename came back empty and every document looked publicly
    readable. Both failures were silent.
    """

    def test_the_real_field_names_are_read(self) -> None:
        doc = pb.parse_documents(DOCUMENTS)[0]
        self.assertEqual(doc["file_id"], 527484)
        self.assertEqual(doc["file_name"],
                         "CAO-153605-v1-RFP_-_Energy_Efficiency_Consultant.pdf")
        self.assertEqual(doc["size_bytes"], 323368)
        self.assertEqual(doc["title"], "RFP Energy Efficiency Consulting")

    def test_the_login_gate_is_carried_rather_than_assumed_open(self) -> None:
        docs = pb.parse_documents(DOCUMENTS)
        self.assertFalse(docs[0]["publicly_visible"])
        self.assertTrue(docs[1]["publicly_visible"])

    def test_a_recalled_document_is_flagged_not_dropped(self) -> None:
        # Usually superseded by an addendum. The caller decides, not the parser.
        docs = pb.parse_documents(DOCUMENTS)
        self.assertFalse(docs[0]["recalled"])
        self.assertTrue(docs[1]["recalled"])

    def test_the_download_url_quotes_the_stored_filename(self) -> None:
        # Stored names routinely contain spaces, so pasting them yields a broken URL.
        self.assertEqual(
            pb.parse_documents(DOCUMENTS)[0]["download_url"],
            "https://files-prod01.planetbids.com/Anaheim/BMfiles/"
            "20241206132307123%20CAO-153605-v1-RFP_-_Energy_Efficiency_Consultant.pdf")

    def test_a_document_with_no_server_path_has_no_url(self) -> None:
        self.assertIsNone(pb.parse_documents(DOCUMENTS)[1]["download_url"])

    def test_document_url_needs_both_halves(self) -> None:
        self.assertIsNone(pb.document_url("host/dir/", None))
        self.assertIsNone(pb.document_url(None, "file.pdf"))


if __name__ == "__main__":
    unittest.main()
