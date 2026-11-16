"""Recording tool: wrap a real client, append every exchange to a JSONL file for ``FakeLLM``.

    rec = RecordingLLM(ClaudeClient(), Path("data/demo/library/llm_recordings.jsonl"))
    rec.generate(req)                         # calls Claude, appends one line

    python -m stitch_common.llm.recording check FILE [FILE ...]   # validate line format
    python -m stitch_common.llm.recording keys FILE                # list keys and purposes

Lines are ``{key, purpose, request, response: {text}, provider, model, recorded_at}``. Review
recordings like code before committing them; consumers verify replayed output like live output.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from stitch_common.llm.base import BaseLLMClient, LLMClient, LLMRequest, LLMResponse, prompt_key
from stitch_common.llm.fake import load_recordings


def recording_line(req: LLMRequest, resp: LLMResponse) -> str:
    obj = {
        "key": prompt_key(req),
        "purpose": req.purpose,
        "request": req.model_dump(mode="json"),
        "response": {"text": resp.text},
        "provider": resp.provider,
        "model": resp.model,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


class RecordingLLM(BaseLLMClient):
    """Delegates to ``inner`` and appends each successful exchange to ``path``."""

    def __init__(self, inner: LLMClient, path: Path) -> None:
        self.inner = inner
        self.path = path
        self.provider = inner.provider
        self.model = inner.model

    def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
        resp = self.inner.generate(req, timeout_s=timeout_s)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(recording_line(req, resp) + "\n")
        return resp


def stale_keys(paths: Iterable[Path], requests: Iterable[LLMRequest]) -> list[str]:
    """Keys of ``requests`` that have no recording in ``paths`` (sorted, unique)."""
    have = load_recordings(list(paths))
    return sorted({prompt_key(r) for r in requests} - set(have))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stitch_common.llm.recording")
    parser.add_argument("command", choices=["check", "keys"])
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        recs = load_recordings(args.files)
    except ValueError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    if args.command == "keys":
        for rec in recs.values():
            print(f"{rec.key}  {rec.purpose or '-'}  {rec.model}")
    else:
        print(f"ok: {len(recs)} recordings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
