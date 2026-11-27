from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from edgebench.config import ConfigError, StrategyConfig, load_all, load_strategy, unconfirmed_items

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def base() -> dict[str, object]:
    return {"instruments": ["EURUSD"], "sessions": ["london"]}


def test_repository_configs_are_valid_and_consistent() -> None:
    config = load_all(CONFIG_DIR)
    assert "strategy_v1" in config.strategies
    assert config.strategies["strategy_v1"].zones.fractal.right == 2


def test_placeholders_are_reported_until_confirmed() -> None:
    items = unconfirmed_items(load_all(CONFIG_DIR))
    assert any("instrument XAUUSD" in item for item in items)
    assert any("session london" in item for item in items)


def test_defaults_form_a_valid_strategy() -> None:
    cfg = StrategyConfig.model_validate(base())
    assert cfg.exits.ladder_r == [1, 2, 3, 5, 8, 10, 15]
    assert cfg.mode == "shadow"


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate({**base(), "enter": {}})
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate({**base(), "zones": {"fvg": {"min_size": 1}}})


@pytest.mark.parametrize("ladder", [[3, 2], [0, 1], [1, 1], []])
def test_bad_ladders_are_rejected(ladder: list[float]) -> None:
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate({**base(), "exits": {"ladder_r": ladder}})


def test_trigger_must_be_enabled() -> None:
    with pytest.raises(ValidationError, match="disabled"):
        StrategyConfig.model_validate(
            {**base(), "patterns": {"stall": {"enabled": False}}, "entry": {"triggers": ["stall"]}}
        )


def test_duplicate_triggers_and_empty_zone_set_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        StrategyConfig.model_validate({**base(), "entry": {"triggers": ["sweep", "sweep"]}})
    with pytest.raises(ValidationError, match="zone kind"):
        StrategyConfig.model_validate(
            {**base(), "zones": {"fvg": {"enabled": False}, "fractal": {"enabled": False}}}
        )


def test_config_hash_is_stable_and_sensitive() -> None:
    a = StrategyConfig.model_validate(base())
    b = StrategyConfig.model_validate(base())
    c = StrategyConfig.model_validate({**base(), "zones": {"fractal": {"left": 1, "right": 1}}})
    assert a.config_hash() == b.config_hash()
    assert a.config_hash() != c.config_hash()


def test_cross_file_references_are_checked(tmp_path: Path) -> None:
    for name in ("instruments.yaml", "sessions.yaml", "splits.yaml", "strategy_v1.yaml"):
        (tmp_path / name).write_text((CONFIG_DIR / name).read_text())
    broken = yaml.safe_load((CONFIG_DIR / "strategy_v1.yaml").read_text())
    broken["instruments"] = ["NOPE"]
    (tmp_path / "strategy_v1.yaml").write_text(yaml.safe_dump(broken))
    with pytest.raises(ConfigError, match="unknown instruments"):
        load_all(tmp_path)


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_strategy(tmp_path / "nope.yaml")
