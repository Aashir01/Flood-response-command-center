'use client';
import type { Claim, Lang } from '@/api/types';
import { IconEvidence } from '@/components/icons';
import { useLang } from '@/i18n/LangProvider';
import { useEvidence } from './EvidenceContext';
import { LabelChip, ModeledLabel } from './labels';

export class UnverifiedClaimError extends Error {
  constructor(id: string) {
    super(`claim ${id} has no evidence and cannot render (FRN-P4)`);
  }
}

const shorten = (s: string, n = 60) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** A claim always renders with an accessible evidence control; a claim without evidence cannot render (FRN-P4). */
export function ClaimItem({ claim, lang, extra }: { claim: Claim; lang: Lang; extra?: React.ReactNode }) {
  const { t } = useLang();
  const { open } = useEvidence();
  if (!claim.evidence || claim.evidence.length === 0) {
    if (process.env.NODE_ENV !== 'production') throw new UnverifiedClaimError(claim.id);
    return (
      <li className="sr-only" data-removed-claim={claim.id}>
        {t('claim.removed')}
      </li>
    );
  }
  const labels = claim.labels ?? [];
  const oracle = claim.evidence.some((e) => e.organ === 'oracle');
  const disputed = labels.includes('disputed');
  const kindKey = claim.kind === 'number' ? 'claim.kind.number' : claim.kind === 'recommendation' ? 'claim.kind.recommendation' : 'claim.kind.statement';
  return (
    <li className="claim" data-claim-id={claim.id} data-kind={claim.kind} data-disputed={disputed} {...(oracle ? { 'data-oracle-value': '' } : {})}>
      <p className="claim__text" dir="auto" lang={lang}>
        {claim.text}
      </p>
      <button
        type="button"
        className="btn btn--evidence"
        aria-label={t('claim.evidenceFor', { n: claim.evidence.length, text: shorten(claim.text) })}
        aria-haspopup="dialog"
        onClick={() => open({ refs: claim.evidence, claimText: claim.text, claimLang: lang })}
        data-testid="evidence-button"
      >
        <IconEvidence />
        <span>
          {t('claim.evidence')} ({claim.evidence.length})
        </span>
      </button>
      <div className="claim__meta">
        <span className="claim__kind">{t(kindKey)}</span>
        {oracle && !labels.includes('modeled') ? <ModeledLabel /> : null}
        {labels.map((l) => (
          <LabelChip key={l} label={l} />
        ))}
        {extra}
      </div>
    </li>
  );
}
