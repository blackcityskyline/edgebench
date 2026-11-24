"""Data layer: parsing, canonical M1 frames, resampling, storage, splits and the holdout guard."""

from edgebench.data.errors import DataError
from edgebench.data.holdout import HoldoutDenied, authorize_holdout
from edgebench.data.loader import HoldoutRequest, iter_bars, load_bars, load_m1
from edgebench.data.parsers import merge_ask, parse_binance_klines, parse_dukascopy_csv
from edgebench.data.resample import DEFAULT_MIN_M1_FRACTION, resample
from edgebench.data.schema import find_gaps, normalize_m1, validate_m1
from edgebench.data.splits import Fold, SplitBounds, derive_bounds, walk_forward_folds
from edgebench.data.store import content_hash, data_version, verify_store, write_m1

__all__ = [
    "DEFAULT_MIN_M1_FRACTION",
    "DataError",
    "Fold",
    "HoldoutDenied",
    "HoldoutRequest",
    "SplitBounds",
    "authorize_holdout",
    "content_hash",
    "data_version",
    "derive_bounds",
    "find_gaps",
    "iter_bars",
    "load_bars",
    "load_m1",
    "merge_ask",
    "normalize_m1",
    "parse_binance_klines",
    "parse_dukascopy_csv",
    "resample",
    "validate_m1",
    "verify_store",
    "walk_forward_folds",
    "write_m1",
]
