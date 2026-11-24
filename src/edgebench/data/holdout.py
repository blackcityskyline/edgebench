"""Holdout guard and ledger (docs/CONTRACT.md section 7.2).

Holdout data is available only through ``authorize_holdout``, which needs the owner's token in the
environment and appends one line to ``holdout/ledger.jsonl`` before anything is returned. This
protects against accidents (an agent or a script reaching for the holdout), not against a person
who wants to bypass it. The runner environment must never have the token.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from edgebench.data.errors import DataError

TOKEN_ENV = "EDGEBENCH_HOLDOUT_TOKEN"  # noqa: S105 - an environment variable name, not a secret


class HoldoutDenied(DataError):
    """Holdout access was requested without the owner's token."""


def authorize_holdout(
    ledger: Path,
    reason: str,
    config_hash: str,
    code_commit: str,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> None:
    """Check the token and record the access; raise HoldoutDenied if it is not allowed."""
    env = os.environ if environ is None else environ
    if not env.get(TOKEN_ENV, "").strip():
        raise HoldoutDenied(
            f"holdout access needs {TOKEN_ENV} in the owner's shell; "
            "agents and the runner must not set it"
        )
    if not reason.strip():
        raise HoldoutDenied("a reason is required for every holdout access")
    stamp = (now or datetime.now(UTC)).isoformat()
    record = {
        "time": stamp,
        "reason": reason.strip(),
        "config_hash": config_hash,
        "code_commit": code_commit,
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def read_ledger(ledger: Path) -> list[dict[str, str]]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
