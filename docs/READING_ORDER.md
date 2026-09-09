# Reading Order

Guide to navigating this repository and understanding the SLED competitive intelligence trial.

---

## The 20-Minute Version

If you only read three things:

1. [tasks/todo.md](file:///Users/pookie/chromie-sled-intelligence-trial/tasks/todo.md#L85-L135) — Jump to the "Review" section at the bottom. It maps all six graded areas, what is implemented, and what remains honestly short.
2. [build/report.md](file:///Users/pookie/chromie-sled-intelligence-trial/build/report.md) — 211 lines of plain prose. This is what the system actually produces for a reader, generated from real data.
3. [DECISIONS.md:L421](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L421) — "Observed bidder identity DOES exist in California, inside award-notice PDFs." The central finding of the whole trial.

Reading these three takes approximately 20 minutes and covers the core thesis and findings.

---

## The Full Five-Stage Path

### Stage 1: What was asked, and what came back (20 min)

| Read | Why |
| --- | --- |
| [README.md](file:///Users/pookie/chromie-sled-intelligence-trial/README.md#L90-L111) — "Core deliverable" and "Definition of done" | The assignment. Skip the middle; it is 357 lines. |
| [tasks/todo.md](file:///Users/pookie/chromie-sled-intelligence-trial/tasks/todo.md#L85-L135) — Review section | Scorecard against the six graded areas. |
| [build/report.md](file:///Users/pookie/chromie-sled-intelligence-trial/build/report.md) | The output in prose, with real numbers. |

Skip `PROJECT_BRIEF.md` — it was confirmed stale in favor of `README.md`.

---

### Stage 2: The findings (45 min, highest value)

[DECISIONS.md](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md) documents the trial progression. Read these ten entries in order:

| Line | Entry | Why it matters |
| ---: | --- | --- |
| [293](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L293) | Bidder lists are definitively not public | The answer to the brief's central question. |
| [421](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L421) | Observed bidder identity DOES exist, in PDFs | Where the answer actually lives. |
| [201](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L201) | CORRECTION: Cal eProcure IS reachable | How direct HTTP requests succeeded where initial assumptions failed. |
| [363](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L363) | Attachments download over plain HTTP | How attachments are fetched without needing a headless browser. |
| [267](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L267) | SCPRS solves vendor identity | Stable supplier IDs remove the need to guess vendor identity. |
| [322](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L322) | No deterministic solicitation-to-award join | Why procurement lineage is probabilistic rather than factual. |
| [509](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L509) | Precision guards after 8 false positives in 9 | Example of precision filters on table extraction. |
| [657](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L657) | Prediction baseline: precision@3 0.17 | The first evaluation — superseded, read the next two rows with it. |
| [975](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L975) | Re-evaluated honestly: 0.073, not 0.17 | The 0.17 came from a favourably selected event set. Published downward. |
| [1604](file:///Users/pookie/chromie-sled-intelligence-trial/DECISIONS.md#L1604) | Pre-submission review | Two deliverables were empty or zero through wiring bugs; what changed and why. |

Then review [sources/source_registry.csv](file:///Users/pookie/chromie-sled-intelligence-trial/sources/source_registry.csv) for the 10 surveyed California surfaces, what each exposes, and what access constraints exist.

---

### Stage 3: Running the pipeline (10 min)

[docs/RUNNING.md](file:///Users/pookie/chromie-sled-intelligence-trial/docs/RUNNING.md) has install, the full command list, and what each command costs. The short version:

```bash
python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
python -m pytest -q                       # 356 passed, offline, no credentials

python -m sled_trial.cli analyze \
  --opportunity data/examples/active_opportunity.json \
  --download-documents --reuse-awards --output build
```

Read [data/examples/active_opportunity.json](file:///Users/pookie/chromie-sled-intelligence-trial/data/examples/active_opportunity.json) first: it is the input file and is commented. As the command executes, watch the nine logged stages. That sequence represents the execution architecture.

Four commands sit outside `analyze` on purpose, each expensive in a different way:

| Command | Why it is separate |
| --- | --- |
| `evaluate` | Reproduces the headline precision figure with no live crawl. |
| `backfill-primes` | Deepens award history for the prime-eligible set; without it the sweep leaves the median vendor holding one award and the teaming section is empty. |
| `bidders --resolve` | Harvests Caltrans bid results and resolves each bidder name to an SCPRS `supplier_id`, which is what populates win rates. |
| `tabulations` | Harvests SF Public Works bid tabulations; `--page` is repeatable because the meeting pages holding them are not indexed anywhere. |

`analyze` consumes whatever these have written and says which corpus it used.

---

### Stage 4: Code in pipeline execution order

Read modules in execution order rather than alphabetical order:

| Stage | Module | Lines | Writes |
| --- | --- | ---: | --- |
| 1: Reach the portal | [sources/caleprocure.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/sources/caleprocure.py) | 457 | `events.jsonl` |
| 1: Bidder fields (the only CA sources naming losers) | [sources/caltrans.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/sources/caltrans.py) + [sources/sfpublicworks.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/sources/sfpublicworks.py) | 189 + 221 | `caltrans_bidders.jsonl`, `sf_bidders.jsonl` |
| 2: Validate and store documents | [documents.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/documents.py) | 222 | `documents_manifest.jsonl` |
| 2: Read documents | [extract.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/extract.py) | 395 | `document_pages.jsonl`, `participant_candidates.jsonl` |
| 4: Award history | [sources/scprs.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/sources/scprs.py) | 204 | `awards.jsonl` |
| 5: Predecessor search | [lineage.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/lineage.py) | 277 | `procurement_lineage.json` |
| 6: Vendor identity | [vendors.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/vendors.py) | 436 | `vendor_profiles.json` |
| 6: Prediction | [predict.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/predict.py) | 552 | `opportunity_intelligence.json`, `evaluation.json` |
| 7: Prime teaming | [primes.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/primes.py) | 308 | `prime_candidates.json` |
| 8: Exports | [supabase_export.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/supabase_export.py) + [docs/supabase_mapping.md](file:///Users/pookie/chromie-sled-intelligence-trial/docs/supabase_mapping.md) | 546 + 177 | `build/supabase/` |
| 8: Report generation | [report.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/report.py) | 335 | `report.md` |
| Assembly | [assemble.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/assemble.py) — artifact shaping, no network | 190 | `source_coverage.json`, `review_queue.json` |
| Glue | [cli.py](file:///Users/pookie/chromie-sled-intelligence-trial/src/sled_trial/cli.py) — examine `cmd_analyze` | 536 | — |

Every module's top docstring explains what the code can and cannot claim. Reading those docstrings first gives a clear view of the architectural boundaries.

---

### Stage 5: Tests as failure documentation

Tests capture specific failure cases and edge cases encountered during live testing:

- [tests/test_extract.py](file:///Users/pookie/chromie-sled-intelligence-trial/tests/test_extract.py): `ParticipantPrecisionTests` — Guards against eight observed false positives in requirement text.
- [tests/test_caleprocure.py](file:///Users/pookie/chromie-sled-intelligence-trial/tests/test_caleprocure.py): `BootstrapTests`, `RetryTests` — Handles session bootstrapping where missing state looked like an empty result.
- [tests/test_documents.py](file:///Users/pookie/chromie-sled-intelligence-trial/tests/test_documents.py): `RerunTests` — Verifies that deduplication does not drop extraction output across reruns.
- [tests/test_lineage.py](file:///Users/pookie/chromie-sled-intelligence-trial/tests/test_lineage.py): `SelfIdentifierTests` — Prevents a document from matching its own solicitation number as a predecessor.
- [tests/test_supabase_export.py](file:///Users/pookie/chromie-sled-intelligence-trial/tests/test_supabase_export.py): `test_every_referenced_table_precedes_its_children` — Enforces foreign key dependency ordering across exported tables.

---

### Core Narrative

California hides who bids on active solicitations; pages that contain response inquiries are login-gated. However, bidder identities and winning amounts are disclosed in award-notice attachments. By retrieving those PDFs, extracting the participant data, and matching them to permanent SCPRS supplier IDs, competitive history can be constructed entirely from public records without conflating predictions with observed facts.
