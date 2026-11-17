'use client';
// Announces organ state changes and briefing completion (FRN-R11.3). Polite and assertive regions,
// deduplicated by announcement id and rate-limited to one message per 400 ms.
import { useEffect, useRef, useState } from 'react';
import { useLang } from '@/i18n/LangProvider';
import { hasKey } from '@/i18n/t';
import type { Announcement } from '@/state/benchReducer';

export const ANNOUNCE_GAP_MS = 400;

export function LiveRegion({ announcements }: { announcements: Announcement[] }) {
  const { t, dict } = useLang();
  const [polite, setPolite] = useState('');
  const [assertive, setAssertive] = useState('');
  const seen = useRef(new Set<number>());
  const queue = useRef<{ level: 'polite' | 'assertive'; text: string }[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const render = (a: Announcement) => {
      const params: Record<string, string | number> = { ...a.params };
      if (typeof params.organ === 'string' && hasKey(dict, `organ.${params.organ}`)) params.organ = t(`organ.${params.organ}` as never);
      return hasKey(dict, a.key) ? t(a.key, params) : a.key;
    };
    for (const a of announcements) {
      if (seen.current.has(a.id)) continue;
      seen.current.add(a.id);
      queue.current.push({ level: a.level, text: render(a) });
    }
    if (announcements.length === 0) seen.current.clear();
    const pump = () => {
      const next = queue.current.shift();
      if (!next) {
        timer.current = null;
        return;
      }
      if (next.level === 'assertive') setAssertive(next.text);
      else setPolite(next.text);
      timer.current = setTimeout(pump, ANNOUNCE_GAP_MS);
    };
    if (!timer.current) pump();
  }, [announcements, t, dict]);

  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  return (
    <>
      <div className="sr-only" aria-live="polite" aria-atomic="true" data-testid="live-polite">
        {polite}
      </div>
      <div className="sr-only" role="alert" aria-live="assertive" aria-atomic="true" data-testid="live-assertive">
        {assertive}
      </div>
    </>
  );
}
