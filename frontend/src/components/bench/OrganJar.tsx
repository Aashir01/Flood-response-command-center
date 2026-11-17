'use client';
import { m } from 'motion/react';
import { memo } from 'react';
import type { OrganId } from '@/api/types';
import { useLang } from '@/i18n/LangProvider';
import type { MessageKey } from '@/i18n/t';
import { getAnim } from '@/motion/registry';
import type { OrganView } from '@/state/benchReducer';
import { usePrefs } from '@/state/prefs';
import { JarIllustration } from './JarArt';
import { STATE_KEY, StatusIcon } from './StatusIcon';

const GLOW: Record<OrganView['state'], string> = {
  idle: '#9fd3ff',
  calling: '#9fd3ff',
  done: '#2cf5c0',
  unwell: '#ff9d3c',
  disabled: '#000000',
};

const TWITCH = getAnim('jar-calling-twitch');
const CALL_GLOW = getAnim('jar-calling-glow');
const UNWELL = getAnim('jar-unwell-flicker');
const DONE = getAnim('jar-done-glow');

function glowAnim(state: OrganView['state'], animated: boolean) {
  if (state === 'calling')
    return animated
      ? { animate: { opacity: [0.55, 1, 0.55] }, transition: { duration: CALL_GLOW.durationMs / 1000, repeat: Infinity, ease: 'easeInOut' as const } }
      : { animate: { opacity: 0.85 }, transition: { duration: 0 } };
  if (state === 'unwell')
    return animated
      ? { animate: { opacity: [0.7, 1, 0.7] }, transition: { duration: UNWELL.durationMs / 1000, repeat: Infinity, ease: 'easeInOut' as const } }
      : { animate: { opacity: 0.85 }, transition: { duration: 0 } };
  if (state === 'done') return { animate: { opacity: 0.6 }, transition: { duration: animated ? DONE.durationMs / 1000 : 0 } };
  return { animate: { opacity: 0 }, transition: { duration: animated ? 0.24 : 0 } };
}

export const OrganJar = memo(function OrganJar({
  organ,
  view,
  onOpen,
  expanded,
}: {
  organ: OrganId;
  view: OrganView;
  onOpen: (organ: OrganId, el: HTMLButtonElement) => void;
  expanded: boolean;
}) {
  const { t } = useLang();
  const { fx } = usePrefs();
  const name = t(`organ.${organ}` as MessageKey);
  const stateText = t(STATE_KEY[view.state]);
  const note = view.state === 'unwell' ? view.note : view.note === 'queued' ? t('state.queued') : view.degraded ? t('state.degraded') : view.stub ? t('state.recorded') : undefined;
  const twitch = view.state === 'calling' && fx === 'full';
  const glow = glowAnim(view.state, fx !== 'none');
  const noteId = `jar-note-${organ}`;

  return (
    <button
      type="button"
      className="jar"
      data-organ={organ}
      data-state={view.state}
      aria-haspopup="dialog"
      aria-expanded={expanded}
      aria-describedby={noteId}
      onClick={(e) => onOpen(organ, e.currentTarget)}
    >
      <svg className="jar__art" viewBox="0 0 96 120" aria-hidden="true" focusable="false">
        <m.g className="jar-glow" initial={false} animate={glow.animate} transition={glow.transition}>
          <ellipse className="jar-glow--blur" cx="48" cy="66" rx="40" ry="48" fill={GLOW[view.state]} opacity=".35" />
          <ellipse cx="48" cy="66" rx="34" ry="42" fill="none" stroke={GLOW[view.state]} strokeOpacity=".55" strokeWidth="1.5" />
        </m.g>
        <m.g
          style={{ transformOrigin: '48px 110px' }}
          initial={false}
          animate={twitch ? { x: [0, -2, 2, -1, 1, 0], rotate: [0, -1, 1, 0, 0, 0] } : { x: 0, rotate: 0 }}
          transition={
            twitch
              ? { duration: TWITCH.durationMs / 1000, repeat: Infinity, repeatDelay: ((TWITCH.periodMs ?? 1300) - TWITCH.durationMs) / 1000, ease: [0.65, 0, 0.35, 1] }
              : { duration: 0.16 }
          }
        >
          <JarIllustration organ={organ} />
        </m.g>
        {/* bench shadow */}
        <ellipse cx="48" cy="114" rx="30" ry="3.5" fill="#000" opacity=".55" />
      </svg>
      <span className="jar__name">{name}</span>
      <span className="jar__status" data-testid={`jar-status-${organ}`}>
        <StatusIcon state={view.state} />
        <span>{stateText}</span>
      </span>
      <span className="jar__note" id={noteId}>
        {note ?? t(`organ.${organ}.role` as MessageKey)}
      </span>
    </button>
  );
});
