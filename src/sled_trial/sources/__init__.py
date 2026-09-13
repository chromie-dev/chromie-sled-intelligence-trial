"""Source adapters, one package per jurisdiction.

`ca/` holds California. A new state is a sibling package with its own adapters; the
pipeline reaches them through `BIDDER_SOURCES` below and through `sources/source_registry.csv`,
so adding one does not mean editing the exporter, the assembler or the report.
"""
from __future__ import annotations

from typing import NamedTuple


class BidderSource(NamedTuple):
    """A surface that publishes who bid, not just who won.

    `cache` is the file its harvest writes under the build directory. `record_source` names
    the registry the solicitation belongs to, which is what stops a city sourcing id being
    attributed to a state event list.
    """

    key: str
    cache: str
    record_source: str
    label: str


BIDDER_SOURCES = (
    BidderSource("caltrans_bid_results", "caltrans_bidders.jsonl",
                 "caleprocure_event_list", "Caltrans bid results"),
    BidderSource("sfpublicworks_bid_tabulation", "sf_bidders.jsonl",
                 "sfpublicworks_bid_tabulation", "SF Public Works tabulations"),
    BidderSource("planetbids_agency_portal", "planetbids_bidders.jsonl",
                 "planetbids_agency_portal", "PlanetBids agency portals"),
)

BY_KEY = {source.key: source for source in BIDDER_SOURCES}
