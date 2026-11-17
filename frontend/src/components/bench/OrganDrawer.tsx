'use client';
import type { OrganId } from '@/api/types';
import { Drawer } from '@/components/shell/Drawer';
import { Bdi } from '@/i18n/bidi';
import { useLang } from '@/i18n/LangProvider';
import type { MessageKey } from '@/i18n/t';
import { useBench } from '@/state/BenchProvider';
import { STATE_KEY, StatusIcon } from './StatusIcon';

export function OrganDrawer({ organ, onClose }: { organ: OrganId | null; onClose: () => void }) {
  const { t, fmt } = useLang();
  const { state, health } = useBench();
  const view = organ ? state.organs[organ] : null;
  const info = organ ? health?.organs.find((o) => o.organ === organ) : undefined;
  const calls = organ ? state.calls.filter((c) => c.organ === organ) : [];
  const last = view?.lastCall;
  const name = organ ? t(`organ.${organ}` as MessageKey) : '';

  return (
    <Drawer open={organ !== null} onClose={onClose} title={t('drawer.organTitle', { organ: name })}>
      {organ && view ? (
        <>
          <p className="muted">{t(`organ.${organ}.role` as MessageKey)}</p>
          <div className="jar__status" style={{ justifySelf: 'start' }} data-state={view.state}>
            <StatusIcon state={view.state} />
            <span>{t(STATE_KEY[view.state])}</span>
          </div>
          <section aria-labelledby="drawer-health">
            <h3 id="drawer-health">{t('drawer.health')}</h3>
            <dl className="kv">
              <dt>{t('drawer.health')}</dt>
              <dd>
                <Bdi ltr>{info?.status ?? t('common.unknown')}</Bdi>
                {info?.served_by ? (
                  <>
                    {' · '}
                    <Bdi ltr>{info.served_by}</Bdi>
                  </>
                ) : null}
              </dd>
              {info?.version ? (
                <>
                  <dt>version</dt>
                  <dd>
                    <Bdi ltr>{info.version}</Bdi>
                  </dd>
                </>
              ) : null}
              {info?.reason ? (
                <>
                  <dt>{t('drawer.reason')}</dt>
                  <dd dir="auto">{info.reason}</dd>
                </>
              ) : null}
            </dl>
          </section>
          <section aria-labelledby="drawer-last">
            <h3 id="drawer-last">{t('drawer.lastCall')}</h3>
            {last ? (
              <>
                <dl className="kv">
                  <dt>{t('drawer.tool')}</dt>
                  <dd>
                    <Bdi ltr className="mono">
                      {last.tool}
                    </Bdi>
                  </dd>
                  <dt>{t('drawer.started')}</dt>
                  <dd>{fmt.dateTime(last.startedAt)}</dd>
                  <dt>{t('drawer.duration')}</dt>
                  <dd>{last.durationMs !== undefined ? t('drawer.seconds', { n: fmt.num(last.durationMs / 1000, 2) }) : '–'}</dd>
                  <dt>{t('drawer.result')}</dt>
                  <dd>{last.ok === undefined ? t('state.calling') : last.ok ? t('drawer.ok') : `${t('drawer.failed')}: ${last.errorCode ?? ''} ${last.reason ?? ''}`}</dd>
                  {last.runId ? (
                    <>
                      <dt>{t('drawer.runId')}</dt>
                      <dd>
                        <Bdi ltr className="mono">
                          {last.runId}
                        </Bdi>
                      </dd>
                    </>
                  ) : null}
                  {last.servedBy ? (
                    <>
                      <dt>{t('drawer.servedBy')}</dt>
                      <dd>
                        <Bdi ltr>{last.servedBy}</Bdi>
                      </dd>
                    </>
                  ) : null}
                </dl>
                {last.warnings?.length ? (
                  <div>
                    <h4 className="small muted">{t('drawer.warnings')}</h4>
                    <ul className="small">
                      {last.warnings.map((w) => (
                        <li key={w} dir="auto">
                          {w}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {last.summary ? (
                  <div>
                    <h4 className="small muted">{t('drawer.summary')}</h4>
                    <pre className="json" tabIndex={0} aria-label={t('drawer.summary')}>
                      {JSON.stringify(last.summary, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </>
            ) : (
              <p className="muted">{t('drawer.noCall')}</p>
            )}
          </section>
          {calls.length > 1 ? (
            <section aria-labelledby="drawer-calls">
              <h3 id="drawer-calls">{t('drawer.calls')}</h3>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">{t('drawer.tool')}</th>
                      <th scope="col" className="n">
                        {t('drawer.duration')}
                      </th>
                      <th scope="col">{t('drawer.result')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calls.map((c) => (
                      <tr key={c.taskId}>
                        <td>
                          <Bdi ltr className="mono">
                            {c.tool}
                          </Bdi>
                        </td>
                        <td className="n">{c.durationMs !== undefined ? t('drawer.seconds', { n: fmt.num(c.durationMs / 1000, 2) }) : '–'}</td>
                        <td>{c.ok === undefined ? t('state.calling') : c.ok ? t('drawer.ok') : t('drawer.failed')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </Drawer>
  );
}
