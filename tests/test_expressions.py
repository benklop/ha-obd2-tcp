"""Unit tests for ExprParser port (no Home Assistant runtime required)."""

# Run from ha-obd2-tcp with PYTHONPATH=custom_components
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

from obd2_tcp.expressions import ExprParser, eval_scale_expression  # noqa: E402


def test_scale_expression() -> None:
    assert abs(eval_scale_expression("1.0 / 4.0") - 0.25) < 1e-9


def test_trig_degrees() -> None:
    p = ExprParser()
    assert abs(p.eval_exp("SIN(90)") - 1.0) < 1e-9
    assert abs(p.eval_exp("COS(0)") - 1.0) < 1e-9


def test_bitwise() -> None:
    p = ExprParser()
    assert p.eval_exp("3 & 1") == 1.0
    assert p.eval_exp("2 | 1") == 3.0


def test_power() -> None:
    p = ExprParser()
    assert abs(p.eval_exp("2 ^ 3") - 8.0) < 1e-9


def test_variable_resolve() -> None:
    p = ExprParser()
    p.set_variable_resolve_function(lambda raw: 2000.0 if raw.lstrip("$") == "millis" else 0.0)
    assert abs(p.eval_exp("$millis / 1000") - 2.0) < 1e-6


def test_min_max() -> None:
    p = ExprParser()
    assert p.eval_exp("MIN(3,5)") == 3.0
    assert p.eval_exp("MAX(3,5)") == 5.0
