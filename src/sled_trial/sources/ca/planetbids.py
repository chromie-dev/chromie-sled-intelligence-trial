"""PlanetBids agency portals: the largest bidder-list corpus in California local government.

Hundreds of CA cities, counties, school and special districts run a portal here, one per
agency, keyed by a numeric `companyId`. Unlike the state portal, these publish **who
competed** rather than only who won:

* `bid-prospective-bidders` - every company that took out the documents, with contact
  details, small/disadvantaged-business classifications, and whether it attended the
  pre-bid meeting. That is declared interest, not a bid.
* `bid-responses` - the companies that actually responded, with rank, amount and whether
  the response was judged responsive. That is a bid.

Both carry `vendorId`, a stable platform identifier, so bidders resolve by id instead of
by name matching. That is the difference between this source and the agency PDF sources:
`vendors.resolve_bidder_identities` has to guess at Caltrans and SF names, and does not
have to guess here.

The portal is a single-page app whose JSON API answers 403 to a bare client, so a caller
supplies `fetch_json` backed by a real browser session. Nothing here performs a request
itself, which is what keeps the module testable offline and read-only by construction.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse
from typing import Any, Callable, Iterable, Iterator

API = "https://api-external.prod.planetbids.com/papi"
PORTAL = "https://pbsystem.planetbids.com/portal/{cid}/bo/bo-search"
DETAIL = "https://pbsystem.planetbids.com/portal/{cid}/bo/bo-detail/{bid_id}"
SOURCE_KEY = "planetbids_agency_portal"

# The API rejects any other page size with a 400; discovered the hard way.
PAGE_SIZE = 30

# stageId -> label, as the portal's own filter names them.
STAGES = {1: "Planning", 2: "Bidding", 4: "Closed", 5: "Award Pending",
          6: "Awarded", 7: "Canceled", 8: "Rejected"}
# Stages where a bidder field can exist at all. A bid still open has no respondents, and
# harvesting one would record "no bidders" for a solicitation that simply has not closed.
CLOSED_STAGES = (4, 5, 6)


AGENCY_REGISTRY = "sources/planetbids/agencies.csv"


def curated_agencies(path: str = AGENCY_REGISTRY) -> list[dict[str, str]]:
    """The agency portals we harvest, as a checked-in list.

    PlanetBids publishes no directory -- `/papi/agencies/{id}` resolves one id but the
    collection form 404s -- so the set is curated rather than discovered, and each id is
    confirmed against that endpoint before it lands here. Probing the id space would
    find more, and is not worth doing to a live portal at volume.
    """
    import csv
    import pathlib as _p

    file = _p.Path(path)
    if not file.exists():
        return []
    with file.open() as fh:
        return [r for r in csv.DictReader(fh) if (r.get("company_id") or "").strip()]


def bids_url(cid: int | str, page: int = 1, stage_id: int = 0) -> str:
    """One page of an agency's solicitations. `stage_id=0` means every stage."""
    return (f"{API}/bids?bid_type_id=0&cid={cid}&dept_id=0&due_date_from=&due_date_to="
            f"&keyword=&page={page}&per_page={PAGE_SIZE}&sort_by=&sort_order=-1"
            f"&stage_id={stage_id}")


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Flatten a JSON:API document to a list of attribute dicts."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        data = [data]
    return [r.get("attributes", {}) for r in (data or []) if isinstance(r, dict)]


def total_pages(payload: Any) -> int:
    meta = (payload or {}).get("meta") or {}
    return int(meta.get("totalPages") or 0)


def total_bids(payload: Any) -> int:
    meta = (payload or {}).get("meta") or {}
    return int(meta.get("totalBids") or 0)


def parse_bids(payload: Any) -> list[dict[str, Any]]:
    """Solicitations from one page of the bid list."""
    out = []
    for a in _rows(payload):
        stage_id = a.get("stageId")
        out.append({
            "bid_id": a.get("bidId"),
            "company_id": a.get("companyId"),
            "title": (a.get("title") or "").strip(),
            "invitation_number": (a.get("invitationNum") or "").strip(),
            "issue_date": a.get("issueDate"),
            "due_date": a.get("bidDueDate"),
            "stage_id": stage_id,
            "stage": a.get("stageStr") or STAGES.get(stage_id),
            "bid_type_id": a.get("bidTypeId"),
            "by_invitation": bool(a.get("byInvitation")),
            "category_ids": [c.strip() for c in (a.get("categoryIds") or "").split(",")
                             if c.strip()],
        })
    return out


def _money(value: Any) -> float | None:
    """Amount, or None. Zero is 'not published' here, not a free bid."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _rank(value: Any) -> int | None:
    """Rank, or None. The portal writes 0 when it has not ranked the field."""
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def _classifications(value: Any) -> list[str]:
    """`dbeStatus` is a comma-joined set of certifications: OSB, CADIR, WBE, MBE..."""
    return [c.strip() for c in (value or "").split(",") if c.strip()]


def parse_prospective_bidders(payload: Any) -> list[dict[str, Any]]:
    """Planholders: companies that took out the documents.

    Declared interest, never a bid. A planholder list routinely runs several times the
    length of the response list -- 57 against 6 on the reference solicitation -- so
    treating these as bidders would inflate the competitive field roughly tenfold.
    """
    out = []
    for a in _rows(payload):
        out.append({
            "bid_id": a.get("bidId"),
            "vendor_id": a.get("vendorId"),
            "bidder_id": a.get("bidderId"),
            "vendor_name": (a.get("vendorName") or "").strip(),
            "contact_name": (a.get("contactName") or "").strip() or None,
            "phone": (a.get("phone") or "").strip() or None,
            "city": (a.get("city") or "").strip() or None,
            "zip_code": (a.get("zipCode") or "").strip() or None,
            "classifications": _classifications(a.get("dbeStatus")),
            "pre_bid_meeting_attendee": bool(a.get("preBidMtgAttendee")),
            "is_prime": a.get("classification") == 1,
        })
    return out


def parse_responses(payload: Any) -> list[dict[str, Any]]:
    """Submissions: the companies that actually bid."""
    out = []
    for a in _rows(payload):
        out.append({
            "bid_id": a.get("bidId"),
            "vendor_id": a.get("vendorId"),
            "bidder_id": a.get("bidderId"),
            "response_id": a.get("responseId"),
            "vendor_name": (a.get("vendorName") or "").strip(),
            "rank": _rank(a.get("ranking")),
            "amount": _money(a.get("amount")),
            # `responsive` is tri-state: 1 yes, 2 no, 0 not yet judged. Collapsing the
            # last two to False would record a responsive bidder as rejected.
            "responsive": {1: True, 2: False}.get(a.get("responsive")),
            "city": (a.get("city") or "").strip() or None,
            "classifications": _classifications(a.get("dbeStatus")),
        })
    return out


def parse_documents(payload: Any) -> list[dict[str, Any]]:
    """Documents attached to a solicitation.

    Field names are as the API returns them, verified against a live response rather
    than guessed: an earlier version looked for `fileId`, `fileName` and `requiresLogin`,
    none of which exist, so every filename came back empty and every document looked
    publicly readable.

    `publiclyVisible` is the login gate the portal shows as an asterisk in its own
    document list, and `recalled` marks a file the agency has withdrawn -- usually
    superseded by an addendum. Both are carried rather than filtered, so a caller
    decides what to fetch.
    """
    out = []
    for a in _rows(payload):
        server_path = (a.get("serverFullPath") or "").strip()
        server_name = (a.get("serverFilename") or "").strip()
        out.append({
            "bid_id": a.get("bidId"),
            "file_id": a.get("downloadableFileId"),
            "title": (a.get("fileTitle") or "").strip() or None,
            "file_name": (a.get("filename") or "").strip() or None,
            "size_bytes": a.get("fileSize"),
            "uploaded": a.get("uploadedDate"),
            "sort_label": (a.get("sortLabel") or "").strip() or None,
            "publicly_visible": bool(a.get("publiclyVisible")),
            "recalled": bool(a.get("recalled")),
            "download_url": document_url(server_path, server_name),
        })
    return out


def document_url(server_path: str | None, server_filename: str | None) -> str | None:
    """Where a document actually lives.

    The API returns the host and directory separately from the stored filename, and the
    stored name routinely contains spaces, so it has to be quoted rather than pasted.
    """
    if not server_path or not server_filename:
        return None
    path = server_path.strip().strip("/")
    return f"https://{path}/{urllib.parse.quote(server_filename.strip())}"


def with_derived_rank(responses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank the field by amount when the portal has not ranked it itself.

    Most agencies here leave `ranking` at 0 while still publishing every amount, so the
    low bidder is knowable but unstated. Same situation as the SF tabulations, and
    handled the same way: derive the order, keep it in a separate field, and never
    overwrite what the portal actually asserted. `rank` stays null so a caller can always
    tell a stated rank from an inferred one.
    """
    priced = sorted((r for r in responses if r["amount"] is not None),
                    key=lambda r: r["amount"])
    order = {id(r): n for n, r in enumerate(priced, start=1)}
    return [{**r, "derived_rank": order.get(id(r))} for r in responses]


def bidder_candidates(bid: dict[str, Any], responses: Iterable[dict[str, Any]],
                      *, cid: int | str) -> list[dict[str, Any]]:
    """Observed-bidder rows in the shape the participant export already reads.

    Emitting into the existing shape means these flow through
    `supabase_export.participant_rows` without a second code path, exactly as the
    Caltrans and SF adapters do.
    """
    evidence = DETAIL.format(cid=cid, bid_id=bid["bid_id"])
    rows = []
    for r in with_derived_rank(list(responses)):
        rows.append({
            "business_unit": f"PB{cid}",
            "event_id": str(bid["bid_id"]),
            "vendor_name_raw": r["vendor_name"],
            "vendor_id": r["vendor_id"],
            "rank": r["rank"],
            "derived_rank": r.get("derived_rank"),
            "amount_numeric": r["amount"],
            "amount_raw": None if r["amount"] is None else f"{r['amount']:.2f}",
            "responsive": r["responsive"],
            "classifications": r["classifications"],
            "source_key": SOURCE_KEY,
            "evidence_url": evidence,
            "evidence_row": " | ".join(
                p for p in (r["vendor_name"],
                            None if r["rank"] is None else f"rank {r['rank']}",
                            None if r["amount"] is None else f"{r['amount']:.2f}")
                if p),
        })
    return rows


def declared_interest_rows(bid: dict[str, Any], planholders: Iterable[dict[str, Any]],
                           *, cid: int | str) -> list[dict[str, Any]]:
    """Planholders, tagged so they can never be counted as bidders."""
    evidence = DETAIL.format(cid=cid, bid_id=bid["bid_id"])
    return [{
        "business_unit": f"PB{cid}",
        "event_id": str(bid["bid_id"]),
        "vendor_name_raw": p["vendor_name"],
        "vendor_id": p["vendor_id"],
        "participation": "declared_interest",
        "pre_bid_meeting_attendee": p["pre_bid_meeting_attendee"],
        "classifications": p["classifications"],
        "source_key": SOURCE_KEY,
        "evidence_url": evidence,
    } for p in planholders]


def harvest_agency(fetch_json: Callable[[str], Any], cid: int | str, *,
                   max_bids: int | None = None,
                   stages: tuple[int, ...] = CLOSED_STAGES,
                   on_progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Walk one agency portal and return its solicitations, bidders and planholders.

    `fetch_json` performs the request; this module never does. A bid whose fetch fails is
    recorded as a typed failure rather than dropped, because a silently missing
    solicitation is indistinguishable from one with no bidders.
    """
    say = on_progress or (lambda _msg: None)
    bids: list[dict[str, Any]] = []
    page, pages, reported = 1, None, 0
    while True:
        payload = fetch_json(bids_url(cid, page=page))
        chunk = parse_bids(payload)
        if pages is None:
            pages, reported = total_pages(payload), total_bids(payload)
            say(f"{reported} solicitations across {pages} pages")
        bids += chunk
        if len(chunk) < PAGE_SIZE or (pages and page >= pages):
            break
        page += 1

    wanted = [b for b in bids if b["stage_id"] in stages]
    if max_bids is not None:
        wanted = wanted[:max_bids]
    say(f"{len(wanted)} of {len(bids)} solicitations are closed enough to name a field")

    out: dict[str, Any] = {
        "company_id": cid, "bids": bids,
        "bids_reported_by_portal": reported, "bids_collected": len(bids),
        "complete": reported == 0 or len(bids) >= reported,
        "candidates": [], "declared_interest": [], "documents": [],
        # `failures` is "we could not read it"; `absent` is "the portal says it does not
        # exist". Merging them would let a real outage read as an empty solicitation.
        "failures": [], "absent": [], "harvested_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    def _part(bid_id: int, endpoint: str, parse):
        """One endpoint for one bid, isolated.

        The endpoints fail independently: a solicitation with no response set answers
        `bid-responses` with HTTP 400 while still serving its planholders. Failing the
        whole bid on that loses real data, so each part is fetched on its own.

        A 400 is recorded as `absent` rather than as an error, because it is the API
        saying the set does not exist -- but it is still recorded, never swallowed, so
        "no responses published" stays distinguishable from "we did not look".
        """
        try:
            return parse(fetch_json(f"{API}/{endpoint}?bid_id={bid_id}")), None
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            kind = "absent" if "HTTP 400" in detail else "error"
            return [], {"bid_id": bid_id, "endpoint": endpoint,
                        "outcome": kind, "detail": detail[:200]}

    for bid in wanted:
        bid_id = bid["bid_id"]
        responses, r_note = _part(bid_id, "bid-responses", parse_responses)
        planholders, p_note = _part(bid_id, "bid-prospective-bidders",
                                    parse_prospective_bidders)
        documents, d_note = _part(bid_id, "bid-downloadable-files", parse_documents)
        for note in (r_note, p_note, d_note):
            if note:
                out["failures" if note["outcome"] == "error" else "absent"].append(note)
        out["candidates"] += bidder_candidates(bid, responses, cid=cid)
        out["declared_interest"] += declared_interest_rows(bid, planholders, cid=cid)
        out["documents"] += documents
    say(f"{len(out['candidates'])} bidders, "
        f"{len(out['declared_interest'])} planholders, "
        f"{len(out['failures'])} failures, "
        f"{len(out['absent'])} sets the portal reports as absent")
    return out
