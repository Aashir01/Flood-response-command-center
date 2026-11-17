// Streams recorded from the real Brain (recorded organs, fake LLM) drive the reducer to the expected
// end state. Regenerate with `STITCH_WRITE_FRONTEND_STREAM=1 uv run pytest brain/tests/contract/test_frontend_payloads.py -k write`.
import { describe, expect, it } from 'vitest';
import { benchReducer, initialState, reduceAll } from '@/state/benchReducer';
import { selectMissingSections, selectRunId } from '@/state/selectors';
import { organs, stream } from '../helpers/fixtures';

function run(name: string, lang: 'en' | 'ur') {
  const frames = stream(`brain-${name}`, lang);
  const health = benchReducer(initialState(), { type: 'HEALTH', organs: organs('default').organs });
  return { frames, state: reduceAll(frames.map((f) => ({ seq: f.seq, event: f.data })), health) };
}

describe('real Brain streams', () => {
  it('headline demo: completed, briefing organs done, run ids usable for drill-down', () => {
    const { frames, state } = run('default-demo', 'en');
    expect(state.lastSeq).toBe(frames.length);
    expect(state.run.status).toBe('completed');
    expect(state.briefing?.sections.map((s) => s.id)).toEqual(['extent', 'forecast', 'guidance', 'allocation', 'caveats']);
    for (const o of ['eyes', 'oracle', 'library', 'ledger'] as const) {
      expect(state.organs[o].state).toBe('done');
      expect(state.organs[o].stub).toBe(true); // recorded organs are labelled
    }
    expect(state.errors).toEqual([]);
    expect(selectRunId(state, 'ledger', 'optimize_allocation')).toBeTruthy();
    expect(selectRunId(state, 'eyes', 'segment_flood')).toBeTruthy();
    expect(state.briefing?.conflicts).toEqual([]);
    for (const m of selectMissingSections(state)) expect(m.missing.length).toBeGreaterThan(0);
  });

  it('seeded conflicts in Urdu: two final conflicts, the latest Ledger run is the re-run', () => {
    const { state } = run('conflict', 'ur');
    expect(state.run.status).toBe('completed');
    expect(state.briefing?.lang).toBe('ur');
    expect(state.conflicts.map((c) => [c.rule_id, c.resolution, c.status])).toEqual([
      ['R2_ledger_to_dry_district', 'reconciled', 'final'],
      ['R3_library_vs_ledger_need', 'flagged', 'final'],
    ]);
    const rerun = state.calls.find((c) => c.taskId === 'ledger.rerun');
    expect(rerun?.ok).toBe(true);
    expect(selectRunId(state, 'ledger', 'optimize_allocation')).toBe(rerun?.runId);
    expect(state.run.plan?.revision).toBe(2);
    for (const m of selectMissingSections(state)) expect(m.missing.length).toBeGreaterThan(0);
  });
});
