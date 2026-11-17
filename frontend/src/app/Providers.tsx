'use client';
import { domAnimation, LazyMotion, MotionConfig } from 'motion/react';
import type { ReactNode } from 'react';
import type { Lang } from '@/api/types';
import { LangProvider } from '@/i18n/LangProvider';
import type { Dict } from '@/i18n/t';
import { SoundProvider } from '@/sound/SoundProvider';
import { PrefsProvider, usePrefs } from '@/state/prefs';

function WithLang({ lang, dict, children }: { lang: Lang; dict: Dict; children: ReactNode }) {
  const { digits, fx } = usePrefs();
  return (
    <LangProvider lang={lang} dict={dict} digits={digits}>
      <MotionConfig reducedMotion={fx === 'none' ? 'always' : 'user'}>{children}</MotionConfig>
    </LangProvider>
  );
}

export function Providers({ lang, dict, children }: { lang: Lang; dict: Dict; children: ReactNode }) {
  return (
    <PrefsProvider>
      <LazyMotion features={domAnimation} strict>
        <WithLang lang={lang} dict={dict}>
          <SoundProvider>{children}</SoundProvider>
        </WithLang>
      </LazyMotion>
    </PrefsProvider>
  );
}
