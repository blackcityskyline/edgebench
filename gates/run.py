"""edgebench quality gates. Protected path: workers must not edit this file.

Usage: python gates/run.py [--quick] [--only G1,G3]

Exit code is 0 when no gate FAILs. SKIP is always printed explicitly and is never a PASS.
Gate ids follow docs/CONTRACT.md section 9.4 (G9, the task's own acceptance, is run by the runner).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_FILE_BYTES = 1_000_000
SIZE_ALLOWLIST: frozenset[str] = frozenset()
FORBIDDEN_SUFFIXES = (".parquet", ".zip", ".h5", ".feather")
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "openai-style key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "upscale key": re.compile(r"usk_[A-Za-z0-9_]{16,}"),
    "api key assignment": re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
}
SECRET_SCAN_SKIP = frozenset({"gates/run.py"})


@dataclass
class Result:
    gate: str
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _tail(text: str, lines: int = 15) -> str:
    return "\n".join(text.splitlines()[-lines:])


def scan_secrets(text: str) -> list[str]:
    """Names of secret patterns found in ``text``."""
    return [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]


def hygiene_problems(files: list[str], root: Path = ROOT) -> list[str]:
    """Problems with tracked files: forbidden types, oversized files, secret-like content."""
    problems: list[str] = []
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        if rel.startswith("data/") or rel.lower().endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"{rel}: data file must not be tracked")
            continue
        if path.stat().st_size > MAX_FILE_BYTES and rel not in SIZE_ALLOWLIST:
            problems.append(f"{rel}: larger than {MAX_FILE_BYTES} bytes")
        if rel in SECRET_SCAN_SKIP:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name in scan_secrets(content):
            problems.append(f"{rel}: looks like a secret ({name})")
    return problems


def gate_g1() -> Result:
    code, out = _run([sys.executable, "-m", "ruff", "check", "."])
    if code != 0:
        return Result("G1", "lint and format", "FAIL", _tail(out))
    code, out = _run([sys.executable, "-m", "ruff", "format", "--check", "."])
    if code != 0:
        return Result("G1", "lint and format", "FAIL", _tail(out))
    return Result("G1", "lint and format", "PASS")


def gate_g2() -> Result:
    code, out = _run([sys.executable, "-m", "mypy"])
    return Result(
        "G2", "types (mypy)", "PASS" if code == 0 else "FAIL", "" if code == 0 else _tail(out)
    )


def gate_g3(quick: bool) -> Result:
    cmd = [sys.executable, "-m", "pytest", "-q"]
    if quick:
        cmd += ["-m", "not slow"]
    code, out = _run(cmd)
    return Result(
        "G3", "unit tests", "PASS" if code == 0 else "FAIL", "" if code == 0 else _tail(out)
    )


def _required_test_gate(gate: str, name: str, test_file: str) -> Result:
    path = ROOT / "tests" / test_file
    if not path.exists():
        return Result(gate, name, "SKIP", f"pending M4: tests/{test_file} is not written yet")
    code, out = _run([sys.executable, "-m", "pytest", "-q", str(path)])
    return Result(gate, name, "PASS" if code == 0 else "FAIL", "" if code == 0 else _tail(out))


def gate_g4() -> Result:
    return _required_test_gate("G4", "causality", "test_causality.py")


def gate_g5() -> Result:
    return _required_test_gate("G5", "determinism", "test_determinism.py")


def gate_g6() -> Result:
    try:
        from edgebench.config import load_all

        config = load_all(ROOT / "config")
    except Exception as exc:  # noqa: BLE001 - any failure here is a gate failure
        return Result("G6", "config schema", "FAIL", f"{type(exc).__name__}: {exc}")
    return Result("G6", "config schema", "PASS", f"{len(config.strategies)} strategy file(s)")


def gate_g7() -> Result:
    code, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0 or not branch.startswith("agent/"):
        return Result("G7", "protected paths", "SKIP", "not a worker branch (agent/*)")
    code, out = _run(["git", "diff", "--name-only", "origin/main...HEAD"])
    if code != 0:
        return Result("G7", "protected paths", "FAIL", f"cannot diff against origin/main: {out}")
    from edgebench.runner.protected import violations

    found = violations(out.splitlines())
    protected = [v for v in found if v.reason in {"protected path", "path escapes the repository"}]
    if protected:
        return Result(
            "G7", "protected paths", "FAIL", "\n".join(f"{v.path}: {v.reason}" for v in protected)
        )
    return Result("G7", "protected paths", "PASS")


def gate_g8() -> Result:
    code, out = _run(["git", "ls-files"])
    if code != 0:
        return Result("G8", "repo hygiene", "FAIL", f"git ls-files failed: {out}")
    problems = hygiene_problems(out.splitlines())
    if problems:
        return Result("G8", "repo hygiene", "FAIL", "\n".join(problems[:20]))
    return Result("G8", "repo hygiene", "PASS")


def build_gates(quick: bool) -> list[tuple[str, Callable[[], Result], bool]]:
    """(id, function, included_in_quick)."""
    return [
        ("G1", gate_g1, True),
        ("G2", gate_g2, False),
        ("G3", lambda: gate_g3(quick), True),
        ("G4", gate_g4, False),
        ("G5", gate_g5, False),
        ("G6", gate_g6, True),
        ("G7", gate_g7, True),
        ("G8", gate_g8, True),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gates")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--only", help="comma-separated gate ids")
    args = parser.parse_args(argv)
    only = {g.strip().upper() for g in args.only.split(",")} if args.only else None

    results: list[Result] = []
    for gate_id, func, in_quick in build_gates(args.quick):
        if only is not None and gate_id not in only:
            continue
        if args.quick and not in_quick and only is None:
            results.append(Result(gate_id, "", "SKIP", "not part of --quick"))
            continue
        results.append(func())

    failed = False
    for res in results:
        label = f"{res.gate} {res.name}".strip()
        print(
            f"{res.status:<5} {label}"
            + (f"  ({res.detail.splitlines()[0]})" if res.status != "FAIL" and res.detail else "")
        )
        if res.status == "FAIL":
            failed = True
            print("\n".join("      " + line for line in res.detail.splitlines()))
    print("gates: FAILED" if failed else "gates: ok (SKIP is not PASS)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
