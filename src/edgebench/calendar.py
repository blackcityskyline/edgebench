"""Session labels (docs/CONTRACT.md section 2.1): windows in a named IANA timezone."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from edgebench.config.environment import SessionsConfig
from edgebench.contracts import require_utc


def _parse(hhmm: str) -> time:
    hour, minute = hhmm.split(":")
    return time(int(hour), int(minute))


def session_of(ts: datetime, cfg: SessionsConfig) -> str | None:
    """Name of the first session whose window contains ``ts``, or None.

    A window is ``start <= local time < end`` in ``cfg.tz`` (DST handled by the timezone). A window
    with ``start > end`` crosses midnight. Overlapping windows resolve to the first one declared.
    """
    require_utc(ts, "ts")
    local = ts.astimezone(ZoneInfo(cfg.tz)).time()
    for name, window in cfg.sessions.items():
        start, end = _parse(window.start), _parse(window.end)
        inside = start <= local < end if start <= end else (local >= start or local < end)
        if inside:
            return name
    return None
