import unittest

from sled_trial.pipeline import canonical_id, normalize


class PipelineTests(unittest.TestCase):
    def test_canonical_id_is_stable(self) -> None:
        self.assertEqual(canonical_id("Example City", "RFP-1"), canonical_id(" example city ", "rfp-1"))


    def test_normalize_preserves_provenance(self) -> None:
        item = normalize({
            "source_id": "x",
            "source_url": "https://example.invalid/x",
            "solicitation": "RFP-1",
            "title": "Test",
            "agency": "Agency",
            "jurisdiction": "CA",
            "observed_at": "2026-09-01T00:00:00Z",
        })
        self.assertEqual(item.source_ids, ("x",))
        self.assertEqual(item.status, "unknown")


    def test_missing_source_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize({"title": "Incomplete"})


if __name__ == "__main__":
    unittest.main()
