"""Offline tests for Supabase-shaped exports and their proposed contracts."""
import json
import pathlib
import tempfile
import unittest

from sled_trial import supabase_export as se


class IdentifierTests(unittest.TestCase):
    def test_ids_are_deterministic_across_calls(self) -> None:
        a = se.local_id("gov_competitors", "scprs", "0000015031")
        b = se.local_id("gov_competitors", "scprs", "0000015031")
        self.assertEqual(a, b)

    def test_different_natural_keys_give_different_ids(self) -> None:
        self.assertNotEqual(se.local_id("gov_competitors", "scprs", "1"),
                            se.local_id("gov_competitors", "scprs", "2"))

    def test_table_name_is_part_of_the_key(self) -> None:
        self.assertNotEqual(se.local_id("gov_competitors", "x"),
                            se.local_id("gov_procurement_records", "x"))

    def test_none_and_empty_parts_are_distinguishable(self) -> None:
        self.assertNotEqual(se.local_id("t", None, "a"), se.local_id("t", "", "a"))

    def test_ids_are_uuid_shaped(self) -> None:
        import uuid
        uuid.UUID(se.local_id("t", "x"))  # raises if malformed


class ContractTests(unittest.TestCase):
    def test_every_table_has_a_schema(self) -> None:
        self.assertEqual(set(se.SCHEMAS), set(se.TABLES))

    def test_schemas_declare_themselves_proposed_not_production(self) -> None:
        # The trial author asked for a clearly labelled proposed contract and explicitly
        # said not to claim production compatibility.
        for table, schema in se.SCHEMAS.items():
            with self.subTest(table=table):
                self.assertIn("PROPOSED CONTRACT", schema["description"])
                self.assertIn("no claim of production compatibility",
                              schema["description"])
                self.assertIn("docs/supabase_mapping.md", schema["description"])

    def test_schemas_allow_unknown_columns(self) -> None:
        # A real table will carry columns this trial cannot know; rejecting them would be
        # a false negative.
        for table, schema in se.SCHEMAS.items():
            with self.subTest(table=table):
                self.assertTrue(schema["additionalProperties"])

    def test_contracts_are_written_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            written = se.write_contracts(tmp)
            self.assertEqual(len(written), len(se.TABLES))
            for path in written:
                json.loads(pathlib.Path(path).read_text())


class ValidationTests(unittest.TestCase):
    def test_missing_required_field_is_reported_not_swallowed(self) -> None:
        result = se.validate_rows("gov_procurement_sources", [{"source_key": "x"}])
        self.assertFalse(result["valid"])
        self.assertTrue(result["errors"])

    def test_valid_row_passes(self) -> None:
        row = {"id": se.local_id("gov_procurement_sources", "x"), "source_key": "x",
               "provider": "Cal eProcure", "jurisdiction": "California",
               "observed_at": "2026-09-07T00:00:00+00:00"}
        self.assertTrue(se.validate_rows("gov_procurement_sources", [row])["valid"])

    def test_validation_result_names_its_contract_and_status(self) -> None:
        result = se.validate_rows("gov_competitors", [])
        self.assertIn("contracts/supabase/gov_competitors.schema.json", result["contract"])
        self.assertIn("proposed contract", result["contract_status"])
        self.assertIn("not production schema", result["contract_status"])

    def test_every_error_is_collected_not_just_the_first(self) -> None:
        bad = [{"source_key": "a"}, {"source_key": "b"}]
        self.assertGreaterEqual(
            len(se.validate_rows("gov_procurement_sources", bad)["errors"]), 2)


class HandoffTests(unittest.TestCase):
    def test_import_order_lists_every_table(self) -> None:
        self.assertEqual(set(se.handoff_manifest()["import_order"]), set(se.TABLES))

    def test_every_referenced_table_precedes_its_children(self) -> None:
        # Spot-checking two pairs missed that gov_competitors sat AFTER
        # gov_procurement_participants, which carries competitor_id. Assert the whole
        # dependency graph instead of a sample of it.
        order = se.handoff_manifest()["import_order"]
        for table, parents in se.FOREIGN_KEYS.items():
            for parent in parents:
                with self.subTest(table=table, parent=parent):
                    self.assertLess(order.index(parent), order.index(table),
                                    f"{parent} must be imported before {table}")

    def test_foreign_keys_cover_every_table(self) -> None:
        self.assertEqual(set(se.FOREIGN_KEYS), set(se.TABLES))

    def test_import_order_is_a_permutation_of_the_tables(self) -> None:
        order = se.handoff_manifest()["import_order"]
        self.assertEqual(sorted(order), sorted(se.TABLES))
        self.assertEqual(len(order), len(set(order)))

    def test_natural_keys_cover_every_table(self) -> None:
        self.assertEqual(set(se.handoff_manifest()["natural_upsert_keys"]), set(se.TABLES))

    def test_conflict_rule_protects_evidence_class(self) -> None:
        # A weaker evidence class must never overwrite a stronger one on upsert.
        self.assertIn("never overwrite a stronger evidence_class",
                      se.handoff_manifest()["conflict_behaviour"])

    def test_production_ids_are_declared_unresolved(self) -> None:
        self.assertTrue(se.handoff_manifest()["production_ids_unresolved"])

    def test_no_supabase_target_is_asserted(self) -> None:
        self.assertIn("no script", se.handoff_manifest()["safety"].lower())


class MapperTests(unittest.TestCase):
    EVENT = {"business_unit": "2660", "event_id": "04A7615", "agency": "Caltrans",
             "title": "On-call services", "event_type": "RFx", "format": "Sell",
             "end_dttm": "09/08/2026 10:00AM PDT", "buyer_email": "x@dot.ca.gov"}
    AWARD = {"purchase_doc": "26IT-0168", "department": "Department of Justice",
             "description": "Laptops", "start_date": "09/03/2026", "end_date": "N/A",
             "awarded_amt": "$3,140.49", "supplier_id": "0000000269",
             "supplier_name": "TECHNOLOGY INTEGRATION GROUP", "category": "IT Goods",
             "acq_method": "Statewide Contracts", "cert_type": "SB|MB"}

    def test_event_maps_to_a_solicitation_record_with_a_canonical_url(self) -> None:
        row = se.event_record_rows([self.EVENT])[0]
        self.assertEqual(row["record_type"], "solicitation")
        self.assertIn("caleprocure.ca.gov/event/2660/04A7615", row["canonical_url"])
        self.assertEqual(row["buyer_code"], "2660")

    def test_award_amount_is_numeric_and_the_raw_string_is_kept(self) -> None:
        row = se.award_record_rows([self.AWARD])[0]
        self.assertEqual(row["amount"], 3140.49)
        self.assertEqual(row["amount_raw"], "$3,140.49")

    def test_unparseable_award_amount_stays_null(self) -> None:
        row = se.award_record_rows([{**self.AWARD, "awarded_amt": "N/A"}])[0]
        self.assertIsNone(row["amount"])
        self.assertEqual(row["amount_raw"], "N/A")

    def test_award_participant_is_derived_not_observed(self) -> None:
        row = se.participant_rows([], [self.AWARD])[0]
        self.assertEqual(row["role"], "awardee")
        self.assertEqual(row["evidence_class"], "derived")
        self.assertEqual(row["identity_confidence"], "high")

    def test_document_participant_is_observed_but_identity_unresolved(self) -> None:
        candidate = {"vendor_name_raw": "AVIATE ENTERPRISES, INC.",
                     "amount_numeric": "437862.48", "amount_raw": "$437,862.48",
                     "business_unit": "2740", "event_id": "0000040075",
                     "displayed_filename": "Intent_to_Award.pdf", "page": 1,
                     "sha256": "abc", "evidence_row": ["AVIATE", "$437,862.48"]}
        row = se.participant_rows([candidate], [])[0]
        self.assertEqual(row["role"], "known_bidder")
        self.assertEqual(row["evidence_class"], "observed")
        self.assertEqual(row["identity_confidence"], "unresolved")
        self.assertEqual(row["evidence"]["page"], 1)

    def test_participants_never_carry_a_predicted_class(self) -> None:
        rows = se.participant_rows([], [self.AWARD])
        self.assertNotIn("predicted", {r["evidence_class"] for r in rows})

    def test_document_and_handoff_ids_link(self) -> None:
        manifest = [{"business_unit": "2740", "event_id": "E1",
                     "displayed_filename": "a.pdf", "sha256": "s1",
                     "download_status": "downloaded", "retrieved_at": "now"}]
        pages = [{"business_unit": "2740", "event_id": "E1",
                  "displayed_filename": "a.pdf", "sha256": "s1", "page": 1,
                  "method": "native"}]
        doc_row = se.document_rows(manifest)[0]
        page_row = se.handoff_rows(pages)[0]
        self.assertEqual(page_row["document_id"], doc_row["id"])

    def test_failed_download_is_marked_not_processed(self) -> None:
        row = se.document_rows([{"business_unit": "x", "event_id": "y",
                                 "displayed_filename": "f", "sha256": None,
                                 "download_status": "no_serving_url"}])[0]
        self.assertEqual(row["processing_state"], "not_processed")

    def test_exports_write_all_tables_and_a_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = se.write_exports({"gov_competitors": []}, tmp)
            files = {p.name for p in pathlib.Path(tmp).iterdir()}
            for table in se.TABLES:
                self.assertIn(f"{table}.jsonl", files)
            self.assertIn("validation_report.json", files)
            self.assertIn("handoff.json", files)
            self.assertIn("PROPOSED CONTRACT", report["contract_status"])
            self.assertIn("no production compatibility is claimed",
                          report["contract_status"])



class BidderRankTests(unittest.TestCase):
    def test_an_observed_bidder_keeps_its_rank_and_names_its_own_source(self) -> None:
        # Caltrans bid results give rank and a page URL; hardcoding rank to null and the
        # source to the event package would throw away the only ranked bidder evidence
        # California publishes.
        candidate = {
            "business_unit": "2660", "event_id": "08A3933",
            "vendor_name_raw": "Apex Waste Systems Inc.",
            "amount_raw": "$480,480.00", "amount_numeric": 480480.0,
            "rank": 2, "source_key": "caltrans_bid_results",
            "evidence_url": "https://dot.ca.gov/x", "evidence_row": "Apex | SB: Y",
        }
        row = next(r for r in se.participant_rows([candidate], []))
        self.assertEqual(row["rank"], 2)
        self.assertEqual(row["role"], "known_bidder")
        self.assertEqual(row["evidence"]["source_key"], "caltrans_bid_results")

    def test_a_document_candidate_still_defaults_to_the_event_package(self) -> None:
        candidate = {"business_unit": "2740", "event_id": "0000040075",
                     "vendor_name_raw": "AVIATE ENTERPRISES, INC.",
                     "amount_raw": "$437,862.48", "amount_numeric": 437862.48}
        row = next(r for r in se.participant_rows([candidate], []))
        self.assertIsNone(row["rank"])
        self.assertEqual(row["evidence"]["source_key"], "caleprocure_event_package")


class ParticipantRecordSourceTests(unittest.TestCase):
    def test_an_sf_bidder_is_not_attributed_to_a_cal_eprocure_solicitation(self) -> None:
        # San Francisco has no Cal eProcure event. Hanging its sourcing id off the state
        # event list would assert a record that does not exist.
        sf = {"business_unit": "SFPW", "event_id": "0000007165",
              "vendor_name_raw": "Ronan Construction", "amount_numeric": 6563340.0,
              "source_key": "sfpublicworks_bid_tabulation"}
        state = {"business_unit": "2660", "event_id": "08A3933",
                 "vendor_name_raw": "Apex Waste Systems Inc.", "amount_numeric": 480480.0,
                 "source_key": "caltrans_bid_results"}
        rows = se.participant_rows([sf, state], [])
        self.assertNotEqual(rows[0]["record_id"], rows[1]["record_id"])
        expected = se.local_id("gov_procurement_records", "sfpublicworks_bid_tabulation",
                               "solicitation", "SFPW/0000007165")
        self.assertEqual(rows[0]["record_id"], expected)

    def test_a_cal_eprocure_bidder_keeps_the_event_list_record(self) -> None:
        state = {"business_unit": "2660", "event_id": "08A3933",
                 "vendor_name_raw": "Apex Waste Systems Inc.",
                 "source_key": "caltrans_bid_results"}
        row = se.participant_rows([state], [])[0]
        expected = se.local_id("gov_procurement_records", "caleprocure_event_list",
                               "solicitation", "2660/08A3933")
        self.assertEqual(row["record_id"], expected)


class ResolvedIdentityExportTests(unittest.TestCase):
    def test_a_resolved_bidder_links_to_its_scprs_competitor(self) -> None:
        # Otherwise the row never joins the gov_competitors profile built from that id, and
        # the resolution work is discarded at the export boundary.
        resolved = {"business_unit": "2660", "event_id": "08A3933",
                    "vendor_name_raw": "Apex Waste Systems Inc.",
                    "supplier_id": "0000011589", "identity_confidence": "medium",
                    "source_key": "caltrans_bid_results"}
        row = se.participant_rows([resolved], [])[0]
        self.assertEqual(row["identity_confidence"], "medium")
        self.assertEqual(row["competitor_id"],
                         se.local_id("gov_competitors", "caleprocure_scprs", "0000011589"))

    def test_an_unresolved_bidder_still_reads_as_unresolved(self) -> None:
        row = se.participant_rows([{"business_unit": "2660", "event_id": "08A3933",
                                    "vendor_name_raw": "Nobody Inc."}], [])[0]
        self.assertEqual(row["identity_confidence"], "unresolved")


class PartnerMatchRecordTests(unittest.TestCase):
    def test_the_payload_points_at_the_solicitation_record_that_exists(self) -> None:
        # event_ref only exists on holdout evaluation events, so a real opportunity fell
        # back to the department name and keyed off a record nothing emits.
        opportunity = {"business_unit": "2740", "event_id": "0000040075",
                       "department": "Department of Motor Vehicles"}
        row = se.partner_match_rows([{"opportunity": opportunity,
                                      "prime_candidates": []}])[0]
        expected = se.local_id("gov_procurement_records", "caleprocure_event_list",
                               "solicitation", "2740/0000040075")
        self.assertEqual(row["record_id"], expected)
        self.assertEqual(row["record_id"],
                         se.event_record_rows([opportunity])[0]["id"])

    def test_the_analysed_opportunity_gets_a_record_even_when_it_has_closed(self) -> None:
        # Records are seeded from the active feed, which drops an event at close. The
        # opportunity under analysis must still have a solicitation row, or the partner
        # payload and its participants reference something that was never written.
        opportunity = {"business_unit": "2740", "event_id": "0000040075",
                       "department": "Department of Motor Vehicles"}
        rows = se.event_record_rows([{"business_unit": "2660", "event_id": "08A3933"}],
                                    target=opportunity)
        ids = {r["id"] for r in rows}
        self.assertIn(se.local_id("gov_procurement_records", "caleprocure_event_list",
                                  "solicitation", "2740/0000040075"), ids)

    def test_a_target_already_in_the_feed_is_not_duplicated(self) -> None:
        opportunity = {"business_unit": "2740", "event_id": "0000040075"}
        rows = se.event_record_rows([opportunity], target=opportunity)
        self.assertEqual(len(rows), 1)


class ParticipantRecordIntegrityTests(unittest.TestCase):
    """Every participant must point at a solicitation record that is actually emitted."""

    CALTRANS = {"business_unit": "2660", "event_id": "08A3933",
                "vendor_name_raw": "Apex Waste Systems Inc.",
                "source_key": "caltrans_bid_results"}
    SF = {"business_unit": "SFPW", "event_id": "0000007165",
          "vendor_name_raw": "Ronan Construction",
          "source_key": "sfpublicworks_bid_tabulation"}

    def test_harvested_solicitations_get_their_own_records(self) -> None:
        # Bidder harvests name solicitations the active feed never carried, so without
        # this every harvested participant is a dangling reference.
        records = se.event_record_rows([], target=None,
                                       participants=[self.CALTRANS, self.SF])
        ids = {r["id"] for r in records}
        for candidate in (self.CALTRANS, self.SF):
            with self.subTest(source=candidate["source_key"]):
                row = se.participant_rows([candidate], [])[0]
                self.assertIn(row["record_id"], ids)

    def test_a_planholder_and_an_advertiser_are_different_states(self) -> None:
        # The brief asks the system to distinguish interested vendors, planholders,
        # respondents, bidders, awardees and incumbents. Collapsing the first two into
        # "interested" is the inflation those six states exist to prevent: a planholder
        # took the package from the agency, an advertiser posted about itself.
        rows = se.declared_interest_rows([
            {"business_unit": "PB14424", "event_id": "122502",
             "vendor_name_raw": "1st California Construction, Inc.", "vendor_id": 217539,
             "source_key": "planetbids_agency_portal", "pre_bid_meeting_attendee": True},
            {"business_unit": "7760", "event_id": "0000039865",
             "vendor_name_raw": "Integrity Technology", "intends_to_bid": False,
             "interest_direction": "sub_seeking_prime",
             "source_key": "caleprocure_vendor_ads"}])
        self.assertEqual([r["role"] for r in rows], ["planholder", "interested_vendor"])

    def test_declared_interest_never_becomes_a_bidder(self) -> None:
        rows = se.declared_interest_rows([
            {"business_unit": "PB14424", "event_id": "122502",
             "vendor_name_raw": "ACME", "source_key": "planetbids_agency_portal"}])
        self.assertNotIn(rows[0]["role"], ("known_bidder", "awardee"))
        self.assertIsNone(rows[0]["submitted_amount"])
        self.assertIsNone(rows[0]["rank"])
        self.assertEqual(rows[0]["identity_confidence"], "unresolved")

    def test_an_unmapped_surface_is_skipped_rather_than_given_a_role(self) -> None:
        # Defaulting an unknown surface into a role is how a weak signal quietly
        # acquires a strong name.
        self.assertEqual(se.declared_interest_rows(
            [{"business_unit": "X", "event_id": "1", "vendor_name_raw": "ACME",
              "source_key": "some_new_portal"}]), [])

    def test_a_planholder_resolves_to_a_competitor_and_a_record(self) -> None:
        # Exporting the participation without the rows it points at is how 2,703
        # dangling competitor references happened the first time.
        declared = [{"business_unit": "PB14424", "event_id": "122502",
                     "vendor_name_raw": "ACME", "vendor_id": 1,
                     "source_key": "planetbids_agency_portal"}]
        part = se.declared_interest_rows(declared)[0]
        self.assertIn(part["competitor_id"],
                      {c["id"] for c in se.observed_competitor_rows(declared)})
        self.assertIn(part["record_id"],
                      {r["id"] for r in se.event_record_rows([], participants=declared)})

    def test_a_document_whose_event_left_the_feed_still_has_a_record(self) -> None:
        # The document corpus accumulates across runs; the feed lists only what is open
        # today. An event that closes between two runs leaves its already-downloaded
        # documents parentless -- 34 of them in the first real corpus the audit ran on.
        closed = {"business_unit": "3600", "event_id": "0000040132",
                  "displayed_filename": "RFQ-2026-IDR6-002.docx"}
        records = se.event_record_rows([], target=None, documents=[closed])
        doc = se.document_rows([closed])[0]
        self.assertIn(doc["record_id"], {r["id"] for r in records},
                      "the document we retrieved points at a solicitation nothing emits")

    def test_a_document_on_a_still_listed_event_adds_no_second_record(self) -> None:
        feed = [{"business_unit": "3600", "event_id": "0000040132"}]
        records = se.event_record_rows(
            feed, target=None,
            documents=[{"business_unit": "3600", "event_id": "0000040132"}])
        self.assertEqual(len(records), 1)

    def test_a_city_solicitation_is_recorded_under_its_own_source(self) -> None:
        records = se.event_record_rows([], target=None, participants=[self.SF])
        self.assertEqual(records[0]["source_key"], "sfpublicworks_bid_tabulation")

    def test_no_duplicate_record_for_a_solicitation_already_in_the_feed(self) -> None:
        feed = [{"business_unit": "2660", "event_id": "08A3933"}]
        records = se.event_record_rows(feed, target=None, participants=[self.CALTRANS])
        self.assertEqual(len(records), 1)


class ReferentialIntegrityTests(unittest.TestCase):
    """Ordering was already enforced; existence was not, and that is where rows dangled."""

    def test_no_participant_or_payload_references_a_record_that_is_not_emitted(self) -> None:
        target = {"business_unit": "2740", "event_id": "0000040075",
                  "department": "Department of Motor Vehicles"}
        participants = [
            {"business_unit": "2660", "event_id": "08A3933", "vendor_name_raw": "Apex",
             "source_key": "caltrans_bid_results"},
            {"business_unit": "SFPW", "event_id": "0000007165",
             "vendor_name_raw": "Ronan", "source_key": "sfpublicworks_bid_tabulation"},
            {"business_unit": "2740", "event_id": "0000040075", "vendor_name_raw": "Aviate"},
        ]
        # A feed that carries none of them, which is the state after an event closes.
        records = se.event_record_rows([], target=target, participants=participants)
        emitted = {r["id"] for r in records}

        for row in se.participant_rows(participants, []):
            with self.subTest(vendor=row["competitor_id"]):
                self.assertIn(row["record_id"], emitted)

        payload = se.partner_match_rows([{"opportunity": target, "prime_candidates": []}])[0]
        self.assertIn(payload["record_id"], emitted)

class DerivedRankAndPlatformIdTests(unittest.TestCase):
    """Fields a newer source carries that the export was quietly dropping."""

    STATED = {"business_unit": "2660", "event_id": "08A3933", "rank": 1,
              "vendor_name_raw": "Ware Disposal Inc.", "amount_numeric": 436020.0,
              "source_key": "caltrans_bid_results"}
    DERIVED = {"business_unit": "PB14424", "event_id": "122502", "rank": None,
               "derived_rank": 1, "vendor_name_raw": "SS+K Construction Inc.",
               "amount_numeric": 3916068.0, "vendor_id": 1057345,
               "source_key": "planetbids_agency_portal"}

    def test_a_derived_rank_is_exported_rather_than_dropped(self) -> None:
        # PlanetBids publishes amounts and leaves ranking at 0, so the low bidder is
        # knowable. Exporting rank as null threw that away on 353 of 521 rows.
        row = se.participant_rows([self.DERIVED], [])[0]
        self.assertEqual(row["rank"], 1)

    def test_a_derived_rank_is_labelled_as_derived(self) -> None:
        row = se.participant_rows([self.DERIVED], [])[0]
        self.assertEqual(row["rank_basis"], "derived_from_amount")

    def test_a_stated_rank_is_labelled_as_stated(self) -> None:
        row = se.participant_rows([self.STATED], [])[0]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["rank_basis"], "stated")

    def test_a_row_with_neither_has_no_rank_and_no_basis(self) -> None:
        bare = {**self.DERIVED, "rank": None, "derived_rank": None}
        row = se.participant_rows([bare], [])[0]
        self.assertIsNone(row["rank"])
        self.assertIsNone(row["rank_basis"])

    def test_a_platform_vendor_id_is_namespaced_by_its_source(self) -> None:
        # It deduplicates a vendor across that platform's agencies and does NOT cross
        # into SCPRS supplier_id, so it must never sit in a field implying it does.
        row = se.participant_rows([self.DERIVED], [])[0]
        self.assertEqual(row["evidence"]["platform_vendor_id"],
                         {"planetbids_agency_portal": 1057345})
        self.assertNotEqual(row["competitor_id"], 1057345)

    def test_a_source_without_a_platform_id_carries_none(self) -> None:
        row = se.participant_rows([self.STATED], [])[0]
        self.assertIsNone(row["evidence"]["platform_vendor_id"])

class ObservedCompetitorTests(unittest.TestCase):
    """A company we watched bid is a competitor, even without a state supplier id.

    `competitor_rows` was built from award history only, so every observed bidder that
    could not be matched to SCPRS got a competitor id minted for it by `participant_rows`
    and nothing emitted the row. Measured on a real export: 2,703 participant rows
    pointing at 1,786 competitor records that did not exist. The companies were in the
    data and unreachable from it.
    """

    OBSERVED = [
        {"vendor_name_raw": "SS+K Construction Inc.", "business_unit": "PB14424",
         "event_id": "122502", "source_key": "planetbids_agency_portal",
         "vendor_id": 1057345, "classifications": ["WBE", "OSB"]},
        {"vendor_name_raw": "SS+K Construction Inc.", "business_unit": "PB14424",
         "event_id": "122503", "source_key": "planetbids_agency_portal",
         "vendor_id": 1057345, "classifications": ["WBE", "OSB"]},
        {"vendor_name_raw": "Ware Disposal Inc.", "business_unit": "2660",
         "event_id": "08A3933", "source_key": "caltrans_bid_results"},
        {"vendor_name_raw": "RESOLVED CO", "supplier_id": "0000005196",
         "source_key": "caltrans_bid_results"},
    ]

    def _rows(self):
        return se.observed_competitor_rows(self.OBSERVED)

    def test_one_row_per_distinct_vendor_not_per_observation(self) -> None:
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["legal_name"] for r in rows},
                         {"SS+K Construction Inc.", "Ware Disposal Inc."})

    def test_a_vendor_already_resolved_to_a_supplier_id_is_not_duplicated(self) -> None:
        # It already has a competitor row from the award-history side.
        self.assertNotIn("RESOLVED CO", {r["legal_name"] for r in self._rows()})

    def test_the_id_matches_what_the_participant_row_references(self) -> None:
        # This is the whole fix: the ids have to agree, or the reference still dangles.
        participant = se.participant_rows([self.OBSERVED[0]], [])[0]
        emitted = {r["id"] for r in self._rows()}
        self.assertIn(participant["competitor_id"], emitted)

    def test_an_observed_competitor_is_an_unresolved_stub(self) -> None:
        # Observed is not profiled, and saying otherwise would imply award history we
        # do not have.
        row = next(r for r in self._rows() if r["legal_name"] == "Ware Disposal Inc.")
        self.assertEqual(row["profile_status"], "stub")
        self.assertEqual(row["identity_confidence"], "unresolved")
        self.assertIsNone(row["external_source_id"])

    def test_a_platform_id_is_carried_but_never_as_a_state_supplier_id(self) -> None:
        row = next(r for r in self._rows() if r["legal_name"].startswith("SS+K"))
        self.assertEqual(row["public_identifiers"],
                         {"planetbids_agency_portal_vendor_id": 1057345})
        self.assertNotIn("scprs_supplier_id", row["public_identifiers"])

    def test_certifications_observed_on_the_bid_are_kept(self) -> None:
        row = next(r for r in self._rows() if r["legal_name"].startswith("SS+K"))
        self.assertEqual(sorted(row["certifications"]), ["OSB", "WBE"])

    def test_the_export_has_no_dangling_competitor_references(self) -> None:
        """The end state, asserted end to end.

        Both competitor sources are needed: award history covers resolved vendors,
        this covers observed ones. Either alone leaves references dangling, which is
        how the defect survived -- only the first was emitted.
        """
        from sled_trial import evidence

        participants = se.participant_rows(self.OBSERVED, [])
        competitors = self._rows() + se.competitor_rows([
            {"supplier_id": "0000005196", "canonical_name": "RESOLVED CO"}])
        report = evidence.audit({
            "gov_procurement_records": [{"id": p["record_id"]} for p in participants],
            "gov_competitors": competitors,
            "gov_procurement_participants": participants,
        })
        self.assertEqual(report["dangling_references"], 0)

    def test_observed_rows_alone_are_not_enough(self) -> None:
        # Stated explicitly so nobody removes the award-history source thinking this
        # one supersedes it.
        from sled_trial import evidence

        participants = se.participant_rows(self.OBSERVED, [])
        report = evidence.audit({
            "gov_procurement_records": [{"id": p["record_id"]} for p in participants],
            "gov_competitors": self._rows(),
            "gov_procurement_participants": participants,
        })
        self.assertEqual(report["dangling_references"], 1)


if __name__ == "__main__":
    unittest.main()
