"""Smoke test for the Streamlit UI: importable + key constants/helpers present."""
from pathlib import Path
import importlib.util

UI = Path(__file__).parent.parent / "src" / "ui.py"


def test_ui_importable():
    """src/ui.py compiles + imports without errors (streamlit decorators run on import)."""
    spec = importlib.util.spec_from_file_location("ui", UI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "_load_extracted")
    assert hasattr(mod, "_load_sample")


def test_ui_emits_correct_constants():
    """The UI module references the expected repo paths and audit events."""
    text = UI.read_text()
    assert "EXTRACTED = REPO_ROOT" in text
    assert "AUDIT_LOG = Path" in text
    assert "human_approved" in text
    assert "human_overridden" in text
    assert "human_dlq" in text
    assert "Senior reviewer queue" in text
