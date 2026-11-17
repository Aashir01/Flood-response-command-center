'use client';
import { useCallback, useEffect, useState } from 'react';
import { isCitation, resolveEvidence } from '@/api/evidence';
import type { EvidenceRef, EvidenceValue } from '@/api/types';
import { Drawer } from '@/components/shell/Drawer';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import { hasKey } from '@/i18n/t';
import type { EvidenceRequest } from './EvidenceContext';
import { ModeledLabel } from './labels';

type Load = { status: 'loading' } | { status: 'ok'; value: EvidenceValue } | { status: 'error'; reason: string };

function preview(v: unknown): string {
  const s = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
  return s.length > 4000 ? `${s.slice(0, 4000)}\n…` : s;
}

function EvidenceItem({ refItem, index }: { refItem: EvidenceRef; index: number }) {
  const { t, dict } = useLang();
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const run = useCallback(() => {
    setLoad({ status: 'loading' });
    void resolveEvidence(refItem).then((r) => setLoad(r.ok ? { status: 'ok', value: r.value } : { status: 'error', reason: `${r.error.code}: ${r.error.message}` }));
  }, [refItem]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on open
  useEffect(run, [run]);
  const organKey = `organ.${refItem.organ}`;
  const organName = hasKey(dict, organKey) ? t(organKey) : refItem.organ;
  const value = load.status === 'ok' ? load.value.value : undefined;
  const cite = isCitation(value) ? value : null;

  return (
    <li className="evidence-item" data-testid="evidence-item">
      <div className="evidence-item__head">
        <span>
          {index + 1}. {organName}
        </span>
        {refItem.organ === 'oracle' ? <ModeledLabel /> : null}
      </div>
      <dl className="kv">
        <dt>{t('evidence.organ')}</dt>
        <dd>
          <Bdi ltr>{refItem.organ}</Bdi>
          {refItem.organ === 'brain' ? <span className="muted"> · {t('evidence.brain')}</span> : null}
        </dd>
        <dt>{t('evidence.tool')}</dt>
        <dd>
          <Bdi ltr className="mono">
            {refItem.tool}
          </Bdi>
        </dd>
        <dt>{t('evidence.pointer')}</dt>
        <dd>
          <Bdi ltr className="mono">
            {refItem.json_pointer}
          </Bdi>
        </dd>
        {load.status === 'ok' ? (
          <>
            <dt>{t('evidence.servedBy')}</dt>
            <dd>
              <Bdi ltr>{load.value.served_by}</Bdi>
            </dd>
            <dt>{t('evidence.mode')}</dt>
            <dd>
              <Bdi ltr>{load.value.mode}</Bdi>
            </dd>
          </>
        ) : null}
      </dl>
      {load.status === 'loading' ? (
        <p className="small muted" role="status">
          {t('evidence.loading')}
        </p>
      ) : null}
      {load.status === 'error' ? (
        <div className="state state--error" role="alert">
          <p className="small">{t('evidence.error', { reason: load.reason })}</p>
          <div>
            <button type="button" className="btn btn--small" onClick={run}>
              {t('evidence.retry')}
            </button>
          </div>
        </div>
      ) : null}
      {load.status === 'ok' && cite ? (
        <div className="evidence-cite" data-testid="evidence-citation">
          <h4 className="small muted">{t('evidence.quote')}</h4>
          <blockquote className="quote" lang={cite.lang ?? undefined} dir="auto">
            {cite.quote}
          </blockquote>
          <p className="small">
            <Bdi>{t('evidence.source', { publisher: cite.publisher ?? '', title: cite.title ?? cite.doc_id, page: cite.page })}</Bdi>
          </p>
          {cite.url ? (
            <a href={cite.url} target="_blank" rel="noreferrer noopener" className="small">
              {t('evidence.open')}
            </a>
          ) : null}
        </div>
      ) : null}
      {load.status === 'ok' && !cite ? (
        <div>
          <h4 className="small muted">{t('evidence.value')}</h4>
          {typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? (
            <p dir="auto" data-testid="evidence-value">
              <Bdi>{String(value)}</Bdi>
            </p>
          ) : (
            <pre className="json" tabIndex={0} aria-label={t('evidence.value')} data-testid="evidence-value">
              {preview(value)}
            </pre>
          )}
        </div>
      ) : null}
    </li>
  );
}

export function EvidenceDrawer({ request, onClose }: { request: EvidenceRequest; onClose: () => void }) {
  const { t } = useLang();
  return (
    <Drawer open onClose={onClose} title={t('evidence.title')}>
      <div>
        <p className="small muted">{t('evidence.for')}</p>
        <p dir="auto" lang={request.claimLang}>
          {request.claimText}
        </p>
      </div>
      <ol className="claims" style={{ listStyle: 'none' }}>
        {request.refs.map((r, i) => (
          <EvidenceItem key={`${r.run_id}${r.json_pointer}`} refItem={r} index={i} />
        ))}
      </ol>
    </Drawer>
  );
}
