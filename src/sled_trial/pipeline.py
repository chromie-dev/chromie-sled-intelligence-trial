import hashlib
import json
from pathlib import Path
from typing import Any

from .models import Opportunity


def canonical_id(agency: str, solicitation: str) -> str:
    raw = f"{agency.strip().lower()}::{solicitation.strip().lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def normalize(record: dict[str, Any]) -> Opportunity:
    """Starter mapping for the canonical fixture format; interns add portal adapters."""
    required = ("source_id", "source_url", "solicitation", "title", "agency", "jurisdiction", "observed_at")
    missing = [field for field in required if not record.get(field)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    return Opportunity(
        canonical_id=canonical_id(record["agency"], record["solicitation"]),
        title=record["title"].strip(),
        agency=record["agency"].strip(),
        jurisdiction=record["jurisdiction"].strip(),
        status=record.get("status", "unknown"),
        due_date=record.get("due_date"),
        source_ids=(record["source_id"],),
        source_urls=(record["source_url"],),
        observed_at=record["observed_at"],
        confidence=float(record.get("confidence", 1.0)),
    )


def load_records(input_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        value = json.loads(path.read_text())
        records.extend(value if isinstance(value, list) else [value])
    return records

