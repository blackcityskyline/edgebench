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
        row = [str(name), str(len(g)), str(g["day"].nunique()), _median(g, "risk_bps", ".1f"),
               _median(g, "cost_r", ".2f")]  # fmt: skip
        small = len(g) < MIN_N
        for k in ks:
            key = rung_key(k)
            hit = f"{100 * g[f'hit_{key}'].mean():.0f}%"
            ev = "n<30" if small else _fmt(day_bootstrap_mean(g[f"r_{key}"], g["day"], seed=seed))
            row += [hit, ev]
        rows.append(row)
    return rows


def _median(g: pd.DataFrame, col: str, fmt: str) -> str:
    return format(float(g[col].median()), fmt) if col in g and g[col].notna().any() else "-"


def _header(first: str, ks: list[float]) -> list[str]:
    cols = [first, "n", "days", "stop bps", "cost R"]
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
    frames = {k: v.assign(session=v["session"].fillna("none")) for k, v in frames.items() if len(v)}
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
        "by chance (no multiple-comparison correction). `stop bps` is the median stop distance in "
        "basis points of price; `cost R` is the median total friction (spread, stop slippage, "
        "commission) as a fraction of the risk: when it is large, costs decide the result.",
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


def build_cost_study(
    frames_by_mult: dict[float, pd.DataFrame], rung: float = 2.0, seed: int = 0
) -> str:
    """E[R] at one target for the same candidates priced with different cost multipliers.

    ``x0`` is frictionless (no spread, slippage or fees): it shows what the entries are worth
    before costs, and for the pattern-free ``baseline`` it should be close to zero. The candidate
    set is identical across multipliers because filters use the nominal spread.
    """
    key = f"r_{rung_key(rung)}"
    mults = sorted(frames_by_mult)
    traded = {m: f[f["traded"]] for m, f in frames_by_mult.items()}
    base = traded[mults[0]]
    parts = [f"# Cost study: E[R] @{rung_key(rung)}R by cost multiplier", ""]

    def cells(mask_fn: object) -> list[str]:
        out = []
        for m in mults:
            g = mask_fn(traded[m])  # type: ignore[operator]
            out.append(
                "-" if len(g) < MIN_N else _fmt(day_bootstrap_mean(g[key], g["day"], seed=seed))
            )
        return out

    header = ["cell", "n", "stop bps", "cost R @x1", *[f"x{m:g}" for m in mults]]

    def row(label: str, fn: object) -> list[str]:
        g = fn(base)  # type: ignore[operator]
        ref = fn(traded.get(1.0, base))  # type: ignore[operator]
        return [
            label,
            str(len(g)),
            _median(g, "risk_bps", ".1f"),
            _median(ref, "cost_r", ".2f"),
            *cells(fn),
        ]

    rows = [
        row(trig, lambda d, t=trig: d[d["trigger"] == t]) for trig in sorted(set(base["trigger"]))
    ]
    parts += ["## By trigger (all instruments)", "", _table(header, rows)]
    rows = [
        row(
            f"{inst} / {trig}",
            lambda d, i=inst, t=trig: d[(d["instrument"] == i) & (d["trigger"] == t)],
        )
        for inst in sorted(set(base["instrument"]))
        for trig in sorted(set(base[base["instrument"] == inst]["trigger"]))
    ]
    parts += ["", "## By instrument and trigger", "", _table(header, rows)]
    if "baseline" in set(base["trigger"]):
        drows = []
        for inst in sorted(set(base["instrument"])):
            for trig in sorted(set(base["trigger"]) - {"baseline"}):
                cell = [f"{inst} / {trig} - baseline"]
                for m in mults:
                    d = traded[m]
                    a = d[(d["instrument"] == inst) & (d["trigger"] == trig)]
                    b = d[(d["instrument"] == inst) & (d["trigger"] == "baseline")]
                    if len(a) < MIN_N or len(b) < MIN_N:
                        cell.append("-")
                    else:
                        cell.append(
                            _fmt(day_bootstrap_diff(a[key], a["day"], b[key], b["day"], seed=seed))
                        )
                drows.append(cell)
        parts += [
            "",
            "## Trigger minus baseline",
            "",
            _table(["cell", *[f"x{m:g}" for m in mults]], drows),
        ]
    parts.append("")
    return "\n".join(parts)
