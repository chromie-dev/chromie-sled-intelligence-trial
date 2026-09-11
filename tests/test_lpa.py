"""Offline tests for the LPA / statewide-contract adapter. No network.

The markup below is the shape the component returned live for supplier 0000005196
(WW GRAINGER INC), which holds cooperative agreement 7-25-51-02.
"""
import datetime as dt
import unittest

from sled_trial.sources.ca import lpa

PAGE = """
<table>
<tr>
  <td><span id='CNTRCT_ID$0'>7-25-51-02</span></td>
  <td><span id='NAME11$0'>WW GRAINGER INC</span></td>
  <td><span id='VENDOR_ID1$0'>0000005196</span></td>
  <td><span id='ZZ_CNTRCT_TYPE$0'>Cooperative Agreement</span></td>
  <td><span id='DESCR2$0'>Facilities Maintenance, Repair, and Operations</span></td>
  <td><span id='ZZ_CTR_SRC_VW_ZZ_ACQ_TYPE$0'>NON-IT Goods</span></td>
  <td><span id='CNTRCT_BEGIN_DT$0'>01/01/2025</span></td>
  <td><span id='CNTRCT_EXPIRE_DT1$0'>08/31/2028</span></td>
  <td><span id='OPRDEFNDESC1$0'>Yolanda Tutt</span></td>
</tr>
<tr>
  <td><span id='CNTRCT_ID$1'>1-22-99-01</span></td>
  <td><span id='NAME11$1'>WW GRAINGER INC</span></td>
  <td><span id='VENDOR_ID1$1'>0000005196</span></td>
  <td><span id='ZZ_CNTRCT_TYPE$1'>Statewide Contract</span></td>
  <td><span id='DESCR2$1'>Expired vehicle</span></td>
  <td><span id='ZZ_CTR_SRC_VW_ZZ_ACQ_TYPE$1'>NON-IT Goods</span></td>
  <td><span id='CNTRCT_BEGIN_DT$1'>01/01/2020</span></td>
  <td><span id='CNTRCT_EXPIRE_DT1$1'>12/31/2022</span></td>
  <td><span id='OPRDEFNDESC1$1'>Someone Else</span></td>
</tr>
</table>
<!-- the search form's own dropdowns, which are not results -->
<span id='ZZ_SOMEFILTER_VW_DESCR$0'>noise</span>
<span id='ZZ_SOMEFILTER_VW_DESCR$1'>more noise</span>
<span id='ZZ_SOMEFILTER_VW_DESCR$2'>yet more</span>
"""

EMPTY = "<table></table><span id='ZZ_SOMEFILTER_VW_DESCR$0'>noise</span>"


class ParseTests(unittest.TestCase):
    def test_every_contract_row_is_returned(self) -> None:
        rows = lpa.parse_results(PAGE)
        self.assertEqual([r["contract_id"] for r in rows], ["7-25-51-02", "1-22-99-01"])

    def test_the_supplier_id_is_the_one_scprs_uses(self) -> None:
        # The whole point of this source: an identifier join, not a name match.
        self.assertEqual(lpa.parse_results(PAGE)[0]["supplier_id"], "0000005196")

    def test_contract_metadata_is_captured(self) -> None:
        row = lpa.parse_results(PAGE)[0]
        self.assertEqual(row["contract_type"], "Cooperative Agreement")
        self.assertEqual(row["acq_type"], "NON-IT Goods")
        self.assertEqual(row["begin_date"], "01/01/2025")
        self.assertEqual(row["expire_date"], "08/31/2028")

    def test_unrelated_field_families_do_not_invent_rows(self) -> None:
        # A first version of the supplier search keyed rows off the highest index across
        # every family and reported six results for a two-supplier query.
        self.assertEqual(len(lpa.parse_results(PAGE)), 2)

    def test_a_search_with_no_hits_yields_nothing(self) -> None:
        self.assertEqual(lpa.parse_results(EMPTY), [])


class ValidityTests(unittest.TestCase):
    """Holding an expired vehicle is not current standing."""

    def test_a_live_vehicle_is_current(self) -> None:
        row = lpa.parse_results(PAGE)[0]
        self.assertTrue(lpa.is_current(row, dt.date(2026, 9, 10)))

    def test_an_expired_vehicle_is_not(self) -> None:
        row = lpa.parse_results(PAGE)[1]
        self.assertFalse(lpa.is_current(row, dt.date(2026, 9, 10)))

    def test_a_vehicle_not_yet_started_is_not_current(self) -> None:
        row = lpa.parse_results(PAGE)[0]
        self.assertFalse(lpa.is_current(row, dt.date(2024, 1, 1)))

    def test_unreadable_dates_stay_unknown_rather_than_defaulting_to_current(self) -> None:
        # "vendor holds a live statewide contract" is a claim about standing; guessing it
        # from a date we could not parse would assert something unevidenced.
        self.assertIsNone(lpa.is_current({"begin_date": "", "expire_date": None}))


class CriteriaTests(unittest.TestCase):
    def test_unknown_criteria_are_rejected_before_any_request(self) -> None:
        with self.assertRaises(ValueError):
            lpa.search(None, nonsense="x")

    def test_an_unfiltered_search_is_refused(self) -> None:
        # The component would happily return the whole register; asking for it is rude
        # and the grid caps anyway.
        with self.assertRaises(ValueError):
            lpa.search(None, supplier_id="")

    def test_every_criterion_maps_to_a_real_form_field(self) -> None:
        for field in lpa.CRITERIA.values():
            self.assertTrue(field.startswith("ZZ_CTR_SRC2_WRK_"), field)


class FakeSession:
    def __init__(self, page: str, fail_for: set[str] | None = None):
        self.page, self.fail_for, self.asked = page, fail_for or set(), []

    def get(self, url, referer=None, timeout=120):
        return b"<html></html>", {}

    def absorb_state(self, body):
        pass

    def post_action(self, action, referer, timeout=120, url=None, extra=None):
        supplier = (extra or {}).get("ZZ_CTR_SRC2_WRK_VENDOR_ID")
        self.asked.append(supplier)
        if supplier in self.fail_for:
            raise OSError("connection reset")
        return (self.page.encode() if supplier == "0000005196"
                else EMPTY.encode()), {}


class LookupTests(unittest.TestCase):
    def test_vehicles_are_keyed_by_supplier_id(self) -> None:
        out = lpa.vehicles_by_supplier(
            FakeSession(PAGE), ["0000005196", "0000000001"])
        self.assertEqual(list(out["by_supplier"]), ["0000005196"])
        self.assertEqual(out["suppliers_checked"], 2)
        self.assertEqual(out["suppliers_with_vehicles"], 1)

    def test_a_supplier_with_no_vehicle_is_absent_not_recorded_empty(self) -> None:
        out = lpa.vehicles_by_supplier(FakeSession(PAGE), ["0000000001"])
        self.assertEqual(out["by_supplier"], {})
        self.assertEqual(out["failures"], [])

    def test_a_failed_lookup_is_recorded_not_read_as_no_vehicles(self) -> None:
        session = FakeSession(PAGE, fail_for={"0000000002"})
        out = lpa.vehicles_by_supplier(session, ["0000005196", "0000000002"])
        self.assertEqual(len(out["failures"]), 1)
        self.assertEqual(out["failures"][0]["supplier_id"], "0000000002")

    def test_duplicate_supplier_ids_are_asked_once(self) -> None:
        session = FakeSession(PAGE)
        lpa.vehicles_by_supplier(session, ["0000005196", "0000005196"])
        self.assertEqual(session.asked, ["0000005196"])

    def test_rows_flatten_one_per_supplier_and_contract(self) -> None:
        out = lpa.vehicles_by_supplier(FakeSession(PAGE), ["0000005196"])
        rows = lpa.vehicle_rows(out["by_supplier"], on=dt.date(2026, 9, 10))
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["supplier_id"] for r in rows}, {"0000005196"})
        self.assertEqual([r["current"] for r in rows], [True, False])



class AttachTests(unittest.TestCase):
    """Standing on a statewide vehicle, attached to a vendor profile."""

    def _rows(self):
        return [
            {"supplier_id": "0000005196", "contract_id": "7-25-51-02",
             "contract_type": "Cooperative Agreement", "current": True},
            {"supplier_id": "0000005196", "contract_id": "1-22-99-01",
             "contract_type": "Statewide Contract", "current": False},
        ]

    def test_the_join_is_on_supplier_id_not_on_a_name(self) -> None:
        from sled_trial.vendors import attach_vehicles

        profiles = [{"supplier_id": "0000005196", "canonical_name": "ANYTHING AT ALL"}]
        summary = attach_vehicles(profiles, self._rows())
        self.assertTrue(profiles[0]["vehicles"]["matched"])
        self.assertEqual(profiles[0]["vehicles"]["identity_basis"], "supplier_id")
        self.assertEqual(summary["matched"], 1)

    def test_expired_vehicles_are_held_but_not_counted_as_current(self) -> None:
        from sled_trial.vendors import attach_vehicles

        profiles = [{"supplier_id": "0000005196", "canonical_name": "X"}]
        attach_vehicles(profiles, self._rows())
        self.assertEqual(len(profiles[0]["vehicles"]["held"]), 2)
        self.assertEqual(profiles[0]["vehicles"]["current_count"], 1)

    def test_no_vehicle_is_a_real_answer_here(self) -> None:
        # Unlike the supplier registry, the LPA register is complete, so absence means
        # the vendor holds none rather than that it is uncatalogued.
        from sled_trial.vendors import attach_vehicles

        profiles = [{"supplier_id": "0000000001", "canonical_name": "X"}]
        attach_vehicles(profiles, self._rows())
        self.assertFalse(profiles[0]["vehicles"]["matched"])
        self.assertIn("holds no statewide contract", profiles[0]["vehicles"]["note"])

    def test_it_is_registered_as_an_enrichment_so_analyze_picks_it_up(self) -> None:
        from sled_trial import assemble

        self.assertIn(("lpa_vehicles.json", None, "attach_vehicles"),
                      assemble.ENRICHMENTS)

if __name__ == "__main__":
    unittest.main()
