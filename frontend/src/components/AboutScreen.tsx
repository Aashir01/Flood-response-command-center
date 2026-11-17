'use client';
import { ModeledLabel } from '@/components/briefing/labels';
import { SimpleScreen } from '@/components/SimpleScreen';
import { useLang } from '@/i18n/LangProvider';

export function AboutScreen() {
  const { t } = useLang();
  return (
    <SimpleScreen route="about/">
      <article className="panel prose" aria-labelledby="about-title">
        <h1 id="about-title">{t('about.title')}</h1>
        <p>{t('about.intro')}</p>
        <div className="banner banner--offline" role="note">
          <span>{t('about.notOperational')}</span>
        </div>
        <h2>{t('about.honest')}</h2>
        <ul>
          <li>{t('about.honest.eyes')}</li>
          <li data-oracle-value="">
            {t('about.honest.oracle')} <ModeledLabel />
          </li>
          <li>{t('about.honest.library')}</li>
          <li>{t('about.honest.ledger')}</li>
          <li>{t('about.honest.voice')}</li>
        </ul>
        <h2>{t('about.credits')}</h2>
        <ul>
          <li>{t('about.credits.geo')}</li>
          <li>{t('about.credits.ne')}</li>
          <li>{t('about.credits.weather')}</li>
          <li>{t('about.credits.pop')}</li>
          <li>{t('about.credits.fonts')}</li>
          <li>{t('about.credits.sound')}</li>
        </ul>
        <p className="small muted">{t('about.urdu')}</p>
      </article>
    </SimpleScreen>
  );
}
