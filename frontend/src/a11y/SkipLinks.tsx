'use client';
import { useLang } from '@/i18n/LangProvider';

export type SkipKey = 'skip.bench' | 'skip.briefing' | 'skip.ask' | 'skip.main';

/** Skip links: hidden until focused, first in the tab order after the awakening's Skip button. */
export function SkipLinks({ links }: { links: { href: string; key: SkipKey }[] }) {
  const { t } = useLang();
  return (
    <div className="skip-links">
      {links.map((l) => (
        <a key={l.href} href={l.href}>
          {t(l.key)}
        </a>
      ))}
    </div>
  );
}
