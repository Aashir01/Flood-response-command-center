'use client';
import type { SegmentOut } from '@/api/types';
import { IconDemo, IconInfo, IconWarning } from '@/components/icons';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import { hasKey } from '@/i18n/t';

/**
 * Two separate labels, always shown together (FRN-R14.1): the demo scene, and the dataset the model was
 * validated on. When the scene is not validated for the region, a third line says so. Never merged.
 */
export function EyesLabels({ segment, mode }: { segment?: SegmentOut; mode: 'demo' | 'live' }) {
  const { t, dict, fmt } = useLang();
  // Before the Eyes output arrives, the demo scenario's scene date is known (demo-sindh-2022).
  const acquired = segment?.source_scene?.acquired ?? (mode === 'demo' ? '2022-08-30T00:00:00Z' : undefined);
  const dataset = segment?.validation?.eval_dataset ?? 'sen1floods11_test';
  const dsKey = `eyes.dataset.${dataset}`;
  const validatedHere = segment?.validation?.validated_for_region === true;
  const date = acquired ? new Intl.DateTimeFormat(fmt.lang === 'ur' ? 'ur-PK' : 'en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(acquired)) : t('common.unknown');
  return (
    <div className="eyes-labels" data-testid="eyes-labels" style={{ display: 'grid', gap: 6, marginBlockEnd: 12 }}>
      <div className="chips">
        <span className="chip chip--demo" data-eyes-label="scene">
          <IconDemo />
          {mode === 'demo' ? t('eyes.demoScene', { place: t('eyes.sindh'), date }) : <Bdi ltr>{segment?.source_scene?.scene_id ?? ''}</Bdi>}
        </span>
        <span className="chip chip--validated" data-eyes-label="validation">
          <IconInfo />
          {t('eyes.validated', { dataset: hasKey(dict, dsKey) ? t(dsKey) : dataset })}
        </span>
      </div>
      {!validatedHere ? (
        <p className="small" data-eyes-label="not-validated" style={{ display: 'flex', gap: 6, alignItems: 'center', color: '#ffc58f' }}>
          <IconWarning width={16} height={16} />
          {t('eyes.notValidated')}
        </p>
      ) : null}
    </div>
  );
}
