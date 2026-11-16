"""Claim model projection and the shared FakeLLM contract the Brain relies on (task 2)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from stitch_brain.core.claims import ClaimDraft, Slot, id_token
from stitch_common.llm import FakeLLM, LLMRequest, Message, RecordingMissing, prompt_key
from stitch_common.types import EvidenceRef

REF = EvidenceRef(run_id="r", organ="ledger", tool="optimize_allocation", json_pointer="/data")


def test_claim_projection_dedupes_refs_and_orders_labels() -> None:
    c = ClaimDraft(
        id="allocation.summary",
        section="allocation",
        kind="number",
        template_id="allocation.summary",
        slots={"n": Slot(name="n", value=Decimal(3), fmt="int", refs=[REF])},
        evidence=[REF, REF],
        final_text="x",
        labels=["disputed", "demo"],
    )
    claim = c.to_contract()
    assert claim.evidence == [REF]
    assert claim.labels == ["demo", "disputed"]


def test_id_token() -> None:
    assert id_token("pk-sindh-dadu") == "pk_sindh_dadu"
    assert id_token("///") == "x"


def _req(text: str = "hello") -> LLMRequest:
    return LLMRequest(
        purpose="brain.phrase", system="s", messages=(Message(role="user", content=text),)
    )


def test_prompt_key_is_stable_and_provider_free() -> None:
    assert prompt_key(_req()) == prompt_key(_req())
    assert prompt_key(_req()) != prompt_key(_req("other"))


def test_fakellm_replays_by_key_and_raises_on_miss(tmp_path: Path) -> None:
    rec = tmp_path / "brain.jsonl"
    rec.write_text(
        json.dumps({"key": prompt_key(_req()), "response": {"text": "{}"}}) + "\n",
        encoding="utf-8",
    )
    fake = FakeLLM(rec)
    assert fake.generate(_req()).text == "{}"
    with pytest.raises(RecordingMissing):
        fake.generate(_req("miss"))
