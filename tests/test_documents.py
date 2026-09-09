"""Offline tests for validation, dedupe, persistence and non-PDF extraction.

Fixtures are synthesised in-process rather than committed as binaries: the bytes are
small, fully described by the code that makes them, and nothing opaque enters git.
"""
import io
import hashlib
import pathlib
import tempfile
import unittest
import zipfile

from sled_trial import documents, extract

FIX = pathlib.Path(__file__).parent / "fixtures"
PDF = (FIX / "tiny_text.pdf").read_bytes()

DOCX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
 <w:p><w:r><w:t>Notice of Intent to Award</w:t></w:r></w:p>
 <w:tbl>
  <w:tr><w:tc><w:p><w:r><w:t>Company Name</w:t></w:r></w:p></w:tc>
         <w:tc><w:p><w:r><w:t>Bid Amount</w:t></w:r></w:p></w:tc></w:tr>
  <w:tr><w:tc><w:p><w:r><w:t>DOCX VENDOR LLC</w:t></w:r></w:p></w:tc>
         <w:tc><w:p><w:r><w:t>$5,000.00</w:t></w:r></w:p></w:tc></w:tr>
 </w:tbl>
</w:body></w:document>"""


def make_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", DOCX_XML)
    return buf.getvalue()


def make_xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bid Tab"
    ws.append(["Bidder", "Bid Amount"])
    ws.append(["XLSX VENDOR INC", 7500.5])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CSV_BYTES = b"Vendor,Bid Amount\nCSV VENDOR CO,$99.00\n"


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class ValidateTests(unittest.TestCase):
    def test_accepts_a_real_pdf(self) -> None:
        ok, notes = documents.validate(PDF, "a.pdf", "application/pdf")
        self.assertTrue(ok)
        self.assertEqual(notes, [])

    def test_rejects_signature_mismatch(self) -> None:
        # An extension is a claim; the leading bytes are the evidence.
        ok, notes = documents.validate(b"PK\x03\x04" + b"x" * 200, "a.pdf", "application/pdf")
        self.assertFalse(ok)
        self.assertIn("signature mismatch", notes[0])

    def test_rejects_oversize_and_undersize(self) -> None:
        self.assertFalse(documents.validate(b"%PDF-" + b"x" * 10, "a.pdf", None)[0])
        big = b"%PDF-" + b"x" * (documents.MAX_BYTES + 1)
        ok, notes = documents.validate(big, "a.pdf", None)
        self.assertFalse(ok)
        self.assertIn("size cap", notes[0])

    def test_rejects_unsupported_type(self) -> None:
        ok, notes = documents.validate(b"MZ" + b"x" * 200, "installer.exe", None)
        self.assertFalse(ok)
        self.assertIn("unsupported type", notes[0])

    def test_content_type_mismatch_is_a_note_not_a_rejection(self) -> None:
        # PeopleSoft mislabels; the signature is the stronger signal.
        ok, notes = documents.validate(PDF, "a.pdf", "text/html; charset=utf-8")
        self.assertTrue(ok)
        self.assertTrue(any("unexpected" in n for n in notes))

    def test_empty_body_rejected(self) -> None:
        self.assertFalse(documents.validate(b"", "a.pdf", None)[0])


class SafeFilenameTests(unittest.TestCase):
    def test_path_traversal_is_neutralised(self) -> None:
        self.assertEqual(documents.safe_filename("../../etc/passwd"), "passwd")
        self.assertNotIn("/", documents.safe_filename("a/b/c.pdf"))

    def test_dot_names_and_control_chars(self) -> None:
        self.assertEqual(documents.safe_filename(".."), "_")
        self.assertNotIn("\x00", documents.safe_filename("bad\x00name.pdf"))

    def test_empty_becomes_named(self) -> None:
        self.assertEqual(documents.safe_filename(""), "unnamed")


class StoreTests(unittest.TestCase):
    def test_identical_bytes_are_stored_once_but_reported_each_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = documents.DocumentStore(tmp)
            sha = hashlib.sha256(PDF).hexdigest()
            p1, dup1 = store.put(PDF, business_unit="2660", event_id="E1",
                                 filename="a.pdf", sha256=sha)
            p2, dup2 = store.put(PDF, business_unit="2660", event_id="E2",
                                 filename="b.pdf", sha256=sha)
            self.assertFalse(dup1)
            self.assertTrue(dup2)
            self.assertEqual(p1, p2)
            self.assertEqual(len(list(pathlib.Path(tmp).rglob("*.pdf"))), 1)


class ProcessTests(unittest.TestCase):
    def _doc(self, filename: str, data: bytes, **over):
        base = {
            "business_unit": "2740", "event_id": "0000040075", "filename": filename,
            "description": "d", "portal_version": "0.00", "document_role": None,
            "filename_solicitation_mismatch": False, "source_page": "https://example.invalid",
            "serving_url": "https://example.invalid/view", "status": "downloaded",
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": "application/pdf", "content": data,
        }
        base.update(over)
        return base

    def test_failed_download_still_gets_a_manifest_row_and_no_pages(self) -> None:
        doc = self._doc("x.pdf", b"", status="no_serving_url", content=None)
        with tempfile.TemporaryDirectory() as tmp:
            man, pages = documents.process_event_documents(
                [doc], store=documents.DocumentStore(tmp))
        self.assertEqual(len(man), 1)
        self.assertEqual(man[0]["download_status"], "no_serving_url")
        self.assertEqual(pages, [])

    def test_rejected_document_is_marked_rejected_not_downloaded(self) -> None:
        doc = self._doc("evil.pdf", b"PK\x03\x04" + b"x" * 300)
        with tempfile.TemporaryDirectory() as tmp:
            man, pages = documents.process_event_documents(
                [doc], store=documents.DocumentStore(tmp))
        self.assertEqual(man[0]["download_status"], "rejected")
        self.assertEqual(pages, [])

    def test_manifest_never_carries_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            man, _ = documents.process_event_documents(
                [self._doc("a.pdf", PDF)], store=documents.DocumentStore(tmp))
        self.assertNotIn("content", man[0])

    def test_duplicate_is_not_extracted_twice(self) -> None:
        d1 = self._doc("a.pdf", PDF)
        d2 = self._doc("copy.pdf", PDF, event_id="0000040076")
        with tempfile.TemporaryDirectory() as tmp:
            man, pages = documents.process_event_documents(
                [d1, d2], store=documents.DocumentStore(tmp))
        self.assertEqual(len(man), 2)
        self.assertIsNone(man[0]["duplicate_of_sha256"])
        self.assertEqual(man[1]["duplicate_of_sha256"], d2["sha256"])
        self.assertEqual(len({p["displayed_filename"] for p in pages}), 1)


class OfficeExtractionTests(unittest.TestCase):
    def test_docx_text_and_table(self) -> None:
        rows = list(extract.extract_document(
            make_docx(), filename="a.docx", document_ref="r", sha256="s"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["method"], "docx")
        self.assertIn("Intent to Award", rows[0]["text"])
        got = extract.participants_from_tables(rows[0]["tables"])
        self.assertEqual(got[0]["vendor_name_raw"], "DOCX VENDOR LLC")
        self.assertEqual(got[0]["amount_numeric"], "5000.00")

    def test_xlsx_sheet_becomes_a_table(self) -> None:
        rows = list(extract.extract_document(
            make_xlsx(), filename="a.xlsx", document_ref="r", sha256="s"))
        self.assertEqual(rows[0]["method"], "xlsx")
        self.assertEqual(rows[0]["sheet_name"], "Bid Tab")
        got = extract.participants_from_tables(rows[0]["tables"])
        self.assertEqual(got[0]["vendor_name_raw"], "XLSX VENDOR INC")

    def test_csv_becomes_a_table(self) -> None:
        rows = list(extract.extract_document(
            CSV_BYTES, filename="a.csv", document_ref="r", sha256="s"))
        self.assertEqual(rows[0]["method"], "csv")
        got = extract.participants_from_tables(rows[0]["tables"])
        self.assertEqual(got[0]["vendor_name_raw"], "CSV VENDOR CO")

    def test_zip_is_expanded_one_level(self) -> None:
        data = make_zip({"inner.csv": CSV_BYTES, "notes.txt": b"ignored"})
        rows = list(extract.extract_document(
            data, filename="pkg.zip", document_ref="r", sha256="s"))
        methods = {r["method"] for r in rows}
        self.assertIn("csv", methods)
        self.assertIn("skipped", methods)  # the .txt member
        refs = [r["document_ref"] for r in rows]
        self.assertTrue(any("!inner.csv" in r for r in refs))

    def test_nested_archive_is_recorded_not_followed(self) -> None:
        inner = make_zip({"deep.csv": CSV_BYTES})
        data = make_zip({"nested.zip": inner})
        rows = list(extract.extract_document(
            data, filename="pkg.zip", document_ref="r", sha256="s"))
        self.assertTrue(any("nested archive not expanded" in (r["warnings"] or [""])[0]
                            for r in rows))

    def test_unsupported_type_yields_explicit_skip(self) -> None:
        rows = list(extract.extract_document(
            b"whatever", filename="a.rtf", document_ref="r", sha256="s"))
        self.assertEqual(rows[0]["method"], "skipped")
        self.assertIn("unsupported type", rows[0]["warnings"][0])

    def test_corrupt_docx_warns_and_still_yields_a_record(self) -> None:
        rows = list(extract.extract_document(
            b"PK\x03\x04garbage", filename="a.docx", document_ref="r", sha256="s"))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["warnings"])


if __name__ == "__main__":
    unittest.main()


class RerunTests(unittest.TestCase):
    """A re-run must produce complete outputs, not empty ones."""

    def test_bytes_already_on_disk_do_not_suppress_extraction(self) -> None:
        # Regression: on a second run the store found the file already present, reported a
        # duplicate, and the caller skipped extraction -- so document_pages.jsonl came out
        # empty, indistinguishable from documents that contain no text.
        sha = hashlib.sha256(PDF).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            first = documents.DocumentStore(tmp)
            _, dup1 = first.put(PDF, business_unit="2740", event_id="E1",
                                filename="a.pdf", sha256=sha)
            self.assertFalse(dup1)
            # A new run means a new store instance over the same directory.
            second = documents.DocumentStore(tmp)
            _, dup2 = second.put(PDF, business_unit="2740", event_id="E1",
                                 filename="a.pdf", sha256=sha)
            self.assertFalse(dup2)

    def test_duplicates_within_one_run_are_still_suppressed(self) -> None:
        sha = hashlib.sha256(PDF).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            store = documents.DocumentStore(tmp)
            store.put(PDF, business_unit="a", event_id="b", filename="x.pdf", sha256=sha)
            _, dup = store.put(PDF, business_unit="c", event_id="d", filename="y.pdf",
                               sha256=sha)
            self.assertTrue(dup)

    def test_rerun_still_writes_the_file_only_once(self) -> None:
        sha = hashlib.sha256(PDF).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(3):
                documents.DocumentStore(tmp).put(
                    PDF, business_unit="2740", event_id="E1", filename="a.pdf", sha256=sha)
            self.assertEqual(len(list(pathlib.Path(tmp).rglob("*.pdf"))), 1)


class IntegrityTests(unittest.TestCase):
    """A correct signature at byte zero does not mean the payload is intact.

    Real case: an agency attachment arrived with valid zip magic and
    "</PRE><hr> </BODY></HTML>" at the end -- the portal had appended an error page to a
    partial download. It passed signature and size checks, failed silently at extraction,
    and produced an empty page record that looked like a document with no text.
    """

    def test_html_appended_to_a_valid_header_is_rejected(self) -> None:
        payload = make_zip({"word/document.xml": DOCX_XML})
        payload += b"<HTML><BODY>Service unavailable</BODY></HTML>\n"
        ok, notes = documents.validate(payload, "a.docx", None)
        self.assertFalse(ok)
        self.assertTrue(any("error page was appended" in n for n in notes))

    def test_a_corrupt_archive_is_rejected_despite_zip_magic(self) -> None:
        payload = b"PK\x03\x04" + b"\x00" * 4096
        ok, notes = documents.validate(payload, "a.docx", None)
        self.assertFalse(ok)
        self.assertTrue(any("not a readable archive" in n for n in notes))

    def test_a_sound_archive_still_passes(self) -> None:
        ok, notes = documents.validate(
            make_zip({"word/document.xml": DOCX_XML}), "a.docx", None)
        self.assertTrue(ok, notes)

    def test_a_sound_xlsx_still_passes(self) -> None:
        self.assertTrue(documents.validate(make_xlsx(), "a.xlsx", None)[0])

    def test_pdfs_are_not_subjected_to_the_archive_check(self) -> None:
        self.assertTrue(documents.validate(PDF, "a.pdf", None)[0])

    def test_a_rejected_document_yields_a_manifest_row_with_the_reason(self) -> None:
        payload = make_zip({"word/document.xml": DOCX_XML}) + b"</BODY></HTML>"
        doc = {"business_unit": "0820", "event_id": "E1", "filename": "bad.docx",
               "status": "downloaded", "bytes": len(payload),
               "sha256": hashlib.sha256(payload).hexdigest(),
               "content_type": "application/vnd.openxmlformats-officedocument."
                               "wordprocessingml.document", "content": payload}
        with tempfile.TemporaryDirectory() as tmp:
            man, pages = documents.process_event_documents(
                [doc], store=documents.DocumentStore(tmp))
        self.assertEqual(man[0]["download_status"], "rejected")
        self.assertTrue(man[0]["validation_notes"])
        self.assertEqual(pages, [])  # never reaches extraction


class FilenameCollisionTests(unittest.TestCase):
    def test_two_documents_sharing_a_filename_are_both_kept(self) -> None:
        # Overwriting left the first document's manifest row pointing at the second
        # document's bytes, with a hash that no longer matched what was on disk.
        with tempfile.TemporaryDirectory() as tmp:
            store = documents.DocumentStore(tmp)
            first, dup_a = store.put(b"one", business_unit="2740", event_id="E1",
                                     filename="Attachment.pdf",
                                     sha256=hashlib.sha256(b"one").hexdigest())
            second, dup_b = store.put(b"two", business_unit="2740", event_id="E1",
                                      filename="Attachment.pdf",
                                      sha256=hashlib.sha256(b"two").hexdigest())
        self.assertFalse(dup_a)
        self.assertFalse(dup_b)
        self.assertNotEqual(first, second)
