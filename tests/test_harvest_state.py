"""Tests for the harvest watermark store.

The store exists so a backfill resumes rather than restarting, and so a killed run
costs one unit instead of an hour. The distinction it must never lose: a unit that
answered and had nothing is done; a unit that failed to answer is not.
"""
import datetime as dt
import pathlib
import tempfile
import unittest

from sled_trial import harvest_state as hs


class RoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_an_absent_store_is_empty_not_an_error(self) -> None:
        self.assertEqual(hs.load(self.tmp), {"sources": {}})

    def test_state_survives_a_save_and_load(self) -> None:
        state = hs.load(self.tmp)
        hs.record(state, "caltrans_bid_results", "2026-01-11", rows=17)
        hs.save(self.tmp, state)
        self.assertTrue(hs.is_done(hs.load(self.tmp),
                                   "caltrans_bid_results", "2026-01-11"))

    def test_a_corrupt_store_degrades_to_refetching(self) -> None:
        # Refetching is what happened before this existed, so it is a safe failure.
        # Raising would let a bad file stop a harvest entirely.
        (self.tmp / hs.STATE_FILE).write_text("{not json")
        self.assertEqual(hs.load(self.tmp), {"sources": {}})


class OutcomeTests(unittest.TestCase):
    """An empty week and a failed week look identical in the data and are not."""

    def setUp(self) -> None:
        self.state = {"sources": {}}

    def test_a_unit_that_produced_rows_is_done(self) -> None:
        hs.record(self.state, "s", "u1", outcome=hs.OK, rows=5)
        self.assertTrue(hs.is_done(self.state, "s", "u1"))

    def test_a_unit_that_answered_and_had_nothing_is_also_done(self) -> None:
        # A Caltrans week with no bid openings answered correctly. Asking again every
        # run would spend the whole backfill budget re-confirming silence.
        hs.record(self.state, "s", "u2", outcome=hs.EMPTY, rows=0)
        self.assertTrue(hs.is_done(self.state, "s", "u2"))

    def test_a_unit_that_failed_is_not_done(self) -> None:
        hs.record(self.state, "s", "u3", outcome=hs.FAILED)
        self.assertFalse(hs.is_done(self.state, "s", "u3"))

    def test_an_unknown_unit_is_not_done(self) -> None:
        self.assertFalse(hs.is_done(self.state, "s", "never-seen"))

    def test_an_invalid_outcome_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            hs.record(self.state, "s", "u", outcome="probably-fine")


class PendingTests(unittest.TestCase):
    def test_pending_returns_only_what_is_still_worth_asking(self) -> None:
        state = {"sources": {}}
        hs.record(state, "s", "a", outcome=hs.OK, rows=3)
        hs.record(state, "s", "b", outcome=hs.EMPTY)
        hs.record(state, "s", "c", outcome=hs.FAILED)
        self.assertEqual(hs.pending(state, "s", ["a", "b", "c", "d"]), ["c", "d"])

    def test_order_is_preserved_so_a_backfill_stays_predictable(self) -> None:
        self.assertEqual(hs.pending({"sources": {}}, "s", ["3", "1", "2"]),
                         ["3", "1", "2"])


class StalenessTests(unittest.TestCase):
    """Closed history never changes; an open feed does."""

    def setUp(self) -> None:
        self.state = {"sources": {}}
        hs.record(self.state, "s", "u", outcome=hs.OK, rows=1)
        self.now = dt.datetime.now(dt.UTC)

    def test_without_a_window_an_answered_unit_is_done_forever(self) -> None:
        # A past week's bid results will not change.
        self.assertTrue(hs.is_done(self.state, "s", "u",
                                   now=self.now + dt.timedelta(days=3650)))

    def test_inside_the_window_it_is_still_fresh(self) -> None:
        self.assertTrue(hs.is_done(self.state, "s", "u", stale_after_days=7,
                                   now=self.now + dt.timedelta(days=3)))

    def test_past_the_window_it_needs_asking_again(self) -> None:
        self.assertFalse(hs.is_done(self.state, "s", "u", stale_after_days=7,
                                    now=self.now + dt.timedelta(days=9)))


class SummaryTests(unittest.TestCase):
    def test_summary_counts_outcomes_and_rows(self) -> None:
        state = {"sources": {}}
        hs.record(state, "caltrans", "w1", outcome=hs.OK, rows=17)
        hs.record(state, "caltrans", "w2", outcome=hs.EMPTY)
        hs.record(state, "caltrans", "w3", outcome=hs.FAILED)
        s = hs.summary(state)["caltrans"]
        self.assertEqual(s["units"], 3)
        self.assertEqual(s["rows"], 17)
        self.assertEqual(s["outcomes"], {hs.OK: 1, hs.EMPTY: 1, hs.FAILED: 1})

    def test_retryable_is_what_a_rerun_will_actually_do(self) -> None:
        state = {"sources": {}}
        hs.record(state, "s", "a", outcome=hs.EMPTY)
        hs.record(state, "s", "b", outcome=hs.FAILED)
        self.assertEqual(hs.summary(state)["s"]["retryable"], 1)



class DaysHeldTests(unittest.TestCase):
    """Is this window finished? That is a question about days, not about rows.

    A resumed month re-asks only its unheld days, so the rows it fetches are that
    run's yield and never the month's total. September logged 2,274 then 1,603, each
    marked complete, which reads as a contradiction to anyone but the author.
    """

    def _state(self, *keys):
        state = hs.load(pathlib.Path(tempfile.mkdtemp()))
        for key in keys:
            hs.record(state, "caleprocure_scprs", key, rows=1)
        return state

    def test_a_day_reached_by_subdivision_counts(self) -> None:
        # Most days are recorded pinned to an axis, not as a bare range.
        state = self._state(
            "from=09/01/2026|to=09/01/2026",
            "acq_method=Fair and Reasonable - COMPETITIVE|from=09/02/2026|to=09/02/2026")
        self.assertEqual(
            hs.days_held(state, "caleprocure_scprs",
                                    "09/01/2026", "09/03/2026"),
            ["09/01/2026", "09/02/2026"])

    def test_a_multi_day_range_is_not_a_day(self) -> None:
        # A bisected range delegates to its halves; counting it as covered would call
        # a window finished on the strength of work that was handed off.
        state = self._state("from=09/01/2026|to=09/03/2026")
        self.assertEqual(hs.days_held(state, "caleprocure_scprs",
                                                 "09/01/2026", "09/03/2026"), [])

    def test_days_outside_the_window_are_not_counted(self) -> None:
        state = self._state("from=08/31/2026|to=08/31/2026",
                            "from=09/01/2026|to=09/01/2026")
        self.assertEqual(hs.days_held(state, "caleprocure_scprs",
                                                 "09/01/2026", "09/30/2026"),
                         ["09/01/2026"])

    def test_a_failed_day_is_not_held(self) -> None:
        state = hs.load(pathlib.Path(tempfile.mkdtemp()))
        hs.record(state, "caleprocure_scprs", "from=09/01/2026|to=09/01/2026",
                             outcome=hs.FAILED)
        self.assertEqual(hs.days_held(state, "caleprocure_scprs",
                                                 "09/01/2026", "09/01/2026"), [])

    def test_window_days_counts_inclusively(self) -> None:
        self.assertEqual(hs.window_days("09/01/2026", "09/10/2026"), 10)
        self.assertEqual(hs.window_days("09/01/2026", "09/01/2026"), 1)

if __name__ == "__main__":
    unittest.main()
