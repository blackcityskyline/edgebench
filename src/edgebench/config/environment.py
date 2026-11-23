"""Instruments, sessions and splits configuration (docs/CONTRACT.md sections 2.1, 3, 7.1)."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InstrumentSpec(_Base):
    source: Literal["dukascopy", "binance"]
    symbol: str
    tick_size: float = Field(gt=0)
    spread: float = Field(ge=0, description="Fixed spread in price units when no ask series")
    slippage_spreads: float = Field(0.0, ge=0, description="Stop-order slippage, in spreads")
    commission_bps: float = Field(0.0, ge=0, description="Per side, basis points of notional")
    placeholder: bool = Field(True, description="True until measured from data or statements")


class InstrumentsConfig(_Base):
    instruments: dict[str, InstrumentSpec] = Field(min_length=1)


class SessionWindow(_Base):
    start: str
    end: str
    confirmed: bool = Field(False, description="True once the owner has approved the window")

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if not _HHMM.match(value):
            raise ValueError("expected HH:MM")
        return value


class SessionsConfig(_Base):
    tz: str = "America/New_York"
    sessions: dict[str, SessionWindow] = Field(min_length=1)

    @field_validator("tz")
    @classmethod
    def _known_tz(cls, value: str) -> str:
        ZoneInfo(value)
        return value


class SplitsConfig(_Base):
    holdout_fraction: float = Field(0.2, gt=0, lt=0.5)
    embargo_days: int = Field(2, ge=0)
    walk_forward_folds: int = Field(4, ge=1)
    dev_start: date | None = None
    dev_end: date | None = None
    holdout_start: date | None = None
