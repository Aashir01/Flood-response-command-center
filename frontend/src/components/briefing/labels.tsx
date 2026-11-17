'use client';
// Honest labels (FRN-R14). Every Oracle-derived value renders inside <OracleValue>, which always carries
// the "Modeled (GloFAS)" label (FRN-P6). The words "gauge" and "observed" are never used for Oracle output.
import type { ReactNode } from 'react';
import { IconDemo, IconPulse, IconWarning } from '@/components/icons';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';

export function ModeledLabel({ label }: { label?: string }) {
  const { t, lang } = useLang();
  // `target_label` is English from the Oracle; the short chip uses the dictionary so Urdu stays Urdu.
  return (
    <span className="modeled-label" data-modeled-label="" title={lang === 'en' && label ? label : undefined}>
      <IconPulse width={12} height={12} />
      {t('label.modeled')}
    </span>
  );
}

export function OracleValue({ children, unit, label }: { children: ReactNode; unit?: string; label?: string }) {
  return (
    <span className="oracle-value" data-oracle-value="">
      <Bdi>
        {children}
        {unit ? <> {unit}</> : null}
      </Bdi>
      <ModeledLabel label={label} />
    </span>
  );
}

const CHIP: Record<string, { cls: string; key: Parameters<ReturnType<typeof useLang>['t']>[0]; icon?: ReactNode }> = {
  modeled: { cls: 'chip--modeled', key: 'label.modeled' },
  unvalidated: { cls: 'chip--unvalidated', key: 'label.unvalidated', icon: <IconWarning /> },
  recorded: { cls: 'chip--recorded', key: 'label.recorded' },
  demo: { cls: 'chip--demo', key: 'label.demo', icon: <IconDemo /> },
  refusal: { cls: 'chip--refusal', key: 'label.refusal' },
  disputed: { cls: 'chip--disputed', key: 'label.disputed', icon: <IconWarning /> },
  live: { cls: 'chip--live', key: 'label.live' },
};

export function LabelChip({ label }: { label: string }) {
  const { t } = useLang();
  const c = CHIP[label];
  if (!c) return null;
  if (label === 'modeled') return <ModeledLabel />;
  return (
    <span className={`chip ${c.cls}`} data-label={label}>
      {c.icon}
      {t(c.key)}
    </span>
  );
}

export function ModeChip({ mode }: { mode: 'demo' | 'live' }) {
  return <LabelChip label={mode} />;
}
