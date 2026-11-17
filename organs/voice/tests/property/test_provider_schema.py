"""VOX-P5: swapping TTS providers never changes the ``speak`` output schema. The same request
goes through ``fake``, ``prerendered`` (fixture), ``deepgram`` and ``azure`` (httpx mocks);
every response validates against the exported schema and has the same key set."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import voice_helpers as h
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from stitch_common.organs.voice import SpeakOut
from stitch_voice.providers.azure import AzureTTS
from stitch_voice.providers.base import TTSProvider
from stitch_voice.providers.fake import FakeTTS

TEXTS = {
    "en": ["The Indus at Kotri is above the danger level.", "Move to higher ground now."],
    "ur": ["کوٹری پر دریائے سندھ خطرے کی سطح سے اوپر ہے۔", "فوراً اونچی جگہ پر چلے جائیں۔"],
}


def _providers(lang: str) -> dict[str, Callable[[], list[TTSProvider]]]:
    out: dict[str, Callable[[], list[TTSProvider]]] = {
        "fake": lambda: [FakeTTS()],
        "prerendered": lambda: [],
    }
    if lang == "en":
        out["deepgram"] = lambda: [h.deepgram_tts(h.Recorder([h.wav_response()]))]
    else:
        out["azure"] = lambda: [
            AzureTTS(
                h.KEY, "eastus", client=h.client(h.Recorder([h.wav_response()])), sleep=h.no_sleep
            )
        ]
    return out


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(lang=st.sampled_from(["en", "ur"]), idx=st.integers(min_value=0, max_value=1))
def test_vox_p5_schema_is_provider_independent(
    lang: str, idx: int, voice_env: Path, load_schema: Callable[[str], dict[str, Any]]
) -> None:
    text = TEXTS[lang][idx]
    h.add_prerendered(voice_env / "prerendered", text, lang, f"pre-{lang}")
    validator = Draft202012Validator(load_schema("voice.speak.out.json"))
    keysets = {}
    for name, make in _providers(lang).items():
        res = h.call(h.service(tts=make(), stt=[]), "speak", {"text": text, "lang": lang})
        assert res.ok, (name, res.error)
        assert res.data.provider == name
        payload = res.data.model_dump(mode="json")
        validator.validate(payload)
        SpeakOut.model_validate(payload)
        keysets[name] = frozenset(payload)
    assert len(set(keysets.values())) == 1, keysets
