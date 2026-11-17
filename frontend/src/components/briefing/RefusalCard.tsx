'use client';
import type { Citation } from '@/api/types';
import { IconRefusal } from '@/components/icons';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import { hasKey } from '@/i18n/t';

export interface RefusalInfo {
  reason?: string | null;
  closest_hits?: Citation[];
}

/** A refusal is a normal, labelled outcome with a neutral tone (FRN-R5.4). */
export function RefusalCard({ refusal, text, children }: { refusal?: RefusalInfo | null; text?: string; children?: React.ReactNode }) {
  const { t, dict } = useLang();
  const key = `refusal.title.${refusal?.reason ?? ''}`;
  return (
    <div className="refusal" data-testid="refusal-card" role="group" aria-label={hasKey(dict, key) ? t(key) : t('refusal.title.generic')}>
      <p className="refusal__title">
        <IconRefusal />
        {hasKey(dict, key) ? t(key) : t('refusal.title.generic')}
      </p>
      {text ? <p dir="auto">{text}</p> : null}
      <p className="small muted">{t('refusal.body')}</p>
      {refusal?.closest_hits?.length ? (
        <details className="disclosure">
          <summary>{t('refusal.closest')}</summary>
          <ul className="hits">
            {refusal.closest_hits.map((h) => (
              <li key={`${h.doc_id}-${h.page}-${h.span?.[0] ?? 0}`}>
                <blockquote className="quote" lang={h.lang} dir="auto">
                  {h.quote}
                </blockquote>
                <p className="small muted">
                  <Bdi>{t('evidence.source', { publisher: h.publisher, title: h.title, page: h.page })}</Bdi>
                </p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {children}
    </div>
  );
}
