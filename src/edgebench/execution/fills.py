"""Side-aware fills: the only place that knows bid, ask and slippage (docs/CONTRACT.md 2.2).

Bar prices are bid. A long entry pays the ask (bid + spread). A long exit sells at the bid. A short
entry sells at the bid, and a short exit buys at the ask (bid + spread).
"""

from __future__ import annotations

from edgebench.contracts import Bar, Side
from edgebench.execution.costs import CostModel


def entry_fill(side: Side, bar_open: float, costs: CostModel) -> float:
    """Market entry at the open of the entry bar."""
    return bar_open + costs.spread if side is Side.LONG else bar_open


def stop_triggered(side: Side, bar: Bar, stop: float, costs: CostModel) -> bool:
    if side is Side.LONG:
        return bar.low <= stop
    return bar.high + costs.spread >= stop


def stop_fill(side: Side, bar: Bar, stop: float, costs: CostModel) -> float:
    """Stop order fill: the stop price plus slippage against us, or the open if the bar gapped."""
    if side is Side.LONG:
        return min(stop, bar.open) - costs.slippage
    return max(stop, bar.open + costs.spread) + costs.slippage


def target_price(side: Side, entry: float, risk: float, r: float) -> float:
    return entry + side.sign * r * risk


def target_triggered(side: Side, bar: Bar, price: float, costs: CostModel) -> bool:
    if side is Side.LONG:
        return bar.high >= price
    return bar.low + costs.spread <= price


def timeout_fill(side: Side, close: float, costs: CostModel) -> float:
    """Market exit at the close of the last bar inside the holding limit."""
    return close if side is Side.LONG else close + costs.spread


def favorable_adverse(
    side: Side, bar: Bar, entry: float, risk: float, costs: CostModel
) -> tuple[float, float]:
    """Best and worst excursion of the bar in R, relative to the entry fill."""
    if side is Side.LONG:
        return (bar.high - entry) / risk, (entry - bar.low) / risk
    return (entry - (bar.low + costs.spread)) / risk, ((bar.high + costs.spread) - entry) / risk


def commission_r(entry: float, risk: float, costs: CostModel) -> float:
    """Round-trip commission expressed in R."""
    return 2 * costs.commission_bps / 1e4 * entry / risk
