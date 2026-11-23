"""Strategy configuration schema (docs/CONTRACT.md sections 4.2 and 6).

Every parameter has a default and a description. Unknown keys are rejected so typos fail loudly.
Default values are placeholders, not recommendations.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TriggerName = Literal["sweep", "rejection", "stall", "inside"]
SweepReference = Literal["zone_edge", "h1_fractal", "ltf_fractal_m1", "ltf_fractal_m3"]
InvalidOn = Literal["close_through", "full_fill", "first_touch", "never"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _default_sweep_references() -> list[SweepReference]:
    return ["h1_fractal", "ltf_fractal_m1"]


def _default_triggers() -> list[TriggerName]:
    return ["sweep", "rejection", "stall", "inside"]


def _default_ladder() -> list[float]:
    return [1.0, 2.0, 3.0, 5.0, 8.0, 10.0, 15.0]


class FvgConfig(_Base):
    enabled: bool = True
    min_size_atr_h1: float = Field(0.2, ge=0, description="Minimum gap size in H1 ATR")
    min_displacement_body_atr_h1: float | None = Field(
        None, ge=0, description="Optional minimum body of the middle bar in H1 ATR"
    )
    invalid_on: InvalidOn = Field("close_through", description="Decision D2")
    max_episodes: int = Field(1, ge=1, description="Touch episodes per zone")
    max_age_h1_bars: int = Field(200, ge=1, description="Zone expires after this many H1 bars")


class FractalConfig(_Base):
    enabled: bool = True
    left: int = Field(2, ge=1, description="Bars on the left of the pivot (decision D1)")
    right: int = Field(2, ge=1, description="Bars on the right; the level is known after them")


class ZonesConfig(_Base):
    fvg: FvgConfig = FvgConfig()
    fractal: FractalConfig = FractalConfig()
    episode_gap_bars: int = Field(5, ge=1, description="M1 bars outside the zone that end a touch")
    window_bars: int = Field(30, ge=1, description="M1 bars after touch start with detectors on")


class SweepConfig(_Base):
    enabled: bool = True
    references: list[SweepReference] = Field(
        default_factory=_default_sweep_references, min_length=1
    )
    min_depth_atr_m1: float = Field(0.1, ge=0)
    max_return_bars: int = Field(3, ge=1)


class StallConfig(_Base):
    enabled: bool = True
    n_bars: int = Field(3, ge=2)
    max_range_atr_m1: float = Field(0.5, gt=0)
    max_extension_atr_m1: float = Field(0.1, ge=0)


class RejectionConfig(_Base):
    enabled: bool = True
    min_wick_ratio: float = Field(0.6, gt=0, le=1)
    close_zone: float = Field(0.33, gt=0, le=0.5)


class InsideConfig(_Base):
    enabled: bool = True
    mode: Literal["range", "body"] = "range"
    min_count: int = Field(1, ge=1)


class PatternsConfig(_Base):
    sweep: SweepConfig = SweepConfig()
    stall: StallConfig = StallConfig()
    rejection: RejectionConfig = RejectionConfig()
    inside: InsideConfig = InsideConfig()


class StopBufferConfig(_Base):
    spreads: float = Field(1.0, ge=0)
    atr_m1: float = Field(0.0, ge=0)


class EntryConfig(_Base):
    triggers: list[TriggerName] = Field(default_factory=_default_triggers, min_length=1)
    combine: Literal["first", "all_of"] = "first"
    policy: Literal["market_next_open", "limit_retrace", "stop_break"] = Field(
        "market_next_open", description="Decision D5"
    )
    limit_retrace_frac: float = Field(0.5, gt=0, le=1, description="Used by limit_retrace only")
    stop_buffer: StopBufferConfig = StopBufferConfig()
    min_stop_spreads: float = Field(5.0, ge=0, description="Skip trades with a tighter stop")
    max_stop_atr_h1: float = Field(0.5, gt=0, description="Skip trades with a wider stop")
    max_trades_per_zone: int = Field(1, ge=1, description="Decision D6")

    @field_validator("triggers")
    @classmethod
    def _unique_triggers(cls, value: list[TriggerName]) -> list[TriggerName]:
        if len(set(value)) != len(value):
            raise ValueError("triggers must be unique")
        return value


class ExitsConfig(_Base):
    max_hold_minutes: int = Field(360, ge=1, description="Decision D4")
    ladder_r: list[float] = Field(default_factory=_default_ladder, min_length=1)

    @field_validator("ladder_r")
    @classmethod
    def _ascending_positive(cls, value: list[float]) -> list[float]:
        if any(v <= 0 for v in value):
            raise ValueError("ladder_r values must be positive")
        if any(b <= a for a, b in zip(value, value[1:], strict=False)):
            raise ValueError("ladder_r must be strictly ascending")
        return value


class RiskConfig(_Base):
    risk_pct: float = Field(0.2, gt=0, le=5, description="Percent of equity; equity simulator only")


class StrategyConfig(_Base):
    version: int = Field(1, ge=1)
    mode: Literal["shadow", "portfolio"] = "shadow"
    instruments: list[str] = Field(min_length=1)
    sessions: list[str] = Field(min_length=1)
    zones: ZonesConfig = ZonesConfig()
    patterns: PatternsConfig = PatternsConfig()
    entry: EntryConfig = EntryConfig()
    exits: ExitsConfig = ExitsConfig()
    risk: RiskConfig = RiskConfig()

    @model_validator(mode="after")
    def _cross_checks(self) -> StrategyConfig:
        if not (self.zones.fvg.enabled or self.zones.fractal.enabled):
            raise ValueError("enable at least one zone kind")
        for trigger in self.entry.triggers:
            if not getattr(self.patterns, trigger).enabled:
                raise ValueError(f"entry trigger {trigger!r} is disabled in patterns")
        return self

    def config_hash(self) -> str:
        """Stable hash of the full configuration (used in run_id)."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
