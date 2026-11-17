import { render, type RenderResult } from '@testing-library/react';
import { domAnimation, LazyMotion } from 'motion/react';
import type { ReactElement, ReactNode } from 'react';
import type { Lang } from '@/api/types';
import { EvidenceProvider } from '@/components/briefing/EvidenceContext';
import en from '@/i18n/messages/en.json';
import ur from '@/i18n/messages/ur.json';
import { LangProvider } from '@/i18n/LangProvider';
import type { Dict } from '@/i18n/t';
import { BenchContext, type BenchCtx } from '@/state/BenchProvider';
import { initialState, type BenchState } from '@/state/benchReducer';
import { PrefsProvider } from '@/state/prefs';

export const DICTS: Record<Lang, Dict> = { en, ur };

export function benchValue(state: Partial<BenchState> = {}, extra: Partial<BenchCtx> = {}): BenchCtx {
  return {
    state: { ...initialState(), ...state },
    dispatch: () => {},
    health: null,
    healthStatus: 'ok',
    retryHealth: async () => true,
    start: async () => {},
    cancel: async () => {},
    resume: () => {},
    stream: 'idle',
    reconnectAttempt: 0,
    lastRequest: null,
    completions: 0,
    docs: {},
    ensureDoc: () => {},
    ...extra,
  };
}

export function Wrap({ lang = 'en', bench, children, fx = 'none' }: { lang?: Lang; bench?: BenchCtx; children: ReactNode; fx?: 'full' | 'lite' | 'none' }) {
  return (
    <PrefsProvider initial={{ fx, contrast: false, sound: false, digits: 'latn' }}>
      <LazyMotion features={domAnimation} strict>
        <LangProvider lang={lang} dict={DICTS[lang]}>
          <BenchContext.Provider value={bench ?? benchValue()}>
            <EvidenceProvider>{children}</EvidenceProvider>
          </BenchContext.Provider>
        </LangProvider>
      </LazyMotion>
    </PrefsProvider>
  );
}

export function renderUi(ui: ReactElement, opts: { lang?: Lang; bench?: BenchCtx; fx?: 'full' | 'lite' | 'none' } = {}): RenderResult {
  return render(ui, { wrapper: ({ children }) => <Wrap {...opts}>{children}</Wrap> });
}
