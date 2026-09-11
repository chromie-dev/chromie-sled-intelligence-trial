"""Offline tests for the CSLB contractor register. No network."""
import pathlib
import tempfile
import unittest

from sled_trial.sources.ca import cslb

HEADER = "LicenseNo,BusinessName,FullBusinessName,City,State,County,ZIPCode,BusinessType,PrimaryStatus,IssueDate,ExpirationDate\n"
ROWS = ("1000002,DOCKERY RANDALL MARK,DOCKERY RANDALL MARK,LODI,CA,SAN JOAQUIN,95240,Sole Owner,CLEAR,01/02/1990,01/31/2027\n"
        "1155122,AI FENCE & RESTORATION,AI FENCE & RESTORATION,SANTA ANA,CA,ORANGE,92703,Corporation,CLEAR,03/01/2024,03/31/2028\n")


def write(text: str) -> pathlib.Path:
    tmp = pathlib.Path(tempfile.mkdtemp()) / "cslb.csv"
    tmp.write_text(text)
    return tmp


class VerifyTests(unittest.TestCase):
    """A truncated register parses perfectly and is still missing most of California."""

    def test_a_whole_file_is_complete(self) -> None:
        report = cslb.verify(write(HEADER + ROWS))
        self.assertTrue(report["complete"])
        self.assertEqual(report["rows"], 2)
        self.assertEqual(report["columns"], 11)

    def test_a_file_torn_mid_row_is_not_complete(self) -> None:
        # The real failure: 50,077 of ~290,000 rows arrived, header intact, every row
        # valid. Nothing about the content says it is a fragment except the last line.
        report = cslb.verify(write(HEADER + ROWS + "1084223,TOWNSLEY ALEX,TOWNS"))
        self.assertFalse(report["complete"])
        self.assertIn("torn", report["reason"])

    def test_a_missing_file_is_not_complete(self) -> None:
        self.assertFalse(cslb.verify("/nonexistent/cslb.csv")["complete"])

    def test_an_empty_file_is_not_complete(self) -> None:
        self.assertFalse(cslb.verify(write(""))["complete"])


class ReadTests(unittest.TestCase):
    def test_only_the_identity_columns_are_kept(self) -> None:
        rows = list(cslb.read_licences(write(HEADER + ROWS)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), set(cslb.KEEP))

    def test_the_index_is_keyed_by_licence_number(self) -> None:
        # This is the key vendor ads cite in free text and bid tabulations do not carry.
        index = cslb.index_by_licence(cslb.read_licences(write(HEADER + ROWS)))
        self.assertIn("1155122", index)
        self.assertEqual(index["1155122"]["BusinessName"], "AI FENCE & RESTORATION")

    def test_a_row_without_a_licence_number_is_not_indexed(self) -> None:
        index = cslb.index_by_licence([{"LicenseNo": "", "BusinessName": "X"}])
        self.assertEqual(index, {})


class ConfigTests(unittest.TestCase):
    def test_an_unknown_file_is_refused_before_any_request(self) -> None:
        with self.assertRaises(ValueError):
            cslb.download(None, "nonsense")

    def test_all_three_published_files_are_addressable(self) -> None:
        self.assertEqual(set(cslb.FILES), {"license_master", "workers_comp", "personnel"})


if __name__ == "__main__":
    unittest.main()
