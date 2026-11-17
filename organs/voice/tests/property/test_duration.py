"""VOX-P1: ``speak`` duration is > 0 and non-decreasing when sentences are appended
(same language and voice; tolerance 50 ms). Provider ``fake``."""

from __future__ import annotations

import voice_helpers as h
from hypothesis import given, settings
from hypothesis import strategies as st

from stitch_voice.providers.fake import FakeTTS

EN = [
    "The river is rising.",
    "Move to higher ground.",
    "Kotri barrage reads 450,000 m3/s.",
    "Boil water before drinking.",
    "Dadu district is cut off by road.",
]
UR = [
    "دریا کا پانی بڑھ رہا ہے۔",
    "اونچی جگہ پر چلے جائیں۔",
    "پانی ابال کر پئیں۔",
    "دادو کی سڑکیں بند ہیں۔",
]

sentences = st.one_of(
    st.tuples(st.just("en"), st.lists(st.sampled_from(EN), min_size=1, max_size=6)),
    st.tuples(st.just("ur"), st.lists(st.sampled_from(UR), min_size=1, max_size=6)),
)


@settings(deadline=None)
@given(sentences, st.integers(min_value=1, max_value=3))
def test_vox_p1_duration_positive_and_monotone(case: tuple[str, list[str]], extra: int) -> None:
    lang, parts = case
    pool = EN if lang == "en" else UR
    svc = h.service(tts=[FakeTTS()], stt=[])
    prefix = " ".join(parts)
    longer = " ".join([*parts, *pool[:extra]])
    a = h.call(svc, "speak", {"text": prefix, "lang": lang})
    b = h.call(svc, "speak", {"text": longer, "lang": lang})
    assert a.ok and b.ok
    assert a.data.duration_s > 0
    assert b.data.duration_s + 0.05 >= a.data.duration_s
