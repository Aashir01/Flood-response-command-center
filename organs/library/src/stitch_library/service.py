"""The Library service: wires store, models, calibration and LLM to the two tools.

``LibraryService.from_env()`` builds the configured service (``STITCH_LIBRARY_STORE=memory``
loads the committed pack directly). Tests build services from parts. The tool functions
``search`` and ``answer`` return ``Outcome`` objects for ``stitch_common.tooling.run_tool`` and
raise ``ToolFailure`` only for ``INVALID_INPUT`` and ``UPSTREAM_UNAVAILABLE`` (design 9.1). A
refusal is a valid ``ok: true`` result.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import yaml

from stitch_common.llm import LLMClient, LLMRequest, LLMUnavailable, Message, RecordingMissing
from stitch_common.llm import get_llm_client as _get_llm_client
from stitch_common.organs.library import (
    AnswerWithCitationsIn,
    AnswerWithCitationsOut,
    Generation,
    Hit,
    SearchGuidanceIn,
    SearchGuidanceOut,
)
from stitch_common.organs.library import (
    Filters as ContractFilters,
)
from stitch_common.provenance import DataSource, ModelInfo
from stitch_common.tooling import Outcome, ToolFailure
from stitch_common.types import Citation
from stitch_library.calibration import Calibration, load_calibration, profile_key
from stitch_library.core.answer import (
    DraftClaim,
    Support,
    assemble_answer,
    refusal,
    verify_claims,
)
from stitch_library.core.citations import make_citation
from stitch_library.core.conflict import SentenceRef, detect_conflict
from stitch_library.core.context import REPLY_SCHEMA, ReplyInvalid, build_prompt, parse_reply
from stitch_library.core.decide import Signals, decide
from stitch_library.core.extractive import extractive_claims, sentence_candidates
from stitch_library.core.lang import detect_query_lang
from stitch_library.core.normalize import clean_query
from stitch_library.core.retrieve import RetrievalResult, Retriever, ScoredHit
from stitch_library.core.scope import (
    is_quantity_query,
    quantity_supported,
    scope_score,
    states_quantity,
)
from stitch_library.ml.embedder import Embedder, FakeEmbedder, ModelUnavailable, load_embedder
from stitch_library.ml.reranker import NullReranker, Reranker, load_reranker
from stitch_library.settings import Settings
from stitch_library.store.base import Filters, Store, StoreError, Vectors
from stitch_library.store.memory import MemoryStore

log = logging.getLogger("stitch.library")

MAX_QUERY = 1000
MAX_FILTER_ITEMS = 20
MAX_FILTER_LEN = 100
TOP_EVIDENCE = 3
DEFAULT_TOP_K = 8


@dataclass
class LibraryService:
    store: Store
    embedder: Embedder
    reranker: Reranker
    llm: LLMClient | None
    calibration: Calibration
    anchors: Vectors
    settings: Settings = field(default_factory=Settings)
    startup_warnings: list[str] = field(default_factory=list)
    retriever: Retriever = field(init=False)

    def __post_init__(self) -> None:
        self.retriever = Retriever(
            self.store, self.embedder, self.reranker, rerank_langs=self.settings.rerank_langs
        )

    # construction ------------------------------------------------------------------------
    @classmethod
    def build(
        cls,
        store: Store,
        embedder: Embedder,
        reranker: Reranker,
        *,
        llm: LLMClient | None = None,
        settings: Settings | None = None,
        calibration: Calibration | None = None,
        anchor_phrases: Sequence[str] | None = None,
        startup_warnings: Sequence[str] = (),
    ) -> LibraryService:
        settings = settings or Settings()
        phrases = (
            list(anchor_phrases) if anchor_phrases is not None else load_anchor_phrases(settings)
        )
        anchors = embedder.embed_queries(phrases) if phrases else np.zeros((0, 0), dtype=np.float32)
        cal = calibration or load_calibration(profile_key(embedder.model_id, reranker.model_id))
        warnings = list(startup_warnings)
        if cal.warning:
            warnings.append(cal.warning)
            log.error("calibration %s for profile %s", cal.status, cal.key)
        return cls(store, embedder, reranker, llm, cal, anchors, settings, warnings)

    @classmethod
    def from_env(cls) -> LibraryService:
        from stitch_library.pack import load_into_store, load_pack

        settings = Settings.from_env()
        warnings: list[str] = []
        try:
            embedder = load_embedder(
                settings.embed_model, settings.model_dir, threads=settings.threads
            )
        except ModelUnavailable as exc:
            log.error("embedder unavailable (%s); falling back to the lexical test embedder", exc)
            embedder = FakeEmbedder()
            warnings.append("EMBEDDER_FALLBACK")
        try:
            reranker = load_reranker(
                settings.rerank_model, settings.model_dir, threads=settings.threads
            )
        except ModelUnavailable as exc:
            log.warning("reranker unavailable (%s); results carry rerank = null", exc)
            reranker = NullReranker()
            if settings.rerank_model not in ("none", ""):
                warnings.append("RERANKER_UNAVAILABLE")
        pack = load_pack(settings.pack_dir)
        store: Store
        if settings.store == "pgvector":
            from stitch_library.store.pgvector import PgVectorStore
            from stitch_library.store.seed import seed

            if not settings.dsn:
                raise StoreError("STITCH_LIBRARY_STORE=pgvector needs STITCH_LIBRARY_DSN")
            pg = PgVectorStore(settings.dsn)
            warnings += seed(pg, pack, embedder)
            store = pg
        else:
            store = MemoryStore()
            warnings += load_into_store(store, pack, embedder)
        llm: LLMClient | None = None
        try:
            llm = _get_llm_client(settings.llm_provider, recordings=[settings.recordings])
        except ValueError as exc:
            log.error("LLM provider: %s", exc)
        return cls.build(
            store, embedder, reranker, llm=llm, settings=settings, startup_warnings=warnings
        )

    # helpers ------------------------------------------------------------------------------
    def model_infos(self) -> list[ModelInfo]:
        out = [
            ModelInfo(
                name=self.embedder.name, version=self.embedder.revision, sha256=self.embedder.sha256
            )
        ]
        if self.reranker.active:
            out.append(
                ModelInfo(
                    name=self.reranker.name,
                    version=self.reranker.revision,
                    sha256=self.reranker.sha256,
                )
            )
        return out

    def _data_sources(self, doc_ids: Sequence[str]) -> list[DataSource]:
        docs = self.store.get_documents(sorted(set(doc_ids)))
        return [
            DataSource(id=d.doc_id, name=d.title, license=d.license, as_of=d.as_of) for d in docs
        ]

    def _filters(self, f: ContractFilters | None) -> Filters:
        if f is None:
            return Filters()
        out: dict[str, frozenset[str] | None] = {}
        for name in ("publisher", "doc_type", "lang", "doc_id"):
            vals = getattr(f, name)
            if vals is None:
                out[name] = None
                continue
            if len(vals) > MAX_FILTER_ITEMS or any(len(v) > MAX_FILTER_LEN for v in vals):
                raise ToolFailure(
                    "INVALID_INPUT", f"filters.{name}: at most 20 values of 100 chars"
                )
            out[name] = frozenset(vals)
        return Filters(**out)

    def _query(self, raw: str) -> str:
        q = clean_query(raw)
        if not q:
            raise ToolFailure("INVALID_INPUT", "query is empty after normalization")
        if len(q) > MAX_QUERY:
            raise ToolFailure("INVALID_INPUT", f"query longer than {MAX_QUERY} characters")
        return q

    def _embed(self, q: str) -> Vectors:
        try:
            vec: Vectors = self.embedder.embed_queries([q])[0]
        except Exception as exc:
            log.exception("query embedding failed")
            raise ToolFailure("UPSTREAM_UNAVAILABLE", "embedding model failed", True) from exc
        return vec

    def _retrieve(
        self, q: str, lang: str | None, top_k: int, flt: Filters, qvec: Vectors
    ) -> RetrievalResult:
        try:
            return self.retriever.search(q, lang=lang, top_k=top_k, flt=flt, qvec=qvec)
        except StoreError as exc:
            raise ToolFailure("UPSTREAM_UNAVAILABLE", "document store unavailable", True) from exc

    def _log_query(self, tool: str, q: str) -> None:
        if self.settings.log_queries:
            log.info("%s query", tool, extra={"query": q})
        else:
            digest = hashlib.sha256(q.encode("utf-8")).hexdigest()[:12]
            log.info("%s query", tool, extra={"query_sha": digest, "query_len": len(q)})

    def _warnings(self, extra: Sequence[str]) -> list[str]:
        seen: list[str] = []
        for w in [*self.startup_warnings, *extra]:
            if w not in seen:
                seen.append(w)
        return seen

    def _outcome(self, data: Any, doc_ids: Sequence[str], warnings: Sequence[str]) -> Outcome[Any]:
        models = self.model_infos()
        return Outcome(
            data,
            warnings=self._warnings(warnings),
            data_sources=self._data_sources(doc_ids),
            model=models[0],
            models=models,
            mode="demo",
        )

    # search_guidance ----------------------------------------------------------------------
    def search(self, params: SearchGuidanceIn) -> Outcome[SearchGuidanceOut]:
        q = self._query(params.query)
        self._log_query("search_guidance", q)
        flt = self._filters(params.filters)
        lang = params.lang if params.lang in ("en", "ur") else None
        res = self._retrieve(q, lang, params.top_k, flt, self._embed(q))
        hits = [
            Hit(
                doc_id=h.chunk.doc_id,
                page=h.chunk.page,
                score=h.score,
                bm25=h.bm25,
                dense=h.dense,
                rerank=h.rerank,
                text=h.chunk.text,
                lang=h.chunk.lang,
                chunk_id=h.chunk.chunk_id,
                span=(h.chunk.start, h.chunk.end),
                title=h.doc.title,
                publisher=h.doc.publisher,
            )
            for h in res.hits
        ]
        return self._outcome(SearchGuidanceOut(hits=hits), [h.doc_id for h in hits], res.warnings)

    # answer_with_citations ----------------------------------------------------------------
    def _closest(self, q: str, hits: Sequence[ScoredHit]) -> list[Citation]:
        out: list[Citation] = []
        for h in hits[:TOP_EVIDENCE]:
            cands = sentence_candidates(q, [h.chunk])
            if not cands:
                continue
            best = max(cands, key=lambda c: (c.overlap, -c.rank))
            page = self.store.get_page(h.chunk.doc_id, h.chunk.page)
            if page is not None:
                out.append(make_citation(h.doc, page, best.start, best.end))
        return out

    def _sentence_refs(self, q: str, hits: Sequence[ScoredHit]) -> list[SentenceRef]:
        refs: list[SentenceRef] = []
        for h in hits[:TOP_EVIDENCE]:
            for c in sentence_candidates(q, [h.chunk]):
                refs.append(
                    SentenceRef(
                        h.chunk.doc_id, h.chunk.chunk_id, h.chunk.page, c.start, c.end, c.text
                    )
                )
        return refs

    def _cite_refs(self, refs: Sequence[SentenceRef]) -> list[Citation]:
        out: list[Citation] = []
        for r in refs:
            page = self.store.get_page(r.doc_id, r.page)
            docs = self.store.get_documents([r.doc_id])
            if page is not None and docs:
                out.append(make_citation(docs[0], page, r.start, r.end))
        return out

    def answer(self, params: AnswerWithCitationsIn) -> Outcome[AnswerWithCitationsOut]:
        q = self._query(params.query)
        self._log_query("answer_with_citations", q)
        qlang = detect_query_lang(q)
        answer_lang = params.answer_lang or (params.lang if params.lang in ("en", "ur") else qlang)
        lang = params.lang if params.lang in ("en", "ur") else None
        qvec = self._embed(q)
        s_score = scope_score(qvec, self.anchors)
        res = self._retrieve(q, lang, params.top_k or DEFAULT_TOP_K, Filters(), qvec)
        warnings = list(res.warnings)
        evidence_scorer = "rerank" if res.scorer == "rerank" else "dense"
        th = self.calibration.thresholds(res.qlang, evidence_scorer)
        top = res.hits[:TOP_EVIDENCE]
        refs = self._sentence_refs(q, top)
        quantity_q = is_quantity_query(q)
        conflict = detect_conflict(q, refs) if self.settings.conflict_policy == "refuse" else None
        signals = Signals(
            scope_score=s_score,
            evidence_score=res.evidence_score,
            quantity_query=quantity_q,
            quantity_supported=quantity_supported(q, [r.text for r in refs])
            if quantity_q
            else True,
            conflict=conflict is not None,
        )
        verdict = decide(signals, th)
        doc_ids = [h.chunk.doc_id for h in top]
        if not verdict.proceed:
            assert verdict.reason is not None
            if verdict.reason == "OUT_OF_SCOPE":
                closest: list[Citation] = []
            elif verdict.reason == "CONFLICTING_EVIDENCE" and conflict is not None:
                closest = self._cite_refs([conflict.a, conflict.b])
                doc_ids = [conflict.a.doc_id, conflict.b.doc_id]
            else:
                closest = self._closest(q, top)
            warnings.append(f"REFUSED:{verdict.gate}")
            return self._outcome(refusal(verdict.reason, closest, None), doc_ids, warnings)

        # Chunks that individually pass the evidence gate feed generation.
        def chunk_score(h: ScoredHit) -> float:
            return h.rerank if (h.rerank is not None and evidence_scorer == "rerank") else h.dense

        passing = [h for h in res.hits if chunk_score(h) >= th.tau_evid] or top[:1]
        closest = self._closest(q, top)
        result, gen_warnings = self._generate(q, answer_lang, passing, closest)
        warnings += gen_warnings
        used = {c.doc_id for c in result.citations} or set(doc_ids)
        return self._outcome(result, sorted(used), warnings)

    def _generate(
        self, q: str, answer_lang: str, hits: Sequence[ScoredHit], closest: Sequence[Citation]
    ) -> tuple[AnswerWithCitationsOut, list[str]]:
        warnings: list[str] = []
        reason = "no_llm"
        if self.llm is not None:
            prompt = build_prompt(q, answer_lang, [(h.chunk, h.doc) for h in hits])
            warnings += [f"INJECTION_SUSPECT:{cid}" for cid in prompt.suspects]
            req = LLMRequest(
                purpose="library.answer",
                system=prompt.system,
                messages=(Message(role="user", content=prompt.user),),
                max_tokens=700,
                temperature=0.0,
                response_format=REPLY_SCHEMA,
                cache_key=prompt.cache_key,
            )
            try:
                resp = self.llm.generate(req, timeout_s=self.settings.llm_timeout_s)
                reply = parse_reply(resp.text)
            except RecordingMissing:
                reason = "no_recording"
            except LLMUnavailable:
                reason = "llm_unavailable"
            except ReplyInvalid:
                reason = "invalid_reply"
            else:
                gen = Generation(mode="llm", provider=resp.provider, model=resp.model)
                if reply.insufficient:
                    warnings.append("LLM_INSUFFICIENT")
                    return refusal("INSUFFICIENT_EVIDENCE", closest, gen), warnings
                if reply.conflict:
                    warnings.append("LLM_CONFLICT")
                    return refusal("CONFLICTING_EVIDENCE", closest, gen), warnings
                drafts: list[DraftClaim] = []
                for i, claim in enumerate(reply.claims):
                    sups: list[Support] = []
                    for s in claim.support:
                        ps = prompt.sentences.get((s.chunk, s.sentence))
                        if ps is None:
                            sups = []
                            break
                        sups.append(Support(ps.chunk.doc_id, ps.chunk.page, ps.start, ps.end))
                    if not sups:
                        warnings.append(f"CLAIM_DROPPED:{i}:resolve")
                        continue
                    drafts.append(DraftClaim(claim.text, tuple(sups)))
                ver = verify_claims(drafts, self.store.get_page, self._doc)
                warnings += ver.warnings
                return assemble_answer(ver.claims, closest, gen), warnings
        if self.settings.require_llm:
            raise ToolFailure(
                "UPSTREAM_UNAVAILABLE", f"LLM required but unavailable ({reason})", True
            )
        warnings.append(f"EXTRACTIVE_FALLBACK:{reason}")
        # Sentences are scored by query-term overlap, not the cross-encoder: one rerank call per
        # sentence costs about 0.1 s on 2 vCPU (task 21).
        prefer = (lambda s: states_quantity(q, s)) if is_quantity_query(q) else None
        drafts = extractive_claims(q, [h.chunk for h in hits], prefer=prefer)
        ver = verify_claims(drafts, self.store.get_page, self._doc)
        warnings += ver.warnings
        gen = Generation(mode="extractive", provider="none", model=None)
        return assemble_answer(ver.claims, closest, gen), warnings

    def _doc(self, doc_id: str) -> Any:
        docs = self.store.get_documents([doc_id])
        return docs[0] if docs else None

    # health -------------------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        stats = self.store.stats()
        db_ok = self.store.ping()
        return {
            "store": self.store.kind,
            "db_ok": db_ok,
            "seeded": self.store.get_meta("seed_key") is not None or self.store.kind == "memory",
            "seed_key": self.store.get_meta("seed_key"),
            "docs": stats.docs,
            "docs_by_tier": stats.docs_by_tier,
            "chunks": stats.chunks,
            "readable_page_ratio": round(stats.readable_page_ratio, 4),
            "bm25_fingerprint": self.retriever.fingerprint,
            "bm25_chunks": len(self.retriever.rows),
            "embedder": {
                "id": self.embedder.model_id,
                "loaded": "EMBEDDER_FALLBACK" not in self.startup_warnings,
            },
            "reranker": {"id": self.reranker.model_id, "loaded": self.reranker.active},
            "calibration": self.calibration.status,
            "llm_provider": getattr(self.llm, "provider", "none"),
            "warnings": list(self.startup_warnings),
        }

    def health_checks(self) -> dict[str, bool]:
        h = self.health()
        return {
            "db": bool(h["db_ok"]),
            "index_nonempty": h["chunks"] > 0,
            "embedder_loaded": "EMBEDDER_FALLBACK" not in self.startup_warnings,
        }


_SERVICE: LibraryService | None = None
_LOCK = threading.Lock()


def get_service() -> LibraryService:
    """The process-wide service, built from the environment on first use."""
    global _SERVICE
    with _LOCK:
        if _SERVICE is None:
            try:
                _SERVICE = LibraryService.from_env()
            except (StoreError, OSError) as exc:
                log.exception("library service failed to start")
                raise ToolFailure("UPSTREAM_UNAVAILABLE", "library index not ready", True) from exc
        return _SERVICE


def set_service(service: LibraryService | None) -> None:
    """Install a service (tests) or clear it (``None``)."""
    global _SERVICE
    with _LOCK:
        _SERVICE = service


def load_anchor_phrases(settings: Settings) -> list[str]:
    path = settings.anchors_path
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(p) for lang in ("en", "ur") for p in data.get(lang, [])]
