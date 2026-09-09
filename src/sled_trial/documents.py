"""Document acquisition: validate, deduplicate, persist, and record every outcome.

Validation happens before anything reads the bytes, and a rejection is recorded as a
typed failure rather than dropped -- README requires blocked, expired, malformed and
inaccessible documents to appear as explicit failures.

Nothing here executes a downloaded file. Archives are inspected with `zipfile`, Office
documents are parsed as XML, and no macro, embedded object or script is ever run.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable

from . import extract

MAX_BYTES = 100 * 1024 * 1024  # a single public attachment above this is a red flag
MIN_BYTES = 64

# Suffix -> acceptable leading bytes. A file whose signature contradicts its extension is
# rejected: the extension is a claim, the signature is evidence.
MAGIC: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF-",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06"),
}
# Content types the portal is expected to serve. A mismatch is a warning, not a rejection:
# PeopleSoft mislabels often, and the file signature is the stronger check.
EXPECTED_CONTENT_TYPE = {
    ".pdf": ("application/pdf",),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "application/octet-stream"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "application/octet-stream"),
    ".zip": ("application/zip", "application/x-zip-compressed", "application/octet-stream"),
    ".csv": ("text/csv", "text/plain", "application/octet-stream"),
}
_UNSAFE_PATH = re.compile(r"[\x00-\x1f]|^\.+$|[/\\]")
# Formats that are zip containers, so structural integrity can be verified by opening them.
ZIP_BASED = frozenset({".docx", ".xlsx", ".zip"})


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def safe_filename(filename: str) -> str:
    """Filenames come from a remote portal; never let one escape its directory."""
    name = pathlib.PurePosixPath(filename).name
    name = _UNSAFE_PATH.sub("_", name).strip()
    return name[:180] or "unnamed"


def validate(data: bytes, filename: str, content_type: str | None) -> tuple[bool, list[str]]:
    """Return (accepted, notes). Notes are recorded whether or not the file is accepted."""
    notes: list[str] = []
    suffix = pathlib.PurePosixPath(filename.lower()).suffix
    if not data:
        return False, ["empty response body"]
    if len(data) < MIN_BYTES:
        return False, [f"suspiciously small: {len(data)} bytes"]
    if len(data) > MAX_BYTES:
        return False, [f"exceeds size cap: {len(data)} > {MAX_BYTES} bytes"]
    if suffix not in extract.SUPPORTED_SUFFIXES:
        return False, [f"unsupported type: {suffix or 'none'}"]
    expected_magic = MAGIC.get(suffix)
    if expected_magic and not data.startswith(expected_magic):
        return False, [f"signature mismatch for {suffix}: leading bytes {data[:8].hex()}"]
    allowed = EXPECTED_CONTENT_TYPE.get(suffix)
    if content_type and allowed:
        base = content_type.split(";")[0].strip().lower()
        if base not in allowed:
            notes.append(f"content-type {base!r} unexpected for {suffix} (accepted on signature)")

    # A correct signature at byte zero does not mean the whole payload is intact. One agency
    # attachment arrived starting with valid zip magic and ending with
    # "</PRE><hr> </BODY></HTML>" -- the portal had appended an error page to a partial
    # download. Its length even differed between fetches. It passed signature and size
    # checks, then failed silently at extraction and produced an empty page record, which is
    # indistinguishable from a document that genuinely contains no text.
    tail = data[-512:]
    if b"</html>" in tail.lower() or b"</body>" in tail.lower():
        return False, notes + ["payload ends with HTML: an error page was appended to a "
                               "partial download"]
    if suffix in ZIP_BASED:
        import io
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if archive.testzip() is not None:
                    return False, notes + ["archive contains a corrupt member"]
        except zipfile.BadZipFile as exc:
            return False, notes + [f"not a readable archive despite zip magic: {exc}"]
    return True, notes


class DocumentStore:
    """Writes bytes under a gitignored root and deduplicates on SHA-256.

    A hash already present is not written twice; the manifest still gains a row so the
    relationship between that event and that document is never lost.
    """

    def __init__(self, root: str | pathlib.Path) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._seen: dict[str, str] = {}

    def put(self, data: bytes, *, business_unit: str, event_id: str, filename: str,
            sha256: str) -> tuple[str, bool]:
        """Return (stored_path, was_duplicate_within_this_run).

        `was_duplicate` is scoped to this store instance, i.e. this run, because callers
        use it to skip re-extraction. Bytes already on disk from an earlier run are NOT a
        duplicate: skipping extraction for those produced an empty `document_pages.jsonl`
        on every re-run of the deliverable command, which looked exactly like an event
        whose documents contained no text.
        """
        if sha256 in self._seen:
            return self._seen[sha256], True
        folder = self.root / f"{safe_filename(business_unit)}_{safe_filename(event_id)}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_filename(filename)
        # Two attachments on one event can share a displayed filename. Overwriting left the
        # first document's manifest row pointing at the second document's bytes, with a
        # hash that no longer matched what was on disk.
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            path = path.with_name(f"{path.stem}.{sha256[:8]}{path.suffix}")
        if not (path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == sha256):
            path.write_bytes(data)
        self._seen[sha256] = str(path)
        return str(path), False


def manifest_record(doc: dict[str, Any], *, validated: bool, notes: list[str],
                    stored_path: str | None, duplicate_of_hash: str | None) -> dict[str, Any]:
    """Provenance row for one document, README's gov_procurement_documents shape.

    `content` (the raw bytes) is deliberately excluded so the manifest stays serialisable.
    """
    status = doc.get("status")
    if status == "downloaded" and not validated:
        status = "rejected"
    return {
        "business_unit": doc.get("business_unit"),
        "event_id": doc.get("event_id"),
        "document_ref": f"{doc.get('business_unit')}/{doc.get('event_id')}/{doc.get('filename')}",
        "displayed_filename": doc.get("filename"),
        "portal_description": doc.get("description") or None,
        "portal_version": doc.get("portal_version") or None,
        "document_role": doc.get("document_role"),
        "filename_solicitation_mismatch": doc.get("filename_solicitation_mismatch"),
        "source_page": doc.get("source_page"),
        "serving_url": doc.get("serving_url"),
        "content_type": doc.get("content_type") or None,
        "bytes": doc.get("bytes"),
        "sha256": doc.get("sha256"),
        # The fetch stamps this; manifest assembly time is only a fallback for rows that
        # never reached a download attempt.
        "retrieved_at": doc.get("retrieved_at") or utc_now(),
        "download_status": status,
        "validation_notes": notes or [],
        "stored_path": stored_path,
        "duplicate_of_sha256": duplicate_of_hash,
    }


def process_event_documents(
    docs: Iterable[dict[str, Any]], *, store: DocumentStore, allow_ocr: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate, persist and extract one event's documents.

    Returns (manifest_rows, page_rows). Every input document yields exactly one manifest
    row regardless of outcome.
    """
    manifest: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    for doc in docs:
        if doc.get("status") != "downloaded":
            manifest.append(manifest_record(doc, validated=False,
                                            notes=[f"not retrieved: {doc.get('status')}"],
                                            stored_path=None, duplicate_of_hash=None))
            continue
        data = doc.get("content") or b""
        ok, notes = validate(data, doc["filename"], doc.get("content_type"))
        if not ok:
            manifest.append(manifest_record(doc, validated=False, notes=notes,
                                            stored_path=None, duplicate_of_hash=None))
            continue
        stored_path, duplicate = store.put(
            data, business_unit=doc["business_unit"], event_id=doc["event_id"],
            filename=doc["filename"], sha256=doc["sha256"])
        manifest.append(manifest_record(
            doc, validated=True, notes=notes, stored_path=stored_path,
            duplicate_of_hash=doc["sha256"] if duplicate else None))
        if duplicate:
            continue  # identical bytes already extracted; do not re-extract
        ref = f"{doc['business_unit']}/{doc['event_id']}/{doc['filename']}"
        for page in extract.extract_document(
                data, filename=doc["filename"], document_ref=ref,
                sha256=doc["sha256"], allow_ocr=allow_ocr):
            page["business_unit"] = doc["business_unit"]
            page["event_id"] = doc["event_id"]
            page["displayed_filename"] = doc["filename"]
            pages.append(page)
    return manifest, pages


def write_jsonl(rows: Iterable[dict[str, Any]], path: str | pathlib.Path) -> int:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count
