import fc from 'fast-check';
import { ORGAN_IDS, type OrganId, type OrganInfo, type TaskEvent } from '@/api/types';

export const FC_RUNS = Number(process.env.FC_NUM_RUNS ?? (process.env.CI ? 200 : 30));

export const organArb: fc.Arbitrary<OrganId> = fc.constantFrom(...ORGAN_IDS);
export const healthArb: fc.Arbitrary<OrganInfo[]> = fc.tuple(...ORGAN_IDS.map((o) => fc.constantFrom('ready', 'degraded', 'unwell', 'disabled', 'incompatible') as fc.Arbitrary<OrganInfo['status']>)).map((sts) =>
  ORGAN_IDS.map((organ, i) => ({ organ, status: sts[i] as OrganInfo['status'] })),
);

export type Spec =
  | { k: 'plan' }
  | { k: 'call'; o: OrganId }
  | { k: 'ok'; o: OrganId }
  | { k: 'fail'; o: OrganId }
  | { k: 'organError'; o: OrganId }
  | { k: 'conflict'; id: number }
  | { k: 'critic' }
  | { k: 'briefing' }
  | { k: 'fatal'; cancelled: boolean }
  | { k: 'notice' };

export const specArb: fc.Arbitrary<Spec> = fc.oneof(
  { weight: 1, arbitrary: fc.constant<Spec>({ k: 'plan' }) },
  { weight: 5, arbitrary: organArb.map<Spec>((o) => ({ k: 'call', o })) },
  { weight: 5, arbitrary: organArb.map<Spec>((o) => ({ k: 'ok', o })) },
  { weight: 3, arbitrary: organArb.map<Spec>((o) => ({ k: 'fail', o })) },
  { weight: 2, arbitrary: organArb.map<Spec>((o) => ({ k: 'organError', o })) },
  { weight: 2, arbitrary: fc.nat(3).map<Spec>((id) => ({ k: 'conflict', id })) },
  { weight: 1, arbitrary: fc.constant<Spec>({ k: 'critic' }) },
  { weight: 1, arbitrary: fc.constant<Spec>({ k: 'briefing' }) },
  { weight: 1, arbitrary: fc.boolean().map<Spec>((cancelled) => ({ k: 'fatal', cancelled })) },
  { weight: 1, arbitrary: fc.constant<Spec>({ k: 'notice' }) },
);

const T0 = Date.parse('2026-11-20T10:00:00Z');
const ts = (n: number) => new Date(T0 + n * 250).toISOString();
const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;

export function toEvent(spec: Spec, n: number): TaskEvent {
  switch (spec.k) {
    case 'plan':
      return { event: 'plan', ts: ts(n), task_id: 'plan', payload: { plan_id: 'p', revision: 0, planner: 'static', scenario: 'demo-sindh-2022', lang: 'en', mode_requested: 'demo', nodes: ORGAN_IDS.map((o) => ({ id: `${o}.x`, kind: 'organ', organ: o, tool: 't' })) } };
    case 'call':
      return { event: 'organ_call', ts: ts(n), task_id: `${spec.o}.x`, organ: spec.o, tool: 't', payload: { attempt: 1, max_attempts: 1, timeout_s: 5, served_by: 'real', started_at: ts(n) } };
    case 'ok':
      return { event: 'organ_result', ts: ts(n), task_id: `${spec.o}.x`, organ: spec.o, tool: 't', payload: { ok: true, attempt: 1, duration_ms: 100, served_by: 'real', run_id: uuid(n), mode: 'demo' } };
    case 'fail':
      return { event: 'organ_result', ts: ts(n), task_id: `${spec.o}.x`, organ: spec.o, tool: 't', payload: { ok: false, attempt: 1, duration_ms: 100, served_by: 'real', run_id: uuid(n), mode: 'demo', error: { code: 'TIMEOUT', message: 'timed out', retryable: true } } };
    case 'organError':
      return { event: 'error', ts: ts(n), task_id: `${spec.o}.x`, organ: spec.o, payload: { code: 'INTERNAL', message: 'boom', fatal: false } };
    case 'conflict':
      return { event: 'conflict', ts: ts(n), task_id: 'conflicts', payload: { id: `C${spec.id}`, description: 'd', organs: ['eyes', 'ledger'], resolution: 'flagged', evidence: [] } };
    case 'critic':
      return { event: 'critic', ts: ts(n), task_id: 'critic', payload: { pass: 1, passed: true } };
    case 'briefing':
      return { event: 'briefing', ts: ts(n), task_id: 'briefing', payload: { briefing_id: 'b', scenario: 's', lang: 'en', mode: 'demo', sections: [], conflicts: [], critic: { passed: true, removed_claims: [], notes: [] }, confidence: 0.5, generated_at: ts(n) } };
    case 'fatal':
      return { event: 'error', ts: ts(n), task_id: 'run', payload: { code: spec.cancelled ? 'CANCELLED' : 'INTERNAL', message: 'x', fatal: true } };
    case 'notice':
      return { event: 'notice', ts: ts(n), task_id: 'run', payload: { code: 'MODE_FALLBACK', message: 'fell back' } };
  }
}

export const streamArb = fc.array(specArb, { maxLength: 40 }).map((specs) => specs.map((s, i) => ({ seq: i + 1, event: toEvent(s, i + 1), spec: s })));