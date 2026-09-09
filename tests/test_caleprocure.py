"""Offline tests for the Cal eProcure adapter. No network, synthetic fixtures only."""
import pathlib
import unittest

from sled_trial.sources import caleprocure as ca

FIX = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class EventListTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = ca.parse_event_list(fixture("event_list_min.html"))

    def test_parses_every_row_with_every_field(self) -> None:
        self.assertEqual(len(self.rows), 2)
        for row in self.rows:
            self.assertEqual(sorted(row), sorted(ca.EVENT_FIELDS))

    def test_html_entities_are_decoded(self) -> None:
        self.assertIn("A&E", self.rows[0]["title"])
        self.assertEqual(self.rows[1]["agency"], "Dept of Corrections & Rehab")

    def test_identity_is_the_pair_not_the_event_id(self) -> None:
        # event_id formats differ across agencies (zero-padded vs Caltrans style), so the
        # pair is the only safe key.
        keys = {(r["business_unit"], r["event_id"]) for r in self.rows}
        self.assertEqual(len(keys), 2)
        self.assertIn(("2660", "04A7615"), keys)


class AttachmentGridTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page = fixture("attachments_min.html")

    def test_parses_double_quoted_grid(self) -> None:
        # The grid uses double-quoted attributes while the rest of the page uses single.
        rows = ca.parse_attachments(self.page)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["filename"], "01_04A7615_RFQ_Notice_11y_04222026.pdf")
        self.assertEqual(rows[0]["description"], "RFQ Notice")
        self.assertEqual(rows[1]["version"], "1.00")

    def test_pager_mismatch_raises_instead_of_returning_empty(self) -> None:
        # A markup change that breaks the row pattern must not masquerade as "no
        # attachments" -- the pager total is the independent check.
        broken = self.page.replace("PV_ATTACH_WRK_ATTACHUSERFILE", "PV_ATTACH_WRK_RENAMED")
        with self.assertRaises(ValueError) as ctx:
            ca.parse_attachments(broken)
        self.assertIn("pager declares 3", str(ctx.exception))

    def test_no_pager_means_no_assertion(self) -> None:
        rows = ca.parse_attachments(self.page.replace("First 1-3 of 3 Last", ""))
        self.assertEqual(len(rows), 3)


class FilenameSignalTests(unittest.TestCase):
    def test_role_prefix_recognised(self) -> None:
        self.assertEqual(ca.role_from_filename("01_04A7615_RFQ_Notice.pdf"), "notice")
        self.assertEqual(ca.role_from_filename("07_04A7615_Addendum_1.pdf"), "addendum")

    def test_unknown_prefix_returns_none_not_a_guess(self) -> None:
        self.assertIsNone(ca.role_from_filename("99_something.pdf"))
        self.assertIsNone(ca.role_from_filename("scope_of_work.pdf"))

    def test_mismatched_solicitation_in_filename_is_flagged(self) -> None:
        # Real case observed on event 04A7615.
        self.assertTrue(ca.filename_solicitation_mismatch(
            "07_06A3334_Addendum_2_-_Responsible_Person_Question.pdf", "04A7615"))

    def test_matching_filename_is_not_flagged(self) -> None:
        self.assertFalse(ca.filename_solicitation_mismatch(
            "07_04A7615_Addendum_1.pdf", "04A7615"))

    def test_filename_without_a_solicitation_token_is_not_flagged(self) -> None:
        self.assertFalse(ca.filename_solicitation_mismatch("02_SOQ_Instructions.pdf", "04A7615"))


class StateChainTests(unittest.TestCase):
    def test_hidden_fields_read_both_quote_styles(self) -> None:
        fields = ca.hidden_fields(fixture("event_list_min.html"))
        self.assertEqual(fields["ICSID"], "FAKESID==")
        self.assertEqual(fields["ICStateNum"], "2")

    def test_posting_without_state_is_refused(self) -> None:
        session = ca.CalEProcureSession(delay_seconds=0)
        with self.assertRaises(RuntimeError):
            session.post_action(ca.PACKAGE_ACTION, referer="https://example.invalid")

    def test_state_advances_and_pdf_bytes_do_not_clobber_it(self) -> None:
        session = ca.CalEProcureSession(delay_seconds=0)
        session.absorb_state(fixture("event_list_min.html").encode())
        self.assertEqual(session.state_num, "2")
        session.absorb_state(fixture("attachments_min.html").encode())
        self.assertEqual(session.state_num, "3")
        session.absorb_state(b"%PDF-1.6 ...")  # a file response carries no state
        self.assertEqual(session.state_num, "3")

    def test_detail_url_carries_the_identity_pair(self) -> None:
        url = ca.detail_url("2660", "04A7615")
        self.assertIn("BUSINESS_UNIT=2660", url)
        self.assertIn("AUC_ID=04A7615", url)
        self.assertNotIn("page=AUC_RESP_INQ_AUC", url)  # the login-redirect form


if __name__ == "__main__":
    unittest.main()


class BootstrapTests(unittest.TestCase):
    def test_session_starts_unbootstrapped(self) -> None:
        # An unseeded session yields an empty attachment grid that mimics "no documents",
        # so bootstrap state is worth asserting.
        session = ca.CalEProcureSession(delay_seconds=0)
        self.assertFalse(session._bootstrapped)

    def test_bootstrap_is_idempotent_once_marked(self) -> None:
        session = ca.CalEProcureSession(delay_seconds=0)
        session._bootstrapped = True
        session.bootstrap()  # must not attempt a request
        self.assertTrue(session._bootstrapped)


class ResponseKindTests(unittest.TestCase):
    def test_html_page_is_not_mistaken_for_a_document(self) -> None:
        self.assertTrue(ca._looks_like_html(b"<!DOCTYPE html><html>", "text/html"))
        self.assertTrue(ca._looks_like_html(b"  <html><body>x", ""))

    def test_pdf_and_office_bytes_are_treated_as_documents(self) -> None:
        # A PDF-only check here previously rejected every .docx on a 15-file event.
        self.assertFalse(ca._looks_like_html(b"%PDF-1.6 ...", "application/pdf"))
        self.assertFalse(ca._looks_like_html(b"PK\x03\x04...", "application/octet-stream"))

    def test_content_type_html_wins_over_plausible_bytes(self) -> None:
        self.assertTrue(ca._looks_like_html(b"PK\x03\x04", "text/html; charset=utf-8"))


class RetryTests(unittest.TestCase):
    """Retries exist because two real runs died: a portal HTTP 500 and a local DNS blip."""

    def test_retry_settings_are_bounded_by_default(self) -> None:
        session = ca.CalEProcureSession(delay_seconds=0)
        self.assertEqual(session.max_attempts, 3)
        self.assertGreater(session.retry_backoff_seconds, 0)

    def test_transient_failure_raises_a_typed_error_not_an_empty_result(self) -> None:
        # A silent empty result would read as "this event has no documents".
        session = ca.CalEProcureSession(delay_seconds=0, retry_backoff_seconds=0,
                                        max_attempts=2)
        with self.assertRaises(ca.TransientFetchError):
            session.get("https://nonexistent.invalid.example/nothing")

    def test_client_errors_are_not_retried(self) -> None:
        import urllib.error

        calls = []

        class Boom:
            def open(self, req, timeout=None):
                calls.append(1)
                raise urllib.error.HTTPError(req.full_url, 404, "gone", {}, None)

        session = ca.CalEProcureSession(delay_seconds=0, retry_backoff_seconds=0)
        session._opener = Boom()
        with self.assertRaises(urllib.error.HTTPError):
            session.get("https://example.invalid/x")
        self.assertEqual(len(calls), 1)  # a 404 will not become a 200

    def test_server_errors_are_retried_up_to_the_limit(self) -> None:
        import urllib.error

        calls = []

        class Flaky:
            def open(self, req, timeout=None):
                calls.append(1)
                raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

        session = ca.CalEProcureSession(delay_seconds=0, retry_backoff_seconds=0,
                                        max_attempts=3)
        session._opener = Flaky()
        with self.assertRaises(ca.TransientFetchError):
            session.get("https://example.invalid/x")
        self.assertEqual(len(calls), 3)


class DetailFieldTests(unittest.TestCase):
    def test_counties_recovered_from_description_prose(self) -> None:
        # The structured ZZ_SA_VW_COUNTY grid was empty on every event sampled; the
        # description carried the counties in plain text.
        page = ("<span id='ZZ_SA_VW_COUNTY$0'>&nbsp;</span>"
                "<div>work throughout the counties of Alameda, Contra Costa, and "
                "Santa Clara in California</div>")
        f = ca.parse_detail_fields(page)
        self.assertEqual(f["service_area_counties"],
                         ["Alameda", "Contra Costa", "Santa Clara"])
        self.assertEqual(f["counties_source"], "description_text")

    def test_structured_grid_wins_when_populated(self) -> None:
        page = ("<span id='ZZ_SA_VW_COUNTY$0'>Fresno</span>"
                "<div>also mentions Alameda in passing</div>")
        f = ca.parse_detail_fields(page)
        self.assertEqual(f["service_area_counties"], ["Fresno"])
        self.assertEqual(f["counties_source"], "structured_grid")

    def test_only_real_county_names_are_accepted(self) -> None:
        # An arbitrary capitalised phrase must not become a location.
        f = ca.parse_detail_fields("<div>Acme Consolidated Holdings of Springfield</div>")
        self.assertEqual(f["service_area_counties"], [])
        self.assertEqual(f["counties_source"], "none_found")

    def test_multiword_counties_are_not_shadowed(self) -> None:
        f = ca.parse_detail_fields("<div>services in San Luis Obispo county</div>")
        self.assertEqual(f["service_area_counties"], ["San Luis Obispo"])

    def test_unspsc_codes_parsed(self) -> None:
        page = "<span id='ZZ_CATGRY_CD_VW_CATEGORY_CD$0'>43231500</span>"
        self.assertEqual(ca.parse_detail_fields(page)["unspsc_codes"], ["43231500"])

    def test_addenda_collected_without_duplicates(self) -> None:
        page = "<p>Addendum 1 - scope change</p><p>Addendum 1 - scope change</p><p>Addendum 2 - dates</p>"
        f = ca.parse_detail_fields(page)
        self.assertEqual(f["addendum_count"], 2)

    def test_geography_note_states_the_gap_plainly(self) -> None:
        note = ca.parse_detail_fields("<div/>")["geography_note"]
        self.assertIn("left unscored, not approximated", note)
        self.assertIn("where_cf", note)


class CountyContextTests(unittest.TestCase):
    def test_buyer_address_does_not_become_a_service_area(self) -> None:
        # Every state buyer address is in Sacramento, so a bare name anywhere on the page
        # gave most events a service area of "Sacramento".
        page = "<div>Buyer: 707 Third Street, West Sacramento, CA 95605</div>"
        self.assertEqual(ca.parse_detail_fields(page)["service_area_counties"], [])

    def test_counties_named_as_a_service_area_are_still_recovered(self) -> None:
        page = "<div>work in the counties of Alameda, Contra Costa and Santa Clara</div>"
        self.assertEqual(ca.parse_detail_fields(page)["service_area_counties"],
                         ["Alameda", "Contra Costa", "Santa Clara"])
