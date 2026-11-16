"""Shared Hypothesis strategies and test doubles for the Brain tests (``brain_testkit``)."""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

json_scalars = st.none() | st.booleans() | st.integers(-(10**9), 10**9) | st.text(max_size=8)
json_keys = st.text(
    alphabet=st.sampled_from(list("ab/~0 1é漢")) | st.characters(codec="utf-8"),
    max_size=6,
)


def json_docs(max_leaves: int = 20) -> st.SearchStrategy[Any]:
    return st.recursive(
        json_scalars | st.floats(allow_nan=False, allow_infinity=False),
        lambda children: (
            st.lists(children, max_size=4) | st.dictionaries(json_keys, children, max_size=4)
        ),
        max_leaves=max_leaves,
    )
