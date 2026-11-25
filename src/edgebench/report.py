"""Markdown report of a run (docs/CONTRACT.md section 7).

All results are net R of fixed-target exit policies (target at kR or the stop). Intervals are 95%
day-block bootstrap intervals. The report prints every ladder rung instead of picking the best one,
because picking the best of many is how noise gets promoted to an edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from edgebench.execution import rung_key
from edgebench.stats import Interval, day_bootstrap_diff, day_bootstrap_mean

MIN_N = 30
REPORT_RUNGS = (1.0, 2.0, 3.0, 5.0, 10.0)


@dataclass
class RunMeta:
    run_id: str
    strategy: str
    config_hash: str
    data_version: str
    code_commit: str
    split: str
    cost_mult: float
    instruments: list[str]
    trials: int
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)


def _rungs(ladder_r: list[float]) -> list[float]:
    return [k for k in REPORT_RUNGS if k in ladder_r] or ladder_r[:3]


def _fmt(iv: Interval) -> str:
    if iv.n == 0 or iv.mean != iv.mean:
        return "-"
    star = "*" if iv.excludes_zero() else ""
    return f"{iv.mean:+.3f} [{iv.lo:+.2f}, {iv.hi:+.2f}]{star}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _group_rows(df: pd.DataFrame, by: str, ks: list[float], seed: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for name, g in df.groupby(by, dropna=False, sort=True):
        row = [str(name), str(len(g)), str(g["day"].nunique())]
        small = len(g) < MIN_N
        for k in ks:
            key = rung_key(k)
            hit = f"{100 * g[f'hit_{key}'].mean():.0f}%"
            ev = "n<30" if small else _fmt(day_bootstrap_mean(g[f"r_{key}"], g["day"], seed=seed))
            row += [hit, ev]
        rows.append(row)
    return rows


def _header(first: str, ks: list[float]) -> list[str]:
    cols = [first, "n", "days"]
    for k in ks:
        cols += [f"hit {rung_key(k)}R", f"E[R] @{rung_key(k)}R"]
    return cols


def _baseline_rows(df: pd.DataFrame, ks: list[float], seed: int) -> list[list[str]]:
    base = df[df["trigger"] == "baseline"]
    rows: list[list[str]] = []
    for trig in sorted(set(df["trigger"]) - {"baseline"}):
        g = df[df["trigger"] == trig]
        row = [trig, str(len(g)), str(len(base))]
        for k in ks:
            key = f"r_{rung_key(k)}"
            if len(g) < MIN_N or len(base) < MIN_N:
                row.append("n<30")
            else:
                iv = day_bootstrap_diff(g[key], g["day"], base[key], base["day"], seed=seed)
                row.append(_fmt(iv))
        rows.append(row)
    return rows


def build_report(
    frames: dict[str, pd.DataFrame], meta: RunMeta, ladder_r: list[float], seed: int = 0
) -> str:
    ks = _rungs(ladder_r)
    parts = [f"# Run {meta.run_id}: {meta.strategy} on {meta.split}", ""]
    parts.append(
        f"config `{meta.config_hash[:12]}` | data `{meta.data_version[:12]}` | "
        f"code `{meta.code_commit}` | cost x{meta.cost_mult:g} | "
        f"trials so far: {meta.trials}"
    )
    if meta.warnings:
        parts += ["", "**Warnings**", *[f"- {w}" for w in meta.warnings]]
    parts += ["", "## Funnel", ""]
    funnel_cols = ["m1_bars", "zones_fvg", "zones_fractal", "events", "candidates", "trades_opened"]
    rows = [[inst, *[str(c.get(col, 0)) for col in funnel_cols]] for inst, c in meta.counts.items()]
    parts.append(_table(["instrument", *funnel_cols], rows))
    skips = {
        k: sum(c.get(k, 0) for c in meta.counts.values())
        for k in sorted(
            {k for c in meta.counts.values() for k in c if k.startswith(("skip_", "rej", "no_"))}
        )
    }
    if skips:
        parts += ["", "Skipped: " + ", ".join(f"{k}={v}" for k, v in skips.items())]

    traded = [f[f["traded"]] for f in frames.values() if len(f)]
    df = pd.concat(traded, ignore_index=True) if traded else pd.DataFrame()
    if df.empty:
        return "\n".join([*parts, "", "No traded candidates.", ""])
    parts += [
        "",
        f"Cells show `E[R] [95% day-block interval]`; `*` means the interval excludes zero. "
        f"Groups with n<{MIN_N} are not evaluated. Many cells are shown, so some `*` are expected "
        "by chance (no multiple-comparison correction).",
        "",
        "## By trigger (all instruments)",
        "",
        _table(_header("trigger", ks), _group_rows(df, "trigger", ks, seed)),
    ]
    if "baseline" in set(df["trigger"]):
        parts += [
            "",
            "## Trigger minus baseline (same zones, random bar, same stop rule)",
            "",
            _table(
                ["trigger", "n", "n baseline", *[f"diff @{rung_key(k)}R" for k in ks]],
                _baseline_rows(df, ks, seed),
            ),
        ]
    for title, col in (
        ("By instrument", "instrument"),
        ("By side", "side"),
        ("By session", "session"),
        ("By zone kind", "zone_kind"),
        ("By exit of the reference policy", "exit_reason"),
    ):
        parts += ["", f"## {title}", "", _table(_header(col, ks), _group_rows(df, col, ks, seed))]
    inst_trig = df.assign(cell=df["instrument"] + " / " + df["trigger"])
    parts += [
        "",
        "## Instrument x trigger",
        "",
        _table(_header("cell", ks), _group_rows(inst_trig, "cell", ks, seed)),
        "",
        f"Ambiguous bars (stop and target in one bar, stop wins): "
        f"{int(df['ambiguous_bars'].sum())} in {len(df)} trades.",
        "",
    ]
    return "\n".join(parts)
