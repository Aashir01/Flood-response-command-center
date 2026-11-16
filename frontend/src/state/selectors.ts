import type { BenchState, CallRecord } from './benchReducer';
import type { Briefing, EvidenceRef, OrganId, Section } from '@/api/types';

export function selectBriefingSections(b: Briefing | undefined): Section[] {
  return b?.sections ?? [];
}

export function selectSection(b: Briefing | undefined, id: Section['id']): Section | undefined {
  return b?.sections.find((s) => s.id === id);
}

export function selectClaimEvidence(b: Briefing | undefined, claimId: string): EvidenceRef[] {
  for (const s of b?.sections ?? []) {
    const c = s.claims.find((x) => x.id === claimId);
    if (c) return c.evidence;
  }
  return [];
}

/** Latest call to organ.tool: from live events, else from a briefing's evidence refs (restored session). */
export function selectRunId(state: BenchState, organ: OrganId, tool: string): string | undefined {
  for (let i = state.calls.length - 1; i >= 0; i--) {
    const c = state.calls[i] as CallRecord;
    if (c.organ === organ && c.tool === tool && c.ok && c.runId) return c.runId;
  }
  for (const s of state.briefing?.sections ?? [])
    for (const c of s.claims) for (const e of c.evidence) if (e.organ === organ && e.tool === tool) return e.run_id;
  return undefined;
}

export interface MissingItem {
  section: Section['id'];
  status: Section['status'];
  missing: string[];
}
/** Names what the briefing lacks, for error and partial copy. */
export function selectMissingSections(state: BenchState): MissingItem[] {
  const out: MissingItem[] = [];
  for (const s of state.briefing?.sections ?? []) {
    if (s.status !== 'ok') out.push({ section: s.id, status: s.status, missing: s.missing ?? [] });
  }
  return out;
}

export function selectConfidence(b: Briefing | undefined): number | undefined {
  return b?.confidence;
}

export function confidenceBand(c: number): 'low' | 'medium' | 'high' {
  return c < 0.4 ? 'low' : c < 0.7 ? 'medium' : 'high';
}

export function organOfSection(id: Section['id']): OrganId | undefined {
  return ({ extent: 'eyes', forecast: 'oracle', guidance: 'library', allocation: 'ledger', caveats: undefined } as const)[id];
}