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


if __name__ == "__main__":
    unittest.main()


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
