"""Browser transport, for pages plain HTTP cannot read.

Two cases justify it: a page that renders client-side and serves no data to a bare GET,
and a portal that answers a non-browser client with a verification challenge. Driving a
real Chrome is being the client the site expects, not defeating a control -- see the
anti-bot clause in `SECURITY.md` for where that line sits.

Deterministic Playwright rather than an LLM-driven browser framework: a harvester wants
the same parse every run, no per-page token cost, and offline tests. Playwright is
imported lazily so this module -- and the whole test suite -- import fine without it.

Read-only by construction: `get` and `close` are the only methods. There is deliberately
no post, submit, upload or click surface here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from . import UA, TransientFetchError

BROWSERBASE_API = "https://api.browserbase.com/v1"


@dataclass
class BrowserFetcher:
    """Retrieve rendered pages through a real browser.

    `page` is injectable so tests can supply a fake and never touch the network. Left
    unset, the first `get` launches one: local Chrome by default, hosted when `remote`.
    """

    delay_seconds: float = 1.5
    remote: bool = False
    context_id: str | None = None
    persist: bool = False
    user_data_dir: str = "build/browser-profile"
    wait_until: str = "domcontentloaded"
    # A page whose rows arrive by XHR is "loaded" long before it has data, and a template
    # with its bindings unrendered parses as a real page with zero rows -- the soft-404
    # trap in another costume. Waiting for a selector the data actually produces is the
    # only reliable signal; a fixed sleep just moves the race.
    wait_for: str | None = None
    page: Any = None
    session_id: str | None = None
    _closers: list = field(default_factory=list, repr=False)

    def get(self, url: str, referer: str | None = None,
            timeout: int = 120) -> tuple[bytes, Any]:
        """Navigate and return the rendered HTML, matching `HttpFetcher.get`.

        Callers cannot tell which transport they hold, which is the point -- adapters take
        a fetcher, not a session type.
        """
        page = self._ensure_page()
        time.sleep(self.delay_seconds)
        try:
            if referer:
                response = page.goto(url, referer=referer, wait_until=self.wait_until,
                                     timeout=timeout * 1000)
            else:
                response = page.goto(url, wait_until=self.wait_until,
                                     timeout=timeout * 1000)
        except Exception as exc:  # playwright raises its own error types
            raise TransientFetchError(
                f"browser navigation failed for {url[:120]}: "
                f"{type(exc).__name__}: {exc}") from exc
        if self.wait_for:
            try:
                # "attached", not the default "visible": a harvester reads the DOM, and
                # rows inside a scrolled or collapsed container are real data that a
                # visibility check would sit and wait out until it timed out.
                page.wait_for_selector(self.wait_for, state="attached",
                                       timeout=timeout * 1000)
            except Exception as exc:
                raise TransientFetchError(
                    f"{url[:120]} never produced {self.wait_for!r}: "
                    f"{type(exc).__name__}") from exc
        headers = response.headers if response is not None else {}
        return page.content().encode("utf-8"), headers

    def close(self) -> None:
        for closer in reversed(self._closers):
            try:
                closer()
            except Exception:  # nothing useful to do while tearing down
                pass
        self._closers.clear()
        self.page = None

    def __enter__(self) -> BrowserFetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_page(self) -> Any:
        if self.page is None:
            self.page = self._launch_remote() if self.remote else self._launch_local()
        return self.page

    def _launch_local(self) -> Any:
        """Local Chrome with a persistent profile, so a login survives between runs."""
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        self._closers.append(playwright.stop)
        context = playwright.chromium.launch_persistent_context(
            self.user_data_dir, headless=True, user_agent=UA)
        self._closers.append(context.close)
        return context.pages[0] if context.pages else context.new_page()

    def _launch_remote(self) -> Any:
        """Hosted Chrome. Reuses a saved context so an earlier manual login still applies.

        The API key alone identifies the project -- there is no project id to supply.
        """
        from playwright.sync_api import sync_playwright

        session = create_session(context_id=self.context_id, persist=self.persist)
        self.session_id = session["id"]
        playwright = sync_playwright().start()
        self._closers.append(playwright.stop)
        browser = playwright.chromium.connect_over_cdp(session["connectUrl"])
        self._closers.append(browser.close)
        context = browser.contexts[0]
        return context.pages[0] if context.pages else context.new_page()


def _client() -> Any:
    """Browserbase SDK client, imported lazily and keyed off the environment."""
    import os

    from browserbase import Browserbase

    key = os.environ.get("BROWSERBASE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("BROWSERBASE_API_KEY is not set; see .env.example")
    return Browserbase(api_key=key)


def create_session(*, context_id: str | None = None, persist: bool = False) -> dict:
    settings: dict[str, Any] = {}
    if context_id:
        settings["context"] = {"id": context_id, "persist": persist}
    session = _client().sessions.create(**({"browser_settings": settings} if settings else {}))
    return {"id": session.id, "connectUrl": session.connect_url}


def create_context(name: str) -> str:
    """A saved cookie store. Created once per portal, reused by every later run."""
    return _client().contexts.create(name=name).id


def live_view_url(session_id: str) -> str:
    """The URL a person opens to drive the browser -- to log in, or clear a one-off check."""
    debug = _client().sessions.debug(session_id)
    return getattr(debug, "debugger_fullscreen_url", None) or debug.debugger_url


def account_limits() -> dict:
    """What this key is actually allowed to do.

    Recorded rather than assumed, so a later failure is read as a quota rather than a bug.
    `concurrency` is the tier tell: 3 is the free plan, 25 the developer plan.
    """
    client = _client()
    out: dict[str, Any] = {"projects": []}
    for project in client.projects.list():
        row = {"id": project.id, "name": project.name,
               "concurrency": project.concurrency,
               "session_timeout_seconds": project.default_timeout}
        try:
            usage = client.projects.usage(project.id)
            row["browser_minutes_used"] = usage.browser_minutes
            row["proxy_bytes_used"] = usage.proxy_bytes
        except Exception as exc:
            row["usage_error"] = f"{type(exc).__name__}: {exc}"
        out["projects"].append(row)
    return out
