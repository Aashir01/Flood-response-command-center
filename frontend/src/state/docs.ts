'use client';
import type {
  AnswerOut,
  CompareOut,
  ForecastOut,
  OptimizeOut,
  OrganId,
  ScenarioDistrict,
  SegmentOut,
  SensitivityOut,
  ToolEnvelope,
} from '@/api/types';
import { useBench, type DocEntry } from './BenchProvider';
import { selectRunId } from './selectors';
import type { BenchState } from './benchReducer';

export interface ToolDocs {
  segment?: SegmentOut;
  compare?: CompareOut;
  forecast?: ForecastOut;
  optimize?: OptimizeOut;
  sensitivity?: SensitivityOut;
  districts?: ScenarioDistrict[];
  library: { runId: string; data?: AnswerOut }[];
  envelopes: Record<string, ToolEnvelope<unknown> | undefined>;
  loading: Set<string>;
}

/** All run ids for an organ/tool, from live calls first, then from the briefing's evidence (restored session). */
export function runIdsFor(state: BenchState, organ: OrganId, tool: string): string[] {
  const out: string[] = [];
  for (const c of state.calls) if (c.organ === organ && c.tool === tool && c.ok && c.runId && !out.includes(c.runId)) out.push(c.runId);
  for (const s of state.briefing?.sections ?? [])
    for (const cl of s.claims) for (const e of cl.evidence) if (e.organ === organ && e.tool === tool && !out.includes(e.run_id)) out.push(e.run_id);
  return out;
}

function dataOf<T>(e: DocEntry | undefined): T | undefined {
  return e?.status === 'ok' && e.doc?.ok ? (e.doc.data as T) : undefined;
}

export function collectDocs(state: BenchState, docs: Record<string, DocEntry>): ToolDocs {
  const loading = new Set<string>();
  const envelopes: Record<string, ToolEnvelope<unknown> | undefined> = {};
  const get = <T,>(organ: OrganId, tool: string): T | undefined => {
    const id = selectRunId(state, organ, tool);
    if (!id) return undefined;
    const e = docs[id];
    if (e?.status === 'loading') loading.add(tool);
    envelopes[tool] = e?.doc;
    return dataOf<T>(e);
  };
  const districtsRaw = get<{ items?: ScenarioDistrict[] } | ScenarioDistrict[]>('ledger', 'resource:districts') ?? get<{ items?: ScenarioDistrict[] } | ScenarioDistrict[]>('ledger', 'resource:ledger.districts');
  const districts = Array.isArray(districtsRaw) ? districtsRaw : districtsRaw?.items;
  return {
    segment: get<SegmentOut>('eyes', 'segment_flood'),
    compare: get<CompareOut>('eyes', 'compare_with_permanent_water'),
    forecast: get<ForecastOut>('oracle', 'forecast_river'),
    optimize: get<OptimizeOut>('ledger', 'optimize_allocation'),
    sensitivity: get<SensitivityOut>('ledger', 'sensitivity_report'),
    districts,
    library: runIdsFor(state, 'library', 'answer_with_citations').map((runId) => ({ runId, data: dataOf<AnswerOut>(docs[runId]) })),
    envelopes,
    loading,
  };
}

export function useToolDocs(): ToolDocs {
  const { state, docs } = useBench();
  return collectDocs(state, docs);
}
