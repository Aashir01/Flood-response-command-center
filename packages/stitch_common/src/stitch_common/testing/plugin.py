"""pytest plugin registered through the ``pytest11`` entry point (BOOT-R2.4).

Provides, with no per-package conftest:

* ``no_network`` (autouse): outbound sockets and DNS are blocked during every test.
  ``@pytest.mark.allow_loopback`` permits connecting to ``127.0.0.1`` only.
  ``@pytest.mark.live`` disables the guard (excluded from CI).
* Hypothesis profiles ``dev`` (30 examples, default) and ``ci`` (200 examples, no deadline).
* Fixtures ``schema_dir``, ``contract_schemas`` and ``load_schema``.

Why not ``pytest-socket``: on Windows, ``socket.socketpair()`` (used by every asyncio event loop
as its self-pipe) is implemented in Python as a loopback TCP connect. ``pytest-socket`` blocks
that connect, which breaks asyncio. This guard allows loopback connects only while a
``socketpair()`` call is in progress, and blocks everything else that leaves the process.
Child processes are not affected (stdio MCP servers run in a subprocess and use pipes).
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from hypothesis import settings

settings.register_profile("dev", max_examples=30)
settings.register_profile("ci", max_examples=200, deadline=None)
settings.load_profile("dev")

LOOPBACK_NAMES = {"127.0.0.1", "::1", "localhost"}


class NetworkBlockedError(RuntimeError):
    """Raised when a test tries to reach the network while ``no_network`` is active."""


class _Guard:
    def __init__(self) -> None:
        self.active = False
        self.allow_loopback = False
        self._local = threading.local()

    @property
    def in_socketpair(self) -> bool:
        return bool(getattr(self._local, "depth", 0))

    def enter_socketpair(self) -> None:
        self._local.depth = getattr(self._local, "depth", 0) + 1

    def exit_socketpair(self) -> None:
        self._local.depth -= 1


_guard = _Guard()
_real_socket = socket.socket
_real_socketpair = socket.socketpair
_real_getaddrinfo = socket.getaddrinfo
_real_gethostbyname = socket.gethostbyname


def _host_of(address: Any) -> str | None:
    if isinstance(address, str | bytes | os.PathLike):
        return None  # AF_UNIX path
    if isinstance(address, tuple) and address:
        host = address[0]
        return host.decode() if isinstance(host, bytes) else str(host)
    return None


def _check_address(address: Any) -> None:
    if not _guard.active:
        return
    host = _host_of(address)
    if host is None:
        return
    if _guard.in_socketpair and host in LOOPBACK_NAMES:
        return
    if _guard.allow_loopback and host == "127.0.0.1":
        return
    raise NetworkBlockedError(
        f"network access to {host!r} is blocked by stitch no_network "
        "(use @pytest.mark.allow_loopback for 127.0.0.1 or @pytest.mark.live)"
    )


class _GuardedSocket(_real_socket):
    def connect(self, address: Any) -> None:
        _check_address(address)
        super().connect(address)

    def connect_ex(self, address: Any) -> int:
        _check_address(address)
        return int(super().connect_ex(address))

    def sendto(self, *args: Any) -> int:
        _check_address(args[-1])
        return int(super().sendto(*args))


def _guarded_socketpair(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
    _guard.enter_socketpair()
    try:
        return _real_socketpair(*args, **kwargs)
    finally:
        _guard.exit_socketpair()


def _guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
    name = host.decode() if isinstance(host, bytes) else host
    if _guard.active and name not in (None, "") and name not in LOOPBACK_NAMES:
        raise NetworkBlockedError(f"DNS lookup of {name!r} is blocked by stitch no_network")
    return _real_getaddrinfo(host, *args, **kwargs)


def _guarded_gethostbyname(host: str) -> str:
    if _guard.active and host not in LOOPBACK_NAMES:
        raise NetworkBlockedError(f"DNS lookup of {host!r} is blocked by stitch no_network")
    return _real_gethostbyname(host)


def install_guard(*, allow_loopback: bool = False) -> None:
    """Activate the guard. Safe to call twice."""
    _guard.active = True
    _guard.allow_loopback = allow_loopback
    socket.socket = _GuardedSocket  # type: ignore[misc]
    socket.socketpair = _guarded_socketpair
    socket.getaddrinfo = _guarded_getaddrinfo
    socket.gethostbyname = _guarded_gethostbyname


def remove_guard() -> None:
    _guard.active = False
    _guard.allow_loopback = False
    socket.socket = _real_socket  # type: ignore[misc]
    socket.socketpair = _real_socketpair
    socket.getaddrinfo = _real_getaddrinfo
    socket.gethostbyname = _real_gethostbyname


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """Block outbound network for the test (see module docstring)."""
    if request.node.get_closest_marker("live"):
        yield
        return
    install_guard(allow_loopback=request.node.get_closest_marker("allow_loopback") is not None)
    try:
        yield
    finally:
        remove_guard()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "allow_loopback: permit connecting to 127.0.0.1 (HTTP smoke tests)"
    )
    config.addinivalue_line("markers", "live: needs the network; excluded from CI")


def _find_schema_dir() -> Path:
    env = os.environ.get("STITCH_SCHEMA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "schemas"


@pytest.fixture(scope="session")
def schema_dir() -> Path:
    """Directory holding the exported ``*.json`` contract schemas."""
    return _find_schema_dir()


@pytest.fixture(scope="session")
def load_schema(schema_dir: Path) -> Callable[[str], dict[str, Any]]:
    """Return ``f(name)`` that loads ``<schema_dir>/<name>`` as a dict."""
    import json

    def _load(name: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads((schema_dir / name).read_text(encoding="utf-8"))
        return data

    return _load


@pytest.fixture(scope="session")
def contract_schemas() -> dict[str, dict[str, Any]]:
    """Schemas regenerated in memory from the models."""
    from stitch_common.schemas import all_schemas

    return all_schemas()
