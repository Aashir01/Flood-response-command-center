'use client';
// Lightning awakening (FRN-R1): plays on boot and, shorter, when a briefing completes. Skippable by the Skip
// button, Esc, Enter, Space or a click. Never traps focus; pointer events pass through except on Skip.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLang } from '@/i18n/LangProvider';
import { flashKeyframes, timelineFor, type AwakeningKind } from '@/motion/awakening';
import { usePrefs } from '@/state/prefs';

const BOLTS = [
  'M520 0 L470 120 L540 150 L430 330 L500 350 L380 560',
  'M500 350 L590 420 L560 470 L660 560',
  'M1180 40 L1120 170 L1190 190 L1080 380',
  'M1120 170 L1040 230 L1060 280',
  'M200 60 L250 180 L190 200 L270 340',
];

export function LightningAwakening({ play, onDone, onThunder }: { play: { kind: AwakeningKind; key: number } | null; onDone: () => void; onThunder?: () => void }) {
  const { t } = useLang();
  const { fx } = usePrefs();
  const [active, setActive] = useState<{ kind: AwakeningKind; key: number } | null>(null);
  const flashRef = useRef<HTMLDivElement>(null);
  const veilRef = useRef<HTMLDivElement>(null);
  const boltsRef = useRef<SVGSVGElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const anims = useRef<Animation[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const finish = useCallback(() => {
    for (const a of anims.current) a.cancel();
    anims.current = [];
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setActive(null);
    onDone();
  }, [onDone]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start a new play when asked
    if (play) setActive(play);
  }, [play]);

  useEffect(() => {
    if (!active) return;
    const tl = timelineFor(active.kind, fx);
    const can = typeof Element !== 'undefined' && typeof Element.prototype.animate === 'function';
    if (can) {
      if (flashRef.current) anims.current.push(flashRef.current.animate(flashKeyframes(tl), { duration: tl.totalMs, fill: 'forwards', easing: 'linear' }));
      if (veilRef.current && tl.veil.opacity > 0)
        anims.current.push(
          veilRef.current.animate(
            [
              { opacity: tl.veil.opacity, offset: 0 },
              { opacity: tl.veil.opacity, offset: tl.veil.holdUntil / tl.totalMs },
              { opacity: 0, offset: 1 },
            ],
            { duration: tl.totalMs, fill: 'forwards', easing: 'ease-out' },
          ),
        );
      if (textRef.current)
        anims.current.push(
          textRef.current.animate(
            [
              { opacity: 0, offset: 0 },
              { opacity: 1, offset: Math.min(0.3, 300 / tl.totalMs) },
              { opacity: 1, offset: 0.7 },
              { opacity: 0, offset: 1 },
            ],
            { duration: tl.totalMs, fill: 'forwards' },
          ),
        );
      if (boltsRef.current && tl.bolts) {
        const b = tl.bolts;
        boltsRef.current.querySelectorAll('path').forEach((p, i) => {
          const len = 900;
          p.style.strokeDasharray = `${len}`;
          anims.current.push(
            p.animate(
              [
                { strokeDashoffset: len, opacity: 1, offset: 0 },
                { strokeDashoffset: 0, opacity: 1, offset: (b.to - (i % 2) * 60) / tl.totalMs },
                { strokeDashoffset: 0, opacity: 1, offset: b.fadeAt / tl.totalMs },
                { strokeDashoffset: 0, opacity: 0, offset: Math.min(1, (b.fadeAt + 400) / tl.totalMs) },
                { strokeDashoffset: 0, opacity: 0, offset: 1 },
              ],
              { duration: tl.totalMs, fill: 'forwards' },
            ),
          );
        });
      }
    }
    if (tl.flashes.length) setTimeout(() => onThunder?.(), tl.flashes[0]?.at ?? 0);
    timer.current = setTimeout(finish, tl.totalMs);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') finish();
    };
    const onPointer = () => finish();
    window.addEventListener('keydown', onKey);
    window.addEventListener('pointerdown', onPointer);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pointerdown', onPointer);
      if (timer.current) clearTimeout(timer.current);
    };
  }, [active, fx, finish, onThunder]);

  if (!active) return null;
  const tl = timelineFor(active.kind, fx);
  return (
    <div className="awakening" data-testid="awakening" data-kind={active.kind} data-timeline={tl.id}>
      <div aria-hidden="true">
        {tl.veil.opacity > 0 ? <div ref={veilRef} className="awakening__veil" style={{ opacity: tl.veil.opacity }} /> : null}
        {tl.bolts ? (
          <svg ref={boltsRef} className="awakening__bolts" viewBox="0 0 1400 600" preserveAspectRatio="xMidYMin slice" data-testid="bolts">
            {BOLTS.map((d) => (
              <path key={d} d={d} />
            ))}
          </svg>
        ) : null}
        <div ref={flashRef} className="awakening__flash" />
        {tl.veil.opacity > 0 ? (
          <div ref={textRef} style={{ opacity: 0 }}>
            <div className="awakening__title">{active.kind === 'boot' ? t('awaken.title') : t('awaken.complete')}</div>
            {active.kind === 'boot' ? <div className="awakening__sub">{t('awaken.sub')}</div> : null}
          </div>
        ) : null}
      </div>
      <button type="button" className="btn awakening__skip" onClick={finish} data-testid="awakening-skip">
        {t('awaken.skip')}
      </button>
    </div>
  );
}
