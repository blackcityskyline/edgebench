"""Typed objects shared by all modules. Changes here are architect-only (docs/CONTRACT.md 9.4)."""

from edgebench.contracts.bars import TIMEFRAME_SECONDS, Bar, require_utc
from edgebench.contracts.events import Event, Observation
from edgebench.contracts.manifest import (
    RunManifest,
    candidate_id,
    event_id,
    make_run_id,
    zone_id,
)
from edgebench.contracts.trading import ExitReason, OrderIntent, Side, Trade
from edgebench.contracts.zones import Direction, Zone, ZoneEvent, ZoneEventType, ZoneKind

__all__ = [
    "TIMEFRAME_SECONDS",
    "Bar",
    "Direction",
    "Event",
    "ExitReason",
    "Observation",
    "OrderIntent",
    "RunManifest",
    "Side",
    "Trade",
    "Zone",
    "ZoneEvent",
    "ZoneEventType",
    "ZoneKind",
    "candidate_id",
    "event_id",
    "make_run_id",
    "require_utc",
    "zone_id",
]
