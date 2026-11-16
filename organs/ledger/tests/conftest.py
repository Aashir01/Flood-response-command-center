"""Make ``tests/strategies.py`` importable as ``ledger_strategies`` (the repo runs pytest with
``--import-mode=importlib``, which does not put test directories on ``sys.path``)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_path = Path(__file__).parent / "strategies.py"
if "ledger_strategies" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("ledger_strategies", _path)
    assert _spec is not None and _spec.loader is not None
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["ledger_strategies"] = _module
    _spec.loader.exec_module(_module)
