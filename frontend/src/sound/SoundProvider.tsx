'use client';
import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { usePrefs } from '@/state/prefs';
import { SoundEngine } from './engine';
import type { SoundId } from './voices';

interface Ctx {
  play: (id: SoundId) => void;
}
const SoundCtx = createContext<Ctx>({ play: () => {} });

/** Sound is off by default; the AudioContext exists only after the toggle (autoplay policy). */
export function SoundProvider({ children }: { children: ReactNode }) {
  const { sound } = usePrefs();
  const engine = useRef<SoundEngine | null>(null);
  useEffect(() => {
    if (sound) {
      engine.current ??= new SoundEngine();
      void engine.current.enable();
    } else void engine.current?.disable();
  }, [sound]);
  const value = useMemo<Ctx>(() => ({ play: (id) => (sound ? engine.current?.play(id) : undefined) }), [sound]);
  return <SoundCtx.Provider value={value}>{children}</SoundCtx.Provider>;
}

export const useSound = () => useContext(SoundCtx);
