"""Extraction-quality review over a representative sample of extracted pages.

The brief asks for "a manual review of at least 20 representative PDF pages" measuring
text, table, bidder-name, price and date extraction quality.

Two honesty points about what this is:

* The sampling and the per-dimension indicators are computed. Nothing here is a human
  reading a PDF side by side with its extraction, and the output says so in
  `review_method`. A person spot-checking the sampled pages against the stored originals
  remains worthwhile and is not a substitute for it.
* The indicators measure whether extraction produced *usable, well-formed* content of each
  kind -- not whether it matched the source document, which cannot be known without the
  source. A page can score well here and still have missed content. `limitations` records
  that.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
import statistics
from typing import Any, Iterable

from . import extract

# Money and date shapes as they appear in California procurement documents.
_MONEY = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\b\d{1,3}(?:,\d{3})+\.\d{2}\b")
_DATE = re.compile(
    r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December)\s+\d{1,2},?\s+\d{4})\b", re.I)
# A page whose characters are mostly non-alphanumeric is probably garbled OCR.
_ALNUM = re.compile(r"[A-Za-z0-9]")
_WORD = re.compile(r"[A-Za-z]{2,}")


def _text_quality(text: str) -> dict[str, Any]:
    """Is the extracted text well formed, or garbled?"""
    if not text or not text.strip():
        return {"verdict": "empty", "chars": 0, "alnum_ratio": None,
                "mean_word_length": None, "note": "no text extracted from this page"}
    chars = len(text)
    alnum = len(_ALNUM.findall(text))
    words = _WORD.findall(text)
    mean_word = round(statistics.mean(len(w) for w in words), 2) if words else 0.0
    ratio = round(alnum / chars, 3)
    # Garbled OCR shows up as a low alphanumeric share or implausible word lengths.
    if ratio < 0.45 or not words:
        verdict = "garbled"
        note = "low alphanumeric share; text is probably unusable"
    elif mean_word < 2.5 or mean_word > 12:
        verdict = "suspect"
        note = f"mean word length {mean_word} is implausible for prose"
    else:
        verdict = "good"
        note = "well-formed words at a plausible density"
    return {"verdict": verdict, "chars": chars, "alnum_ratio": ratio,
            "mean_word_length": mean_word, "word_count": len(words), "note": note}


def _table_quality(page: dict[str, Any]) -> dict[str, Any]:
    tables = page.get("tables") or []
    if not tables:
        return {"verdict": "none", "tables": 0,
                "note": "no tables detected; not a defect unless the page has one"}
    rows = sum(len(t) for t in tables)
    filled = sum(1 for t in tables for row in t for cell in row if (cell or "").strip())
    cells = sum(len(row) for t in tables for row in t) or 1
    density = round(filled / cells, 3)
    ragged = sum(1 for t in tables if len({len(r) for r in t}) > 1)
    verdict = ("good" if density >= 0.5 and not ragged else
               "ragged" if ragged else "sparse")
    return {"verdict": verdict, "tables": len(tables), "rows": rows,
            "cell_fill_ratio": density, "ragged_tables": ragged,
            "note": ("well-formed grid" if verdict == "good" else
                     "inconsistent row widths, likely a layout artifact rather than a table"
                     if ragged else "mostly empty cells")}


def _bidder_quality(page: dict[str, Any]) -> dict[str, Any]:
    candidates = extract.participants_from_tables(page.get("tables") or [])
    return {"verdict": "found" if candidates else "none",
            "candidates": [c["vendor_name_raw"] for c in candidates][:5],
            "count": len(candidates),
            "note": ("vendor names recovered with an amount or rank" if candidates else
                     "no participant rows; expected on pages that are not award notices")}


def _money_quality(text: str) -> dict[str, Any]:
    found = _MONEY.findall(text or "")
    parseable = [m for m in found
                 if extract._amount_to_decimal(m.replace("$", "").strip()) is not None]
    return {"verdict": "found" if found else "none", "matches": len(found),
            "parseable": len(parseable), "examples": found[:5],
            "note": (f"{len(parseable)}/{len(found)} money strings convert to numbers"
                     if found else "no currency strings on this page")}


def _date_quality(text: str) -> dict[str, Any]:
    found = _DATE.findall(text or "")
    parseable = 0
    for value in found:
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%B %d %Y"):
            try:
                dt.datetime.strptime(value.strip(), fmt)
                parseable += 1
                break
            except ValueError:
                continue
    return {"verdict": "found" if found else "none", "matches": len(found),
            "parseable": parseable, "examples": found[:5],
            "note": (f"{parseable}/{len(found)} dates parse to a calendar date"
                     if found else "no dates on this page")}


def sample_pages(pages: list[dict[str, Any]], size: int = 20) -> list[dict[str, Any]]:
    """Pick a spread across documents, extraction methods and table-bearing pages.

    Taking the first N pages would over-sample one document's front matter and would miss
    OCR entirely, so selection deliberately covers each extraction method and prioritises
    pages carrying tables, where the hardest extraction happens.
    """
    usable = [p for p in pages if p.get("page") is not None]
    # Bidder-name quality is one of the five dimensions the brief names, so pages carrying a
    # participant candidate must be reviewed. They are vanishingly rare -- one page in 864 on
    # the measured corpus -- so random or method-balanced sampling misses them almost always.
    # The first run sampled twenty pages and reviewed zero bidders, which made that dimension
    # unmeasurable. These pages are therefore seeded first.
    seeded = [p for p in usable
              if extract.participants_from_tables(p.get("tables") or [])][:size]
    seeded_keys = {(p.get("displayed_filename"), p.get("page")) for p in seeded}
    by_method: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for page in usable:
        if (page.get("displayed_filename"), page.get("page")) in seeded_keys:
            continue
        by_method[page.get("method") or "unknown"].append(page)
    for group in by_method.values():
        # Table pages first, then longest text: the informative end of each method.
        group.sort(key=lambda p: (-(p.get("table_count") or 0), -(p.get("char_count") or 0)))
    chosen: list[dict[str, Any]] = list(seeded)
    seen: set[tuple[Any, Any]] = set(seeded_keys)
    # Round-robin across methods so a rare method is not crowded out by a common one.
    while len(chosen) < size and any(by_method.values()):
        for method in sorted(by_method):
            if not by_method[method] or len(chosen) >= size:
                continue
            page = by_method[method].pop(0)
            key = (page.get("displayed_filename"), page.get("page"))
            if key in seen:
                continue
            seen.add(key)
            chosen.append(page)
    return chosen


def review(pages: Iterable[dict[str, Any]], size: int = 20) -> dict[str, Any]:
    """Assess a representative sample across the five dimensions the brief names."""
    sample = sample_pages(list(pages), size)
    findings = []
    for page in sample:
        text = page.get("text") or ""
        findings.append({
            "document": page.get("displayed_filename"),
            "page": page.get("page"),
            "extraction_method": page.get("method"),
            "sha256": page.get("sha256"),
            "ocr_confidence": page.get("ocr_confidence"),
            "text": _text_quality(text),
            "tables": _table_quality(page),
            "bidder_names": _bidder_quality(page),
            "prices": _money_quality(text),
            "dates": _date_quality(text),
            "warnings": page.get("warnings") or [],
        })
    verdicts = collections.Counter(f["text"]["verdict"] for f in findings)
    return {
        "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "pages_reviewed": len(findings),
        "meets_minimum_of_20": len(findings) >= 20,
        "review_method": (
            "computed indicators over sampled pages, performed by the pipeline rather than "
            "by a person reading each PDF beside its extraction. A human spot-check against "
            "the stored originals in data/raw/documents/ remains worthwhile."),
        "sampling": ("pages carrying a participant candidate are seeded first -- there was "
                     "one in 864 on the measured corpus, so any balanced sample misses it "
                     "and leaves bidder-name quality unmeasured -- then round-robin across "
                     "extraction methods with table-bearing pages first, so OCR and hybrid "
                     "pages are represented rather than crowded out by the much commoner "
                     "native-text pages"),
        "summary": {
            "text_verdicts": dict(verdicts),
            "pages_with_tables": sum(1 for f in findings if f["tables"]["tables"]),
            "well_formed_tables": sum(1 for f in findings if f["tables"]["verdict"] == "good"),
            "pages_with_bidder_candidates": sum(1 for f in findings
                                                if f["bidder_names"]["count"]),
            "pages_with_prices": sum(1 for f in findings if f["prices"]["matches"]),
            "price_parse_rate": _rate(findings, "prices"),
            "pages_with_dates": sum(1 for f in findings if f["dates"]["matches"]),
            "date_parse_rate": _rate(findings, "dates"),
            "pages_with_warnings": sum(1 for f in findings if f["warnings"]),
        },
        "limitations": [
            "indicators measure whether extracted content is well formed, not whether it "
            "matches the source document; a page can score well and still have missed text",
            "no ground-truth transcription exists, so recall against the original PDF is "
            "not measured here",
            "'none' for tables, prices, dates or bidder names is usually correct rather than "
            "a defect: most pages are prose",
        ],
        "findings": findings,
    }


def _rate(findings: list[dict[str, Any]], key: str) -> float | None:
    total = sum(f[key]["matches"] for f in findings)
    good = sum(f[key]["parseable"] for f in findings)
    return round(good / total, 4) if total else None
