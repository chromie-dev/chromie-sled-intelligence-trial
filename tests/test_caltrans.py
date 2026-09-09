"""Offline tests for the Caltrans bid-results adapter. No network.

The markup below mirrors a real weekly page: a row per contract, the contract number
linking to its Cal eProcure event, and an ordered list of bidders where list position is
the rank.
"""
import datetime as dt
import unittest

from sled_trial.sources.ca import caltrans

WEEK_PAGE = """
<h1>Bid Results: Week of January 11, 2026</h1>
<table class="table">
  <thead><tr><th>Date</th><th>Contract No.</th><th>Service, Bidder Information</th></tr></thead>
  <tbody>
    <tr>
      <td>1/13</td>
      <td><a href="https://caleprocure.ca.gov/event/2660/07A6272">07A6272</a></td>
      <td>
      <p>IFB 07A6272 Equipment Maintenance &amp; Repair Services, Los Angeles County&nbsp;</p>
      <ol>
        <li>CraneTech Inc.<br />
        SB: N<br />
        $406,911.00</li>
      </ol>
      </td>
    </tr>
    <tr>
      <td>1/13</td>
      <td><a href="https://caleprocure.ca.gov/event/2660/08A3933">08A3933</a></td>
      <td>
      <p>IFB - Trash Collecting, Hauling, and Disposal Services</p>
      <ol>
        <li>Ware Disposal Inc.<br />
        SB: N<br />
        $436,020.00</li>
        <li>Apex Waste Systems Inc.<br />
        SB: Y<br />
        $480,480.00</li>
        <li>Burrtec Waste Industries, Inc.<br />
        SB: N<br />
        $801,571.80</li>
      </ol>
      </td>
    </tr>
  </tbody>
</table>
"""


class ParseTests(unittest.TestCase):
    def test_every_bidder_is_returned_not_only_the_winner(self) -> None:
        # The whole point of this source: California's state portal exposes awardees, and
        # this page exposes the companies that lost too.
        results = caltrans.parse_bid_results(WEEK_PAGE)
        trash = next(r for r in results if r["event_id"] == "08A3933")
        self.assertEqual([b["vendor_name"] for b in trash["bidders"]],
                         ["Ware Disposal Inc.", "Apex Waste Systems Inc.",
                          "Burrtec Waste Industries, Inc."])

    def test_rank_comes_from_list_position(self) -> None:
        results = caltrans.parse_bid_results(WEEK_PAGE)
        trash = next(r for r in results if r["event_id"] == "08A3933")
        self.assertEqual([b["rank"] for b in trash["bidders"]], [1, 2, 3])

    def test_amounts_keep_the_raw_string_and_a_numeric_form(self) -> None:
        results = caltrans.parse_bid_results(WEEK_PAGE)
        low = next(r for r in results if r["event_id"] == "08A3933")["bidders"][0]
        self.assertEqual(low["bid_amount_raw"], "$436,020.00")
        self.assertEqual(low["bid_amount"], 436020.0)

    def test_small_business_preference_is_captured_as_a_flag(self) -> None:
        results = caltrans.parse_bid_results(WEEK_PAGE)
        bidders = next(r for r in results if r["event_id"] == "08A3933")["bidders"]
        self.assertEqual([b["small_business_preference"] for b in bidders],
                         [False, True, False])

    def test_rows_carry_the_cal_eprocure_identity(self) -> None:
        # Business unit plus event id is the pair the rest of the pipeline joins on, and
        # here it is exact rather than inferred.
        results = caltrans.parse_bid_results(WEEK_PAGE)
        self.assertEqual({r["business_unit"] for r in results}, {"2660"})
        self.assertEqual({r["event_id"] for r in results}, {"07A6272", "08A3933"})

    def test_single_bidder_contracts_are_kept(self) -> None:
        results = caltrans.parse_bid_results(WEEK_PAGE)
        solo = next(r for r in results if r["event_id"] == "07A6272")
        self.assertEqual(len(solo["bidders"]), 1)

    def test_a_page_with_no_bid_table_yields_nothing(self) -> None:
        self.assertEqual(caltrans.parse_bid_results("<h1>Bid Results</h1>"), [])


class SoftNotFoundTests(unittest.TestCase):
    """An unpopulated week returns HTTP 200 and an empty shell, not a 404."""

    def test_a_populated_page_is_recognised(self) -> None:
        self.assertTrue(caltrans.looks_populated(WEEK_PAGE))

    def test_an_empty_shell_is_not_mistaken_for_a_week_with_no_bids(self) -> None:
        # This is the difference between "nobody bid that week" and "that page does not
        # exist". Recording the first when the truth is the second invents a fact.
        shell = "<html><body><h1>Bid Results</h1><p>Public bid openings are held every "
        shell += "Tuesday and Thursday.</p></body></html>"
        self.assertFalse(caltrans.looks_populated(shell))


class WeekEnumerationTests(unittest.TestCase):
    def test_slugs_are_the_week_start_sundays_covering_the_range(self) -> None:
        # Pages are dated to the Sunday their week begins -- the page for 2026-01-11
        # carries bids opened on Tuesday 1/13. A Monday slug silently returns the empty
        # shell, so this cannot be "every seven days from any start date".
        slugs = list(caltrans.week_slugs(dt.date(2026, 1, 7), dt.date(2026, 1, 26)))
        self.assertEqual(slugs, ["2026-01-04", "2026-01-11", "2026-01-18", "2026-01-25"])

    def test_a_range_inside_one_week_yields_that_weeks_sunday(self) -> None:
        # Monday the 12th belongs to the week that began Sunday the 11th. Rounding forward
        # instead would skip the page holding that week's bids entirely.
        slugs = list(caltrans.week_slugs(dt.date(2026, 1, 12), dt.date(2026, 1, 13)))
        self.assertEqual(slugs, ["2026-01-11"])

    def test_an_inverted_range_yields_nothing(self) -> None:
        self.assertEqual(list(caltrans.week_slugs(dt.date(2026, 2, 1),
                                                  dt.date(2026, 1, 1))), [])


class FakeSession:
    """Stands in for the network only. Returns canned bytes per URL."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str, referer: str | None = None, timeout: int = 120):
        self.requested.append(url)
        return self.pages.get(url, SHELL).encode(), {}


SHELL = "<html><body><h1>Bid Results</h1><p>Public bid openings.</p></body></html>"


class HarvestTests(unittest.TestCase):
    def _session(self) -> FakeSession:
        return FakeSession(
            {caltrans.WEEK_URL.format(date="2026-01-11"): WEEK_PAGE})

    def test_solicitations_come_back_from_the_populated_week(self) -> None:
        out = caltrans.harvest(self._session(), dt.date(2026, 1, 11), dt.date(2026, 1, 25))
        self.assertEqual({s["event_id"] for s in out["solicitations"]},
                         {"07A6272", "08A3933"})

    def test_an_empty_week_is_recorded_as_no_page_not_as_no_bids(self) -> None:
        # The distinction the whole source hinges on: the site answers 200 with a shell
        # for a week it never published, and calling that "zero bidders" invents a fact.
        out = caltrans.harvest(self._session(), dt.date(2026, 1, 11), dt.date(2026, 1, 25))
        self.assertEqual(out["weeks_populated"], ["2026-01-11"])
        self.assertEqual(out["weeks_absent"], ["2026-01-18", "2026-01-25"])

    def test_every_week_in_range_is_requested_once(self) -> None:
        session = self._session()
        caltrans.harvest(session, dt.date(2026, 1, 11), dt.date(2026, 1, 25))
        self.assertEqual(len(session.requested), 3)


class BidderCandidateTests(unittest.TestCase):
    def _candidates(self) -> list:
        return caltrans.bidder_candidates(caltrans.parse_bid_results(WEEK_PAGE))

    def test_one_row_per_bidder_carrying_the_event_identity(self) -> None:
        rows = self._candidates()
        self.assertEqual(len(rows), 4)
        self.assertEqual({r["business_unit"] for r in rows}, {"2660"})

    def test_rows_use_the_field_names_the_participant_export_reads(self) -> None:
        # Emitting into the existing observed-candidate shape means these flow through
        # supabase_export.participant_rows without a second code path.
        row = next(r for r in self._candidates() if r["vendor_name_raw"] == "Ware Disposal Inc.")
        self.assertEqual(row["amount_raw"], "$436,020.00")
        self.assertEqual(row["amount_numeric"], 436020.0)
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["source_key"], "caltrans_bid_results")

    def test_the_evidence_row_records_where_the_claim_came_from(self) -> None:
        # Every material claim has to cite a retrievable source, and for this one the
        # source is the weekly page rather than a document and page number.
        rows = caltrans.bidder_candidates(caltrans.parse_bid_results(WEEK_PAGE),
                                          week="2026-01-11")
        low = next(r for r in rows if r["vendor_name_raw"] == "Ware Disposal Inc.")
        self.assertEqual(low["evidence_url"],
                         caltrans.WEEK_URL.format(date="2026-01-11"))
        self.assertEqual(low["evidence_row"], "Ware Disposal Inc. | SB: N | $436,020.00")


if __name__ == "__main__":
    unittest.main()
