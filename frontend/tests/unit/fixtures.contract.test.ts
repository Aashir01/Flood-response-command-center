// Every mock-Brain fixture (REST bodies and SSE frames) validates against the exported JSON Schemas,
// so the mock cannot drift from the contract (design section 16, task 5).
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const repo = resolve(__dirname, '..', '..', '..');
const schemaDir = resolve(repo, 'packages/stitch_common/schemas');
const fx = resolve(__dirname, '..', '..', 'fixtures');

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
const validators = new Map<string, ReturnType<typeof ajv.compile>>();
function v(name: string) {
  let f = validators.get(name);
  if (!f) {
    f = ajv.compile(JSON.parse(readFileSync(resolve(schemaDir, `${name}.json`), 'utf8')));
    validators.set(name, f);
  }
  return f;
}
function check(name: string, data: unknown, where: string) {
  const f = v(name);
  const ok = f(data);
  if (!ok) throw new Error(`${where} does not match ${name}: ${ajv.errorsText(f.errors)}`);
  expect(ok).toBe(true);
}
const read = (p: string) => JSON.parse(readFileSync(resolve(fx, p), 'utf8')) as unknown;

const PAYLOAD: Record<string, string> = {
  plan: 'brain_api.payload_plan',
  organ_call: 'brain_api.payload_organ_call',
  organ_result: 'brain_api.payload_organ_result',
  critic: 'brain_api.payload_critic',
  error: 'brain_api.payload_error',
  notice: 'brain_api.payload_notice',
  briefing: 'brain.briefing',
};
const TOOL_OUT: Record<string, string> = {
  segment_flood: 'eyes.segment_flood.out',
  compare_with_permanent_water: 'eyes.compare_with_permanent_water.out',
  forecast_river: 'oracle.forecast_river.out',
  explain_forecast: 'oracle.explain_forecast.out',
  answer_with_citations: 'library.answer_with_citations.out',
  optimize_allocation: 'ledger.optimize_allocation.out',
  sensitivity_report: 'ledger.sensitivity_report.out',
  
};

describe('fixture contract (Ajv against packages/stitch_common/schemas)', () => {
  const streams = readdirSync(resolve(fx, 'streams')).filter((f) => f.endsWith('.ndjson'));
  it.each(streams)('stream %s: every frame is a TaskEvent with a valid payload and contiguous ids', (file) => {
    const lines = readFileSync(resolve(fx, 'streams', file), 'utf8').trim().split('\n');
    lines.forEach((line, i) => {
      const f = JSON.parse(line) as { seq: number; event: string; data: { event: string; payload: unknown } };
      expect(f.seq).toBe(i + 1);
      expect(f.data.event).toBe(f.event);
      check('brain.task_event', f.data, `${file}#${f.seq}`);
      const p = PAYLOAD[f.event];
      if (p) check(p, f.data.payload, `${file}#${f.seq} payload`);
    });
    expect(JSON.parse(lines.at(-1) as string).event).toBe('briefing');
  });

  const rest = readdirSync(resolve(fx, 'rest'));
  it.each(rest.filter((f) => f.startsWith('briefing.')))('%s is a Briefing', (f) => check('brain.briefing', read(`rest/${f}`), f));
  it.each(rest.filter((f) => f.startsWith('organs.')))('%s is an OrganList', (f) => check('brain_api.organ_list', read(`rest/${f}`), f));
  it.each(rest.filter((f) => f.startsWith('ask.')))('%s is an AskResponse', (f) => check('brain_api.ask_response', read(`rest/${f}`), f));
  it.each(rest.filter((f) => f.startsWith('evidence.')))('%s: every stored ToolResult validates', (f) => {
    const ev = read(`rest/${f}`) as Record<string, { organ: string; tool: string; doc: { ok: boolean; data: unknown } }>;
    for (const [runId, entry] of Object.entries(ev)) {
      // Brain-origin evidence (derived inputs, static text) is not an organ ToolResult; it only needs a data object.
      if (entry.organ === 'brain') {
        expect(typeof entry.doc.data).toBe('object');
        continue;
      }
      check('common.tool_result', entry.doc, `${f}:${runId}`);
      const out = TOOL_OUT[entry.tool];
      if (out && entry.doc.ok) check(out, entry.doc.data, `${f}:${runId} data`);
    }
  });
  it.each(rest.filter((f) => f.startsWith('evals.')))('%s matches evals/results/schema.json', (f) => {
    const schema = JSON.parse(readFileSync(resolve(repo, 'evals/results/schema.json'), 'utf8')) as object;
    const val = ajv.compile(schema);
    expect(val(read(`rest/${f}`)), ajv.errorsText(val.errors)).toBe(true);
  });

  it('every evidence ref in every briefing resolves in that scenario evidence file (BRN-P1 for fixtures)', () => {
    for (const f of rest.filter((x) => x.startsWith('briefing.'))) {
      const b = read(`rest/${f}`) as { sections: { claims: { evidence: { run_id: string; json_pointer: string }[] }[] }[] };
      const ev = read(`rest/${f.replace('briefing.', 'evidence.')}`) as Record<string, { doc: unknown }>;
      for (const s of b.sections)
        for (const c of s.claims) {
          expect(c.evidence.length).toBeGreaterThan(0);
          for (const r of c.evidence) {
            const entry = ev[r.run_id];
            expect(entry, `${f}: ${r.run_id}`).toBeDefined();
            let cur: unknown = entry?.doc;
            for (const k of r.json_pointer.slice(1).split('/')) cur = (cur as Record<string, unknown> | undefined)?.[k];
            expect(cur, `${f}: ${r.json_pointer}`).not.toBeUndefined();
          }
        }
    }
  });
});
