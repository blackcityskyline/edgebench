"""Read-only probe of the Upscale public API (https://docs.upscale.trade/developers).

Run it on your own machine; the key is read from the UPSCALE_API_KEY environment variable and is
never printed or written. Only GET requests are sent. Raw responses are saved under
data/upscale/ (git-ignored) so they can be inspected offline.

    export UPSCALE_API_KEY=...        # do not put the key in a file inside the repository
    python tools/upscale_probe.py [--account <uuid>] [--no-save]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "https://api.upscale.trade"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "upscale"
PAUSE_SECONDS = 0.3  # stay well below the default 10 requests per second


def get(path: str, key: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    """GET ``path``; return (HTTP status, parsed JSON or raw text)."""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(  # noqa: S310 - fixed https base URL
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            status, body = response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read().decode("utf-8", errors="replace")
        if status == 429:
            print(f"  rate limited, Retry-After={exc.headers.get('Retry-After')}")
    time.sleep(PAUSE_SECONDS)
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


def items_of(payload: Any) -> list[Any]:
    """The list inside a response, whether it is a bare array or wrapped in ``data``."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for field in ("data", "items", "accounts", "markets"):
            if isinstance(payload.get(field), list):
                return list(payload[field])
    return []


def find_account_id(accounts: list[Any]) -> str | None:
    for item in accounts:
        if isinstance(item, dict):
            for field in ("id", "accountId", "traderId"):
                if isinstance(item.get(field), str):
                    return str(item[field])
    return None


def probe(key: str, account: str | None, save: bool) -> int:
    if save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    def call(name: str, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
        status, payload = get(path, key, params)
        count = len(items_of(payload))
        shape = list(payload)[:8] if isinstance(payload, dict) else type(payload).__name__
        print(f"{status}  GET {path}  items={count}  top-level={shape}")
        if status >= 400:
            print(f"     error: {payload}")
        if save:
            (OUT_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return status, payload

    status, _ = call("markets", "/v2/markets")
    if status == 401:
        print("key rejected (401): missing, malformed, revoked or expired")
        return 1
    status, accounts = call("accounts", "/accounts/with-risk-status")
    account = account or find_account_id(items_of(accounts))
    if account is None:
        print("no account id found; pass --account <uuid> to probe account endpoints")
        return 0
    print(f"using account {account}")
    call("positions_active", f"/positions/{account}/active")
    call("positions_history", f"/positions/{account}/portfolio/history", {"limit": 100})
    call("equity_history", f"/accounts/{account}/equity-history")
    call("account_stats", f"/accounts/{account}/stats")
    call("risk_status", f"/accounts/{account}/risk-status")
    if save:
        print(f"raw responses saved in {OUT_DIR}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Upscale API probe")
    parser.add_argument("--account", help="account UUID (default: first account found)")
    parser.add_argument("--no-save", action="store_true", help="do not write responses to disk")
    args = parser.parse_args()
    key = os.environ.get("UPSCALE_API_KEY", "").strip()
    if not key:
        print("set UPSCALE_API_KEY in the environment first", file=sys.stderr)
        return 2
    return probe(key, args.account, save=not args.no_save)


if __name__ == "__main__":
    raise SystemExit(main())
