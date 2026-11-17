// Pure reducer: BenchState = f(health, Brain event stream). No Date.now(), Math.random() or DOM.
import { isOrganId } from '@/api/guards';
import {
  ORGAN_IDS,
  type Briefing,
  type Conflict,
  type CriticPayload,
  type ErrorPayload,
  type OrganCallPayload,
  type OrganId,
  type OrganInfo,
  type OrganResultPayload,
  type PlanPayload,
  type TaskEvent,
} from '@/api/types';

export type OrganState = 'idle' | 'calling' | 'done' | 'unwell' | 'disabled';
export type RunStatus = 'idle' | 'starting' | 'running' | 'completed' | 'failed' | 'cancelled' | 'disconnected';

export interface CallRecord {
  taskId: string;
  organ: OrganId;
  tool: string;
  startedAt: string;
  endedAt?: string;
  durationMs?: number;
  ok?: boolean;
  runId?: string;
  errorCode?: string;
  reason?: string;
  servedBy?: string;
  warnings?: string[];
  summary?: Record<string, unknown>;
}
export interface OrganView {
  state: OrganState;
  degraded: boolean;
  /** Secondary text from health (reason) or the plan ("queued"). */
  note?: string;
  stub: boolean;
  lastCall?: CallRecord;
}
export interface BenchError {
  organ?: OrganId;
  code: string;
  message: string;
  ts: string;
  fatal: boolean;
}
export interface Announcement {
  id: number;
  level: 'polite' | 'assertive';
  key: string;
  params: Record<string, string | number>;
}
export interface BenchState {
  lastSeq: number;
  health: 'unknown' | 'loaded' | 'failed';
  baseline: Record<OrganId, OrganState>;
  run: { taskId?: string; status: RunStatus; plan?: PlanPayload; startedAt?: string; endedAt?: string };
  organs: Record<OrganId, OrganView>;
  calls: CallRecord[];
  conflicts: Conflict[];
  critic?: CriticPayload;
  briefing?: Briefing;
  notices: { code: string; message: string; ts: string }[];
  errors: BenchError[];
  announcements: Announcement[];
}

export type BenchAction =
  | { type: 'HEALTH'; organs: OrganInfo[] }
  | { type: 'HEALTH_FAILED' }
  | { type: 'RUN_STARTING' }
  | { type: 'RUN_ACCEPTED'; taskId: string }
  | { type: 'RUN_REJECTED'; code: string; message: string; ts: string }
  | { type: 'EVENT'; seq: number; event: TaskEvent }
  | { type: 'RUN_CANCELLED' }
  | { type: 'STREAM_LOST' }
  | { type: 'BRIEFING_LOADED'; briefing: Briefing; taskId: string };

const MAX_ANNOUNCEMENTS = 24;

const emptyView = (state: OrganState = 'idle'): OrganView => ({ state, degraded: false, stub: false });

export function initialState(): BenchState {
  const organs = {} as Record<OrganId, OrganView>;
  const baseline = {} as Record<OrganId, OrganState>;
  for (const o of ORGAN_IDS) {
    organs[o] = emptyView();
    baseline[o] = 'idle';
  }
  return {
    lastSeq: 0,
    health: 'unknown',
    baseline,
    run: { status: 'idle' },
    organs,
    calls: [],
    conflicts: [],
    notices: [],
    errors: [],
    announcements: [],
  };
}

function healthToState(status: OrganInfo['status']): { state: OrganState; degraded: boolean } {
  switch (status) {
    case 'ready':
      return { state: 'idle', degraded: false };
    case 'degraded':
      return { state: 'idle', degraded: true };
    case 'disabled':
      return { state: 'disabled', degraded: false };
    default:
      return { state: 'unwell', degraded: false }; // unwell | incompatible
  }
}

function announce(s: BenchState, a: Omit<Announcement, 'id'> & { id: number }): BenchState {
  return { ...s, announcements: [...s.announcements, a].slice(-MAX_ANNOUNCEMENTS) };
}

function setOrgan(s: BenchState, o: OrganId, patch: Partial<OrganView>): BenchState {
  return { ...s, organs: { ...s.organs, [o]: { ...s.organs[o], ...patch } } };
}

function upsertCall(calls: CallRecord[], rec: CallRecord): CallRecord[] {
  const i = calls.findIndex((c) => c.taskId === rec.taskId);
  if (i === -1) return [...calls, rec];
  const next = calls.slice();
  next[i] = rec;
  return next;
}

function msBetween(a: string, b: string): number | undefined {
  const d = Date.parse(b) - Date.parse(a);
  return Number.isFinite(d) && d >= 0 ? d : undefined;
}

function applyEvent(s: BenchState, seq: number, ev: TaskEvent): BenchState {
  const organ = isOrganId(ev.organ) ? ev.organ : undefined;
  switch (ev.event) {
    case 'plan': {
      const plan = ev.payload as unknown as PlanPayload;
      let next: BenchState = { ...s, run: { ...s.run, taskId: s.run.taskId ?? ev.task_id, status: 'running', plan, startedAt: s.run.startedAt ?? ev.ts } };
      const planned = new Set<string>();
      for (const n of plan.nodes ?? []) if (n.organ) planned.add(n.organ);
      for (const o of ORGAN_IDS) {
        const stub = (plan.stub_organs ?? []).includes(o);
        next = setOrgan(next, o, { stub, note: next.organs[o].state === 'idle' && planned.has(o) ? 'queued' : next.organs[o].note });
      }
      return announce(next, { id: seq, level: 'polite', key: 'live.runStarted', params: {} });
    }
    case 'organ_call': {
      if (!organ || s.organs[organ].state === 'disabled') return s;
      const p = ev.payload as unknown as OrganCallPayload;
      const rec: CallRecord = { taskId: ev.task_id, organ, tool: ev.tool ?? '', startedAt: p.started_at ?? ev.ts, servedBy: p.served_by };
      let next = setOrgan(s, organ, { state: 'calling', note: undefined, lastCall: rec, stub: p.served_by === 'recorded' || s.organs[organ].stub });
      next = { ...next, calls: upsertCall(next.calls, rec) };
      return announce(next, { id: seq, level: 'polite', key: 'live.organCalling', params: { organ } });
    }
    case 'organ_result': {
      if (!organ || s.organs[organ].state === 'disabled') return s;
      const p = ev.payload as unknown as OrganResultPayload;
      const prev = s.calls.find((c) => c.taskId === ev.task_id);
      const startedAt = prev?.startedAt ?? ev.ts;
      const durationMs = p.duration_ms ?? msBetween(startedAt, ev.ts);
      const rec: CallRecord = {
        taskId: ev.task_id,
        organ,
        tool: ev.tool ?? prev?.tool ?? '',
        startedAt,
        endedAt: ev.ts,
        durationMs,
        ok: p.ok,
        runId: p.run_id,
        errorCode: p.error?.code,
        reason: p.error?.message,
        servedBy: p.served_by,
        warnings: p.warnings,
        summary: p.summary as Record<string, unknown> | undefined,
      };
      let next = { ...s, calls: upsertCall(s.calls, rec) };
      if (p.ok) {
        next = setOrgan(next, organ, { state: 'done', note: undefined, lastCall: rec, stub: p.served_by === 'recorded' || s.organs[organ].stub });
        return announce(next, { id: seq, level: 'polite', key: 'live.organDone', params: { organ, seconds: ((durationMs ?? 0) / 1000).toFixed(1) } });
      }
      next = setOrgan(next, organ, { state: 'unwell', note: rec.reason, lastCall: rec });
      next = { ...next, errors: [...next.errors, { organ, code: rec.errorCode ?? 'INTERNAL', message: rec.reason ?? '', ts: ev.ts, fatal: false }] };
      return announce(next, { id: seq, level: 'assertive', key: 'live.organUnwell', params: { organ, reason: rec.reason ?? '' } });
    }
    case 'conflict': {
      const c = ev.payload as unknown as Conflict;
      const existing = s.conflicts.findIndex((x) => x.id === c.id);
      const conflicts = existing === -1 ? [...s.conflicts, c] : s.conflicts.map((x, i) => (i === existing ? c : x));
      return { ...s, conflicts };
    }
    case 'critic':
      return { ...s, critic: ev.payload as unknown as CriticPayload };
    case 'notice': {
      const p = ev.payload as { code?: string; message?: string };
      return { ...s, notices: [...s.notices, { code: p.code ?? 'NOTICE', message: p.message ?? '', ts: ev.ts }] };
    }
    case 'briefing': {
      const briefing = ev.payload as unknown as Briefing;
      let next: BenchState = { ...s, briefing, run: { ...s.run, status: 'completed', endedAt: ev.ts } };
      for (const o of ORGAN_IDS) {
        if (next.organs[o].state === 'calling') next = setOrgan(next, o, { state: 'unwell', note: 'no result' });
      }
      return announce(next, {
        id: seq,
        level: 'polite',
        key: 'live.briefingReady',
        params: { sections: briefing.sections?.length ?? 0, conflicts: briefing.conflicts?.length ?? s.conflicts.length },
      });
    }
    case 'error': {
      const p = ev.payload as unknown as ErrorPayload;
      const err: BenchError = { organ, code: p.code ?? 'INTERNAL', message: p.message ?? '', ts: ev.ts, fatal: p.fatal === true };
      let next: BenchState = { ...s, errors: [...s.errors, err] };
      if (organ) {
        if (next.organs[organ].state !== 'disabled') next = setOrgan(next, organ, { state: 'unwell', note: err.message });
        return announce(next, { id: seq, level: 'assertive', key: 'live.organUnwell', params: { organ, reason: err.message } });
      }
      if (err.fatal) {
        const cancelled = err.code === 'CANCELLED';
        next = { ...next, run: { ...next.run, status: cancelled ? 'cancelled' : 'failed', endedAt: ev.ts } };
        if (cancelled) for (const o of ORGAN_IDS) if (next.organs[o].state === 'calling') next = setOrgan(next, o, { state: next.baseline[o] });
        return announce(next, { id: seq, level: 'assertive', key: cancelled ? 'live.runCancelled' : 'live.runFailed', params: { reason: err.message } });
      }
      return next;
    }
    default:
      return s;
  }
}

function resetForRun(s: BenchState): BenchState {
  const organs = {} as Record<OrganId, OrganView>;
  for (const o of ORGAN_IDS) {
    const cur = s.organs[o];
    organs[o] = { ...cur, state: s.baseline[o], note: s.baseline[o] === 'unwell' ? cur.note : undefined, lastCall: undefined };
  }
  return { ...s, lastSeq: 0, organs, calls: [], conflicts: [], critic: undefined, briefing: undefined, notices: [], errors: [], run: { status: 'starting' } };
}

export function benchReducer(s: BenchState, a: BenchAction): BenchState {
  switch (a.type) {
    case 'HEALTH': {
      const organs = { ...s.organs };
      const baseline = { ...s.baseline };
      for (const info of a.organs) {
        const { state, degraded } = healthToState(info.status);
        const o = info.organ;
        baseline[o] = state;
        const busy = s.organs[o].state === 'calling' || s.organs[o].state === 'done';
        organs[o] = {
          ...s.organs[o],
          state: busy && state !== 'disabled' ? s.organs[o].state : state,
          degraded,
          note: info.reason ?? undefined,
          stub: info.stub === true || info.served_by === 'recorded',
        };
      }
      return { ...s, health: 'loaded', baseline, organs };
    }
    case 'HEALTH_FAILED':
      return { ...s, health: 'failed' };
    case 'RUN_STARTING':
      return resetForRun(s);
    case 'RUN_ACCEPTED':
      return { ...s, run: { ...s.run, taskId: a.taskId, status: s.run.status === 'starting' ? 'starting' : s.run.status } };
    case 'RUN_REJECTED':
      return { ...s, run: { ...s.run, status: 'failed' }, errors: [...s.errors, { code: a.code, message: a.message, ts: a.ts, fatal: true }] };
    case 'EVENT':
      if (a.seq <= s.lastSeq) return s;
      return applyEvent({ ...s, lastSeq: a.seq }, a.seq, a.event);
    case 'RUN_CANCELLED': {
      let next: BenchState = { ...s, run: { ...s.run, status: 'cancelled' } };
      for (const o of ORGAN_IDS) if (next.organs[o].state === 'calling') next = setOrgan(next, o, { state: next.baseline[o] });
      return next;
    }
    case 'STREAM_LOST':
      return s.run.status === 'completed' || s.run.status === 'cancelled' || s.run.status === 'failed' ? s : { ...s, run: { ...s.run, status: 'disconnected' } };
    case 'BRIEFING_LOADED':
      return { ...s, briefing: a.briefing, run: { ...s.run, taskId: a.taskId, status: 'completed' } };
    default:
      return s;
  }
}

export function reduceAll(events: { seq: number; event: TaskEvent }[], from: BenchState = initialState()): BenchState {
  return events.reduce((st, e) => benchReducer(st, { type: 'EVENT', seq: e.seq, event: e.event }), from);
}