'use client';
// The single panel wrapper: every panel renders one of six states from one prop (design section 10).
import type { ReactNode } from 'react';
import { IconInfo, IconWarning, IconWifiOff } from '@/components/icons';
import { useLang } from '@/i18n/LangProvider';

export type PanelState = 'loading' | 'empty' | 'partial' | 'error' | 'offline' | 'success';

export interface PanelError {
  reason?: string;
  code?: string;
  missing?: string[];
  onRetry?: () => void;
  retryLabel?: string;
}

export function Skeleton({ lines = 3, block = false }: { lines?: number; block?: boolean }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {block ? <div className="skeleton__block" /> : null}
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton__line" style={{ inlineSize: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, title }: { error: PanelError; title?: string }) {
  const { t } = useLang();
  return (
    <div className="state state--error" role="alert" data-state="error">
      <p className="state__title">
        <IconWarning />
        {title ?? t('section.error.title')}
      </p>
      <p className="small">
        {t('section.error.reason', { reason: error.code ? `${error.code}: ${error.reason ?? ''}` : (error.reason ?? t('section.error.noReason')) })}
      </p>
      {error.missing?.length ? <p className="small">{t('section.error.missing', { missing: error.missing.join(', ') })}</p> : null}
      {error.onRetry ? (
        <div>
          <button type="button" className="btn btn--small" onClick={error.onRetry}>
            {error.retryLabel ?? t('section.error.retry')}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function Panel({
  id,
  title,
  icon,
  state,
  headerExtra,
  loadingText,
  emptyText,
  partialText,
  offlineText,
  error,
  className = '',
  children,
  skeleton,
  as = 'section',
}: {
  id?: string;
  title: ReactNode;
  icon?: ReactNode;
  state: PanelState;
  headerExtra?: ReactNode;
  loadingText?: string;
  emptyText?: string;
  partialText?: string;
  offlineText?: string;
  error?: PanelError;
  className?: string;
  children?: ReactNode;
  skeleton?: ReactNode;
  as?: 'section' | 'article';
}) {
  const { t } = useLang();
  const Tag = as;
  const headingId = id ? `${id}-title` : undefined;
  return (
    <Tag className={`panel ${className}`} id={id} aria-labelledby={headingId} aria-busy={state === 'loading'} data-panel-state={state}>
      <div className="panel__head">
        {icon}
        <h2 id={headingId}>{title}</h2>
        {headerExtra ? <div className="spacer chips">{headerExtra}</div> : null}
      </div>
      {state === 'loading' ? (
        <div role="status" className="state" style={{ borderStyle: 'none', padding: 0, background: 'none' }}>
          <span className="small muted">{loadingText ?? t('common.loading')}</span>
          {skeleton ?? <Skeleton />}
        </div>
      ) : null}
      {state === 'empty' ? (
        <p className="state small muted" data-state="empty">
          {emptyText ?? t('section.empty')}
        </p>
      ) : null}
      {state === 'error' ? <ErrorState error={error ?? {}} /> : null}
      {state === 'partial' && partialText ? (
        <p className="state state--partial small" data-state="partial">
          <span className="state__title">
            <IconInfo />
            {partialText}
          </span>
        </p>
      ) : null}
      {state === 'offline' && offlineText ? (
        <p className="state state--offline small" data-state="offline">
          <span className="state__title">
            <IconWifiOff />
            {offlineText}
          </span>
        </p>
      ) : null}
      {state === 'success' || state === 'partial' || state === 'offline' ? children : null}
    </Tag>
  );
}
