"""CSLB contractor licence registry: a stable state identifier for CA contractors.

The Contractors State License Board publishes its whole register for download at no
charge and with no login. That matters here because it is the one identifier that
crosses the bidder sources: Caltrans and SF publish names only, PlanetBids publishes a
platform id that stops at its own edge, and vendor ads cite a CSLB number in free text.
A licence number keys all of them to the same company.

Three things this module has to get right.

**Stream, never buffer.** The master file runs to tens of megabytes and the machine it
harvests on may not have that spare. Rows are written straight to disk.

**A truncated download is not a small registry.** The first attempt died at 15.5MB with
`IncompleteRead` after 50,077 of roughly 290,000 rows, and the partial file parsed
perfectly well -- header intact, rows valid, simply missing five sixths of California.
So completeness is checked rather than assumed, and an incomplete file is never left
under the name a caller would read.

**It covers renewed and expired-but-renewable licences only.** Cancelled and revoked
licences are excluded, so absence means "not currently licensed", not "never existed".
"""
from __future__ import annotations

import csv
import io
import pathlib
import re
import shutil
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable, Iterator

from ...net import UA, TransientFetchError
from ...net.http import BROWSER_HEADERS

PORTAL = "https://www.cslb.ca.gov/onlineservices/dataportal/ContractorList"
SOURCE_KEY = "cslb_license_master"

# The dropdown values the portal offers, and the postback that downloads each as CSV.
FILES = {
    "license_master": ("M", "ctl00$MainContent$lbMasterCSV"),
    "workers_comp": ("W", "ctl00$MainContent$lbWCCSV"),
    "personnel": ("P", "ctl00$MainContent$lbPersonnelCSV"),
}
_HIDDEN = re.compile(
    r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"')
# Columns worth keeping for identity resolution. The file carries 52; the rest are
# bond and workers-comp detail that belongs in its own file.
KEEP = ("LicenseNo", "BusinessName", "FullBusinessName", "City", "State", "County",
        "ZIPCode", "BusinessType", "PrimaryStatus", "IssueDate", "ExpirationDate")


def hidden_fields(page: str) -> dict[str, str]:
    return dict(_HIDDEN.findall(page))


def _post(opener, fields: dict[str, str], timeout: int):
    request = urllib.request.Request(
        PORTAL, data=urllib.parse.urlencode(fields).encode(),
        headers={"User-Agent": UA, **BROWSER_HEADERS,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": PORTAL})
    return opener.open(request, timeout=timeout)


def download(fetcher, which: str = "license_master", *,
             dest: str | pathlib.Path = "data/raw/registries",
             timeout: int = 600, attempts: int = 4,
             on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Fetch one register file, streamed to disk, retrying a torn transfer.

    ASP.NET WebForms: load the page for its viewstate, fire the dropdown postback to
    reveal the download control, then post that control. The response is chunked and
    breaks at a different point each run -- 15.5MB then 6.5MB on two real attempts --
    so this is flaky transfer rather than a size ceiling. Each attempt writes its own
    file and the longest one is kept, because a retry exists to improve on a fragment,
    never to replace it with a smaller one.
    """
    if which not in FILES:
        raise ValueError(f"unknown CSLB file {which!r}; expected {sorted(FILES)}")
    say = on_progress or (lambda _m: None)
    directory = pathlib.Path(dest)
    directory.mkdir(parents=True, exist_ok=True)

    best: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        scratch = directory / f".cslb_{which}.attempt{attempt}"
        report = _download_once(fetcher, which, scratch, timeout, say)
        if best is None or report["rows"] > best["rows"]:
            if best is not None:
                pathlib.Path(best["path"]).unlink(missing_ok=True)
            best = report
        else:
            scratch.unlink(missing_ok=True)
        if report["complete"]:
            break
        say(f"attempt {attempt}/{attempts} torn at {report['rows']} rows; "
            + ("retrying" if attempt < attempts else "giving up"))
        if attempt < attempts:
            time.sleep(5 * attempt)

    assert best is not None
    kept = pathlib.Path(best["path"])
    target = (directory / f"cslb_{which}.csv" if best["complete"]
              else directory / f"cslb_{which}.PARTIAL.csv")
    kept.replace(target)
    best["path"] = str(target)
    say(f"{which}: {'complete' if best['complete'] else 'INCOMPLETE'}, "
        f"{best['rows']} rows, {best['bytes']/1048576:.1f}MB -> {target.name}")
    return best


def _download_once(fetcher, which: str, scratch: pathlib.Path,
                   timeout: int, say) -> dict[str, Any]:
    """One attempt, written to `scratch`. Never promotes anything."""
    value, control = FILES[which]
    opener = fetcher._opener

    page = fetcher.get(PORTAL, timeout=60)[0].decode("utf-8", "replace")
    with _post(opener, {**hidden_fields(page),
                        "__EVENTTARGET": "ctl00$MainContent$ddlStatus",
                        "ctl00$MainContent$ddlStatus": value}, 120) as response:
        revealed = response.read().decode("utf-8", "replace")
    if control.split("$")[-1] not in revealed:
        raise TransientFetchError(
            f"the {which} download control never appeared after selecting {value!r}")

    error: str | None = None
    with _post(opener, {**hidden_fields(revealed),
                        "__EVENTTARGET": control,
                        "ctl00$MainContent$ddlStatus": value}, timeout) as response, \
            scratch.open("wb") as handle:
        try:
            shutil.copyfileobj(response, handle, length=1024 * 512)
        except Exception as exc:
            # Keep what arrived: the shortfall is the finding, and throwing the bytes
            # away would mean downloading again to learn the same thing.
            error = f"{type(exc).__name__}: {exc}"
        written = handle.tell()

    report = verify(scratch)
    report.update({"file": which, "bytes": written, "source_key": SOURCE_KEY,
                   "transfer_error": error, "path": str(scratch)})
    if error:
        report["complete"] = False
    return report


def verify(path: str | pathlib.Path) -> dict[str, Any]:
    """Is this file a whole register or the front of one?

    A truncated CSV parses fine, so the signal is the last line: a complete download
    ends with a newline, and a torn one stops mid-row.
    """
    file = pathlib.Path(path)
    if not file.exists():
        return {"complete": False, "rows": 0, "reason": "file does not exist"}
    size = file.stat().st_size
    with file.open("rb") as handle:
        header = handle.readline().decode("utf-8", "replace")
        handle.seek(max(0, size - 4096))
        tail = handle.read().decode("utf-8", "replace")
    rows = sum(1 for _ in file.open("rb")) - 1
    ends_cleanly = tail.endswith("\n") or tail.endswith("\r\n")
    return {
        "complete": bool(ends_cleanly and rows > 0),
        "rows": max(rows, 0),
        "columns": len(next(csv.reader(io.StringIO(header)))) if header else 0,
        "reason": None if ends_cleanly else "last line is torn; download stopped early",
    }


def read_licences(path: str | pathlib.Path,
                  columns: Iterable[str] = KEEP) -> Iterator[dict[str, str]]:
    """Stream the register, keeping only the identity columns."""
    wanted = list(columns)
    with pathlib.Path(path).open(newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            yield {c: (row.get(c) or "").strip() for c in wanted}


def index_by_licence(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Licence number -> row. The join key vendor ads and bid tabulations point at."""
    return {r["LicenseNo"]: r for r in rows if r.get("LicenseNo")}
