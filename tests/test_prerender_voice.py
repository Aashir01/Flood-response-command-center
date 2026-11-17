"""scripts/prerender_voice.py: env loading never echoes values, the committed scripts exist,
rendering with the ``fake`` provider writes an index the prerendered store can serve, and Urdu is
skipped when no Urdu voice is configured (voice task 8)."""

from __future__ import annotations

import json
from pathlib import Path

import prerender_voice as pv
import pytest

# Urdu: the water is rising (escaped to keep the Arabic full stop out of ruff's RUF001).
UR = "\u067e\u0627\u0646\u06cc \u0628\u0691\u06be \u0631\u06c1\u0627 \u06c1\u06d2\u06d4"


@pytest.fixture(autouse=True)
def _voice_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in pv.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STITCH_STT_PROVIDER", "fake")
    monkeypatch.setenv("STITCH_VOICE_CACHE_DIR", str(tmp_path / "cache"))


def test_committed_scripts_exist_and_fit_speak() -> None:
    scripts = pv.read_scripts()
    assert set(scripts) == {"en", "ur"}
    assert all(0 < len(t) <= 4000 for t in scripts.values())


def test_env_file_loads_only_voice_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env = tmp_path / ".env"
    env.write_text('DEEPGRAM_API_KEY="dg-secret-value"\nOTHER=1\nAZURE_SPEECH_KEY=\n', "utf-8")
    monkeypatch.delenv("OTHER", raising=False)
    assert pv.load_env_file(env) == ["DEEPGRAM_API_KEY"]
    import os

    assert os.environ["DEEPGRAM_API_KEY"] == "dg-secret-value" and "OTHER" not in os.environ
    assert "dg-secret-value" not in capsys.readouterr().out


def test_render_with_fake_writes_a_servable_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STITCH_TTS_PROVIDER", "fake")
    out = tmp_path / "prerendered"
    scripts = {"en": "The river is rising.", "ur": UR}
    assert pv.render(scripts, out, dry_run=False) == 0
    entries = json.loads((out / "index.json").read_text("utf-8"))["entries"]
    assert {e["lang"] for e in entries} == {"en", "ur"}
    assert all((out / e["file"]).is_file() for e in entries)
    # Re-rendering replaces entries instead of duplicating them.
    assert pv.render(scripts, out, dry_run=False) == 0
    assert len(json.loads((out / "index.json").read_text("utf-8"))["entries"]) == 2

    from stitch_voice.providers.prerendered import PrerenderedStore

    hit = PrerenderedStore(out).lookup("The river is rising.", "en")
    assert hit.source_provider == "fake" and hit.wav[:4] == b"RIFF"


def test_urdu_is_skipped_without_an_urdu_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("STITCH_TTS_PROVIDER", "deepgram")  # no key: nothing can speak
    out = tmp_path / "prerendered"
    assert pv.render({"ur": UR}, out, dry_run=False) == 0
    assert "Urdu needs AZURE_SPEECH_KEY" in capsys.readouterr().out
    assert not (out / "index.json").exists()


def test_dry_run_calls_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STITCH_TTS_PROVIDER", "fake")
    out = tmp_path / "prerendered"
    assert pv.render({"en": "Hello."}, out, dry_run=True) == 0
    assert not out.exists()
