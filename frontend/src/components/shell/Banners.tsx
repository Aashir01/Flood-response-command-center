'use client';
import { IconDemo, IconInfo, IconWifiOff } from '@/components/icons';
import { useLang } from '@/i18n/LangProvider';

export function DecisionSupportNotice() {
  const { t } = useLang();
  return (
    <div className="banner" role="note" data-testid="decision-support">
      <IconInfo />
      <span>{t('notice.decisionSupport')}</span>
    </div>
  );
}

export function DemoNotice() {
  const { t } = useLang();
  return (
    <div className="banner banner--demo" role="note" data-testid="demo-banner">
      <IconDemo />
      <span>{t('notice.demo')}</span>
    </div>
  );
}

export function OfflineBanner({ reason }: { reason: 'offline' | 'fallback' }) {
  const { t } = useLang();
  return (
    <div className="banner banner--offline" role="status" data-testid="offline-banner">
      <IconWifiOff />
      <span>
        <strong>{t('notice.offline')}</strong> {reason === 'fallback' ? t('notice.fallback') : null}
      </span>
    </div>
  );
}
