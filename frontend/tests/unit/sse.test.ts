import { describe, expect, it } from 'vitest';
import { BACKOFF_MS, openEventStream, WATCHDOG_MS, type SseDeps } from '@/api/sse';
import { initialState, reduceAll } from '@/state/benchReducer';
import type { TaskEvent } from '@/api/types';

class FakeES {
  static instances: FakeES[] = [];
  readyState = 1;
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, ((e: MessageEvent<string>) => void)[]>();
  constructor(url: string) {
    this.url = url;
    FakeES.instances.push(this);
  }
  addEventListener(n: string, f: (e: MessageEvent<string>) => void) {
    this.listeners.set(n, [...(this.listeners.get(n) ?? []), f]);
  }
  close() {
    this.readyState = 2;
  }
  emit(name: string, seq: number, ev: TaskEvent) {
    for (const f of this.listeners.get(name) ?? []) f({ data: JSON.stringify(ev), lastEventId: String(seq) } as MessageEvent<string>);
  }
}
const mkDeps = () => {
  const timers: { fn: () => void; ms: number; id: number; live: boolean }[] = [];
  const deps: SseDeps = {
    EventSourceCtor: FakeES as unknown as typeof EventSource,
    setTimer: (fn, ms) => {
      const t = { fn, ms, id: timers.length, live: true };
      timers.push(t);
      return t.id;
    },
    clearTimer: (h) => {
      const t = timers[h as number];
      if (t) t.live = false;
    },
  };
  return { deps, timers };
};
const ev = (event: TaskEvent['event'], task_id: string, extra: Partial<TaskEvent> = {}, payload: Record<string, unknown> = {}): TaskEvent => ({ event, ts: '2026-11-20T10:00:00Z', task_id, payload, ...extra });

describe('SSE wrapper', () => {
  it('reconnects with ?last_event_id and the reducer sees no duplicates', () => {
    FakeES.instances = [];
    const { deps, timers } = mkDeps();
    const got: { seq: number; event: TaskEvent }[] = [];
    let lost = 0;
    openEventStream({ makeUrl: (n) => `/e${n ? `?last_event_id=${n}` : ''}`, onEvent: (seq, event) => got.push({ seq, event }), onLost: () => lost++, deps });
    const a = FakeES.instances[0] as FakeES;
    a.emit('plan', 1, ev('plan', 'plan', {}, { nodes: [] }));
    a.emit('organ_call', 2, ev('organ_call', 'eyes.x', { organ: 'eyes', tool: 't' }, { started_at: 'x', served_by: 'real' }));
    a.readyState = 2;
    a.onerror?.();
    const retry = timers.find((t) => t.live && t.ms === BACKOFF_MS[0]);
    expect(retry).toBeTruthy();
    retry?.fn();
    const b = FakeES.instances[1] as FakeES;
    expect(b.url).toBe('/e?last_event_id=2');
    // server replays seq 2 again then continues
    b.emit('organ_call', 2, ev('organ_call', 'eyes.x', { organ: 'eyes', tool: 't' }, { started_at: 'x', served_by: 'real' }));
    b.emit('organ_result', 3, ev('organ_result', 'eyes.x', { organ: 'eyes', tool: 't' }, { ok: true, duration_ms: 5, run_id: 'r', served_by: 'real', mode: 'demo' }));
    const resumed = reduceAll(got);
    const plain = reduceAll([got[0] as { seq: number; event: TaskEvent }, got[1] as { seq: number; event: TaskEvent }, got[3] as { seq: number; event: TaskEvent }]);
    expect(resumed).toEqual(plain);
    expect(resumed.organs.eyes.state).toBe('done');
    expect(initialState().organs.eyes.state).toBe('idle');
    expect(lost).toBe(0);
  });

  it('gives up after the backoff schedule and reports loss', () => {
    FakeES.instances = [];
    const { deps, timers } = mkDeps();
    let lost = 0;
    openEventStream({ makeUrl: () => '/e', onEvent: () => {}, onLost: () => lost++, deps });
    for (let i = 0; i < BACKOFF_MS.length; i++) {
      const es = FakeES.instances.at(-1) as FakeES;
      es.readyState = 2;
      es.onerror?.();
      const t = timers.filter((x) => x.live && x.ms === BACKOFF_MS[i]).at(-1);
      expect(t, `backoff ${i}`).toBeTruthy();
      t?.fn();
    }
    const last = FakeES.instances.at(-1) as FakeES;
    last.readyState = 2;
    last.onerror?.();
    expect(lost).toBe(1);
  });

  it('watchdog reconnects a stalled stream', () => {
    FakeES.instances = [];
    const { deps, timers } = mkDeps();
    openEventStream({ makeUrl: () => '/e', onEvent: () => {}, onLost: () => {}, deps });
    const wd = timers.filter((t) => t.live && t.ms === WATCHDOG_MS).at(-1);
    wd?.fn();
    expect(timers.some((t) => t.live && t.ms === BACKOFF_MS[0])).toBe(true);
  });

  it('closes on the briefing event', () => {
    FakeES.instances = [];
    const { deps } = mkDeps();
    openEventStream({ makeUrl: () => '/e', onEvent: () => {}, onLost: () => {}, deps });
    const a = FakeES.instances[0] as FakeES;
    a.emit('briefing', 9, ev('briefing', 'briefing'));
    expect(a.readyState).toBe(2);
  });
});