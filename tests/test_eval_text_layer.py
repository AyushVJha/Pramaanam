import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "eval_text_layer", Path(__file__).parent.parent / "bench" / "eval_text_layer.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_identical_text_has_zero_error():
    assert mod.cer("a b c", "a b c") == 0.0


def test_line_breaks_are_not_errors():
    assert mod.cer("the court\nheld that", "the court held that") == 0.0


def test_one_wrong_letter_in_ten():
    assert abs(mod.cer("abcdefghiX", "abcdefghij") - 0.1) < 1e-9


def test_empty_human_text():
    assert mod.cer("", "") == 0.0
    assert mod.cer("junk", "") == 1.0
