import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "research" / "coverage-study" / "classify.py"
SPEC = importlib.util.spec_from_file_location("coverage_classify", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CLASSIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLASSIFIER)


def test_classifier_can_be_imported_without_running_cli():
    assert callable(CLASSIFIER.classify)
    assert callable(CLASSIFIER.hunks)


def test_classifier_identifies_documentation_and_non_code():
    assert CLASSIFIER.classify("README.md", ["old"], ["new"]) == "docs"
    assert CLASSIFIER.classify("assets/logo.svg", ["old"], ["new"]) == "outro"


def test_classifier_identifies_simple_deterministic_shapes():
    assert CLASSIFIER.classify("src/app.py", ["import os"], ["import sys"]) == "import"
    assert CLASSIFIER.classify("src/app.py", ["# old note"], ["# new note"]) == "comentario"
    assert CLASSIFIER.classify("src/app.py", ["unused = 1"], []) == "remocao_pura"


def test_classifier_does_not_call_new_logic_deterministic():
    assert CLASSIFIER.classify("src/app.py", ["return old_value"], ["return calculate(value)"]) == "logica_nova"
