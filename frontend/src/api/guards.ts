import { ORGAN_IDS, type OrganId, type TaskEvent } from './types';

const EVENT_TYPES = new Set(['plan', 'organ_call', 'organ_result', 'conflict', 'critic', 'briefing', 'error', 'notice']);

/** Minimal runtime check at the SSE trust boundary (no schema validator ships in the bundle). */
export function isTaskEvent(x: unknown): x is TaskEvent {
  if (typeof x !== 'object' || x === null) return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.event === 'string' &&
    EVENT_TYPES.has(o.event) &&
    typeof o.ts === 'string' &&
    typeof o.task_id === 'string' &&
    typeof o.payload === 'object' &&
    o.payload !== null
  );
}

export function isOrganId(x: unknown): x is OrganId {
  return typeof x === 'string' && (ORGAN_IDS as readonly string[]).includes(x);
}

export function parseTaskEvent(raw: string): TaskEvent | null {
  try {
    const v: unknown = JSON.parse(raw);
    if (isTaskEvent(v)) return v;
  } catch {
    /* fallthrough */
  }
  if (typeof console !== 'undefined') console.warn('dropped malformed SSE event');
  return null;
}