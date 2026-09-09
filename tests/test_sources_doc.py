"""The sources doc must cover every registry surface, and the registry must cover the brief.

Two README-named sources went missing from the registry during a rewrite, and because the
prose about our sources lived separately, nothing caught it. These tests close that loop.
"""
import csv
import pathlib
import unittest

from sled_trial import sources_doc

REPO = pathlib.Path(__file__).parent.parent
REGISTRY = REPO / "sources" / "source_registry.csv"
DOC = REPO / "docs" / "SOURCES.md"

# The eight source families README names, mapped to our registry keys. If the brief names a
# source and we have no row for it, that is a hole in the source-discovery deliverable.
README_FAMILIES = {
    "Cal eProcure public search": "caleprocure_aspx_wrapper",
    "Response Bid Inquiry": "caleprocure_response_bid_inquiry",
    "Cal eProcure supplier search": "caleprocure_supplier_search",
    "SCPRS contract search": "caleprocure_scprs",
    "Leveraged Procurement Agreement search": "caleprocure_lpa",
    "Open FI$Cal department vendor transactions": "openfiscal_dept_vendor_tx",
    "DGS historical contracts data": "dgs_historical_contracts",
    "California procurement datasets": "data_ca_gov_purchase_orders",
}


def registry_keys() -> set[str]:
    with REGISTRY.open(encoding="utf-8") as handle:
        return {row["source_key"] for row in csv.DictReader(handle)}


class RegistryCoversTheBriefTests(unittest.TestCase):
    def test_every_readme_named_source_has_a_registry_row(self) -> None:
        keys = registry_keys()
        for label, key in README_FAMILIES.items():
            with self.subTest(source=label):
                self.assertIn(key, keys, f"README names {label} but the registry has no row")

    def test_the_registry_has_no_blank_official_urls(self) -> None:
        with REGISTRY.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                with self.subTest(source=row["source_key"]):
                    self.assertTrue(row["official_url"].strip())

    def test_every_row_records_when_it_was_verified(self) -> None:
        with REGISTRY.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                with self.subTest(source=row["source_key"]):
                    self.assertRegex(row["verified_on"], r"^\d{4}-\d{2}-\d{2}$")


class DocCoversTheRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = sources_doc.generate(REGISTRY)

    def test_every_registry_surface_appears_in_the_doc(self) -> None:
        # The doc renders source_name, not source_key, so assert on what it actually prints.
        with REGISTRY.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                with self.subTest(source=row["source_key"]):
                    self.assertIn(row["source_name"], self.text,
                                  f"{row['source_key']} is in the registry but not the doc")

    def test_every_endpoint_url_appears(self) -> None:
        with REGISTRY.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                with self.subTest(source=row["source_key"]):
                    self.assertIn(row["official_url"], self.text)

    def test_the_browser_versus_endpoint_distinction_is_explained(self) -> None:
        # This is the finding that cost a day; it must not be dropped from the doc.
        self.assertIn("JavaScript shells that carry no data", self.text)
        self.assertIn("bare `.GBL`", self.text)

    def test_the_login_trap_is_documented(self) -> None:
        self.assertIn("redirects to a login", self.text)
        self.assertIn("FolderPath", self.text)

    def test_it_states_no_credential_is_needed(self) -> None:
        self.assertIn("no browser, API key or credential is needed", self.text)

    def test_the_checked_in_doc_covers_every_current_source(self) -> None:
        """The committed doc must list every source, but need not be byte-identical.

        An earlier version of this test demanded exact equality with the generator output.
        That was wrong: it makes the doc unimprovable, because any human edit to the prose
        fails the build. The drift that actually mattered was a *source* going missing, not
        a sentence being reworded, so this asserts coverage of the committed file instead.
        """
        self.assertTrue(DOC.exists(), "docs/SOURCES.md is missing")
        committed = DOC.read_text()
        with REGISTRY.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                with self.subTest(source=row["source_key"]):
                    self.assertIn(row["source_name"], committed,
                                  f"{row['source_key']} is in the registry but missing from "
                                  f"the committed docs/SOURCES.md")
                    self.assertIn(row["official_url"], committed)


if __name__ == "__main__":
    unittest.main()
