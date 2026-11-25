from datetime import UTC, datetime

from edgebench.calendar import session_of
from edgebench.config.environment import SessionsConfig


def cfg(**windows: tuple[str, str]) -> SessionsConfig:
    return SessionsConfig.model_validate(
        {
            "tz": "America/New_York",
            "sessions": {n: {"start": a, "end": b} for n, (a, b) in windows.items()},
        }
    )


def at(month: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2024, month, 15, hour, minute, tzinfo=UTC)


def test_windows_are_left_closed_in_new_york_time_and_follow_dst() -> None:
    c = cfg(ny_am=("09:30", "12:00"))
    # January: New York is UTC-5, so 09:30 local is 14:30 UTC
    assert session_of(at(1, 14, 29), c) is None
    assert session_of(at(1, 14, 30), c) == "ny_am"
    assert session_of(at(1, 16, 59), c) == "ny_am"
    assert session_of(at(1, 17, 0), c) is None
    # July: UTC-4, so the same window is 13:30-16:00 UTC
    assert session_of(at(7, 13, 30), c) == "ny_am"
    assert session_of(at(7, 14, 29), c) == "ny_am"
    assert session_of(at(7, 16, 0), c) is None


def test_first_declared_window_wins_and_midnight_crossing_works() -> None:
    c = cfg(a=("01:00", "03:00"), b=("02:00", "04:00"), night=("22:00", "01:00"))
    assert session_of(at(1, 7, 30), c) == "a"  # 02:30 local: a and b overlap, a first
    assert session_of(at(1, 8, 30), c) == "b"  # 03:30 local
    assert session_of(at(1, 4, 0), c) == "night"  # 23:00 local the previous evening
    assert session_of(at(1, 5, 59), c) == "night"  # 00:59 local
    assert session_of(at(1, 6, 0), c) == "a"  # 01:00 local
