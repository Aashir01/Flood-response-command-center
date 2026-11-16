"""Brain test setup. ``tests/testkit.py`` is importable as ``brain_testkit`` (the repo runs
pytest with ``--import-mode=importlib``, which does not put test directories on ``sys.path``).
``no_network`` (autouse) and the Hypothesis profiles come from the stitch_common plugin."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("STITCH_LLM_PROVIDER", "fake")

_path = Path(__file__).parent / "testkit.py"
if "brain_testkit" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("brain_testkit", _path)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["brain_testkit"] = _module
    _spec.loader.exec_module(_module)
