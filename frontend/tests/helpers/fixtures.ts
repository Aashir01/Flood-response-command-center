import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Briefing, OrganList, ToolEnvelope } from '@/api/types';
import type { EvalsLatest } from '@/api/client';

const fx = resolve(__dirname, '..', '..', 'fixtures');
export const readFixture = <T,>(p: string): T => JSON.parse(readFileSync(resolve(fx, p), 'utf8')) as T;

export type EvidenceFile = Record<string, { organ: string; tool: string; doc: ToolEnvelope<unknown> }>;
export const briefing = (name: string, lang: 'en' | 'ur' = 'en') => readFixture<Briefing>(`rest/briefing.${name}.${lang}.json`);
export const evidence = (name: string, lang: 'en' | 'ur' = 'en') => readFixture<EvidenceFile>(`rest/evidence.${name}.${lang}.json`);
export const organs = (name = 'default') => readFixture<OrganList>(`rest/organs.${name}.json`);
export const evals = (name: string) => readFixture<EvalsLatest>(`rest/evals.${name}.json`);
export function toolData<T>(name: string, tool: string, lang: 'en' | 'ur' = 'en'): T {
  const e = Object.values(evidence(name, lang)).find((v) => v.tool === tool);
  if (!e) throw new Error(`no ${tool} in ${name}`);
  return e.doc.data as T;
}
export function stream(name: string, lang: 'en' | 'ur' = 'en') {
  return readFileSync(resolve(fx, `streams/${name}.${lang}.ndjson`), 'utf8')
    .trim()
    .split('\n')
    .map((l) => JSON.parse(l) as { seq: number; event: string; data: import('@/api/types').TaskEvent });
}
