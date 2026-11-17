"""Property placeholder: the envelope invariant (BOOT-P1) holds for any arguments.

Uses the shared Hypothesis profiles (``dev`` 30 examples, ``ci`` 200) registered by the
stitch_common pytest plugin. Add the organ's own properties (see the spec) next to this one.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from stitch_common.tooling import run_tool
from stitch_eyes.core import CORES
from stitch_eyes.models import TOOL_NAMES

arguments = st.dictionaries(
    st.text(max_size=8),
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=8),
    max_size=5,
)


@given(arguments)
def test_envelope_invariant_for_arbitrary_arguments(args: dict[str, Any]) -> None:
    for tool in TOOL_NAMES:
        result = asyncio.run(run_tool("eyes", tool, "0.1.0", CORES[tool], args))
        assert result.ok == (result.data is not None and result.error is None)
        assert result.ok or result.error is not None
