"""Offline tests for the transport layer. No network, no browser.

The point of `sled_trial.net` is that an adapter cannot tell which transport it holds.
These tests assert that equivalence directly, because it is the property that lets a
browser-backed source reuse every parser written against plain HTTP.
"""
import pathlib
import unittest

from sled_trial import net
from sled_trial.net.browser import BrowserFetcher
from sled_trial.net.http import BROWSER_HEADERS, HttpFetcher
from sled_trial.sources.ca import caleprocure as ca

FIX = pathlib.Path(__file__).parent / "fixtures"


class FakeOpener:
    """Stands in for urllib. Returns canned bytes for any request."""

    def __init__(self, body: bytes, headers=None):
        self.body, self.headers = body, headers or {}
        self.seen = []

    def open(self, req, timeout=None):
        self.seen.append(req)
        outer = self

        class Resp:
            headers = outer.headers

            def read(self):
                return outer.body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Resp()


class FakePage:
    """Stands in for a Playwright page. Records navigation, returns canned HTML."""

    def __init__(self, html: str, headers=None):
        self.html, self._headers = html, headers or {}
        self.goto_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        outer = self

        class Response:
            headers = outer._headers

        return Response()

    def content(self):
        return self.html

    def wait_for_selector(self, selector, state=None, timeout=None):
        self.waited = (selector, state, timeout)
        if selector not in self.html:
            raise TimeoutError(f"no {selector}")
        return object()


class HeaderTests(unittest.TestCase):
    def test_a_bare_fetcher_sends_only_the_self_identifying_agent(self) -> None:
        self.assertEqual(list(HttpFetcher(delay_seconds=0)._headers()), ["User-Agent"])

    def test_browser_headers_are_opt_in(self) -> None:
        # Some hosts answer 403 to a bare crawler UA without running any challenge, so
        # this is the cheap rung below launching Chrome -- but it is not the default,
        # because claiming to be a browser when we are not should be a deliberate choice.
        headers = HttpFetcher(delay_seconds=0, browser_headers=True)._headers()
        for key in BROWSER_HEADERS:
            self.assertIn(key, headers)
        self.assertIn("chromie-sled-trial-research", headers["User-Agent"])

    def test_the_agent_names_the_project_and_no_person(self) -> None:
        # A personal address in a header lands in a third party's access logs on every
        # request, so it is only present when explicitly configured.
        self.assertNotIn("mailto:", net.UA)


class TransportEquivalenceTests(unittest.TestCase):
    """The seam is only real if a parser cannot tell the two transports apart."""

    def setUp(self) -> None:
        self.html = (FIX / "event_list_min.html").read_text(encoding="utf-8")

    def _http_body(self):
        fetcher = HttpFetcher(delay_seconds=0)
        fetcher._opener = FakeOpener(self.html.encode())
        return fetcher.get("https://example.invalid/events")[0]

    def _browser_body(self):
        return BrowserFetcher(delay_seconds=0, page=FakePage(self.html)).get(
            "https://example.invalid/events")[0]

    def test_both_transports_return_bytes(self) -> None:
        self.assertIsInstance(self._http_body(), bytes)
        self.assertIsInstance(self._browser_body(), bytes)

    def test_the_same_page_parses_identically_through_either_transport(self) -> None:
        over_http = ca.parse_event_list(self._http_body().decode())
        over_browser = ca.parse_event_list(self._browser_body().decode())
        self.assertEqual(over_http, over_browser)
        self.assertTrue(over_http, "fixture parsed to nothing; the test proves nothing")

    def test_the_referer_reaches_the_browser_too(self) -> None:
        page = FakePage(self.html)
        BrowserFetcher(delay_seconds=0, page=page).get("https://x/y", referer="https://x/")
        self.assertEqual(page.goto_calls[0][1]["referer"], "https://x/")


class ReadOnlyTests(unittest.TestCase):
    """SECURITY.md: adapters retrieve and parse. Nothing changes state on a portal."""

    def test_the_browser_transport_exposes_no_write_path(self) -> None:
        surface = {name for name in dir(BrowserFetcher) if not name.startswith("_")}
        methods = {n for n in surface if callable(getattr(BrowserFetcher, n, None))}
        self.assertEqual(methods, {"get", "close"})

    def test_no_click_type_or_upload_helper_is_offered(self) -> None:
        # A convenience wrapper here is how read-only quietly stops being true.
        for forbidden in ("click", "fill", "type", "submit", "upload", "post", "press"):
            self.assertFalse(hasattr(BrowserFetcher, forbidden), forbidden)

    def test_a_browser_navigation_failure_is_typed_not_swallowed(self) -> None:
        # A silent empty result reads as "this page has no content", which is the same
        # class of lie as a soft-404 counted as "no bids that week".
        class Broken(FakePage):
            def goto(self, url, **kwargs):
                raise RuntimeError("net::ERR_CONNECTION_REFUSED")

        with self.assertRaises(net.TransientFetchError):
            BrowserFetcher(delay_seconds=0, page=Broken("")).get("https://x/y")


class WaitForTests(unittest.TestCase):
    """A page whose rows arrive by XHR is "loaded" long before it has data."""

    def test_no_selector_means_no_wait(self) -> None:
        page = FakePage("<html>done</html>")
        BrowserFetcher(delay_seconds=0, page=page).get("https://x/y")
        self.assertFalse(hasattr(page, "waited"))

    def test_the_wait_is_for_an_attached_node_not_a_visible_one(self) -> None:
        # Rows inside a scrolled or collapsed container are real data. Playwright's
        # default "visible" state sits and waits those out until it times out -- observed
        # against the Cal eProcure event search, where 4,635 cells were present and the
        # first one was not visible.
        page = FakePage("<table><tr><td>x</td></tr></table>")
        BrowserFetcher(delay_seconds=0, page=page, wait_for="td").get("https://x/y")
        self.assertEqual(page.waited[1], "attached")

    def test_a_template_that_never_fills_is_an_error_not_an_empty_page(self) -> None:
        # The unrendered template parses cleanly as a page with zero rows, which reads as
        # "this search returned nothing" -- a soft-404 in another costume.
        page = FakePage("<table><thead><th>[Event Id]</th></thead></table>")
        with self.assertRaises(net.TransientFetchError):
            BrowserFetcher(delay_seconds=0, page=page, wait_for="td").get("https://x/y")


class FactoryTests(unittest.TestCase):
    def test_each_transport_name_resolves(self) -> None:
        self.assertIsInstance(net.build_fetcher("http", delay_seconds=0), HttpFetcher)
        self.assertTrue(net.build_fetcher("headers", delay_seconds=0).browser_headers)
        self.assertIsInstance(net.build_fetcher("browser", delay_seconds=0), BrowserFetcher)
        self.assertTrue(net.build_fetcher("browserbase", delay_seconds=0).remote)

    def test_an_unknown_transport_is_refused_by_name(self) -> None:
        with self.assertRaises(ValueError) as caught:
            net.build_fetcher("telepathy")
        self.assertIn("telepathy", str(caught.exception))

    def test_building_a_browser_fetcher_launches_nothing(self) -> None:
        # Playwright is an optional extra. Importing the module, or constructing the
        # fetcher, must not require it -- only calling get() does.
        self.assertIsNone(net.build_fetcher("browser", delay_seconds=0).page)


class CalEProcureStillWorksTests(unittest.TestCase):
    """The PeopleSoft session now inherits the shared transport rather than owning one."""

    def test_it_is_an_http_fetcher(self) -> None:
        self.assertIsInstance(ca.CalEProcureSession(delay_seconds=0), HttpFetcher)

    def test_it_keeps_the_state_chain_the_transport_knows_nothing_about(self) -> None:
        self.assertTrue(hasattr(ca.CalEProcureSession(delay_seconds=0), "post_action"))
        self.assertFalse(hasattr(HttpFetcher(delay_seconds=0), "post_action"))


if __name__ == "__main__":
    unittest.main()
