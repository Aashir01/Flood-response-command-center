# ruff: noqa: E501
"""Record (or check) FakeLLM replies for the Library demo questions (design 7.1, task 15).

    uv run python scripts/record_llm_demo.py --show               # print each demo prompt
    uv run python scripts/record_llm_demo.py --check              # exit 1 if a recording is stale
    uv run python scripts/record_llm_demo.py --provider anthropic # live: needs a key (marked live)
    uv run python scripts/record_llm_demo.py --authored FILE      # write reviewed hand-authored replies

Each demo question in ``data/demo/library/demo_questions.yaml`` is asked twice, the way the Brain
asks it (``lang`` set) and the way ``/ask`` asks it (``lang = auto``). The prompt is captured
from the real service (local models, committed pack) at the point where it would call the LLM;
questions that a refusal gate stops never reach the LLM and need no recording.

``--authored FILE``: a YAML mapping ``"<id>/<lang>": <reply JSON object>``. Use it when no API
key is available. The replies were written by a person (or agent) reading the numbered sentences
shown by ``--show``; recordings made this way carry ``model = "hand-authored"`` so they are never
mistaken for model output. Replayed replies go through the same verification as live ones.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "demo" / "library"
QUESTIONS = DATA / "demo_questions.yaml"
RECORDINGS = DATA / "llm_recordings.jsonl"


@dataclass
class Captured:
    qid: str
    lang: str
    lang_param: str
    request: Any  # LLMRequest
    status_without_llm: str


def capture() -> list[Captured]:
    from stitch_common.llm import LLMRequest, RecordingMissing
    from stitch_common.llm.base import BaseLLMClient, LLMResponse
    from stitch_common.organs.library import AnswerWithCitationsIn
    from stitch_library.service import LibraryService

    class Capture(BaseLLMClient):
        provider = "capture"
        model = "capture"

        def __init__(self) -> None:
            self.last: LLMRequest | None = None

        def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
            self.last = req
            raise RecordingMissing(req.cache_key or "", req.purpose)

    svc = LibraryService.from_env()
    cap = Capture()
    svc.llm = cap
    out: list[Captured] = []
    for q in yaml.safe_load(QUESTIONS.read_text(encoding="utf-8")):
        for lang_param in (q["lang"], "auto"):
            cap.last = None
            res = svc.answer(AnswerWithCitationsIn(query=q["query"], lang=lang_param))
            if cap.last is not None:
                status = res.data.status if res.data else "error"
                out.append(Captured(q["id"], q["lang"], lang_param, cap.last, status))
    return out


def recording_line(req: Any, text: str, provider: str, model: str) -> str:
    from stitch_common.llm.base import prompt_key

    return json.dumps(
        {
            "key": prompt_key(req),
            "purpose": req.purpose,
            "request": req.model_dump(mode="json"),
            "response": {"text": text},
            "provider": provider,
            "model": model,
            "recorded_at": datetime.now(UTC).isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--show", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--provider", choices=["anthropic", "openai"])
    group.add_argument("--authored", type=Path)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from stitch_common.llm import load_recordings
    from stitch_common.llm.base import prompt_key

    caps = capture()
    if args.show:
        for c in caps:
            print(f"===== {c.qid}/{c.lang} (lang={c.lang_param}) key={prompt_key(c.request)}")
            print(c.request.messages[-1].content)
        return 0
    have = load_recordings([RECORDINGS]) if RECORDINGS.exists() else {}
    if args.check:
        stale = [c for c in caps if prompt_key(c.request) not in have]
        for c in stale:
            print(f"stale or missing: {c.qid}/{c.lang} (lang={c.lang_param})")
        print(f"{len(caps) - len(stale)}/{len(caps)} demo prompts have recordings")
        return 1 if stale else 0
    lines: list[str] = []
    if args.authored is not None:
        replies = yaml.safe_load(args.authored.read_text(encoding="utf-8"))
        for c in caps:
            reply = replies.get(f"{c.qid}/{c.lang}")
            if reply is None:
                print(f"no authored reply for {c.qid}/{c.lang}; skipped")
                continue
            text = json.dumps(reply, ensure_ascii=False)
            lines.append(recording_line(c.request, text, "fake", "hand-authored"))
    else:
        from stitch_common.llm import get_llm_client

        client = get_llm_client(args.provider)
        for c in caps:
            resp = client.generate(c.request, timeout_s=30.0)
            lines.append(recording_line(c.request, resp.text, resp.provider, resp.model))
    unique: dict[str, str] = {}
    for ln in lines:  # the Brain-style and /ask-style prompts often share one key
        unique[json.loads(ln)["key"]] = ln
    lines = list(unique.values())
    keep = {prompt_key(c.request) for c in caps}
    old = [
        ln
        for ln in (
            RECORDINGS.read_text(encoding="utf-8").splitlines() if RECORDINGS.exists() else []
        )
        if ln.strip() and json.loads(ln)["key"] not in keep
    ]
    RECORDINGS.write_text("\n".join([*old, *lines]) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} recordings to {RECORDINGS.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
