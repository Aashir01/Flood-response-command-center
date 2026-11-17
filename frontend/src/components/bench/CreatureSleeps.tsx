'use client';
import { useState } from 'react';
import { useLang } from '@/i18n/LangProvider';
import { useBench } from '@/state/BenchProvider';

/** Full-bench state when the Brain API is unreachable (FRN-R10.2). */
export function CreatureSleeps() {
  const { t } = useLang();
  const { retryHealth } = useBench();
  const [busy, setBusy] = useState(false);
  return (
    <section className="panel sleeps" role="alert" aria-labelledby="sleeps-title" data-testid="creature-sleeps">
      <svg viewBox="0 0 160 120" aria-hidden="true" focusable="false">
        {/* a stitched creature head resting on the bench, eyes closed */}
        <path d="M20 104h120" stroke="#6d5532" strokeWidth="4" strokeLinecap="round" />
        <path d="M40 100c-6-30 4-62 40-64s48 32 40 64Z" fill="#1b2a24" stroke="#5f7280" strokeWidth="1.5" />
        <path d="M44 56h72" stroke="#e8dfc8" strokeOpacity=".5" strokeWidth="1.5" strokeDasharray="5 4" />
        <path d="M52 52v8M64 52v8M76 52v8M88 52v8M100 52v8M112 52v8" stroke="#e8dfc8" strokeOpacity=".45" strokeWidth="1.2" />
        <path d="M60 76c4 4 10 4 14 0M88 76c4 4 10 4 14 0" stroke="#b7c4c2" strokeWidth="2" strokeLinecap="round" fill="none" />
        <path d="M74 90c4 2 8 2 12 0" stroke="#b7c4c2" strokeWidth="1.6" strokeLinecap="round" fill="none" />
        <path d="M34 54l-8-6M126 54l8-6" stroke="#9fd3ff" strokeOpacity=".5" strokeWidth="2" strokeLinecap="round" />
        <text x="122" y="30" fill="#9fd3ff" fillOpacity=".7" fontSize="14" fontFamily="serif">z</text>
        <text x="132" y="18" fill="#9fd3ff" fillOpacity=".5" fontSize="11" fontFamily="serif">z</text>
      </svg>
      <h2 id="sleeps-title">{t('sleeps.title')}</h2>
      <p className="muted" style={{ maxInlineSize: '52ch' }}>
        {t('sleeps.body')}
      </p>
      <button
        type="button"
        className="btn btn--primary"
        aria-disabled={busy}
        onClick={async () => {
          if (busy) return;
          setBusy(true);
          await retryHealth();
          setBusy(false);
        }}
      >
        {busy ? t('sleeps.retrying') : t('sleeps.retry')}
      </button>
    </section>
  );
}
