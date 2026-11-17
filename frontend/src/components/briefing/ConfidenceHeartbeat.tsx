'use client';
import { useLang } from '@/i18n/LangProvider';
import { getAnim } from '@/motion/registry';
import { confidenceBand } from '@/state/selectors';

const BEAT = getAnim('heartbeat-strip');

/** Heartbeat strip: amplitude follows confidence; one beat per >= 1200 ms (FRN-P5). Value and band always shown as text. */
export function ConfidenceHeartbeat({ confidence }: { confidence: number }) {
  const { t, fmt } = useLang();
  const band = confidenceBand(confidence);
  const amp = 4 + 16 * Math.max(0, Math.min(1, confidence));
  const mid = 22;
  const d = `M0 ${mid} H46 L52 ${mid - amp * 0.4} L58 ${mid} L64 ${mid} L70 ${mid + amp * 0.35} L76 ${mid - amp} L82 ${mid + amp * 0.6} L88 ${mid} H120 L126 ${mid - amp * 0.3} L132 ${mid} H180`;
  return (
    <div className="heartbeat" data-band={band} data-testid="confidence">
      <svg viewBox="0 0 180 44" aria-hidden="true" focusable="false">
        <path d={`M0 ${mid} H180`} stroke="currentColor" strokeOpacity=".15" />
        <path className="heartbeat__line" d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" style={{ animationDuration: `${BEAT.periodMs}ms` }} />
      </svg>
      <div>
        <div className="small muted">{t('briefing.confidence')}</div>
        <div className="heartbeat__value">{fmt.pct(confidence)}</div>
      </div>
      <span className="chip chip--demo">{t(`briefing.confidenceBand.${band}`)}</span>
      <p className="small muted" style={{ flexBasis: '100%' }}>
        {t('briefing.confidenceHelp')}
      </p>
    </div>
  );
}
