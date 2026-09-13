"""The registry must cover the brief, and the committed doc must cover the registry.

Two README-named sources went missing from the registry during a rewrite, and because the
prose about our sources lived separately, nothing caught it. These tests close that loop.
"""
import csv
import pathlib
import unittest


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
    def test_the_checked_in_doc_covers_every_current_source(self) -> None:
        """The committed doc must list every source, but need not be byte-identical.

        Coverage rather than equality: the drift that matters is a source going missing,
        not a sentence being reworded, and demanding exact text would make the prose
        unimprovable.
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
