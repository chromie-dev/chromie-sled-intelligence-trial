"""What has already been harvested, so a run resumes instead of starting over.

The pipeline was a snapshot: every run refetched everything, which made a twelve-month
backfill impossible to attempt and a killed run cost the whole thing. One run really was
killed mid-sweep for memory, and an hour of polite, throttled requests went with it.

State is a unit per source. A unit is whatever that source can be asked for
independently -- a Caltrans week, an SCPRS date slice, a PlanetBids solicitation -- and
is recorded with what it produced.

**An empty unit is done; a failed unit is not.** A Caltrans week with no bid openings
answered correctly and must never be asked again. A week that timed out answered
nothing and must be. Collapsing those is how a backfill quietly develops holes, and it
is the same distinction the soft-404 handling makes when reading a single page.

**Closed history is immutable, open history is not.** A past week's bid results will not
change, so it is recorded once and skipped forever. A feed of currently-open events
changes hourly, so a unit can declare how long it stays fresh.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
from typing import Any, Iterable

STATE_FILE = "harvest_state.json"

OK = "ok"            # asked, answered, produced rows
EMPTY = "empty"      # asked, answered, legitimately had nothing
FAILED = "failed"    # asked, did not answer -- must be retried
# Only these two count as done. `failed` is deliberately absent.
DONE = (OK, EMPTY)


def load(outdir: pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(outdir) / STATE_FILE
    if not path.exists():
        return {"sources": {}}
    try:
        state = json.loads(path.read_text())
    except (ValueError, OSError):
        # A corrupt state file must not stop a harvest; the cost of ignoring it is
        # refetching, which is the behaviour we had before any of this existed.
        return {"sources": {}}
    state.setdefault("sources", {})
    return state


def save(outdir: pathlib.Path, state: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(outdir) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state["saved_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=1, sort_keys=True))
    return path


def _units(state: dict[str, Any], source_key: str) -> dict[str, Any]:
    return state.setdefault("sources", {}).setdefault(
        source_key, {"units": {}})["units"]


def record(state: dict[str, Any], source_key: str, unit: str, *,
           outcome: str = OK, rows: int = 0, note: str | None = None) -> None:
    """Note what one unit produced."""
    if outcome not in (OK, EMPTY, FAILED):
        raise ValueError(f"unknown outcome {outcome!r}")
    _units(state, source_key)[str(unit)] = {
        "outcome": outcome, "rows": rows, "note": note,
        "collected_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def is_done(state: dict[str, Any], source_key: str, unit: str,
            *, stale_after_days: int | None = None,
            now: dt.datetime | None = None) -> bool:
    """Has this unit been answered, and is that answer still good?

    `stale_after_days` is for units whose content changes -- a feed of open events. Left
    unset, an answered unit is done forever, which is right for closed history.
    """
    entry = _units(state, source_key).get(str(unit))
    if not entry or entry.get("outcome") not in DONE:
        return False
    if stale_after_days is None:
        return True
    try:
        collected = dt.datetime.fromisoformat(entry["collected_at"])
    except (KeyError, ValueError):
        return False
    age = (now or dt.datetime.now(dt.UTC)) - collected
    return age <= dt.timedelta(days=stale_after_days)


def pending(state: dict[str, Any], source_key: str, units: Iterable[str],
            *, stale_after_days: int | None = None,
            now: dt.datetime | None = None) -> list[str]:
    """The units still worth asking for, in the order given."""
    return [str(u) for u in units
            if not is_done(state, source_key, u,
                           stale_after_days=stale_after_days, now=now)]


def days_held(state: dict[str, Any], source_key: str,
              from_date: str, to_date: str) -> list[str]:
    """Which single days in a window have a recorded slice, MM/DD/YYYY.

    A day is reached either directly or pinned to a subdivision axis, so both key
    shapes count. This is the question a backfill log has to answer -- "is this month
    finished" is about days covered, not about how many rows one run happened to
    fetch.
    """
    start = dt.datetime.strptime(from_date, "%m/%d/%Y").date()
    end = dt.datetime.strptime(to_date, "%m/%d/%Y").date()
    seen = set()
    for key, entry in _units(state, source_key).items():
        if entry.get("outcome") not in DONE:
            continue
        parts = dict(p.split("=", 1) for p in str(key).split("|") if "=" in p)
        if parts.get("from") != parts.get("to") or "from" not in parts:
            continue
        try:
            day = dt.datetime.strptime(parts["from"], "%m/%d/%Y").date()
        except ValueError:
            continue
        if start <= day <= end:
            seen.add(day)
    return [d.strftime("%m/%d/%Y") for d in sorted(seen)]


def window_days(from_date: str, to_date: str) -> int:
    start = dt.datetime.strptime(from_date, "%m/%d/%Y").date()
    end = dt.datetime.strptime(to_date, "%m/%d/%Y").date()
    return (end - start).days + 1


def summary(state: dict[str, Any]) -> dict[str, Any]:
    """What the store knows, per source."""
    out = {}
    for source_key, block in (state.get("sources") or {}).items():
        units = block.get("units") or {}
        counts: dict[str, int] = {}
        for entry in units.values():
            outcome = entry.get("outcome", "unknown")
            counts[outcome] = counts.get(outcome, 0) + 1
        stamps = sorted(e.get("collected_at") for e in units.values()
                        if e.get("collected_at"))
        out[source_key] = {
            "units": len(units),
            "rows": sum(int(e.get("rows") or 0) for e in units.values()),
            "outcomes": counts,
            # Retryable is the number that matters for a backfill: it is what a rerun
            # will actually go and do.
            "retryable": counts.get(FAILED, 0),
            "first_collected": stamps[0] if stamps else None,
            "last_collected": stamps[-1] if stamps else None,
        }
    return out
