"""Transports. One interface, several ways of reaching a page.

Every source adapter takes a fetcher and calls exactly one method:

    get(url, referer=None, timeout=120) -> (bytes, headers)

That is the whole contract, which is why a browser-backed transport needs no adapter
changes. Reach for the cheapest rung that works, because a browser is by far the most
expensive:

1. `HttpFetcher`                       plain HTTP, free, local
2. `HttpFetcher(browser_headers=True)` still plain HTTP, but a fuller header set; clears
                                       hosts that refuse a bare crawler UA without
                                       running an actual challenge
3. `BrowserFetcher()`                  local Chrome, for pages that render client-side
4. `BrowserFetcher(transport=...)`     hosted Chrome, when auth persistence or a
                                       different egress address is the point

`SECURITY.md` governs which of these may be pointed at what. Retrieval only: nothing here
submits a form, uploads, or changes state on a portal.
"""
from __future__ import annotations

import os
from typing import Any, Protocol

# Self-identifying crawler user-agent in the conventional format (the same shape as
# Googlebot's). It names the project so the operator can see who is calling, and claims to
# be no particular browser. A contact address is only included when SLED_TRIAL_CONTACT is
# set -- a personal address does not belong in a header sent to a third-party server by
# default, and hard-coding one puts it in that server's access logs on every request.
_CONTACT = os.environ.get("SLED_TRIAL_CONTACT", "").strip()
UA = ("Mozilla/5.0 (compatible; chromie-sled-trial-research/0.1"
      + (f"; +mailto:{_CONTACT}" if _CONTACT else "") + ")")


class TransientFetchError(RuntimeError):
    """Every retry was exhausted. Recorded as a typed failure, never a silent empty result."""


class Fetcher(Protocol):
    """What an adapter is allowed to assume about its transport."""

    def get(self, url: str, referer: str | None = None,
            timeout: int = 120) -> tuple[bytes, Any]:
        ...


def build_fetcher(transport: str = "http", *, delay_seconds: float = 1.5,
                  **kwargs: Any) -> Fetcher:
    """Resolve a transport name to a fetcher.

    Kept here rather than in the CLI so a jurisdiction's adapters, the CLI and the tests
    all name transports the same way.
    """
    if transport in ("http", "headers"):
        from .http import HttpFetcher
        return HttpFetcher(delay_seconds=delay_seconds,
                           browser_headers=transport == "headers", **kwargs)
    if transport in ("browser", "browserbase"):
        from .browser import BrowserFetcher
        return BrowserFetcher(delay_seconds=delay_seconds,
                              remote=transport == "browserbase", **kwargs)
    raise ValueError(f"unknown transport {transport!r}; "
                     "expected http, headers, browser or browserbase")


__all__ = ["UA", "Fetcher", "TransientFetchError", "build_fetcher"]
