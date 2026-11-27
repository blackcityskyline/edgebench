"""Flat tables from an engine run (docs/CONTRACT.md sections 4.6, 7).

``candidate_frame`` has one row per candidate: its event context, the reference trade and the
outcome of every fixed-R exit policy (``r_<k>`` net R, ``hit_<k>`` target reached before the stop).
Candidates that never filled (data hole, gap through the stop) have NaN outcomes and
``traded=False``; reports use traded rows only.
"""

from __future__ import annotations

import pandas as pd

from edgebench.contracts import Trade
from edgebench.engine import RunOutput
from edgebench.execution import rung_key

FEATURES = ("zone_age_h1", "zone_size_atr_h1", "dist_opposite_atr_h1")


def fixed_r(trade: Trade, k: float) -> float:
    """Net R of the policy 'target at kR, stop at the stop, else timeout' for a stored trade."""
    reached = trade.ladder.get(rung_key(k))
    if reached is not None:
        return k - trade.commission_r
    if trade.stop_r is not None:
        return trade.stop_r
    if trade.timeout_r is None:
        raise ValueError(f"trade {trade.trade_id} has no outcome for target {k}")
    return trade.timeout_r


def _zone_parts(zone_id: str) -> tuple[str, str]:
    parts = zone_id.split(":")
    return parts[1], parts[2]


def _zone_columns(out: RunOutput, zone_id: str) -> dict[str, object]:
    zone = next((z for z in out.zones if z.zone_id == zone_id), None)
    if zone is None:
        return {}
    return {
        "zone_low": zone.low,
        "zone_high": zone.high,
        "zone_known_at": pd.Timestamp(zone.known_at),
    }


def candidate_frame(out: RunOutput, instrument: str, ladder_r: list[float]) -> pd.DataFrame:
    events = {e.event_id: e for e in out.events}
    zones = {z.zone_id: z for z in out.zones}
    trades = {t.trade_id: t for t in out.trades}
    rows: list[dict[str, object]] = []
    for cand in out.candidates:
        event = events[cand.event_id]
        kind, direction = _zone_parts(event.zone_id)
        trade = trades.get(cand.candidate_id)
        row: dict[str, object] = {
            "candidate_id": cand.candidate_id,
            "event_id": cand.event_id,
            "zone_id": event.zone_id,
            "instrument": instrument,
            "trigger": cand.trigger,
            "side": cand.side.value,
            "ts_decision": pd.Timestamp(cand.ts_decision),
            "day": cand.ts_decision.strftime("%Y-%m-%d"),
            "session": event.session,
            "zone_kind": kind,
            "zone_dir": direction,
            "traded": trade is not None,
            "entry_ref": cand.entry_ref,
            "stop_price": cand.stop_price,
            "zone_low": zones[event.zone_id].low,
            "zone_high": zones[event.zone_id].high,
            "zone_known_at": pd.Timestamp(zones[event.zone_id].known_at),
            "touch_start": pd.Timestamp(event.touch_start),
        }
        for name in FEATURES:
            row[name] = event.features.get(name, float("nan"))
        nan = float("nan")
        row |= {
            "entry_fill": trade.entry_fill if trade else nan,
            "risk_distance": trade.risk_distance if trade else nan,
            "risk_bps": 1e4 * trade.risk_distance / trade.entry_fill if trade else nan,
            "exit_reason": trade.exit_reason.value if trade else None,
            "r_ref": trade.r_net if trade else nan,
            "mfe_r": trade.mfe_r if trade else nan,
            "mae_r": trade.mae_r if trade else nan,
            "ambiguous_bars": trade.ambiguous_bars if trade else 0,
            "cost_r": trade.cost_r if trade else nan,
        }
        for k in ladder_r:
            key = rung_key(k)
            row[f"r_{key}"] = fixed_r(trade, k) if trade else nan
            row[f"hit_{key}"] = (trade.ladder.get(key) is not None) if trade else False
        rows.append(row)
    return pd.DataFrame(rows)


def event_frame(out: RunOutput, instrument: str) -> pd.DataFrame:
    """One row per touch episode, including those that produced no candidate."""
    counts: dict[str, int] = {}
    for cand in out.candidates:
        counts[cand.event_id] = counts.get(cand.event_id, 0) + 1
    rows: list[dict[str, object]] = []
    for e in out.events:
        kind, direction = _zone_parts(e.zone_id)
        row: dict[str, object] = {
            "event_id": e.event_id,
            "zone_id": e.zone_id,
            "instrument": instrument,
            "zone_kind": kind,
            "zone_dir": direction,
            "touch_start": pd.Timestamp(e.touch_start),
            "session": e.session,
            "n_candidates": counts.get(e.event_id, 0),
            **_zone_columns(out, e.zone_id),
        }
        for name in FEATURES:
            row[name] = e.features.get(name, float("nan"))
        for obs in e.observations:
            key = f"obs_{obs.detector}"
            row[key] = int(row.get(key, 0)) + 1  # type: ignore[call-overload]
        rows.append(row)
    return pd.DataFrame(rows)


def observation_frame(out: RunOutput, instrument: str) -> pd.DataFrame:
    """One row per pattern observation, for charts and for checking detectors by eye."""
    rows = [
        {
            "event_id": e.event_id,
            "instrument": instrument,
            "detector": o.detector,
            "ts_decision": pd.Timestamp(o.ts_decision),
            "direction": o.direction.value,
            **{f"ref_{k}": v for k, v in o.refs.items()},
            **{f"m_{k}": v for k, v in o.metrics.items()},
        }
        for e in out.events
        for o in e.observations
    ]
    return pd.DataFrame(rows)
