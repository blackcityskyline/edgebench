"""Streaming simulation of one trade with a first-passage ladder (docs/CONTRACT.md 2.3, 4.5).

The simulation starts at the entry bar (fill at its open) and evaluates that bar too. It runs until
the stop is hit, every ladder rung has been reached, or the holding limit passes, and records the
time each rung was first reached. A bar that both reaches a rung and hits the stop counts for the
stop (pessimistic) and increments ``ambiguous_bars``. The stored ``Trade`` is the *reference exit*:
a fixed target at ``reference_r`` (it wins if its rung was reached before the stop), else the stop,
else a timeout. Other exit policies are computed from the ladder.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from edgebench.contracts import Bar, ExitReason, Side, Trade
from edgebench.execution import fills
from edgebench.execution.costs import CostModel


def rung_key(r: float) -> str:
    return f"{r:g}"


class TradeSim:
    def __init__(
        self,
        trade_id: str,
        side: Side,
        stop_price: float,
        entry_bar: Bar,
        costs: CostModel,
        ladder_r: list[float],
        reference_r: float,
        max_hold_minutes: int,
    ) -> None:
        self.trade_id = trade_id
        self.side = side
        self._costs = costs
        self._stop = stop_price
        self._ladder_r = ladder_r
        self._reference_r = reference_r
        self.entry_ts = entry_bar.ts_open
        self.entry_fill = fills.entry_fill(side, entry_bar.open, costs)
        self.risk = abs(self.entry_fill - stop_price)
        if (side is Side.LONG and self.entry_fill <= stop_price) or (
            side is Side.SHORT and self.entry_fill >= stop_price
        ):
            raise ValueError("entry fill is at or beyond the stop")
        self._deadline = self.entry_ts + timedelta(minutes=max_hold_minutes)
        self._targets = {
            r: fills.target_price(side, self.entry_fill, self.risk, r) for r in ladder_r
        }
        self._reached: dict[float, datetime] = {}
        self._stop_ts: datetime | None = None
        self._stop_fill: float | None = None
        self._timeout_ts: datetime | None = None
        self._timeout_fill: float | None = None
        self._last_close = self.entry_ts
        self._last_bar_close = entry_bar.open
        self._mfe = 0.0
        self._mae = 0.0
        self._ambiguous = 0
        self.finished = False
        self.position_closed = False  # the reference exit has happened (frees the position)
        self.reference_exit_ts: datetime | None = None
        self.trade: Trade | None = None

    def update(self, bar: Bar) -> Trade | None:
        """Advance by one closed M1 bar. Returns the trade once the simulation is complete."""
        if self.finished:
            return self.trade
        if bar.ts_open >= self._deadline:
            return self._finish_timeout()
        costs = self._costs
        hit_stop = fills.stop_triggered(self.side, bar, self._stop, costs)
        new = [
            r
            for r in self._ladder_r
            if r not in self._reached
            and fills.target_triggered(self.side, bar, self._targets[r], costs)
        ]
        fav, adv = fills.favorable_adverse(self.side, bar, self.entry_fill, self.risk, costs)
        self._mfe, self._mae = max(self._mfe, fav), max(self._mae, adv)
        self._last_close, self._last_bar_close = bar.ts_close, bar.close
        if hit_stop:
            if new:
                self._ambiguous += 1
            self._stop_ts = bar.ts_close
            self._stop_fill = fills.stop_fill(self.side, bar, self._stop, costs)
            self._mark_closed(bar.ts_close)
            return self._finish()
        for r in new:
            self._reached[r] = bar.ts_close
        if self._reference_r in self._reached:
            self._mark_closed(self._reached[self._reference_r])
        if len(self._reached) == len(self._ladder_r):
            return self._finish()
        return None

    def flush(self) -> Trade | None:
        """End of data: close at the last seen bar if the simulation is still running."""
        if self.finished:
            return self.trade
        return self._finish_timeout()

    # -- internals -----------------------------------------------------------------------

    def _mark_closed(self, ts: datetime) -> None:
        if not self.position_closed:
            self.position_closed = True
            self.reference_exit_ts = ts

    def _finish_timeout(self) -> Trade:
        self._timeout_ts = self._last_close
        self._timeout_fill = fills.timeout_fill(self.side, self._last_bar_close, self._costs)
        self._mark_closed(self._last_close)
        trade = self._finish()
        assert trade is not None
        return trade

    def _finish(self) -> Trade | None:
        self.finished = True
        ref_ts = self._reached.get(self._reference_r)
        if ref_ts is not None:
            reason, exit_ts = ExitReason.TARGET, ref_ts
            exit_fill = self._targets[self._reference_r]
        elif self._stop_ts is not None and self._stop_fill is not None:
            reason, exit_ts, exit_fill = ExitReason.STOP, self._stop_ts, self._stop_fill
        else:
            assert self._timeout_ts is not None and self._timeout_fill is not None
            reason, exit_ts, exit_fill = ExitReason.TIMEOUT, self._timeout_ts, self._timeout_fill
        exit_ts = max(exit_ts, self.entry_ts)
        commission = fills.commission_r(self.entry_fill, self.risk, self._costs)
        gross = (exit_fill - self.entry_fill) * self.side.sign / self.risk
        spread_r = self._costs.spread / self.risk
        slip_r = self._costs.slippage / self.risk if reason is ExitReason.STOP else 0.0
        ladder: dict[str, datetime | None] = {"stop": self._stop_ts}
        for r in self._ladder_r:
            ladder[rung_key(r)] = self._reached.get(r)
        self.trade = Trade(
            trade_id=self.trade_id,
            side=self.side,
            entry_ts=self.entry_ts,
            entry_fill=self.entry_fill,
            stop_price=self._stop,
            risk_distance=self.risk,
            exit_ts=exit_ts,
            exit_reason=reason,
            exit_fill=exit_fill,
            r_net=gross - commission,
            mfe_r=self._mfe,
            mae_r=self._mae,
            ambiguous_bars=self._ambiguous,
            cost_r=spread_r + slip_r + commission,
            ladder=ladder,
        )
        return self.trade
