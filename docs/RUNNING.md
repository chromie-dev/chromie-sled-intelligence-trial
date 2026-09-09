# Running this repository

`README.md` is the assignment. This is how to install it, run it, and reproduce every
number in `build/`.

## Install

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Verified on a clean virtualenv: the install above is enough to run the whole test suite.

```bash
python -m pytest -q
# 356 passed, 174 subtests passed
```

Tests are offline and need no credentials, no network and no API key. They use the
fixtures in `tests/fixtures/`.

### Optional: OCR

```bash
pip install -e ".[ocr]"
brew install tesseract poppler        # macOS; the Python packages call these binaries
```

OCR is a fallback for image-only PDF pages. Without it the pipeline still runs:
`extract.ocr_available()` reports what is missing and those pages are recorded with a
warning instead of silently returning empty text. Pass `--no-ocr` to skip it deliberately.

## The deliverable command

```bash
python -m sled_trial.cli analyze \
  --opportunity data/examples/active_opportunity.json \
  --download-documents \
  --output build
```

Writes all ten required artifacts plus the seven Supabase-shaped tables. It reaches
Cal eProcure over plain HTTP; no browser and no API key are involved.

`--reuse-awards` replays the run from `build/awards.jsonl` instead of re-querying the
award registry, which is the fast path when only the analysis changed.

## The other commands

| Command | What it does | Network |
| --- | --- | --- |
| `events` | Fetch and parse the active event feed | yes |
| `documents --event BU/EVENT_ID` | Download and extract one or more events | yes |
| `spending --max-mb 600` | Cache Open FI$Cal payment records | yes, hundreds of MB |
| `backfill-primes --opportunity FILE` | Deepen award history for the prime-eligible vendor set | yes |
| `evaluate` | Regenerate `build/evaluation.json` from the cached corpus | no |
| `analyze --opportunity FILE` | The deliverable above | yes |

`evaluate` and `backfill-primes` are separate commands rather than stages of `analyze`
because each is expensive in a different way, and because the evaluation number has to be
reproducible on its own:

```bash
python -m sled_trial.cli evaluate --output build
# history 836 rows, 55 held-out events at 09/03/2026
# precision@3 0.0727 | precision@5 0.0582 | coverage 0.1918 | lift 1.2x
```

`backfill-primes` matters for one specific reason. A date sweep leaves the median vendor
holding a single award, so almost nobody clears the prime-qualification rule and the
teaming section comes out empty. Backfilling every member of the eligible set — the
vendors holding an award with this agency or in this category — is uniform rather than
biasing, because a vendor outside that set can never qualify however deep its history.
`analyze` picks up `build/awards_prime_enriched.jsonl` automatically when it exists and
records in the output which corpus it used.

## Where the outputs go

`build/` and `data/raw/` are gitignored. `build/` is reproducible from the commands above;
`data/raw/documents/` holds the downloaded bytes, addressed by SHA-256 in
`build/documents_manifest.jsonl`, so the manifest and its hashes stay meaningful even
where the documents themselves cannot be committed.
