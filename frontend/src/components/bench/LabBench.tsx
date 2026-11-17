'use client';
import { useCallback, useState } from 'react';
import { ORGAN_IDS, type OrganId } from '@/api/types';
import { useLang } from '@/i18n/LangProvider';
import { useBench } from '@/state/BenchProvider';
import { OrganDrawer } from './OrganDrawer';
import { OrganJar } from './OrganJar';

export function LabBench() {
  const { t } = useLang();
  const { state, healthStatus } = useBench();
  const [open, setOpen] = useState<OrganId | null>(null);
  const onOpen = useCallback((o: OrganId) => setOpen(o), []);
  const onClose = useCallback(() => setOpen(null), []);

  return (
    <section className="bench" aria-labelledby="bench-title" id="bench" tabIndex={-1} aria-busy={healthStatus === 'loading'}>
      <div className="bench__head">
        <h2 id="bench-title">{t('bench.title')}</h2>
        <p className="small muted">{healthStatus === 'loading' ? t('bench.loading') : t('bench.subtitle')}</p>
      </div>
      <ul className="bench__rail">
        {ORGAN_IDS.map((o) => (
          <li key={o}>
            <OrganJar organ={o} view={state.organs[o]} onOpen={onOpen} expanded={open === o} />
          </li>
        ))}
      </ul>
      <OrganDrawer organ={open} onClose={onClose} />
    </section>
  );
}
