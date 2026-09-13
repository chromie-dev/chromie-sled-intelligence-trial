"""Offline tests for the CSU public bid portal. No network.

Markup below is the shape the Award tab returned live for SSU-IFB-00000823.
"""
import pathlib
import unittest

from sled_trial.sources.ca import csu

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "csu_award_rows.html"
# Captured verbatim from the live Award tab. An earlier hand-written fixture used
# single-quoted attributes and invented class names, so every test passed while the
# parser returned zero rows against the real site.
ROW = FIXTURE.read_text(encoding="utf-8")


class ParseTests(unittest.TestCase):
    def test_rows_parse_with_status_and_identity(self) -> None:
        rows = csu.parse_solicitations(ROW, tab="awarded")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "Awarded")
        self.assertEqual(rows[0]["event_id"], "SSU-IFB-00000823")
        self.assertEqual(rows[0]["title"], "The Gardens at Campus Rec")

    def test_the_header_row_is_not_a_solicitation(self) -> None:
        self.assertEqual(len(csu.parse_solicitations(ROW)), 2)

    def test_dates_type_and_buyer_are_captured(self) -> None:
        row = csu.parse_solicitations(ROW)[0]
        self.assertEqual(row["opens"], "7/6/2026, 9:30 AM PDT")
        self.assertEqual(row["closes"], "8/3/2026, 2:00 PM PDT")
        self.assertEqual(row["solicitation_type"], "IFB")
        self.assertEqual(row["buyer"], "Carolyn Faulconer")

    def test_the_buyer_email_on_the_page_is_not_stored(self) -> None:
        # The Contact cell renders as "Name address@campus.edu". README puts private
        # contact enrichment out of scope, so the name is kept and the address is not.
        for row in csu.parse_solicitations(ROW):
            for value in row.values():
                self.assertNotIn("@", str(value))

    def test_the_event_pdf_is_captured(self) -> None:
        self.assertIn("s3.amazonaws.com",
                      csu.parse_solicitations(ROW)[0]["event_pdf_url"])

    def test_a_second_row_parses_independently(self) -> None:
        # Label classes vary between rows, so pairing must be positional rather than
        # keyed on a class name.
        row = csu.parse_solicitations(ROW)[1]
        self.assertEqual(row["event_id"], "CSUCO-RFQUAL-00000821")
        self.assertEqual(row["solicitation_type"], "RFQUAL")
        self.assertEqual(row["buyer"], "Erika Takenaka")

    def test_the_free_text_description_is_captured(self) -> None:
        self.assertIn("Sonoma State University",
                      csu.parse_solicitations(ROW)[0]["description"])


class CampusTests(unittest.TestCase):
    """The campus is encoded in the solicitation number, nowhere else on the row."""

    def test_campus_is_read_from_the_number(self) -> None:
        self.assertEqual(csu.campus_of("SSU-IFB-00000823"), "SSU")
        self.assertEqual(csu.campus_of("SJSU-RFP-00000834-2026"), "SJSU")
        self.assertEqual(csu.campus_of("CSUMB-RFP-00000829"), "CSUMB")

    def test_the_chancellors_office_is_not_a_campus_but_still_resolves(self) -> None:
        self.assertEqual(csu.campus_of("CSUCO-RFP-00000001"), "CSUCO")

    def test_an_unparseable_number_yields_none_rather_than_a_guess(self) -> None:
        self.assertIsNone(csu.campus_of("12345"))
        self.assertIsNone(csu.campus_of(None))


class ScopeTests(unittest.TestCase):
    """The Award tab marks status; it never names the winner."""

    def test_rows_state_that_no_awardee_is_published(self) -> None:
        # The detail page behind each row redirects to a supplier login, so a consumer
        # must not read `status: Awarded` as award data.
        for row in csu.parse_solicitations(ROW, tab="awarded"):
            self.assertFalse(row["names_awardee"])

    def test_an_unknown_tab_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            csu.tab_url("nonsense")

    def test_every_lifecycle_tab_is_addressable(self) -> None:
        self.assertEqual(set(csu.TABS),
                         {"open", "closed", "awarded", "upcoming", "all"})


class HarvestTests(unittest.TestCase):
    def test_pages_stop_when_nothing_new_appears(self) -> None:
        calls = []

        def fetch(url):
            calls.append(url)
            return ROW

        out = csu.harvest(fetch, tabs=("awarded",))
        # page 1 yields two, page 2 repeats them and ends the tab
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(len(calls), 2)

    def test_solicitations_are_not_double_counted_across_tabs(self) -> None:
        out = csu.harvest(lambda url: ROW, tabs=("open", "awarded"))
        self.assertEqual(len(out["rows"]), 2)

    def test_campuses_are_reported(self) -> None:
        out = csu.harvest(lambda url: ROW, tabs=("awarded",))
        self.assertEqual(out["campuses"], ["CSUCO", "SSU"])

    def test_a_failing_tab_is_recorded_not_read_as_empty(self) -> None:
        def fetch(url):
            raise OSError("connection reset")

        out = csu.harvest(fetch, tabs=("awarded",))
        self.assertEqual(out["rows"], [])
        self.assertEqual(len(out["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
