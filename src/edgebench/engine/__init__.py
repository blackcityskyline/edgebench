"""Streaming reference engine (docs/CONTRACT.md section 4.6)."""

from edgebench.engine.aggregate import Aggregator
from edgebench.engine.run import Engine, RunOutput, UnsupportedConfigError, run_engine

__all__ = ["Aggregator", "Engine", "RunOutput", "UnsupportedConfigError", "run_engine"]
