"""Errors raised by the data layer."""

from __future__ import annotations


class DataError(ValueError):
    """Data is malformed, inconsistent or missing."""
