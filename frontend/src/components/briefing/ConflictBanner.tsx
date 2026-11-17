'use client';
import type { Conflict, Lang } from '@/api/types';
import { IconConflict, IconEvidence } from '@/components/icons';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import { hasKey } from '@/i18n/t';
import { useEvidence } from './EvidenceContext';

/** Conflicts sit above the cards; both sides' evidence side by side, neither styled as correct (FRN-R5.3). */
export function ConflictBanner({ conflicts, lang }: { conflicts: Conflict[]; lang: Lang }) {
  const { t, dict } = useLang();
  const { open } = useEvidence();
  if (!conflicts.length) return null;
  const organName = (o: string) => (hasKey(dict, `organ.${o}`) ? t(`organ.${o}` as never) : o);
  return (
    <section className="panel conflicts" aria-labelledby="conflicts-title" role="region" data-testid="conflict-banner">
      <div className="panel__head">
        <IconConflict className="panel__icon" aria-hidden="true" />
        <h2 id="conflicts-title">{t('conflict.title')}</h2>
      </div>
      <p className="small muted" style={{ marginBlockEnd: 10 }}>
        {t('conflict.intro')}
      </p>
      <ul className="claims">
        {conflicts.map((c) => {
          const resKey = `conflict.resolution.${c.resolution}`;
          return (
            <li key={c.id} className="conflict" data-conflict-id={c.id}>
              <div className="chips">
                <span className="chip chip--disputed">
                  <Bdi ltr>{c.id}</Bdi>
                </span>
                <span className="chip chip--demo">{hasKey(dict, resKey) ? t(resKey) : c.resolution}</span>
                {c.rule_id ? (
                  <span className="chip chip--recorded">
                    {t('conflict.rule', { rule: c.rule_id })}
                  </span>
                ) : null}
              </div>
              <p dir="auto" lang={lang}>
                {c.description}
              </p>
              <div className="conflict__sides">
                {c.evidence.map((e, i) => (
                  <div className="conflict__side" key={`${e.run_id}${e.json_pointer}`}>
                    <span className="small muted">{t('conflict.side', { organ: organName(e.organ) })}</span>
                    <button
                      type="button"
                      className="btn btn--evidence"
                      aria-haspopup="dialog"
                      aria-label={`${t('claim.evidence')} ${i + 1}: ${organName(e.organ)} (${e.tool})`}
                      onClick={() => open({ refs: [e], claimText: c.description, claimLang: lang })}
                    >
                      <IconEvidence />
                      <span>
                        {t('claim.evidence')} {i + 1}
                      </span>
                    </button>
                    <Bdi ltr className="mono small muted">
                      {e.tool}
                    </Bdi>
                  </div>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
