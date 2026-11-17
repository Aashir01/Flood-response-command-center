'use client';
// Owns the pure bench reducer plus the side effects around it: health, run lifecycle, SSE, tool documents.
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react';
import { api, eventsUrl } from '@/api/client';
import { openEventStream, type SseHandle } from '@/api/sse';
import type { ApiError, BriefingRequest, Lang, Mode, OrganList, ToolEnvelope } from '@/api/types';
import { KEYS, readJson, writePref } from '@/lib/storage';
import { benchReducer, initialState, type BenchAction, type BenchState } from './benchReducer';

export type StreamStatus = 'idle' | 'open' | 'reconnecting' | 'lost';
export interface DocEntry {
  status: 'loading' | 'ok' | 'error';
  doc?: ToolEnvelope<unknown>;
  error?: ApiError;
}
export interface RunRequest {
  region: string;
  scenario: string;
  mode: Mode;
}

interface BenchCtx {
  state: BenchState;
  dispatch: (a: BenchAction) => void;
  health: OrganList | null;
  healthStatus: 'loading' | 'ok' | 'failed';
  retryHealth: () => Promise<boolean>;
  start: (req: RunRequest, lang?: Lang) => Promise<void>;
  cancel: () => Promise<void>;
  resume: () => void;
  stream: StreamStatus;
  reconnectAttempt: number;
  lastRequest: (BriefingRequest & { id?: string }) | null;
  /** Increments each time a live run delivers its briefing (drives the short awakening). */
  completions: number;
  docs: Record<string, DocEntry>;
  ensureDoc: (runId: string) => void;
}
const Ctx = createContext<BenchCtx | null>(null);

/** Tools whose whole output feeds charts, the map and tables (design section 4.3). */
export const DOC_TOOLS = new Set([
  'segment_flood',
  'compare_with_permanent_water',
  'forecast_river',
  'answer_with_citations',
  'optimize_allocation',
  'sensitivity_report',
  'resource:districts',
  'resource:ledger.districts',
]);

interface StoredRun {
  id: string;
  request: BriefingRequest;
}

export function BenchProvider({ lang, children, autoHealth = true }: { lang: Lang; children: ReactNode; autoHealth?: boolean }) {
  const [state, dispatch] = useReducer(benchReducer, undefined, initialState);
  const [health, setHealth] = useState<OrganList | null>(null);
  const [healthStatus, setHealthStatus] = useState<'loading' | 'ok' | 'failed'>('loading');
  const [stream, setStream] = useState<StreamStatus>('idle');
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [lastRequest, setLastRequest] = useState<(BriefingRequest & { id?: string }) | null>(null);
  const [completions, setCompletions] = useState(0);
  const [docs, setDocs] = useState<Record<string, DocEntry>>({});
  const sse = useRef<SseHandle | null>(null);
  const runId = useRef<string | null>(null);
  const lastSeq = useRef(0);
  const restoring = useRef(false);
  /** Run ids already requested (a ref, so ensureDoc stays stable). */
  const docsRef = useRef<Record<string, DocEntry>>({});

  const retryHealth = useCallback(async () => {
    const r = await api.getOrgans();
    if (r.ok) {
      setHealth(r.value);
      setHealthStatus('ok');
      dispatch({ type: 'HEALTH', organs: r.value.organs });
      return true;
    }
    setHealthStatus('failed');
    dispatch({ type: 'HEALTH_FAILED' });
    return false;
  }, []);

  const ensureDoc = useCallback((id: string) => {
    if (docsRef.current[id]) return;
    docsRef.current = { ...docsRef.current, [id]: { status: 'loading' } };
    setDocs((d) => ({ ...d, [id]: { status: 'loading' } }));
    void api.getToolResult(id).then((r) => {
      setDocs((d) => ({ ...d, [id]: r.ok ? { status: 'ok', doc: r.value } : { status: 'error', error: r.error } }));
    });
  }, []);

  const attach = useCallback(
    (id: string, fromSeq: number) => {
      sse.current?.close();
      setStream('open');
      setReconnectAttempt(0);
      sse.current = openEventStream({
        initialSeq: fromSeq,
        makeUrl: (seq) => eventsUrl(id, seq),
        onEvent: (seq, event) => {
          lastSeq.current = Math.max(lastSeq.current, seq);
          setReconnectAttempt(0);
          setStream('open');
          dispatch({ type: 'EVENT', seq, event });
          if (event.event === 'briefing') {
            setStream('idle');
            if (!restoring.current) setCompletions((n) => n + 1);
            restoring.current = false;
          }
          if (event.event === 'error' && (event.payload as { fatal?: boolean }).fatal) setStream('idle');
        },
        onReconnecting: (n) => {
          setStream('reconnecting');
          setReconnectAttempt(n);
        },
        onLost: () => {
          setStream('lost');
          dispatch({ type: 'STREAM_LOST' });
          void retryHealth();
        },
      });
    },
    [retryHealth],
  );

  const start = useCallback(
    async (req: RunRequest, runLang: Lang = lang) => {
      sse.current?.close();
      restoring.current = false;
      lastSeq.current = 0;
      setDocs({});
      docsRef.current = {};
      const body: BriefingRequest = { region: req.region, scenario: req.scenario, lang: runLang, mode: req.mode };
      setLastRequest(body);
      dispatch({ type: 'RUN_STARTING' });
      const r = await api.startBriefing(body);
      if (!r.ok) {
        dispatch({ type: 'RUN_REJECTED', code: r.error.code, message: r.error.message, ts: new Date().toISOString() });
        if (r.error.code === 'UNREACHABLE') void retryHealth();
        return;
      }
      const id = r.value.briefing_id;
      runId.current = id;
      setLastRequest({ ...body, id });
      writePref(KEYS.run, JSON.stringify({ id, request: body } satisfies StoredRun), 'session');
      dispatch({ type: 'RUN_ACCEPTED', taskId: id });
      attach(id, 0);
    },
    [attach, lang, retryHealth],
  );

  const cancel = useCallback(async () => {
    const id = runId.current;
    if (!id) return;
    const r = await api.cancelBriefing(id);
    if (!r.ok) {
      // Cancel not acknowledged: close locally and say so.
      sse.current?.close();
      setStream('idle');
    }
    dispatch({ type: 'RUN_CANCELLED' });
  }, []);

  const resume = useCallback(() => {
    if (runId.current) attach(runId.current, lastSeq.current);
  }, [attach]);

  // Boot: health, then re-attach to a run kept in sessionStorage (reload or language switch).
  useEffect(() => {
    if (!autoHealth) return;
    let alive = true;
    void (async () => {
      const ok = await retryHealth();
      if (!ok || !alive) return;
      const stored = readJson<StoredRun>(KEYS.run, 'session');
      if (!stored?.id) return;
      const b = await api.getBriefing(stored.id);
      if (!alive) return;
      if (!b.ok || b.value.status === 'cancelled' || b.value.status === 'failed') {
        writePref(KEYS.run, null, 'session');
        return;
      }
      runId.current = stored.id;
      setLastRequest({ ...stored.request, id: stored.id });
      restoring.current = true;
      dispatch({ type: 'RUN_STARTING' });
      dispatch({ type: 'RUN_ACCEPTED', taskId: stored.id });
      attach(stored.id, 0);
    })();
    return () => {
      alive = false;
      sse.current?.close();
    };
  }, [attach, autoHealth, retryHealth]);

  // While the creature sleeps, try to wake it every 10 s.
  useEffect(() => {
    if (healthStatus !== 'failed') return;
    const h = setInterval(() => void retryHealth(), 10_000);
    return () => clearInterval(h);
  }, [healthStatus, retryHealth]);

  // Fetch whole tool outputs as soon as each organ answers (map and charts fill progressively).
  useEffect(() => {
    for (const c of state.calls) if (c.ok && c.runId && DOC_TOOLS.has(c.tool)) ensureDoc(c.runId);
    for (const s of state.briefing?.sections ?? [])
      for (const cl of s.claims) for (const e of cl.evidence) if (DOC_TOOLS.has(e.tool)) ensureDoc(e.run_id);
  }, [state.calls, state.briefing, ensureDoc]);

  const value = useMemo<BenchCtx>(
    () => ({ state, dispatch, health, healthStatus, retryHealth, start, cancel, resume, stream, reconnectAttempt, lastRequest, completions, docs, ensureDoc }),
    [state, health, healthStatus, retryHealth, start, cancel, resume, stream, reconnectAttempt, lastRequest, completions, docs, ensureDoc],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBench(): BenchCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useBench outside BenchProvider');
  return v;
}

/** For component tests: a provider with a fixed value. */
export const BenchContext = Ctx;
export type { BenchCtx };
