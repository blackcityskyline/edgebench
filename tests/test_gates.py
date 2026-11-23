import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_gates() -> ModuleType:
    spec = importlib.util.spec_from_file_location("edgebench_gates_run", ROOT / "gates" / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gates = load_gates()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("usk_" + "a1B2c3D4e5F6g7H8i9", "upscale key"),
        ("AKIA" + "ABCDEFGHIJKLMNOP", "aws access key"),
        ("gh" + "p_" + "a" * 36, "github token"),
        ("sk-" + "x" * 24, "openai-style key"),
        ('api_key = "' + "z" * 20 + '"', "api key assignment"),
        ("-----BEGIN " + "PRIVATE KEY-----", "private key block"),
    ],
)
def test_secret_patterns_detect_known_shapes(text: str, expected: str) -> None:
    assert expected in gates.scan_secrets(text)


def test_secret_scan_ignores_ordinary_text() -> None:
    assert gates.scan_secrets("the usk prefix and api keys are described in prose") == []
    assert gates.scan_secrets("api_key = os.environ['UPSCALE_API_KEY']") == []


def test_hygiene_flags_data_files_and_secrets(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.csv").write_text("a,b\n")
    (tmp_path / "big.parquet").write_bytes(b"0")
    (tmp_path / "leak.py").write_text('API_KEY = "' + "q" * 24 + '"\n')
    (tmp_path / "fine.py").write_text("print('ok')\n")
    problems = gates.hygiene_problems(
        ["data/x.csv", "big.parquet", "leak.py", "fine.py"], root=tmp_path
    )
    joined = "\n".join(problems)
    assert "data/x.csv" in joined and "big.parquet" in joined and "leak.py" in joined
    assert "fine.py" not in joined


def test_hygiene_flags_oversized_files(tmp_path: Path) -> None:
    (tmp_path / "huge.txt").write_text("x" * (gates.MAX_FILE_BYTES + 1))
    assert any("larger than" in p for p in gates.hygiene_problems(["huge.txt"], root=tmp_path))


def test_required_gates_skip_loudly_until_their_tests_exist() -> None:
    if not (ROOT / "tests" / "test_causality.py").exists():
        result = gates.gate_g4()
        assert result.status == "SKIP" and "pending M4" in result.detail
