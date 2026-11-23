"""Loading and cross-checking configuration files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from edgebench.config.environment import InstrumentsConfig, SessionsConfig, SplitsConfig
from edgebench.config.schema import StrategyConfig


class ConfigError(ValueError):
    """A configuration file is missing, malformed or inconsistent with another one."""


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def load_strategy(path: Path) -> StrategyConfig:
    return StrategyConfig.model_validate(load_yaml(path))


def load_instruments(path: Path) -> InstrumentsConfig:
    return InstrumentsConfig.model_validate(load_yaml(path))


def load_sessions(path: Path) -> SessionsConfig:
    return SessionsConfig.model_validate(load_yaml(path))


def load_splits(path: Path) -> SplitsConfig:
    return SplitsConfig.model_validate(load_yaml(path))


@dataclass(frozen=True)
class LoadedConfig:
    strategies: dict[str, StrategyConfig]
    instruments: InstrumentsConfig
    sessions: SessionsConfig
    splits: SplitsConfig


def load_all(config_dir: Path) -> LoadedConfig:
    """Load and validate every config file, including references between them."""
    instruments = load_instruments(config_dir / "instruments.yaml")
    sessions = load_sessions(config_dir / "sessions.yaml")
    splits = load_splits(config_dir / "splits.yaml")
    strategy_files = sorted(config_dir.glob("strategy_*.yaml"))
    if not strategy_files:
        raise ConfigError(f"no strategy_*.yaml files in {config_dir}")
    strategies: dict[str, StrategyConfig] = {}
    for path in strategy_files:
        strategy = load_strategy(path)
        unknown_instruments = set(strategy.instruments) - set(instruments.instruments)
        if unknown_instruments:
            raise ConfigError(f"{path.name}: unknown instruments {sorted(unknown_instruments)}")
        unknown_sessions = set(strategy.sessions) - set(sessions.sessions)
        if unknown_sessions:
            raise ConfigError(f"{path.name}: unknown sessions {sorted(unknown_sessions)}")
        strategies[path.stem] = strategy
    return LoadedConfig(strategies, instruments, sessions, splits)


def unconfirmed_items(config: LoadedConfig) -> list[str]:
    """Human-readable list of placeholder values that must be confirmed before real runs."""
    items = [
        f"instrument {name}: placeholder costs"
        for name, spec in config.instruments.instruments.items()
        if spec.placeholder
    ]
    items += [
        f"session {name}: window not confirmed by the owner"
        for name, window in config.sessions.sessions.items()
        if not window.confirmed
    ]
    return items
