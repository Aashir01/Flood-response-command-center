'use client';
// UI preferences: high contrast, sound, digits, and the motion level (fx). Persisted per browser.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Digits } from '@/i18n/format';
import { chooseFx, type Fx } from '@/motion/fx';
import { KEYS, readPref, writePref } from '@/lib/storage';

interface Prefs {
  contrast: boolean;
  setContrast: (v: boolean) => void;
  sound: boolean;
  setSound: (v: boolean) => void;
  digits: Digits;
  setDigits: (d: Digits) => void;
  fx: Fx;
  reducedMotion: boolean;
}
const Ctx = createContext<Prefs | null>(null);

/** Inline script run before paint so the contrast theme never flashes (see [lang]/layout). */
export const PREFS_BOOT_SCRIPT = `(function(){try{var d=document.documentElement;var c=localStorage.getItem('${KEYS.contrast}');var m=window.matchMedia&&window.matchMedia('(prefers-contrast: more)').matches;if(c==='more'||(c===null&&m))d.setAttribute('data-contrast','more');var r=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;d.setAttribute('data-fx',r?'none':'full');}catch(e){}})();`;

function probeFx(): Fx {
  if (typeof window === 'undefined') return 'full';
  const nav = navigator as Navigator & { deviceMemory?: number };
  return chooseFx({
    reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
    hardwareConcurrency: nav.hardwareConcurrency,
    deviceMemory: nav.deviceMemory,
  });
}

export function PrefsProvider({ children, initial }: { children: ReactNode; initial?: Partial<Pick<Prefs, 'contrast' | 'sound' | 'digits' | 'fx'>> }) {
  const [contrast, setContrastState] = useState<boolean>(initial?.contrast ?? false);
  const [sound, setSoundState] = useState<boolean>(initial?.sound ?? false);
  const [digits, setDigitsState] = useState<Digits>(initial?.digits ?? 'latn');
  const [fx, setFx] = useState<Fx>(initial?.fx ?? 'full');

  // Hydrate from storage after mount (static HTML always renders the defaults).
  useEffect(() => {
    if (initial) return;
    const c = readPref(KEYS.contrast);
    const prefersMore = window.matchMedia?.('(prefers-contrast: more)').matches ?? false;
    /* eslint-disable react-hooks/set-state-in-effect -- one-time hydration from storage */
    setContrastState(c === 'more' || (c === null && prefersMore));
    setSoundState(readPref(KEYS.sound) === 'on');
    setDigitsState(readPref(KEYS.digits) === 'arabext' ? 'arabext' : 'latn');
    let chosen = probeFx();
    setFx(chosen);
    /* eslint-enable react-hooks/set-state-in-effect */
    // Frame-rate probe over the first 500 ms: under 40 fps drops to the lite effects.
    if (chosen !== 'full') return;
    let frames = 0;
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      frames++;
      if (t - t0 < 500) raf = requestAnimationFrame(tick);
      else if ((frames * 1000) / (t - t0) < 40 && document.visibilityState === 'visible') {
        chosen = 'lite';
        setFx('lite');
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [initial]);

  useEffect(() => {
    const d = document.documentElement;
    if (contrast) d.setAttribute('data-contrast', 'more');
    else d.removeAttribute('data-contrast');
  }, [contrast]);
  useEffect(() => {
    document.documentElement.setAttribute('data-fx', fx);
  }, [fx]);

  const setContrast = useCallback((v: boolean) => {
    setContrastState(v);
    writePref(KEYS.contrast, v ? 'more' : 'normal');
  }, []);
  const setSound = useCallback((v: boolean) => {
    setSoundState(v);
    writePref(KEYS.sound, v ? 'on' : 'off');
  }, []);
  const setDigits = useCallback((d: Digits) => {
    setDigitsState(d);
    writePref(KEYS.digits, d);
  }, []);

  const value = useMemo<Prefs>(
    () => ({ contrast, setContrast, sound, setSound, digits, setDigits, fx, reducedMotion: fx === 'none' }),
    [contrast, setContrast, sound, setSound, digits, setDigits, fx],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePrefs(): Prefs {
  const v = useContext(Ctx);
  if (!v) throw new Error('usePrefs outside PrefsProvider');
  return v;
}
