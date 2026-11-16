// EventSource wrapper: named events, Last-Event-ID resume, manual reconnect with backoff, watchdog.
import { parseTaskEvent } from './guards';
import type { TaskEvent, TaskEventType } from './types';

export const EVENT_NAMES: TaskEventType[] = ['plan', 'organ_call', 'organ_result', 'conflict', 'critic', 'briefing', 'error', 'notice'];
export const BACKOFF_MS = [500, 1000, 2000, 4000, 8000] as const;
export const WATCHDOG_MS = 30_000;

export interface SseDeps {
  EventSourceCtor: typeof EventSource;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (h: unknown) => void;
}
export const defaultDeps = (): SseDeps => ({
  EventSourceCtor: EventSource,
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: (h) => clearTimeout(h as ReturnType<typeof setTimeout>),
});

export interface SseOptions {
  /** Builds the URL; `lastSeq` > 0 asks the Brain to resume after that seq (query form for manual reconnects). */
  makeUrl: (lastSeq: number) => string;
  onEvent: (seq: number, event: TaskEvent) => void;
  onLost: () => void;
  onReconnecting?: (attempt: number) => void;
  initialSeq?: number;
  deps?: SseDeps;
}
export interface SseHandle {
  close: () => void;
}

export function openEventStream(opts: SseOptions): SseHandle {
  const deps = opts.deps ?? defaultDeps();
  let lastSeq = opts.initialSeq ?? 0;
  let es: EventSource | null = null;
  let closed = false;
  let attempts = 0;
  let watchdog: unknown = null;
  let retryTimer: unknown = null;

  const terminate = () => {
    closed = true;
    es?.close();
    if (watchdog) deps.clearTimer(watchdog);
    if (retryTimer) deps.clearTimer(retryTimer);
  };
  const armWatchdog = () => {
    if (watchdog) deps.clearTimer(watchdog);
    watchdog = deps.setTimer(() => {
      if (closed) return;
      es?.close();
      reconnect();
    }, WATCHDOG_MS);
  };
  const reconnect = () => {
    if (closed) return;
    if (attempts >= BACKOFF_MS.length) {
      terminate();
      opts.onLost();
      return;
    }
    const wait = BACKOFF_MS[attempts] as number;
    attempts += 1;
    opts.onReconnecting?.(attempts);
    retryTimer = deps.setTimer(connect, wait);
  };
  const connect = () => {
    if (closed) return;
    es = new deps.EventSourceCtor(opts.makeUrl(lastSeq));
    armWatchdog();
    es.onopen = () => armWatchdog();
    for (const name of EVENT_NAMES) {
      es.addEventListener(name, (e) => {
        const me = e as MessageEvent<string>;
        attempts = 0;
        armWatchdog();
        const ev = parseTaskEvent(me.data);
        if (!ev) return;
        const seq = Number(me.lastEventId);
        if (Number.isFinite(seq) && seq > 0) lastSeq = Math.max(lastSeq, seq);
        opts.onEvent(Number.isFinite(seq) && seq > 0 ? seq : lastSeq + 1, ev);
        const fatal = ev.event === 'error' && (ev.payload as { fatal?: boolean }).fatal === true;
        if (ev.event === 'briefing' || fatal) terminate();
      });
    }
    es.onerror = () => {
      if (closed) return;
      // CONNECTING: the browser retries by itself and sends Last-Event-ID. CLOSED: we reconnect manually.
      if (es && es.readyState === 2) {
        es.close();
        reconnect();
      }
    };
  };
  connect();
  return { close: terminate };
}