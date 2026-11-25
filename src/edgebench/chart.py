"""Candidate charts (docs/CONTRACT.md sections 4.7 and 5). Needs the ``viz`` extra (matplotlib).

``blind=True`` shows only bars closed by the decision time and no outcome lines: the view a human
labeler or an evaluator is allowed to see. Without it the chart also shows the fill, the stop and
the target levels, for checking what the engine did.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

BEFORE = timedelta(minutes=120)
AFTER = timedelta(minutes=150)
LADDER_SHOWN = (1, 2, 3)
COLORS = {
    "sweep": "tab:purple",
    "rejection": "tab:orange",
    "stall": "tab:blue",
    "inside": "tab:cyan",
    "baseline": "tab:gray",
}


def visible_bars(
    m1: pd.DataFrame,
    touch_start: pd.Timestamp,
    ts_decision: pd.Timestamp,
    blind: bool,
    before: timedelta = BEFORE,
    after: timedelta = AFTER,
) -> pd.DataFrame:
    """M1 bars in the chart window. In blind mode only bars closed by ``ts_decision``."""
    start = touch_start - before
    end = ts_decision if blind else ts_decision + after
    closes = m1["ts_open"] + pd.Timedelta(minutes=1)
    return m1[(m1["ts_open"] >= start) & (closes <= end)].reset_index(drop=True)


def render_candidate(
    bars: pd.DataFrame,
    cand: pd.Series,
    observations: pd.DataFrame,
    path: Path,
    blind: bool = False,
    ladder: tuple[int, ...] = LADDER_SHOWN,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    if bars.empty:
        raise ValueError("no bars to draw")

    def x_of(ts: pd.Timestamp) -> float:
        """Bar index of the first bar opening at or after ``ts`` (clamped to the window)."""
        later = bars.index[bars["ts_open"] >= ts]
        return float(later[0]) if len(later) else float(len(bars) - 1)

    fig, ax = plt.subplots(figsize=(13, 6.5))
    for i, r in enumerate(bars.itertuples(index=False)):
        up = r.close >= r.open
        color = "#2a9d5c" if up else "#d1453b"
        ax.vlines(i, r.low, r.high, color=color, linewidth=0.8)
        ax.add_patch(
            Rectangle(
                (i - 0.35, min(r.open, r.close)), 0.7, abs(r.close - r.open) or 1e-12, color=color
            )
        )
    x_end = len(bars) - 0.5
    if "zone_low" in cand and pd.notna(cand["zone_low"]):
        x0 = max(x_of(cand["zone_known_at"]) - 0.5, -0.5) if "zone_known_at" in cand else -0.5
        low, high = float(cand["zone_low"]), float(cand["zone_high"])
        if high - low < 1e-12:
            ax.hlines(low, x0, x_end, colors="tab:olive", linewidth=1.5, label="H1 level")
        else:
            ax.fill_between([x0, x_end], low, high, color="tab:olive", alpha=0.2, label="H1 FVG")
    decision_x = x_of(cand["ts_decision"]) - 1  # index of the last bar the decision saw
    ax.axvline(decision_x + 0.5, color="black", linestyle=":", linewidth=1, label="decision")
    stop = float(cand["stop_price"])
    ax.hlines(
        stop, decision_x - 3, x_end, colors="tab:red", linestyles="--", linewidth=1, label="stop"
    )
    ax.hlines(float(cand["entry_ref"]), decision_x - 3, decision_x + 3, colors="black", linewidth=1)
    for obs in observations.itertuples(index=False):
        ox = x_of(obs.ts_decision) - 1
        if ox < 0 or ox >= len(bars):
            continue
        y = float(bars["low"].iloc[int(ox)])
        ax.scatter([ox], [y], marker="^", s=70, color=COLORS.get(obs.detector, "k"), zorder=5)
        ax.annotate(obs.detector, (ox, y), textcoords="offset points", xytext=(0, -14),
                    ha="center", fontsize=8, color=COLORS.get(obs.detector, "k"))  # fmt: skip
    if not blind and cand.get("traded") and pd.notna(cand.get("entry_fill")):
        fill, risk = float(cand["entry_fill"]), float(cand["risk_distance"])
        sign = 1 if cand["side"] == "LONG" else -1
        ax.hlines(fill, decision_x, x_end, colors="black", linewidth=0.8)
        for k in ladder:
            ax.hlines(fill + sign * k * risk, decision_x, x_end, colors="tab:green",
                      linestyles=":", linewidth=0.9)  # fmt: skip
            ax.text(
                x_end, fill + sign * k * risk, f" {k}R", va="center", fontsize=8, color="tab:green"
            )
    step = max(len(bars) // 12, 1)
    ax.set_xticks(range(0, len(bars), step))
    labels = [bars["ts_open"].iloc[i].strftime("%d %H:%M") for i in range(0, len(bars), step)]
    ax.set_xticklabels(labels, rotation=30, fontsize=8)
    ax.set_xlim(-1, len(bars) + 3)
    seen = bars.iloc[: int(decision_x) + 1]
    lows, highs = [float(seen["low"].min()), stop], [float(seen["high"].max()), stop]
    if not blind and cand.get("traded") and pd.notna(cand.get("entry_fill")):
        far = float(cand["entry_fill"]) + (1 if cand["side"] == "LONG" else -1) * max(
            ladder
        ) * float(cand["risk_distance"])
        lows.append(far)
        highs.append(far)
    pad = 0.08 * (max(highs) - min(lows) or 1.0)
    ax.set_ylim(min(lows) - pad, max(highs) + pad)
    title = (
        f"{cand['instrument']}  {cand['side']}  trigger={cand['trigger']}  "
        f"session={cand['session']}"
    )
    if not blind:
        title += f"\n{cand['candidate_id']}"
        if cand.get("traded") and pd.notna(cand.get("r_ref")):
            title += f"   reference R={float(cand['r_ref']):+.2f}   exit={cand['exit_reason']}"
    ax.set_title(title, fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
