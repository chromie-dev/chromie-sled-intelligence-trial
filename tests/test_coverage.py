"""Tests for the unified coverage report.

The point of this report is that "we never ran it", "we ran it and got nothing", and
"we ran it and fell short of what the portal claims" are three different answers. The
tests exist to keep them apart.
"""
import json
import pathlib
import tempfile
import unittest

from sled_trial import assemble


class CoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def _write(self, name: str, payload) -> None:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".jsonl"):
            path.write_text("".join(json.dumps(r) + "\n" for r in payload))
        else:
            path.write_text(json.dumps(payload))

    def _coverage(self):
        return assemble.unified_coverage(self.tmp, registry_csv="sources/source_registry.csv")

    def test_every_registered_source_appears_even_if_never_run(self) -> None:
        cov = self._coverage()
        self.assertEqual(cov["sources_tracked"], len(assemble.COVERAGE_SOURCES))
        self.assertEqual(cov["sources_harvested"], 0)
        self.assertIn("caleprocure_scprs", cov["sources_never_harvested"])

    def test_never_harvested_is_not_the_same_as_harvested_and_empty(self) -> None:
        # An absent cache means the step never ran. An empty one means it ran and found
        # nothing. Reporting both as zero hides which.
        (self.tmp / "sf_bidders.jsonl").write_text("")
        by_key = {e["source_key"]: e for e in self._coverage()["sources"]}
        ran = by_key["sfpublicworks_bid_tabulation"]
        never = by_key["caltrans_bid_results"]
        # ran and found nothing
        self.assertTrue(ran["harvested"])
        self.assertEqual(ran["rows_on_disk"], 0)
        self.assertIsNotNone(ran["last_sync"])
        # never ran at all
        self.assertFalse(never["harvested"])
        self.assertIsNone(never["last_sync"])

    def test_a_shortfall_against_a_portal_total_is_reported(self) -> None:
        self._write("awards_coverage.json",
                    {"rows_collected": 1252, "rows_reported_by_portal": 3789,
                     "complete": False})
        self._write("awards.jsonl", [{"x": 1}] * 1252)
        entry = {e["source_key"]: e for e in self._coverage()["sources"]}["caleprocure_scprs"]
        self.assertEqual(entry["shortfall"], 2537)
        self.assertFalse(entry["complete"])

    def test_our_own_input_is_a_hit_rate_not_a_shortfall(self) -> None:
        # The supplier registry indexes certified suppliers only, so names we searched
        # is a denominator we chose. Calling the difference a shortfall would report the
        # registry as incomplete on every run forever.
        self._write("supplier_locations_coverage.json",
                    {"suppliers_indexed": 152, "names_searched": 698, "failures": []})
        self._write("supplier_locations.json", {"A": {}})
        entry = {e["source_key"]: e
                 for e in self._coverage()["sources"]}["caleprocure_supplier_search"]
        self.assertEqual(entry["reported_by_portal"], 698)
        self.assertFalse(entry["reported_is_portal_total"])
        self.assertIsNone(entry["shortfall"])

    def test_completeness_is_unknown_when_a_portal_states_no_total(self) -> None:
        # Unknown and incomplete are different. A source that never publishes a count
        # cannot be called short.
        self._write("csu_solicitations.jsonl", [{"x": 1}] * 577)
        entry = {e["source_key"]: e
                 for e in self._coverage()["sources"]}["csu_public_bid_portal"]
        self.assertIsNone(entry["complete"])
        self.assertIsNone(entry["shortfall"])

    def test_failures_are_totalled_across_sources(self) -> None:
        self._write("csu_coverage.json", {"failures": [{"tab": "open"}], "campuses": []})
        self._write("csu_solicitations.jsonl", [{"x": 1}])
        self.assertEqual(self._coverage()["total_failures"], 1)

    def test_last_sync_comes_from_the_most_recent_cache_write(self) -> None:
        self._write("caltrans_bidders.jsonl", [{"x": 1}])
        entry = {e["source_key"]: e
                 for e in self._coverage()["sources"]}["caltrans_bid_results"]
        self.assertIsNotNone(entry["last_sync"])
        self.assertTrue(entry["last_sync"].endswith("+00:00"))

    def test_static_research_is_joined_from_the_registry(self) -> None:
        entry = {e["source_key"]: e
                 for e in self._coverage()["sources"]}["planetbids_agency_portal"]
        self.assertEqual(entry["jurisdiction"], "California (local)")
        self.assertTrue(entry["known_gap"])
        self.assertTrue(entry["record_type"])


if __name__ == "__main__":
    unittest.main()
