// Evidence resolution cache: one request per (run_id, pointer) per page.
import { api } from './client';
import type { EvidenceRef, EvidenceValue, Result } from './types';

const cache = new Map<string, Promise<Result<EvidenceValue>>>();

export function resolveEvidence(ref: EvidenceRef): Promise<Result<EvidenceValue>> {
  const key = `${ref.run_id}|${ref.json_pointer}`;
  let p = cache.get(key);
  if (!p) {
    p = api.getEvidence(ref.run_id, ref.json_pointer).then((r) => {
      if (!r.ok) cache.delete(key); // failures are retried on the next open
      return r;
    });
    cache.set(key, p);
  }
  return p;
}

export function clearEvidenceCache(): void {
  cache.clear();
}

export interface CitationLike {
  doc_id: string;
  title?: string;
  publisher?: string;
  page: number;
  quote: string;
  lang?: string;
  url?: string | null;
}

export function isCitation(v: unknown): v is CitationLike {
  if (typeof v !== 'object' || v === null) return false;
  const o = v as Record<string, unknown>;
  return typeof o.doc_id === 'string' && typeof o.page === 'number' && typeof o.quote === 'string';
}
