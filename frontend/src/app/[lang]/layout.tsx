import type { Metadata, Viewport } from 'next';
import localFont from 'next/font/local';
import type { ReactNode } from 'react';
import '@/styles/globals.css';
import en from '@/i18n/messages/en.json';
import ur from '@/i18n/messages/ur.json';
import { dirOf, isLang, LANGS, type Dict } from '@/i18n/t';
import { PREFS_BOOT_SCRIPT } from '@/state/prefs';
import { Providers } from '../Providers';

// Self-hosted OFL fonts (THIRD_PARTY.md). Urdu faces are not preloaded; English pages never request them.
const cinzel = localFont({
  src: [
    { path: '../../../public/fonts/cinzel-latin-400-normal.woff2', weight: '400' },
    { path: '../../../public/fonts/cinzel-latin-700-normal.woff2', weight: '700' },
  ],
  variable: '--font-cinzel',
  display: 'swap',
  fallback: ['Georgia', 'serif'],
});
const notoSans = localFont({
  src: [
    { path: '../../../public/fonts/noto-sans-latin-400-normal.woff2', weight: '400' },
    { path: '../../../public/fonts/noto-sans-latin-700-normal.woff2', weight: '700' },
  ],
  variable: '--font-noto-sans',
  display: 'swap',
  fallback: ['system-ui', 'Segoe UI', 'Arial', 'sans-serif'],
});
const nastaliq = localFont({
  src: [
    { path: '../../../public/fonts/noto-nastaliq-urdu-arabic-400-normal.woff2', weight: '400' },
    { path: '../../../public/fonts/noto-nastaliq-urdu-arabic-700-normal.woff2', weight: '700' },
  ],
  variable: '--font-nastaliq',
  display: 'swap',
  preload: false,
  fallback: ['serif'],
});
const naskh = localFont({
  src: [
    { path: '../../../public/fonts/noto-naskh-arabic-arabic-400-normal.woff2', weight: '400' },
    { path: '../../../public/fonts/noto-naskh-arabic-arabic-700-normal.woff2', weight: '700' },
  ],
  variable: '--font-naskh',
  display: 'swap',
  preload: false,
  fallback: ['Tahoma', 'sans-serif'],
});

const DICTS: Record<'en' | 'ur', Dict> = { en, ur };

export const dynamicParams = false;
export function generateStaticParams() {
  return LANGS.map((lang) => ({ lang }));
}

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }): Promise<Metadata> {
  const { lang } = await params;
  const d = DICTS[isLang(lang) ? lang : 'en'];
  return {
    title: d['app.title'],
    description: d['app.description'],
    alternates: { languages: { en: '/en/', ur: '/ur/' } },
    icons: { icon: '/favicon.svg' },
  };
}

export const viewport: Viewport = { themeColor: '#07090c', colorScheme: 'dark', width: 'device-width', initialScale: 1 };

export default async function LangLayout({ children, params }: { children: ReactNode; params: Promise<{ lang: string }> }) {
  const { lang: raw } = await params;
  const lang = isLang(raw) ? raw : 'en';
  const fonts = [cinzel.variable, notoSans.variable, ...(lang === 'ur' ? [nastaliq.variable, naskh.variable] : [])].join(' ');
  return (
    <html lang={lang} dir={dirOf(lang)} className={fonts} data-fx="full" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: PREFS_BOOT_SCRIPT }} />
      </head>
      <body>
        <div id="app-root">
          <Providers lang={lang} dict={DICTS[lang]}>
            {children}
          </Providers>
        </div>
      </body>
    </html>
  );
}
