"""The mapping document claims to agree with the module. Assert that it does.

docs/supabase_mapping.md is hand-written prose, so it can drift from
src/sled_trial/supabase_export.py silently. These tests fail when it does, which is the only
reason the document is trustworthy enough to hand to a reviewer.
"""
import pathlib
import re
import unittest

from sled_trial import supabase_export as se

DOC = pathlib.Path(__file__).parent.parent / "docs" / "supabase_mapping.md"


class DocumentExistsTests(unittest.TestCase):
    def test_the_document_is_present(self) -> None:
        self.assertTrue(DOC.exists(), "docs/supabase_mapping.md is required by the brief")


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text()

    def test_every_table_is_documented(self) -> None:
        for table in se.TABLES:
            with self.subTest(table=table):
                self.assertIn(table, self.text)

    def test_import_order_in_the_doc_matches_the_module(self) -> None:
        # The doc numbers its import table 1..7; extract in order and compare.
        rows = re.findall(r"^\| *(\d+) *\| *`([a-z_]+)` *\|", self.text, re.M)
        documented = [table for _, table in sorted(rows, key=lambda r: int(r[0]))]
        self.assertEqual(documented, se.handoff_manifest()["import_order"])

    def test_every_natural_key_field_is_documented(self) -> None:
        for table, keys in se.NATURAL_KEYS.items():
            for key in keys:
                with self.subTest(table=table, key=key):
                    self.assertIn(f"`{key}`", self.text)

    def test_unresolved_production_ids_are_listed(self) -> None:
        for field in se.handoff_manifest()["production_ids_unresolved"]:
            with self.subTest(field=field):
                self.assertIn(field, self.text)

    def test_the_local_namespace_is_published(self) -> None:
        self.assertIn(str(se.NAMESPACE), self.text)

    def test_required_sections_are_present(self) -> None:
        # The trial author asked for these six specifically.
        for heading in ("## Tables", "## Relationships", "## Import order",
                        "## Natural upsert keys", "## Conflict behaviour",
                        "## Local-to-production ID mapping"):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.text)

    def test_assumptions_and_validation_gaps_are_documented(self) -> None:
        # "document assumptions and validation gaps" was an explicit instruction.
        self.assertIn("## Assumptions", self.text)
        self.assertIn("## Validation gaps", self.text)


class HonestyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text()
        # Prose is hard-wrapped, so phrase assertions must ignore line breaks.
        self.flat = re.sub(r"\s+", " ", self.text)

    def test_it_does_not_claim_production_compatibility(self) -> None:
        self.assertIn("proposed, not production", self.text.lower())
        self.assertNotIn("production-compatible", self.text.lower())

    def test_the_evidence_class_ladder_is_stated(self) -> None:
        self.assertIn("never overwrite a stronger `evidence_class` with a weaker one",
                      self.flat)
        self.assertIn("`observed` > `derived` > `predicted`", self.flat)

    def test_it_states_that_no_script_writes_to_supabase(self) -> None:
        self.assertIn("No script in this repository points at", self.flat)


if __name__ == "__main__":
    unittest.main()
