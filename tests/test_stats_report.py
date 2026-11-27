"""Bootstrap, fixed-R policies and the report on synthetic tables with known answers."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from edgebench.contracts import ExitReason, Side, Trade
from edgebench.report import RunMeta, build_report
from edgebench.results import fixed_r
from edgebench.stats import day_bootstrap_diff, day_bootstrap_mean

T0 = datetime(2024, 1, 1, tzinfo=UTC)
LADDER = [1.0, 2.0, 3.0, 5.0, 10.0]


def test_bootstrap_of_a_constant_is_degenerate() -> None:
    iv = day_bootstrap_mean([1.5] * 40, [f"d{i % 10}" for i in range(40)])
    assert (iv.mean, iv.lo, iv.hi, iv.n, iv.days) == (1.5, 1.5, 1.5, 40, 10)


def test_bootstrap_interval_covers_the_truth_and_detects_an_edge() -> None:
    rng = np.random.default_rng(1)
    days = np.repeat([f"2024-{i:03d}" for i in range(200)], 3)
    noise = rng.normal(0.0, 1.0, size=len(days))
    null = day_bootstrap_mean(noise, days)
    assert null.lo < 0 < null.hi and not null.excludes_zero()
    edge = day_bootstrap_mean(noise + 0.5, days)
    assert edge.excludes_zero() and edge.lo > 0.3 and edge.hi < 0.7


def test_bootstrap_is_wider_when_returns_cluster_by_day() -> None:
    rng = np.random.default_rng(2)
    n_days = 100
    shock = np.repeat(rng.normal(0, 1, n_days), 10)  # ten fully correlated trades per day
    days = np.repeat([f"d{i:03d}" for i in range(n_days)], 10)
    clustered = day_bootstrap_mean(shock, days)
    naive = day_bootstrap_mean(shock, [f"t{i}" for i in range(len(shock))])
    assert (clustered.hi - clustered.lo) > 2 * (naive.hi - naive.lo)


def test_difference_of_means() -> None:
    rng = np.random.default_rng(3)
    days = np.repeat([f"d{i:03d}" for i in range(150)], 4)
    a = rng.normal(0.4, 1, len(days))
    b = rng.normal(0.0, 1, len(days))
    diff = day_bootstrap_diff(a, days, b, days)
    assert diff.excludes_zero() and diff.mean == pytest.approx(a.mean() - b.mean())
    same = day_bootstrap_diff(b, days, b, days)
    assert same.mean == 0.0 and same.lo <= 0 <= same.hi
    assert np.isnan(day_bootstrap_mean([], []).mean)


def _trade(
    ladder: dict[str, datetime | None], stop_r: float | None, timeout_r: float | None
) -> Trade:
    return Trade(
        "t", Side.LONG, T0, 100.0, 99.0, 1.0, T0 + timedelta(minutes=5), ExitReason.STOP, 99.0,
        -1.0, 0.0, 1.0, 0, 0.0, ladder, commission_r=0.05, stop_r=stop_r, timeout_r=timeout_r,
    )  # fmt: skip


def test_fixed_r_policies_from_the_ladder() -> None:
    reached = _trade({"stop": T0, "1": T0, "2": None}, stop_r=-1.1, timeout_r=None)
    assert fixed_r(reached, 1.0) == pytest.approx(0.95)  # target reached: k minus commission
    assert fixed_r(reached, 2.0) == pytest.approx(-1.1)  # not reached, stopped later
    timed = _trade({"stop": None, "1": None}, stop_r=None, timeout_r=0.3)
    assert fixed_r(timed, 1.0) == pytest.approx(0.3)
    broken = _trade({"stop": None, "1": None}, stop_r=None, timeout_r=None)
    with pytest.raises(ValueError, match="no outcome"):
        fixed_r(broken, 1.0)


def synthetic_frame() -> pd.DataFrame:
    """'good' wins 2R every other trade (E=+0.5R); 'bad' and 'baseline' win one trade in three
    (E=0 exactly). The patterns are deterministic so the test cannot depend on a lucky seed."""
    rows = []
    for trigger, period in (("good", 2), ("bad", 3), ("baseline", 3)):
        for i in range(600):
            win = (i + (1 if trigger == "baseline" else 0)) % period == 0
            r = 2.0 if win else -1.0
            row: dict[str, object] = {
                "trigger": trigger, "instrument": "EURUSD", "side": "LONG", "session": "all",
                "zone_kind": "FVG", "exit_reason": "TARGET" if win else "STOP",
                "day": f"2024-{(i % 200):03d}", "traded": True, "ambiguous_bars": 0,
                "risk_bps": 5.0, "cost_r": 0.1,
            }  # fmt: skip
            for k in LADDER:
                row[f"r_{k:g}"] = r
                row[f"hit_{k:g}"] = win
            rows.append(row)
    return pd.DataFrame(rows)


def test_report_flags_the_real_edge_and_not_the_coin_flips() -> None:
    frame = synthetic_frame()
    meta = RunMeta(
        "abc123", "strategy_v1", "c" * 64, "d" * 64, "deadbee", "dev", 1.0, ["EURUSD"], 3,
        ["EURUSD: placeholder costs"], {"EURUSD": {"m1_bars": 10, "events": 5, "candidates": 3}},
    )  # fmt: skip
    text = build_report({"EURUSD": frame}, meta, LADDER)
    assert "trials so far: 3" in text and "EURUSD: placeholder costs" in text
    by_trigger = text.split("## By trigger")[1].split("## Trigger minus baseline")[0]
    rows = {line.split("|")[1].strip(): line for line in by_trigger.splitlines() if "|" in line}
    assert "*" in rows["good"] and "*" not in rows["bad"]
    diff = text.split("## Trigger minus baseline")[1].split("## By instrument")[0]
    diff_rows = {line.split("|")[1].strip(): line for line in diff.splitlines() if "|" in line}
    assert "*" in diff_rows["good"] and "*" not in diff_rows["bad"]
    assert "n<30" not in text.split("## By instrument")[0].replace("Groups with n<30", "")


def test_small_groups_are_not_evaluated_and_empty_runs_say_so() -> None:
    frame = synthetic_frame().head(10)
    meta = RunMeta("r", "s", "c" * 64, "d" * 64, "x", "dev", 1.0, ["EURUSD"], 1, [], {"EURUSD": {}})
    assert "n<30" in build_report({"EURUSD": frame}, meta, LADDER)
    empty = frame.assign(traded=False)
    assert "No traded candidates." in build_report({"EURUSD": empty}, meta, LADDER)


def test_cost_study_compares_multipliers_on_the_same_candidates() -> None:
    from edgebench.report import build_cost_study

    base = synthetic_frame()
    worse = base.assign(**{f"r_{k:g}": base[f"r_{k:g}"] - 0.6 for k in LADDER})  # costs eat 0.6R
    zero = base.assign(**{f"r_{k:g}": base[f"r_{k:g}"] + 0.3 for k in LADDER})
    text = build_cost_study({0.0: zero, 1.0: base, 2.0: worse})
    assert "x0" in text and "x1" in text and "x2" in text
    good = next(ln for ln in text.splitlines() if ln.startswith("| good |"))
    cells = [c.strip() for c in good.split("|")[5:-1]]
    assert cells[0].startswith("+0.800") and cells[1].startswith("+0.500")
    assert cells[2].startswith("-0.100")
    assert "## Trigger minus baseline" in text
