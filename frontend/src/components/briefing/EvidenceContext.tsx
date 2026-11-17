'use client';
import dynamic from 'next/dynamic';
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { EvidenceRef, Lang } from '@/api/types';

export interface EvidenceRequest {
  refs: EvidenceRef[];
  claimText: string;
  claimLang?: Lang;
}
interface Ctx {
  open: (r: EvidenceRequest) => void;
}
const EvidenceCtx = createContext<Ctx | null>(null);

// The drawer body is a lazy chunk; it loads on the first open.
const EvidenceDrawer = dynamic(() => import('./EvidenceDrawer').then((m) => m.EvidenceDrawer), { ssr: false });

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [req, setReq] = useState<EvidenceRequest | null>(null);
  const open = useCallback((r: EvidenceRequest) => setReq(r), []);
  const close = useCallback(() => setReq(null), []);
  const value = useMemo(() => ({ open }), [open]);
  return (
    <EvidenceCtx.Provider value={value}>
      {children}
      {req ? <EvidenceDrawer request={req} onClose={close} /> : null}
    </EvidenceCtx.Provider>
  );
}

export function useEvidence(): Ctx {
  const v = useContext(EvidenceCtx);
  if (!v) throw new Error('useEvidence outside EvidenceProvider');
  return v;
}
export { EvidenceCtx };
