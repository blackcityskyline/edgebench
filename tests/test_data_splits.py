from datetime import UTC, date, datetime, timedelta

import pytest

from edgebench.config import SplitsConfig
from edgebench.data import DataError, derive_bounds, walk_forward_folds

FIRST = datetime(2024, 1, 1, tzinfo=UTC)
LAST_END = datetime(2024, 4, 10, tzinfo=UTC)  # 100 days after FIRST


def cfg(**overrides: object) -> SplitsConfig:
    fields: dict[str, object] = {
        "holdout_fraction": 0.2,
        "embargo_days": 2,
        "walk_forward_folds": 4,
    }
    fields.update(overrides)
    return SplitsConfig.model_validate(fields)


def test_derived_bounds_known_answer() -> None:
    bounds = derive_bounds(FIRST, LAST_END, cfg())
    assert bounds.derived
    assert bounds.holdout_start == datetime(2024, 3, 21, tzinfo=UTC)  # last 20 of 100 days
    assert bounds.dev_end == datetime(2024, 3, 19, tzinfo=UTC)  # embargo of 2 days
    assert bounds.dev_start == FIRST


def test_explicit_holdout_start_wins_and_is_not_marked_derived() -> None:
    bounds = derive_bounds(FIRST, LAST_END, cfg(holdout_start=date(2024, 3, 1)))
    assert not bounds.derived
    assert bounds.holdout_start == datetime(2024, 3, 1, tzinfo=UTC)
    assert bounds.dev_end == datetime(2024, 2, 28, tzinfo=UTC)


def test_frozen_holdout_does_not_move_when_more_data_arrives() -> None:
    frozen = cfg(holdout_start=date(2024, 3, 21))
    before = derive_bounds(FIRST, LAST_END, frozen)
    after = derive_bounds(FIRST, LAST_END + timedelta(days=30), frozen)
    assert before.holdout_start == after.holdout_start and before.dev_end == after.dev_end
    drifting = derive_bounds(FIRST, LAST_END + timedelta(days=30), cfg())
    assert drifting.holdout_start != before.holdout_start  # why freezing matters


def test_bad_horizons_and_dates_are_rejected() -> None:
    with pytest.raises(DataError, match="at least"):
        derive_bounds(FIRST, FIRST + timedelta(days=30), cfg())
    with pytest.raises(DataError, match="embargo"):
        derive_bounds(FIRST, LAST_END, cfg(dev_end=date(2024, 3, 21)))
    with pytest.raises(DataError, match="too short"):
        derive_bounds(FIRST, LAST_END, cfg(holdout_start=date(2024, 1, 20)))
    with pytest.raises(DataError, match="timezone"):
        derive_bounds(datetime(2024, 1, 1), LAST_END, cfg())


def test_walk_forward_folds_are_expanding_contiguous_and_embargoed() -> None:
    bounds = derive_bounds(FIRST, LAST_END, cfg())
    folds = walk_forward_folds(bounds, 4)
    assert len(folds) == 4
    for fold in folds:
        assert fold.train_start == bounds.dev_start
        assert fold.train_end == fold.test_start - timedelta(days=bounds.embargo_days)
        assert fold.test_start < fold.test_end
    for a, b in zip(folds, folds[1:], strict=False):
        assert a.test_end == b.test_start  # test segments are contiguous
        assert b.train_end > a.train_end  # training window expands
    assert folds[-1].test_end == bounds.dev_end


def test_walk_forward_rejects_impossible_requests() -> None:
    bounds = derive_bounds(FIRST, LAST_END, cfg())
    with pytest.raises(DataError, match="folds"):
        walk_forward_folds(bounds, 0)
    big_embargo = derive_bounds(FIRST, LAST_END, cfg(embargo_days=25))
    with pytest.raises(DataError, match="embargo"):
        walk_forward_folds(big_embargo, 4)
