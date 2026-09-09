"""Offline tests for the SCPRS award-registry adapter. No network."""
import unittest

from sled_trial.sources import scprs

# Result-grid markup uses double-quoted attributes; the surrounding page uses single
# quotes. A single-quote-only pattern returns zero rows and mimics "no awards found".
GRID = """
<span id="PURCHASE_DOC$0">26IT-0168</span>
<span id="ZZ_SCPR_RSLT_VW_DESCR$0">Department of Justice</span>
<span id="ZZ_SCPR_RSLT_VW_DESCR254_MIXED$0">Dell Pro 14 Premium</span>
<span id="ZZ_SCPR_RSLT_VW_START_DATE$0">09/03/2026</span>
<span id="ZZ_SCPR_RSLT_VW_AWARDED_AMT$0">$3,140.49</span>
<span id="ZZ_SCPR_RSLT_VW_SUPPLIER_ID$0">0000000269</span>
<span id="ZZ_SCPR_RSLT_VW_NAME1$0">TECHNOLOGY INTEGRATION GROUP</span>
<span id="ZZ_SCPR_RSLT_VW_ZZ_COMMENT1$0">IT Goods</span>
<span id="ZZ_SCPR_RSLT_VW_ZZ_ACQ_MTHD$0">Statewide Contracts</span>
<span id="ZZ_SCPR_RSLT_VW_ZZ_LPACONTRACTNBR$0">1-22-70-31C</span>
<span id="PURCHASE_DOC$1">TA26-042</span>
<span id="ZZ_SCPR_RSLT_VW_DESCR$1">Dept of Corrections &amp; Rehab</span>
<span id="ZZ_SCPR_RSLT_VW_NAME1$1">DISTEC SUPPLY CO INC</span>
<span id="ZZ_SCPR_RSLT_VW_SUPPLIER_ID$1">0000020387</span>
<span id="ZZ_SCPR_RSLT_VW_AWARDED_AMT$1">$1,258.35</span>
<span id="ZZ_SCPR_RSLT_VW_ZZ_ACQ_MTHD$1">Fair and Reasonable - COMPETITIVE</span>
<div>1 to 200 of 46,242</div>
"""


class ParseTests(unittest.TestCase):
    def test_parses_double_quoted_grid(self) -> None:
        rows = scprs.parse_results(GRID)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["purchase_doc"], "26IT-0168")
        self.assertEqual(rows[0]["supplier_id"], "0000000269")

    def test_html_entities_decoded(self) -> None:
        rows = scprs.parse_results(GRID)
        self.assertEqual(rows[1]["department"], "Dept of Corrections & Rehab")

    def test_pager_with_thousands_separator(self) -> None:
        self.assertEqual(scprs.parse_pager(GRID), (1, 200, 46242))

    def test_pager_absent(self) -> None:
        self.assertIsNone(scprs.parse_pager("<div>nothing here</div>"))

    def test_empty_grid_yields_no_rows(self) -> None:
        self.assertEqual(scprs.parse_results("<div>No matching rows</div>"), [])


class AmountTests(unittest.TestCase):
    def test_parses_currency(self) -> None:
        self.assertEqual(scprs.amount_to_numeric("$3,140.49"), "3140.49")
        self.assertEqual(scprs.amount_to_numeric("1258"), "1258")

    def test_negative_amount(self) -> None:
        self.assertEqual(scprs.amount_to_numeric("-$500.00"), None)
        self.assertEqual(scprs.amount_to_numeric("-500.00"), "-500.00")

    def test_unparseable_stays_null_not_zero(self) -> None:
        # A missing amount must never become 0 -- README forbids turning unknown into a
        # negative fact.
        for bad in ["N/A", "", None, "see contract", "TBD"]:
            with self.subTest(bad=bad):
                self.assertIsNone(scprs.amount_to_numeric(bad))


class CriteriaTests(unittest.TestCase):
    def test_unknown_criterion_is_rejected_before_any_request(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            scprs.search(None, nonsense="x")
        self.assertIn("nonsense", str(ctx.exception))

    def test_every_criterion_maps_to_a_work_record_field(self) -> None:
        for key, field in scprs.CRITERIA.items():
            with self.subTest(key=key):
                self.assertTrue(field.startswith("ZZ_SCPRS_SP_WRK_"))

    def test_search_url_carries_the_params_that_make_it_public(self) -> None:
        # Without FolderPath/IsFolder/IgnoreParamTempl the component redirects to login.
        for token in ("FolderPath=", "IsFolder=false", "IgnoreParamTempl="):
            self.assertIn(token, scprs.SEARCH_URL)


class TruncationTests(unittest.TestCase):
    def test_page_limit_is_the_documented_cap(self) -> None:
        self.assertEqual(scprs.PAGE_LIMIT, 200)

    def test_subdivide_by_rejects_an_unknown_criterion(self) -> None:
        gen = scprs.search_date_sliced(
            None, "09/02/2026", "09/02/2026", subdivide_by=("nope", ["x"]))
        with self.assertRaises(Exception):
            list(gen)


if __name__ == "__main__":
    unittest.main()


class BusinessUnitCriterionTests(unittest.TestCase):
    def test_criterion_is_named_business_unit_not_department(self) -> None:
        # The field takes a FI$Cal code ("0820"), not a display name. Passing a name
        # returns zero rows, which reads as "nothing was purchased" rather than as an
        # error -- so the parameter name has to signal that a code is required.
        self.assertIn("business_unit", scprs.CRITERIA)
        self.assertNotIn("department", scprs.CRITERIA)

    def test_business_unit_maps_to_the_business_unit_field(self) -> None:
        self.assertEqual(scprs.CRITERIA["business_unit"],
                         "ZZ_SCPRS_SP_WRK_BUSINESS_UNIT")

    def test_result_rows_still_expose_department_as_a_display_name(self) -> None:
        # Asymmetry worth pinning: you search by code but read back a name.
        self.assertEqual(scprs.FIELDS["department"], "ZZ_SCPR_RSLT_VW_DESCR")


class GridAnchorTests(unittest.TestCase):
    def test_unrelated_field_families_do_not_inflate_the_grid(self) -> None:
        # The same bug found and fixed in supplier_search: keying rows off any $N family
        # let the search form's own dropdowns become result rows.
        page = (
            "<span id='PURCHASE_DOC$0'>4500336435</span>"
            "<span id='ZZ_SCPR_RSLT_VW_NAME1$0'>ULINE INC</span>"
            "<span id='ZZ_ACQ_MTHD_VW_DESCR$1'>Competitive</span>"
            "<span id='ZZ_ACQ_MTHD_VW_DESCR$2'>Non-Competitive</span>")
        rows = scprs.parse_results(page)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["supplier_name"], "ULINE INC")
