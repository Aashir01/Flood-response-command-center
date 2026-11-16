"""BOOT-R2.4: the no_network guard, including Windows asyncio and stdio subprocess behaviour."""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from hypothesis import settings

from stitch_common.testing.plugin import NetworkBlockedError


def test_external_connect_is_blocked() -> None:
    # A documentation-range address: if the guard failed this would try a real connect.
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    with pytest.raises(NetworkBlockedError):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("192.0.2.1", 80))
        finally:
            s.close()


def test_udp_sendto_is_blocked() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(NetworkBlockedError):
            s.sendto(b"x", ("192.0.2.1", 53))
    finally:
        s.close()


def test_dns_is_blocked() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 80)
    with pytest.raises(NetworkBlockedError):
        socket.gethostbyname("example.com")


def _listener() -> socket.socket:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv


def test_loopback_blocked_without_marker() -> None:
    srv = _listener()
    try:
        with pytest.raises(NetworkBlockedError):
            socket.create_connection(srv.getsockname(), timeout=1)
    finally:
        srv.close()


@pytest.mark.allow_loopback
def test_loopback_allowed_with_marker() -> None:
    srv = _listener()
    try:
        cli = socket.create_connection(srv.getsockname(), timeout=2)
        conn, _ = srv.accept()
        cli.sendall(b"hi")
        assert conn.recv(2) == b"hi"
        cli.close()
        conn.close()
    finally:
        srv.close()


@pytest.mark.allow_loopback
def test_marker_does_not_open_external_hosts() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=1)


def test_socketpair_allowed() -> None:
    a, b = socket.socketpair()
    try:
        a.sendall(b"x")
        assert b.recv(1) == b"x"
    finally:
        a.close()
        b.close()
    # and the loopback exception does not leak out of socketpair()
    srv = _listener()
    try:
        with pytest.raises(NetworkBlockedError):
            socket.create_connection(srv.getsockname(), timeout=1)
    finally:
        srv.close()


def test_asyncio_new_loop_works() -> None:
    async def main() -> int:
        await asyncio.sleep(0.01)
        return 7

    assert asyncio.run(main()) == 7


async def test_asyncio_native_async_test_works() -> None:
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, lambda: 3)
    assert await fut == 3


async def test_asyncio_subprocess_stdio_pipes() -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys; sys.stdout.write(sys.stdin.readline().upper())",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate(b"ping\n")
    assert out.strip() == b"PING"


def test_subprocess_stdio_pipe_roundtrip() -> None:
    res = subprocess.run(
        [sys.executable, "-c", "print(input()[::-1])"],
        input="abc\n",
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert res.stdout.strip() == "cba"


def test_default_hypothesis_profile_is_dev() -> None:
    assert settings().max_examples == 30


def test_plugin_autoloads_in_fresh_pytest_run(tmp_path: Path) -> None:
    """Entry point registers the plugin: guard on, ci profile selectable, live opt-out."""
    (tmp_path / "test_probe.py").write_text(
        textwrap.dedent(
            """
            import socket, pytest
            from hypothesis import settings

            def test_blocked():
                with pytest.raises(Exception) as e:
                    socket.create_connection(("192.0.2.1", 80), timeout=1)
                assert "no_network" in str(e.value)

            def test_ci_profile():
                assert settings().max_examples == 200 and settings().deadline is None

            @pytest.mark.live
            def test_live_not_guarded():
                assert socket.socket is socket.socket  # guard removed; no exception raised here
                import stitch_common.testing.plugin as p
                assert socket.socket is p._real_socket
            """
        ),
        encoding="utf-8",
    )
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--hypothesis-profile=ci",
            str(tmp_path / "test_probe.py"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "3 passed" in res.stdout
