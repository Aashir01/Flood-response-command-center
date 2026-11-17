'use client';
import { IconContrast, IconGlobe, IconSound } from '@/components/icons';
import { useLang } from '@/i18n/LangProvider';
import { usePrefs } from '@/state/prefs';

export type Route = '' | 'evals/' | 'about/';

function BrandMark() {
  // A stitched heart-and-bolt: the creature's seal.
  return (
    <svg className="brand__mark" viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <circle cx="20" cy="20" r="18" fill="#0d1217" stroke="#5f7280" />
      <path d="M20 31c-7-5-12-9-12-15a6 6 0 0 1 12-2 6 6 0 0 1 12 2c0 6-5 10-12 15Z" fill="none" stroke="#2cf5c0" strokeWidth="1.6" />
      <path d="M21.5 10.5 16 21h5l-2 8.5 6-11h-5l1.5-8Z" fill="#9fd3ff" />
      <path d="M9 18h3M28 18h3M11 23h2.5M26.5 23H29" stroke="#e8dfc8" strokeOpacity=".7" strokeWidth="1.2" />
    </svg>
  );
}

export function Header({ route, mode }: { route: Route; mode?: 'demo' | 'live' }) {
  const { t, lang } = useLang();
  const { contrast, setContrast, sound, setSound, digits, setDigits } = usePrefs();
  const other = lang === 'en' ? 'ur' : 'en';
  const nav: [Route, 'nav.bench' | 'nav.evals' | 'nav.about'][] = [
    ['', 'nav.bench'],
    ['evals/', 'nav.evals'],
    ['about/', 'nav.about'],
  ];
  return (
    <header className="site-header">
      <div className="header-inner">
        <a className="brand" href={`/${lang}/`}>
          <BrandMark />
          <span>
            <span className="brand__name">{t('app.name')}</span>
            <span className="brand__sub">{t('app.tagline')}</span>
          </span>
        </a>
        <nav className="header-nav" aria-label={t('nav.label')}>
          {nav.map(([r, key]) => (
            <a key={r} href={`/${lang}/${r}`} aria-current={r === route ? 'page' : undefined}>
              {t(key)}
            </a>
          ))}
        </nav>
        <div className="header-tools" role="group" aria-label={t('header.tools')}>
          {mode ? (
            <span className={`mode-badge mode-badge--${mode}`} data-testid="mode-badge">
              <span className="sr-only">{t('mode.badge', { mode: '' })}</span>
              {t(mode === 'demo' ? 'mode.demo' : 'mode.live')}
            </span>
          ) : null}
          <a className="tool-btn" href={`/${other}/${route}`} hrefLang={other} lang={other} aria-label={t('lang.switchLabel')} data-testid="lang-toggle">
            <IconGlobe />
            <span>{t('lang.switchTo')}</span>
          </a>
          {lang === 'ur' ? (
            <button type="button" className="tool-btn" aria-pressed={digits === 'arabext'} onClick={() => setDigits(digits === 'arabext' ? 'latn' : 'arabext')}>
              <span aria-hidden="true">۱۲۳</span>
              <span>{t('digits.label')}</span>
            </button>
          ) : null}
          <button type="button" className="tool-btn" aria-pressed={contrast} onClick={() => setContrast(!contrast)} data-testid="contrast-toggle">
            <IconContrast />
            <span>{t('contrast.label')}</span>
          </button>
          <button type="button" className="tool-btn" aria-pressed={sound} onClick={() => setSound(!sound)} data-testid="sound-toggle">
            <IconSound on={sound} />
            <span>{t('sound.label')}</span>
          </button>
        </div>
      </div>
    </header>
  );
}

export function Footer({ contract, brain }: { contract?: string; brain?: string }) {
  const { t, lang } = useLang();
  return (
    <footer className="site-footer">
      <p>{t('footer.disclaimer')}</p>
      <p>
        {contract ? <span>{t('footer.contract', { version: contract })} · </span> : null}
        {brain ? <span>{t('footer.brain', { version: brain })} · </span> : null}
        <a href={`/${lang}/about/`}>{t('footer.license')}</a>
      </p>
    </footer>
  );
}
