from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Opportunity:
    canonical_id: str
    title: str
    agency: str
    jurisdiction: str
    status: str
    due_date: str | None
    source_ids: tuple[str, ...]
    source_urls: tuple[str, ...]
    observed_at: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_ids"] = list(self.source_ids)
        value["source_urls"] = list(self.source_urls)
        return value

