"""Run manifest and deterministic identifiers (docs/CONTRACT.md sections 2.4 and P5)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from edgebench.contracts.bars import require_utc
from edgebench.contracts.zones import Direction, ZoneKind


def zone_id(instrument: str, kind: ZoneKind, direction: Direction, formed_at: datetime) -> str:
    require_utc(formed_at, "formed_at")
    return f"{instrument}:{kind.value}:{direction.value}:{formed_at.strftime('%Y%m%dT%H%M%SZ')}"


def event_id(zone: str, episode_index: int) -> str:
    if episode_index < 0:
        raise ValueError("episode_index must be >= 0")
    return f"{zone}#{episode_index}"


def candidate_id(event: str, trigger: str) -> str:
    return f"{event}:{trigger}"


def make_run_id(config_hash: str, data_version: str, code_commit: str) -> str:
    """run_id = hash(config, data_version, code_commit), shortened for readability."""
    payload = f"{config_hash}|{data_version}|{code_commit}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    config_hash: str
    data_version: str
    code_commit: str
    split: str
    started: datetime
    finished: datetime | None = None
    counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_utc(self.started, "started")
        if self.finished is not None:
            require_utc(self.finished, "finished")
        if self.split not in {"dev", "holdout"}:
            raise ValueError(f"unknown split {self.split!r}")
