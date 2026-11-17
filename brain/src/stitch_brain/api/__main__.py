"""``python -m stitch_brain.api --host 0.0.0.0 --port 8000`` (the Compose entry point)."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    from stitch_brain.api.app import create_app

    parser = argparse.ArgumentParser(prog="stitch_brain.api", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)
    uvicorn.run(
        create_app(),
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        proxy_headers=False,  # the rate limiter reads X-Forwarded-For only if trusted
        access_log=False,  # no query strings (questions, pointers) in logs
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
