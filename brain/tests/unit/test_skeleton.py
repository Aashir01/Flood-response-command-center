"""Skeleton checks (task 1): the package imports, paths resolve, sockets are blocked."""

from __future__ import annotations

import socket

import pytest

import stitch_brain
from stitch_brain import paths


def test_package_and_paths() -> None:
    assert stitch_brain.BRAIN_VERSION
    assert (paths.repo_root() / "data" / "demo").is_dir()
    assert paths.config_dir().name == "config"


def test_no_network_is_on_by_default() -> None:
    with pytest.raises(RuntimeError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)
