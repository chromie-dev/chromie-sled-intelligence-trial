"""Plain-HTTP transport. Lifted from the Cal eProcure adapter, which is where it grew.

Nothing in here is California-specific. The PeopleSoft state chain that used to sit
alongside it stayed behind in `sources/ca/caleprocure.py`, because that part genuinely is.
"""
from __future__ import annotations

import http.cookiejar
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import UA, TransientFetchError

# A host that answers 403 to a bare crawler UA is usually refusing a non-browser client
# rather than running a challenge, and sending the headers a browser sends is enough. This
# is the cheap rung below spinning up actual Chrome -- try it before reaching for one.
BROWSER_HEADERS = {
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class HttpFetcher:
    """A cookie jar, a voluntary delay, and bounded retries."""

    delay_seconds: float = 1.5
    max_attempts: int = 3
    retry_backoff_seconds: float = 2.0
    browser_headers: bool = False
    _opener: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"User-Agent": UA}
        if self.browser_headers:
            headers.update(BROWSER_HEADERS)
        if extra:
            headers.update(extra)
        return headers

    def _open(self, req: urllib.request.Request, timeout: int) -> tuple[bytes, Any]:
        """One request, with a voluntary delay and bounded retries on transient failures.

        Retries cover DNS and connection errors and 5xx responses -- a portal 500 and a
        local DNS blip both killed real runs. A 4xx is not retried: it will not become a
        different answer, and hammering it is rude. Backoff is linear and bounded so a
        broken host cannot turn one call into an unbounded wait.
        """
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            time.sleep(self.delay_seconds + attempt * self.retry_backoff_seconds)
            try:
                with self._opener.open(req, timeout=timeout) as resp:
                    return resp.read(), resp.headers
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    raise
                last = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
        raise TransientFetchError(
            f"{self.max_attempts} attempts failed for {req.full_url[:120]}: "
            f"{type(last).__name__}: {last}") from last

    def get(self, url: str, referer: str | None = None,
            timeout: int = 120) -> tuple[bytes, Any]:
        headers = self._headers({"Referer": referer} if referer else None)
        return self._open(urllib.request.Request(url, headers=headers), timeout)

    def post_raw(self, url: str, body: bytes, *, referer: str | None = None,
                 timeout: int = 180) -> tuple[bytes, Any]:
        """POST a caller-built form body.

        Read-only in the sense `SECURITY.md` means it: these portals drive search and
        pagination through POST, so retrieving a result grid requires one. Nothing here
        submits a bid, uploads, or registers.
        """
        extra = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "*/*"}
        if referer:
            extra["Referer"] = referer
        return self._open(urllib.request.Request(url, data=body,
                                                 headers=self._headers(extra)), timeout)
