"""Record (or check) the Brain's LLM replies for the demo scenarios (brain design 12, task 30).

    uv run python -m evals.brain.record_llm --check                       # exit 1 if stale
    uv run python -m evals.brain.record_llm --provider nebius --env-file .env

The Brain runs every demo scenario in English and Urdu with recorded organs. Each LLM request
(``brain.phrase``, ``brain.translate``, ``brain.judge``) goes to the provider through
``RecordingLLM``; the exchanges are written to ``data/demo/llm/brain.jsonl``, which ``FakeLLM``
replays offline. Replayed replies pass the same code checks as live ones (numbers, units,
language, labels), so a bad recording can only fall back to the template text.

``--env-file`` reads only the provider key variables (``NEBIUS_API_KEY``, ``NEBIUS_BASE_URL``,
``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``) into this process; values are never printed.
Recording uses the network and is never run by tests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCENARIOS = ("demo-sindh-2022", "demo-sindh-2022-conflicts")
LANGS = ("en", "ur")
RECORD_TIMEOUT_S = 120.0
KEY_VARS = ("NEBIUS_API_KEY", "NEBIUS_BASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")


def recordings_path() -> Path:
    from stitch_brain.paths import demo_dir

    return demo_dir() / "llm" / "brain.jsonl"


def briefing_id(scenario: str, lang: str) -> str:
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"stitch-brain-demo/{scenario}/{lang}"))


@dataclass
class MatrixRun:
    scenario: str
    lang: str
    result: Any


@dataclass
class CheckReport:
    misses: list[tuple[str, str, str, str]] = field(default_factory=list)  # sc, lang, purpose, key
    runs: list[MatrixRun] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return bool(self.misses)


async def run_matrix(
    llm: Any,
    scenarios: Sequence[str] = SCENARIOS,
    langs: Sequence[str] = LANGS,
    on_run: Any = None,
) -> list[MatrixRun]:
    """One briefing per (scenario, lang) with every organ recorded and phrasing on."""
    from stitch_brain.config import load_scenarios
    from stitch_brain.runtime.registry import OrganRegistry
    from stitch_brain.runtime.runner import BriefingRunner
    from stitch_brain.settings import Settings
    from stitch_common.brain_api import BriefingRequest

    settings = Settings(recorded_organs=("all",), phrase=True, fake_strict=False)
    catalogue = load_scenarios()
    out: list[MatrixRun] = []
    for sc in scenarios:
        for lang in langs:
            if on_run is not None:
                on_run(sc, lang)
            reg = OrganRegistry.build(settings, None)
            runner = BriefingRunner(reg, settings=settings, llm=llm)
            req = BriefingRequest(
                region=catalogue[sc].region,
                scenario=sc,
                lang=lang,  # type: ignore[arg-type]
                mode="demo",
            )
            out.append(MatrixRun(sc, lang, await runner.run(req, briefing_id(sc, lang))))
    return out


def check(
    path: Path | None = None,
    scenarios: Sequence[str] = SCENARIOS,
    langs: Sequence[str] = LANGS,
) -> CheckReport:
    """Replay with ``FakeLLM``; every request the Brain makes must have a recording."""
    from stitch_common.llm import FakeLLM, LLMRequest, LLMResponse, RecordingMissing

    report = CheckReport()
    current: list[str] = ["", ""]

    class Checker(FakeLLM):
        def has(self, req: LLMRequest) -> bool:
            return True  # send every request, so misses are seen (and fall back)

        def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
            try:
                return super().generate(req, timeout_s=timeout_s)
            except RecordingMissing as exc:
                report.misses.append((current[0], current[1], req.purpose, exc.key))
                raise

    def on_run(sc: str, lang: str) -> None:
        current[0], current[1] = sc, lang

    llm = Checker([path or recordings_path()])
    report.runs = asyncio.run(run_matrix(llm, scenarios, langs, on_run))
    return report


def load_env_keys(env_file: Path) -> list[str]:
    """Set the provider key variables from a dotenv file (only those, only if unset)."""
    loaded: list[str] = []
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if name in KEY_VARS and not value:
            print(f"{env_file}: {name} is empty")
        if name in KEY_VARS and value and not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def merge(path: Path, new_lines: list[str], *, replace: bool) -> int:
    """Write new recordings (last reply per key wins), sorted by purpose and key so diffs
    stay readable. ``replace`` drops old lines the current matrix no longer asks for."""
    new: dict[str, str] = {}
    for ln in new_lines:
        if ln.strip():
            new[json.loads(ln)["key"]] = ln
    old: dict[str, str] = {}
    if path.exists() and not replace:
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                old[json.loads(ln)["key"]] = ln
    merged = {**old, **new}

    def sort_key(ln: str) -> tuple[str, str]:
        obj = json.loads(ln)
        return (str(obj.get("purpose")), str(obj["key"]))

    lines = sorted(merged.values(), key=sort_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8", newline="\n")
    return len(lines)


def record(provider: str, model: str | None, path: Path, *, replace: bool) -> int:
    from stitch_common.llm import (
        BaseLLMClient,
        LLMRequest,
        LLMResponse,
        LLMUnavailable,
        RecordingLLM,
        get_llm_client,
        prompt_key,
    )

    inner = get_llm_client(provider, model=model)

    class Memo(BaseLLMClient):
        """One reply per prompt key in a session. Providers are not deterministic even at
        temperature 0; without this, a prompt shared by two runs could be recorded with a
        reply whose follow-up judge prompt was never recorded."""

        def __init__(self) -> None:
            self.provider, self.model = inner.provider, inner.model
            self.seen: dict[str, LLMResponse] = {}

        def generate(self, req: LLMRequest, *, timeout_s: float = 30.0) -> LLMResponse:
            key = prompt_key(req)
            if key not in self.seen:
                # Recording is offline work: allow slow replies and one retry. The live Brain
                # keeps its own 20 s step timeout and falls back to templates.
                try:
                    self.seen[key] = inner.generate(req, timeout_s=RECORD_TIMEOUT_S)
                except LLMUnavailable:
                    self.seen[key] = inner.generate(req, timeout_s=RECORD_TIMEOUT_S)
            return self.seen[key]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "brain.jsonl"
        rec = RecordingLLM(Memo(), tmp_path)
        runs = asyncio.run(run_matrix(rec, on_run=lambda sc, lang: print(f"recording {sc}/{lang}")))
        for r in runs:
            outcomes: dict[str, int] = {}
            for call in r.result.trace.get("llm_calls", []):
                tag = f"{call['purpose']}:{call['outcome']}"
                if call.get("error"):
                    tag += f"({call.get('detail') or call['error']})"
                outcomes[tag] = outcomes.get(tag, 0) + 1
            print(f"  {r.scenario}/{r.lang}: {outcomes}")
        lines = tmp_path.read_text(encoding="utf-8").splitlines() if tmp_path.exists() else []
    n = merge(path, lines, replace=replace)
    print(f"{len(lines)} exchanges recorded; {path} has {n} lines")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.brain.record_llm")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--provider", choices=["nebius", "anthropic", "openai"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--merge", action="store_true", help="keep recordings not re-asked")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    path = args.out or recordings_path()
    if args.check:
        rep = check(path)
        for sc, lang, purpose, key in rep.misses:
            print(f"stale or missing: {sc}/{lang} {purpose} {key}")
        total = sum(len(r.result.trace.get("llm_calls", [])) for r in rep.runs)
        print(f"{total - len(rep.misses)}/{total} brain LLM requests have recordings")
        return 1 if rep.stale else 0
    if args.env_file is not None:
        names = load_env_keys(args.env_file)
        print(f"loaded from {args.env_file}: {', '.join(names) or 'nothing'}")
    return record(args.provider, args.model, path, replace=not args.merge)


if __name__ == "__main__":
    raise SystemExit(main())
