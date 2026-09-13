"""PDF text extraction, page-addressable, native text first and OCR only as fallback."""
from __future__ import annotations

import hashlib
import io
import pathlib
import re
from typing import Any, Iterator

import pdfplumber

# A page with almost no extractable text is probably a scan. The threshold is deliberately
# low: the cost of a needless OCR pass is time, the cost of skipping one is a silently
# empty page that later reads as "this document says nothing".
NATIVE_TEXT_MIN_CHARS = 20
OCR_DPI = 200
MAX_TABLES = 20
MAX_TABLE_ROWS = 200


def ocr_available() -> tuple[bool, str]:
    """OCR needs two Python packages and two system binaries. Report, never crash."""
    try:
        import pytesseract  # noqa: F401
        import pdf2image  # noqa: F401
    except ImportError as exc:
        return False, f"python package missing: {exc.name}"
    import shutil
    for binary in ("tesseract", "pdftoppm"):
        if not shutil.which(binary):
            return False, f"system binary missing: {binary}"
    return True, "available"


def _ocr_page(pdf_bytes: bytes, page_number: int) -> tuple[str, float | None, str | None]:
    try:
        import pdf2image
        import pytesseract
    except ImportError as exc:  # pragma: no cover - guarded by ocr_available
        return "", None, f"ocr import failed: {exc}"
    try:
        images = pdf2image.convert_from_bytes(
            pdf_bytes, dpi=OCR_DPI, first_page=page_number, last_page=page_number)
        if not images:
            return "", None, "ocr produced no image"
        data = pytesseract.image_to_data(
            images[0], output_type=pytesseract.Output.DICT)
        words = [w for w in data.get("text", []) if w.strip()]
        confs = [float(c) for c in data.get("conf", []) if str(c) not in ("-1", "")]
        mean_conf = round(sum(confs) / len(confs), 2) if confs else None
        return " ".join(words), mean_conf, None
    except Exception as exc:
        return "", None, f"ocr failed: {type(exc).__name__}: {exc}"[:200]


def extract_pages(
    pdf_bytes: bytes, *, document_ref: str, sha256: str, allow_ocr: bool = True
) -> Iterator[dict[str, Any]]:
    """Yield one record per page.

    Every page yields a record even when extraction fails, so a document never silently
    loses pages. `method` is native, ocr, hybrid, or none.
    """
    ocr_ok, ocr_note = ocr_available()
    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    except Exception as exc:
        yield {
            "document_ref": document_ref, "sha256": sha256, "page": None,
            "method": "none", "text": None, "ocr_confidence": None,
            "warnings": [f"pdf open failed: {type(exc).__name__}: {exc}"[:200]],
        }
        return

    with pdf:
        for index, page in enumerate(pdf.pages, start=1):
            warnings: list[str] = []
            native = ""
            try:
                native = page.extract_text() or ""
            except Exception as exc:
                warnings.append(f"native extract failed: {type(exc).__name__}"[:120])

            tables: list[list[list[str | None]]] = []
            try:
                tables = page.extract_tables() or []
            except Exception as exc:
                warnings.append(f"table extract failed: {type(exc).__name__}"[:120])

            text, method, conf = native, "native", None
            if len(native.strip()) < NATIVE_TEXT_MIN_CHARS:
                if allow_ocr and ocr_ok:
                    ocr_text, conf, err = _ocr_page(pdf_bytes, index)
                    if err:
                        warnings.append(err)
                    if ocr_text.strip():
                        text = f"{native}\n{ocr_text}".strip() if native.strip() else ocr_text
                        method = "hybrid" if native.strip() else "ocr"
                    elif not native.strip():
                        method = "none"
                        warnings.append("no text from native or ocr")
                else:
                    method = "native" if native.strip() else "none"
                    warnings.append(f"sparse text, ocr not run ({ocr_note})")

            yield {
                "document_ref": document_ref,
                "sha256": sha256,
                "page": index,
                "method": method,
                "text": text or None,
                "char_count": len(text or ""),
                "ocr_confidence": conf,
                "table_count": len(tables),
                "table_row_counts": [len(t) for t in tables],
                # Cells are retained, not just counted: bidder names and bid amounts in
                # award notices live in tables, not in prose. Capped so one pathological
                # page cannot dominate the output file.
                "tables": [[[(c or "")[:200] for c in row] for row in t[:MAX_TABLE_ROWS]]
                           for t in tables[:MAX_TABLES]],
                "warnings": warnings,
            }


# --- participant mining from award-notice tables -----------------------------------
# The DMV intent-to-award notice puts the awardee in a two-column table
# (["Company Name", "Bid Amount"], ["AVIATE ENTERPRISES, INC.", "$437,862.48"]).
# A prose label regex misses this entirely and, measured, produced 8 false positives in 9
# results, so tables are the only extraction path. The prose miner written first was
# deleted rather than left as an unused fallback.

_VENDOR_HEADER = re.compile(
    r"company|vendor|supplier|bidder|proposer|contractor|firm|business\s+name", re.I)
_AMOUNT_HEADER = re.compile(r"amount|price|bid|cost|total|quote", re.I)
_RANK_HEADER = re.compile(r"rank|score|position|place", re.I)
_MONEY = re.compile(r"^\s*\$?\s*[\d,]+(?:\.\d{1,2})?\s*$")
_NOT_A_VENDOR = re.compile(
    r"^(?:company\s+name|vendor|supplier|bidder|total|n/?a|none|tbd|\s*)$", re.I)


def _amount_to_decimal(cell: str) -> str | None:
    """Keep the raw string too; never coerce an unparseable amount into a number."""
    cell = (cell or "").strip()
    if not _MONEY.match(cell):
        return None
    return cell.replace("$", "").replace(",", "").strip() or None


# Precision guards. Measured on a real 6-event corpus, the permissive first version
# returned 1 true awardee and 8 false positives -- pdfplumber reports prose blocks in RFQ
# documents as "tables", and words like "bidder" and "bid" appear throughout solicitation
# boilerplate, so a loose header match fires on requirement text. A false `known_bidder`
# is the most damaging error this pipeline can make, so the bar is deliberately high and
# recall is sacrificed: a missed bidder is a gap, a fabricated one is a lie.
MAX_HEADER_CELL_CHARS = 40   # real header labels are short; a paragraph is not a header
MAX_VENDOR_WORDS = 9
MAX_VENDOR_CHARS = 120
_SENTENCE_SHAPED = re.compile(r"[.;]\s+\S|:\s*$|\b(?:the|shall|must|following|please|will)\b", re.I)


def _is_entity_shaped(name: str) -> bool:
    """Reject sentences, headings and requirement text posing as a company name."""
    if not (2 < len(name) <= MAX_VENDOR_CHARS):
        return False
    if len(name.split()) > MAX_VENDOR_WORDS:
        return False
    if _SENTENCE_SHAPED.search(name):
        return False
    if name.endswith((":", ".")) and not re.search(r"\b(?:inc|llc|ltd|corp|co)\.$", name, re.I):
        return False
    return True


def participants_from_tables(tables: list[list[list[str]]]) -> list[dict[str, Any]]:
    """Rows that pair a company name with a parseable money amount, a rank, or both.

    Returns candidates with the evidence row attached. A candidate is not a resolved
    vendor: the name still has to reconcile against SCPRS supplier_id, and the citing
    document and page must travel with any claim.

    A row is only accepted when the table looks like a real tabulation: short header
    labels, a vendor column and a value column at *different* indices, an amount that
    actually parses as money (or a numeric rank), and a name shaped like an entity rather
    than a sentence.
    """
    out: list[dict[str, Any]] = []
    for table in tables or []:
        if not table or len(table) < 2:
            continue
        header = [(c or "").strip() for c in table[0]]
        if not header or any(len(h) > MAX_HEADER_CELL_CHARS for h in header):
            continue  # a "header" full of prose means this is not a tabulation
        vendor_col = next((i for i, h in enumerate(header) if _VENDOR_HEADER.search(h)), None)
        if vendor_col is None:
            continue
        amount_col = next((i for i, h in enumerate(header)
                           if i != vendor_col and _AMOUNT_HEADER.search(h)), None)
        rank_col = next((i for i, h in enumerate(header)
                         if i != vendor_col and _RANK_HEADER.search(h)), None)
        if amount_col is None and rank_col is None:
            continue  # a vendor column alone carries no participation evidence
        for row in table[1:]:
            cells = [(c or "").strip() for c in row]
            if vendor_col >= len(cells):
                continue
            name = cells[vendor_col]
            if not name or _NOT_A_VENDOR.match(name) or not _is_entity_shaped(name):
                continue
            raw_amount = cells[amount_col] if amount_col is not None and amount_col < len(cells) else None
            numeric = _amount_to_decimal(raw_amount) if raw_amount else None
            raw_rank = cells[rank_col] if rank_col is not None and rank_col < len(cells) else None
            rank = raw_rank if raw_rank and raw_rank.strip().isdigit() else None
            if numeric is None and rank is None:
                continue  # an unparseable value is not evidence of participation
            if raw_amount and raw_amount.strip() == name.strip():
                continue  # same cell resolved twice: a one-column layout artefact
            out.append({
                "vendor_name_raw": name[:200],
                "amount_raw": raw_amount or None,
                "amount_numeric": numeric,
                "rank_raw": rank,
                "header": header,
                "evidence_row": cells,
            })
    return out


# --- non-PDF formats -----------------------------------------------------------------
# The measured corpus is 94 pdf / 28 docx / 9 xlsx / 5 zip / 1 csv, so a PDF-only reader
# would silently lose a bid tabulation posted as a spreadsheet. docx is parsed with the
# standard library (it is a zip of XML); xlsx uses openpyxl because shared-string and
# cell-reference handling is where a hand-rolled reader gets quietly wrong.

import csv as _csv
import xml.etree.ElementTree as _ET
import zipfile as _zipfile

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx(data: bytes, *, document_ref: str, sha256: str) -> Iterator[dict[str, Any]]:
    """One record for the whole document; docx has no intrinsic page boundaries."""
    warnings: list[str] = []
    paragraphs: list[str] = []
    tables: list[list[list[str]]] = []
    try:
        with _zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml")
        body = _ET.fromstring(xml)
        for para in body.iter(f"{_W}p"):
            text = "".join(t.text or "" for t in para.iter(f"{_W}t"))
            if text.strip():
                paragraphs.append(text)
        for tbl in body.iter(f"{_W}tbl"):
            rows: list[list[str]] = []
            for tr in tbl.iter(f"{_W}tr"):
                cells = ["".join(t.text or "" for t in tc.iter(f"{_W}t")).strip()
                         for tc in tr.iter(f"{_W}tc")]
                if cells:
                    rows.append(cells[:64])
                if len(rows) >= MAX_TABLE_ROWS:
                    break
            if rows:
                tables.append(rows)
            if len(tables) >= MAX_TABLES:
                break
    except (KeyError, _zipfile.BadZipFile, _ET.ParseError) as exc:
        warnings.append(f"docx parse failed: {type(exc).__name__}: {exc}"[:200])
    text = "\n".join(paragraphs)
    yield {
        "document_ref": document_ref, "sha256": sha256, "page": 1,
        "method": "docx" if text or tables else "none",
        "text": text or None, "char_count": len(text),
        "ocr_confidence": None, "table_count": len(tables),
        "table_row_counts": [len(t) for t in tables], "tables": tables,
        "warnings": warnings,
    }


def extract_xlsx(data: bytes, *, document_ref: str, sha256: str) -> Iterator[dict[str, Any]]:
    """One record per worksheet. Each sheet's used range becomes a single table."""
    try:
        import openpyxl
    except ImportError:
        yield {"document_ref": document_ref, "sha256": sha256, "page": None, "method": "none",
               "text": None, "char_count": 0, "ocr_confidence": None, "table_count": 0,
               "table_row_counts": [], "tables": [],
               "warnings": ["openpyxl not installed"]}
        return
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        yield {"document_ref": document_ref, "sha256": sha256, "page": None, "method": "none",
               "text": None, "char_count": 0, "ocr_confidence": None, "table_count": 0,
               "table_row_counts": [], "tables": [],
               "warnings": [f"xlsx open failed: {type(exc).__name__}: {exc}"[:200]]}
        return
    try:
        for index, ws in enumerate(wb.worksheets, start=1):
            rows: list[list[str]] = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c)[:200] for c in row]
                if any(c.strip() for c in cells):
                    rows.append(cells[:64])
                if len(rows) >= MAX_TABLE_ROWS:
                    break
            text = "\n".join("\t".join(r) for r in rows)
            yield {
                "document_ref": document_ref, "sha256": sha256, "page": index,
                "sheet_name": ws.title, "method": "xlsx" if rows else "none",
                "text": text or None, "char_count": len(text), "ocr_confidence": None,
                "table_count": 1 if rows else 0, "table_row_counts": [len(rows)] if rows else [],
                "tables": [rows] if rows else [], "warnings": [],
            }
    finally:
        wb.close()


def extract_csv(data: bytes, *, document_ref: str, sha256: str) -> Iterator[dict[str, Any]]:
    warnings: list[str] = []
    try:
        text_data = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text_data = data.decode("latin-1", "replace")
        warnings.append("decoded as latin-1 after utf-8 failure")
    try:
        rows = [r[:64] for r in _csv.reader(io.StringIO(text_data))][:MAX_TABLE_ROWS]
    except _csv.Error as exc:
        # A NUL byte or an oversized field raises here. Every other extractor turns a parse
        # failure into a warning row; letting this one propagate killed the whole event.
        rows = []
        warnings.append(f"csv parse failed: {exc}")
    rows = [[(c or "")[:200] for c in r] for r in rows if any((c or "").strip() for c in r)]
    text = "\n".join("\t".join(r) for r in rows)
    yield {
        "document_ref": document_ref, "sha256": sha256, "page": 1,
        "method": "csv" if rows else "none", "text": text or None, "char_count": len(text),
        "ocr_confidence": None, "table_count": 1 if rows else 0,
        "table_row_counts": [len(rows)] if rows else [], "tables": [rows] if rows else [],
        "warnings": warnings,
    }


SUPPORTED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".csv", ".zip"}


def extract_document(
    data: bytes, *, filename: str, document_ref: str, sha256: str, allow_ocr: bool = True,
    _depth: int = 0,
) -> Iterator[dict[str, Any]]:
    """Dispatch on suffix. An unsupported type yields an explicit skip, never silence.

    Archives are expanded one level; a zip inside a zip is recorded and not followed,
    which keeps a maliciously nested archive from turning into unbounded work.
    """
    suffix = pathlib.PurePosixPath(filename.lower()).suffix
    if suffix == ".pdf":
        yield from extract_pages(data, document_ref=document_ref, sha256=sha256,
                                 allow_ocr=allow_ocr)
    elif suffix == ".docx":
        yield from extract_docx(data, document_ref=document_ref, sha256=sha256)
    elif suffix == ".xlsx":
        yield from extract_xlsx(data, document_ref=document_ref, sha256=sha256)
    elif suffix == ".csv":
        yield from extract_csv(data, document_ref=document_ref, sha256=sha256)
    elif suffix == ".zip":
        if _depth > 0:
            yield _skip(document_ref, sha256, "nested archive not expanded")
            return
        try:
            with _zipfile.ZipFile(io.BytesIO(data)) as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                if not members:
                    yield _skip(document_ref, sha256, "archive is empty")
                for member in members:
                    inner_ref = f"{document_ref}!{member.filename}"
                    inner_suffix = pathlib.PurePosixPath(member.filename.lower()).suffix
                    if inner_suffix not in SUPPORTED_SUFFIXES:
                        yield _skip(inner_ref, sha256, f"unsupported type in archive: {inner_suffix or 'none'}")
                        continue
                    inner = zf.read(member)
                    yield from extract_document(
                        inner, filename=member.filename, document_ref=inner_ref,
                        sha256=hashlib.sha256(inner).hexdigest(), allow_ocr=allow_ocr,
                        _depth=_depth + 1)
        except _zipfile.BadZipFile as exc:
            yield _skip(document_ref, sha256, f"bad archive: {exc}"[:160])
    else:
        yield _skip(document_ref, sha256, f"unsupported type: {suffix or 'none'}")


def _skip(document_ref: str, sha256: str, reason: str) -> dict[str, Any]:
    return {"document_ref": document_ref, "sha256": sha256, "page": None, "method": "skipped",
            "text": None, "char_count": 0, "ocr_confidence": None, "table_count": 0,
            "table_row_counts": [], "tables": [], "warnings": [reason]}
