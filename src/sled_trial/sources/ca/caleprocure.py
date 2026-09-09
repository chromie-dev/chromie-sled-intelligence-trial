"""Cal eProcure adapter: PeopleSoft components behind caleprocure.ca.gov.

Target the .GBL components directly. The /pages/*.aspx wrapper pages are an InFlight
overlay that renders client-side and carries no data -- see DECISIONS.md 2026-09-07.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as htmllib
import http.cookiejar
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# Self-identifying crawler user-agent in the conventional format (the same shape as
# Googlebot's). It names the project so the operator can see who is calling, and claims to be
# no particular browser. A contact address is only included when SLED_TRIAL_CONTACT is set --
# a personal address does not belong in a header sent to a third-party server by default, and
# hard-coding one puts it in that server's access logs on every request.
_CONTACT = os.environ.get("SLED_TRIAL_CONTACT", "").strip()
UA = ("Mozilla/5.0 (compatible; chromie-sled-trial-research/0.1"
      + (f"; +mailto:{_CONTACT}" if _CONTACT else "") + ")")
HOST = "https://caleprocure.ca.gov"
COMP = f"{HOST}/psc/psfpd1/SUPPLIER/ERP/c"
EVENT_LIST_URL = f"{COMP}/AUC_MANAGE_BIDS.AUC_RESP_INQ_AUC.GBL"
EVENT_DETAIL_URL = f"{COMP}/AUC_MANAGE_BIDS.AUC_RESP_INQ_DTL.GBL"

# Adding ?page=AUC_RESP_INQ_AUC (the form given in the project README) redirects to a
# login page. The bare component URL does not. Keep it bare.

PACKAGE_ACTION = "RESP_INQ_DL0_WK_AUC_DOWNLOAD_PB"
VIEW_ACTION = "PV_ATTACH_WRK_SCM_DOWNLOAD"

# PeopleSoft mixes attribute quoting: the event grid uses single quotes, the attachment
# grid uses double. Every pattern here accepts either -- a single-quote-only pattern
# silently yields zero rows, which is indistinguishable from "no attachments exist".
Q = r"['\"]"

_HIDDEN = re.compile(rf"<input[^>]*type={Q}hidden{Q}[^>]*>", re.I)
_ATTR = re.compile(rf"(\w+)={Q}([^'\"]*){Q}")
_WINDOW_OPEN = re.compile(r"window\.open\('([^']+)'")
_ATTACH_NAME = re.compile(rf"id={Q}PV_ATTACH_WRK_ATTACHUSERFILE\$(\d+){Q}[^>]*>([^<]+)<")
_ATTACH_DESCR = re.compile(rf"id={Q}PV_ATTACH_WRK_ATTACH_DESCR\$(\d+){Q}[^>]*?value={Q}([^'\"]*){Q}")
_ATTACH_VERSION = re.compile(rf"id={Q}CS_AUC_WRK_CS_VERSION\$(\d+){Q}[^>]*>([^<]*)<")
# Pager text, e.g. "First  1-6 of 6  Last" -- the independent count to assert against.
_PAGER = re.compile(r"(\d+)\s*-\s*(\d+)\s+of\s+(\d+)")

EVENT_FIELDS = {
    "business_unit": "RESP_INQA1_WK_BUSINESS_UNIT",
    "agency": r"BUS_UNIT_TBL_FS_DESCR\$201\$",
    "event_id": "AUC_ID_COL",
    "title": "RESP_INQA1_WK_ZZ_AUC_NAME",
    "format": "RESP_INQA1_WK_AUC_FORMAT_BIDBER",
    "event_type": "RESP_INQA1_WK_AUC_TYPE",
    "end_dttm": "RESP_INQA1_WK_AUC_DTTM_FINISH",
    "status": "ZZ_DERIVED_DESCR254",
    "buyer": "RESP_INQA1_WK_OPRDEFNDESC",
    "buyer_email": "RESP_INQA1_WK_EMAILID",
}
_TAGS = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    return htmllib.unescape(_TAGS.sub("", raw)).replace("\xa0", " ").strip()


def hidden_fields(page: str) -> dict[str, str]:
    """Every hidden input on a PeopleSoft page, including ICSID and ICStateNum."""
    out: dict[str, str] = {}
    for tag in _HIDDEN.findall(page):
        attrs = dict(_ATTR.findall(tag))
        if attrs.get("name"):
            out[attrs["name"]] = attrs.get("value", "")
    return out


def parse_event_list(page: str) -> list[dict[str, str]]:
    """Parse the active-event grid. Identity is (business_unit, event_id), not event_id."""
    rows: dict[int, dict[str, str]] = {}
    for key, base in EVENT_FIELDS.items():
        pat = re.compile(rf"id={Q}{base}\$(\d+){Q}[^>]*>(.*?)</(?:span|a)>", re.S)
        for idx, val in pat.findall(page):
            rows.setdefault(int(idx), {})[key] = _text(val)
    return [rows[i] for i in sorted(rows)]


def parse_attachments(page: str) -> list[dict[str, str]]:
    """Parse the attachment grid revealed by the event-package postback.

    Cross-checks the row count against the pager total. A quoting or markup change that
    breaks the row pattern looks exactly like an event with no attachments, so the
    mismatch is raised rather than returned as an empty list.
    """
    names = dict(_ATTACH_NAME.findall(page))
    descrs = dict(_ATTACH_DESCR.findall(page))
    versions = dict(_ATTACH_VERSION.findall(page))
    rows = [
        {
            "row": idx,
            "filename": htmllib.unescape(names[idx]).strip(),
            "description": htmllib.unescape(descrs.get(idx, "")).strip(),
            "version": versions.get(idx, "").strip(),
        }
        for idx in sorted(names, key=int)
    ]
    # The cross-check catches a markup change that would silently halve a grid. It only
    # fires when the parse found nothing at all, though: a detail page carries several
    # grids and `_PAGER` takes the first count on the page, so a mismatch against a
    # populated parse is at least as likely to be another grid's pager. Raising on that
    # aborted the event with no manifest row -- the silent-loss failure this module exists
    # to prevent.
    pager = _PAGER.search(page)
    if pager:
        declared = int(pager.group(3))
        if declared != len(rows):
            if not rows:
                raise ValueError(
                    f"attachment grid parsed 0 rows but a pager declares {declared}; "
                    "markup or attribute quoting probably changed"
                )
            # Parsed something, but not what the first pager on the page declares. Carried
            # on every row instead of raised: the count may belong to another grid, and
            # aborting lost the event's entire manifest rather than flagging a doubt.
            for row in rows:
                row["grid_count_mismatch"] = f"parsed {len(rows)}, pager declares {declared}"
    return rows


def role_from_filename(filename: str) -> str | None:
    """Numeric filename prefixes look like a role convention (01_ notice, 07_ addendum).

    Observed on one agency and one event only, so an unrecognised prefix returns None
    rather than a guess. Validate across agencies before trusting this.
    """
    m = re.match(r"^(\d{2})_", filename)
    if not m:
        return None
    return {"01": "notice", "02": "instructions", "03": "checklist", "07": "addendum"}.get(m.group(1))


def filename_solicitation_mismatch(filename: str, event_id: str) -> bool:
    """True when a filename names a different solicitation than the event it hangs off.

    Real case: 07_06A3334_Addendum_2_-_Responsible_Person_Question.pdf attached to event
    04A7615. README requires preserving both values and flagging, not reconciling.
    """
    tokens = re.findall(r"(?<![0-9A-Za-z])(\d{2}[A-Z]\d{4,})(?![0-9A-Za-z])", filename)
    # \b is useless here: underscore is a word character, so \b never fires inside
    # a name like 07_06A3334_Addendum. Lookarounds excluding alphanumerics do fire.
    return bool(tokens) and event_id not in tokens


class TransientFetchError(RuntimeError):
    """Every retry was exhausted. Recorded as a typed failure, never a silent empty result."""


@dataclass
class CalEProcureSession:
    """Carries the cookie jar and the PeopleSoft state chain.

    ICSID is constant for the session; ICStateNum increments on every postback and each
    POST must carry the value from the previous response. That makes attachment retrieval
    serial within one event.
    """

    delay_seconds: float = 1.5
    max_attempts: int = 3
    retry_backoff_seconds: float = 2.0
    _opener: Any = field(default=None, repr=False)
    _state: dict[str, str] = field(default_factory=dict, repr=False)
    _bootstrapped: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

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

    def get(self, url: str, referer: str | None = None, timeout: int = 120) -> tuple[bytes, Any]:
        headers = {"User-Agent": UA}
        if referer:
            headers["Referer"] = referer
        return self._open(urllib.request.Request(url, headers=headers), timeout)

    def post_raw(self, url: str, body: bytes, *, referer: str | None = None,
                 timeout: int = 180) -> tuple[bytes, Any]:
        """POST a caller-built form body, bypassing the session's state tracking.

        `post_action` is for components where this session harvested the page state itself.
        Some components -- the supplier search, for one -- are simpler to drive by reading
        their hidden fields directly and posting them back, so this exists rather than
        forcing every caller through the state machine.
        """
        headers = {
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
        }
        if referer:
            headers["Referer"] = referer
        return self._open(urllib.request.Request(url, data=body, headers=headers), timeout)

    def post_action(self, action: str, referer: str, timeout: int = 120,
                    url: str | None = None, extra: dict[str, str] | None = None,
                    ) -> tuple[bytes, Any]:
        """Fire one PeopleSoft ICAction against `url` (default: the event detail component).

        `extra` supplies search-criteria fields; SCPRS needs them, the attachment
        postbacks do not.
        """
        if not self._state:
            raise RuntimeError("no PeopleSoft state; GET a component page before posting")
        fields = dict(self._state)
        if extra:
            fields.update(extra)
        fields["ICAction"] = action
        req = urllib.request.Request(
            url or EVENT_DETAIL_URL,
            data=urllib.parse.urlencode(fields).encode(),
            headers={
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": referer,
            },
        )
        body, headers = self._open(req, timeout)
        self.absorb_state(body)
        return body, headers

    def absorb_state(self, body: bytes) -> None:
        """Refresh ICSID/ICStateNum from a response, if it is a page rather than a file."""
        if body[:5] == b"%PDF-":
            return
        found = hidden_fields(body.decode("utf-8", "replace"))
        if found.get("ICSID"):
            self._state = found

    def bootstrap(self) -> None:
        """GET the list component once to establish the session cookie."""
        if self._bootstrapped:
            return
        self.get(EVENT_LIST_URL)
        self._bootstrapped = True

    @property
    def state_num(self) -> str | None:
        return self._state.get("ICStateNum")


def _looks_like_html(data: bytes, content_type: str) -> bool:
    """True when the response is a web page rather than a document.

    PeopleSoft answers a stale or invalid state with a rendered page and HTTP 200, so the
    absence of file bytes is the failure signal, not the status code.
    """
    if "text/html" in (content_type or "").lower():
        return True
    head = data[:512].lstrip()[:64].lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"<?xml version=\"1.0\" encoding=\"utf-8\"?><!doctype")


def detail_url(business_unit: str, event_id: str) -> str:
    params = {
        "Page": "AUC_RESP_INQ_DTL", "Action": "U", "AUC_ID": event_id, "AUC_ROUND": "1",
        "BIDDER_ID": "BID0000001", "BIDDER_LOC": "1", "BIDDER_SETID": "STATE",
        "BIDDER_TYPE": "B", "BUSINESS_UNIT": business_unit,
    }
    return f"{EVENT_DETAIL_URL}?{urllib.parse.urlencode(params)}"


def fetch_event_list(session: CalEProcureSession) -> str:
    body, _ = session.get(EVENT_LIST_URL)
    session._bootstrapped = True
    return body.decode("utf-8", "replace")


def fetch_detail(session: CalEProcureSession, business_unit: str, event_id: str) -> str:
    # The list component seeds the session cookie. A detail GET on an unseeded session
    # returns a page whose package postback yields an empty attachment grid -- which is
    # indistinguishable from an event that genuinely has no documents. Seed once here so
    # call order cannot silently cost us a whole event's documents.
    session.bootstrap()
    url = detail_url(business_unit, event_id)
    body, _ = session.get(url, referer=EVENT_LIST_URL)
    page = body.decode("utf-8", "replace")
    session.absorb_state(body)
    return page


def fetch_attachments(
    session: CalEProcureSession, business_unit: str, event_id: str
) -> list[dict[str, Any]]:
    """Enumerate and download one event's attachments.

    Every row is returned whether or not its bytes arrived; a failure is recorded with a
    reason rather than dropped, per README's explicit-failure requirement.
    """
    # Fetch the detail page first: the package postback needs that page's ICSID and
    # ICStateNum, and requiring callers to remember the ordering is a footgun.
    fetch_detail(session, business_unit, event_id)
    referer = detail_url(business_unit, event_id)
    body, _ = session.post_action(PACKAGE_ACTION, referer)
    rows = parse_attachments(body.decode("utf-8", "replace"))

    results: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        record: dict[str, Any] = {
            "business_unit": business_unit,
            "event_id": event_id,
            "filename": row["filename"],
            "description": row["description"],
            "portal_version": row["version"],
            "document_role": role_from_filename(row["filename"]),
            "filename_solicitation_mismatch": filename_solicitation_mismatch(
                row["filename"], event_id
            ),
            "source_page": referer,
        }
        # Re-establish the page before every View. PeopleSoft validates ICStateNum against
        # the currently rendered page, and fetching an attachment navigates away from it,
        # so state drifts after the first row or two. Measured symptom before this fix:
        # events with 2 attachments succeeded while events with 8-15 mostly returned a
        # session page instead of a file. Costs two extra requests per document; the
        # alternative is silently losing most documents on document-heavy events.
        if index > 0:
            fetch_detail(session, business_unit, event_id)
            session.post_action(PACKAGE_ACTION, referer)
        page, _ = session.post_action(f"{VIEW_ACTION}${row['row']}", referer)
        match = _WINDOW_OPEN.search(page.decode("utf-8", "replace"))
        if not match:
            results.append({**record, "status": "no_serving_url"})
            continue
        serving_url = match.group(1)
        data, headers = session.get(serving_url, referer=referer)
        content_type = headers.get("Content-Type", "")
        # Do not test for PDF here. The measured corpus is roughly a third docx/xlsx/zip,
        # and an earlier PDF-only magic check silently rejected every Word document on a
        # 15-attachment event. This layer only distinguishes "a file arrived" from "a
        # PeopleSoft page arrived"; type and signature enforcement belongs to
        # documents.validate, which owns the accept/reject decision and its reasons.
        # Stamped here, at the fetch. The manifest is assembled later, sometimes much
        # later, and a provenance field that records assembly time is not a retrieval time.
        retrieved_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        if _looks_like_html(data, content_type):
            results.append({
                **record, "status": "unexpected_content", "content_type": content_type,
                "bytes": len(data), "magic": data[:8].hex(), "retrieved_at": retrieved_at,
            })
            continue
        results.append({
            **record, "status": "downloaded", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "content_type": content_type,
            "serving_url": serving_url, "content": data, "retrieved_at": retrieved_at,
        })
    return results


# --- event detail fields ----------------------------------------------------------------
# The detail page carries context absent from the list feed: commodity codes, service-area
# counties, and the addendum history. Parsed here so the opportunity record can hold them.
#
# One requirement cannot be met from this data. The brief asks a prime candidate to "cover
# the required geography". The opportunity side is available -- service-area counties below.
# The vendor side is not: SCPRS award rows carry no supplier location, and `where_cf`, whose
# name suggests one, holds reference identifiers (470 distinct values over 471 populated
# rows) rather than places. Vendor geography would need the supplier profile surface, which
# is not implemented. So counties are captured as opportunity context and geography matching
# is deliberately left unscored rather than approximated.

# The 58 California counties, for recovering service area from prose. The structured
# ZZ_SA_VW_COUNTY grid exists in the page schema but was empty (`&nbsp;`) on every event
# sampled, while the description carried "the counties of Alameda, Contra Costa, and Santa
# Clara" in plain text. Both paths are parsed; the structured one wins when populated.
CA_COUNTIES = (
    "Alameda", "Alpine", "Amador", "Butte", "Calaveras", "Colusa", "Contra Costa",
    "Del Norte", "El Dorado", "Fresno", "Glenn", "Humboldt", "Imperial", "Inyo", "Kern",
    "Kings", "Lake", "Lassen", "Los Angeles", "Madera", "Marin", "Mariposa", "Mendocino",
    "Merced", "Modoc", "Mono", "Monterey", "Napa", "Nevada", "Orange", "Placer", "Plumas",
    "Riverside", "Sacramento", "San Benito", "San Bernardino", "San Diego",
    "San Francisco", "San Joaquin", "San Luis Obispo", "San Mateo", "Santa Barbara",
    "Santa Clara", "Santa Cruz", "Shasta", "Sierra", "Siskiyou", "Solano", "Sonoma",
    "Stanislaus", "Sutter", "Tehama", "Trinity", "Tulare", "Tuolumne", "Ventura", "Yolo",
    "Yuba",
)
# Longest first so "San Luis Obispo" is not shadowed by a shorter prefix match.
_COUNTY_PROSE = re.compile(
    r"(?<![A-Za-z])(" + "|".join(re.escape(c) for c in
                                 sorted(CA_COUNTIES, key=len, reverse=True)) + r")(?![A-Za-z])")

# A county name only counts as a service area when the nearby text is about service areas.
_COUNTY_CUE = re.compile(r"count(?:y|ies)|service\s+area|statewide", re.I)

_UNSPSC = re.compile(rf"id={Q}ZZ_CATGRY_CD_VW_CATEGORY_CD\$(\d+){Q}[^>]*>(\d{{6,10}})<")
_COUNTY = re.compile(rf"id={Q}ZZ_SA_VW_COUNTY\$(\d+){Q}[^>]*>([^<]+)<")
_ADDENDUM = re.compile(r"(Addendum\s+#?\d+[^<\n]{0,120})", re.I)


def parse_detail_fields(page: str) -> dict[str, Any]:
    """Commodity codes, service-area counties and addendum mentions from a detail page."""
    unspsc = sorted({code for _, code in _UNSPSC.findall(page)})
    structured = sorted({_text(name) for _, name in _COUNTY.findall(page)
                         if _text(name) and _text(name) != ""})
    # Fall back to prose. Only county names on the official list are accepted, and only
    # where the surrounding text is talking about counties: every state buyer address sits
    # in Sacramento, so a bare name anywhere on the page yielded a service area of
    # "Sacramento" for most events, and item text yielded "Trinity".
    visible = htmllib.unescape(_TAGS.sub(" ", page))
    prose = sorted({m.group(1) for m in _COUNTY_PROSE.finditer(visible)
                    if _COUNTY_CUE.search(
                        visible[max(0, m.start() - 120):m.end() + 120])})
    counties = structured or prose
    addenda = []
    for raw in _ADDENDUM.findall(page):
        text = htmllib.unescape(" ".join(raw.split()))
        if text not in addenda:
            addenda.append(text)
    return {
        "unspsc_codes": unspsc,
        "service_area_counties": counties,
        "counties_source": ("structured_grid" if structured else
                            "description_text" if prose else "none_found"),
        "addenda_mentioned": addenda[:20],
        "addendum_count": len(addenda),
        "geography_note": (
            "service-area counties describe the opportunity only. The structured county grid "
            "was empty on every event sampled, so these are usually recovered from the "
            "description text. No vendor location exists in the award registry -- `where_cf`, "
            "whose name suggests one, holds reference identifiers -- so geography cannot be "
            "matched between opportunity and vendor and is left unscored, not approximated."),
    }
