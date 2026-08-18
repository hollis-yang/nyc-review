import { useEffect, useMemo, useRef, useState } from 'react';
import { Toast } from 'antd-mobile';
import { CheckCircleFill, CloseCircleFill, RightOutline } from 'antd-mobile-icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  approveAgentAction,
  cancelAgentRun,
  createAgentRun,
  getAgentRun,
  listAgentRuns,
  rejectAgentAction,
  subscribeToAgentRun,
  type AgentActionProposal,
  type AgentRunEvent,
  type AgentRunResponse,
  type AgentRunSnapshot,
} from '../../api/agent';
import { translateText } from '../../api/translate';
import FootBar from '../../components/FootBar';
import styles from './AiWorkspace.module.css';

const MULTI_AGENTS = ['Supervisor', 'Discovery', 'Evidence', 'Itinerary', 'Verifier'] as const;

const EVENT_KEYS: Record<string, string> = {
  'run.created': 'runCreated',
  'model.started': 'modelStarted',
  'model.completed': 'modelCompleted',
  'agent.completed': 'agentCompleted',
  'run.waiting_confirmation': 'waitingConfirmation',
  'run.completed': 'runCompleted',
  'run.failed': 'runFailed',
  'run.cancelled': 'runCancelled',
  'action.approved': 'actionApproved',
  'action.started': 'actionStarted',
  'action.completed': 'actionCompleted',
  'action.failed': 'actionFailed',
  'action.rejected': 'actionRejected',
};

function errorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  return 'The service is temporarily unavailable.';
}

export default function AiWorkspace() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const isChinese = i18n.resolvedLanguage === 'zh-CN';
  const examples = [
    t('aiGuide.exampleOne'),
    t('aiGuide.exampleTwo'),
    t('aiGuide.exampleThree'),
  ];
  const [query, setQuery] = useState(() => t('aiGuide.exampleOne'));
  const [running, setRunning] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentRunEvent[]>([]);
  const [history, setHistory] = useState<AgentRunSnapshot[]>([]);
  const [actions, setActions] = useState<AgentActionProposal[]>([]);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [result, setResult] = useState<AgentRunResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const closeStreamRef = useRef<(() => void) | null>(null);

  useEffect(() => () => closeStreamRef.current?.(), []);
  useEffect(() => {
    if (!sessionStorage.getItem('token')) return;
    listAgentRuns(5).then(setHistory).catch(() => {});
  }, []);

  const evidenceByShop = useMemo(
    () => new Map(result?.evidence.evidence.map((item) => [item.shop_id, item]) || []),
    [result],
  );
  const itineraryByShop = useMemo(
    () => new Map(result?.itinerary.stops.map((item) => [item.shop_id, item]) || []),
    [result],
  );

  const agentStatus = (agent: string) => {
    const matching = events.filter((event) => event.agent === agent);
    if (matching.some((event) => event.status === 'completed')) return 'completed';
    if (matching.some((event) => event.status === 'running')) return 'running';
    return 'waiting';
  };

  const applySnapshot = (snapshot: AgentRunSnapshot) => {
    setEvents(snapshot.events);
    setActions(snapshot.actions || []);
    if (snapshot.result) setResult(snapshot.result);
    if (snapshot.error) setRunError(snapshot.error);
  };

  const loadFinalSnapshot = async (currentRunId: string) => {
    try {
      applySnapshot(await getAgentRun(currentRunId));
      if (sessionStorage.getItem('token')) {
        listAgentRuns(5).then(setHistory).catch(() => {});
      }
    } catch (error) {
      setRunError(errorMessage(error));
    } finally {
      setRunning(false);
    }
  };

  const submit = async () => {
    if (!query.trim()) {
      Toast.show({ icon: 'fail', content: t('aiGuide.queryRequired') });
      return;
    }
    closeStreamRef.current?.();
    setRunning(true);
    setEvents([]);
    setActions([]);
    setResult(null);
    setRunError(null);
    try {
      const created = await createAgentRun({
        mode: 'multi',
        query: query.trim(),
        latitude: 40.7614,
        longitude: -73.9776,
      });
      setRunId(created.run_id);
      closeStreamRef.current = subscribeToAgentRun(
        created.run_id,
        (event) => {
          setEvents((current) => {
            const bySequence = new Map(current.map((item) => [item.sequence, item]));
            bySequence.set(event.sequence, event);
            return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
          });
        },
        () => loadFinalSnapshot(created.run_id),
        () => loadFinalSnapshot(created.run_id),
      );
    } catch (error) {
      setRunning(false);
      setRunError(errorMessage(error));
    }
  };

  const translateQuery = async () => {
    if (!query.trim()) return;
    setTranslating(true);
    try {
      const response = await translateText(query.trim(), 'en');
      const translated = String(response.data ?? response);
      if (translated) {
        setQuery(translated);
        Toast.show({ icon: 'success', content: t('aiGuide.translationSuccess') });
      }
    } catch (error) {
      Toast.show({ icon: 'fail', content: errorMessage(error) });
    } finally {
      setTranslating(false);
    }
  };

  const cancel = async () => {
    if (!runId) return;
    try {
      applySnapshot(await cancelAgentRun(runId));
      closeStreamRef.current?.();
      setRunning(false);
    } catch (error) {
      Toast.show({ icon: 'fail', content: errorMessage(error) });
    }
  };

  const decideAction = async (action: AgentActionProposal, decision: 'approve' | 'reject') => {
    if (!runId) return;
    setActionBusy(action.action_id);
    try {
      const snapshot = decision === 'approve'
        ? await approveAgentAction(runId, action.action_id)
        : await rejectAgentAction(runId, action.action_id);
      applySnapshot(snapshot);
      if (sessionStorage.getItem('token')) {
        listAgentRuns(5).then(setHistory).catch(() => {});
      }
      const updated = snapshot.actions.find((item) => item.action_id === action.action_id);
      if (updated?.status === 'failed') {
        Toast.show({ icon: 'fail', content: updated.error || t('aiGuide.actionFailed') });
      } else {
        Toast.show({
          icon: 'success',
          content: decision === 'approve' ? t('aiGuide.actionCompleted') : t('aiGuide.actionRejected'),
        });
      }
    } catch (error) {
      Toast.show({ icon: 'fail', content: errorMessage(error) });
    } finally {
      setActionBusy(null);
    }
  };

  const formatDistance = (meters?: number): string => {
    if (meters == null) return t('aiGuide.distanceUnavailable');
    const miles = meters / 1609.344;
    return miles < 0.1
      ? t('aiGuide.distanceFeet', { value: Math.round(meters * 3.28084) })
      : t('aiGuide.distanceMiles', { value: miles.toFixed(1) });
  };

  const eventMessage = (event: AgentRunEvent) => {
    const key = EVENT_KEYS[event.event];
    if (!key) return event.message;
    const agent = event.agent ? t(`aiGuide.agents.${event.agent}`, { defaultValue: event.agent }) : '';
    return t(`aiGuide.events.${key}`, { agent });
  };

  const actionTitle = (action: AgentActionProposal) =>
    t(`agentActions.${action.action_type}.title`, { shop: String(action.payload.shopName || '') });
  const actionDescription = (action: AgentActionProposal) =>
    t(`agentActions.${action.action_type}.description`);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerSide} />
        <div className={styles.headerTitle}>{t('aiGuide.title')}</div>
        <div className={styles.multiBadge}>5</div>
      </header>

      <main className={styles.scroll}>
        <section className={styles.intro}>
          <div className={styles.sparkle}>✦</div>
          <div>
            <span>{t('aiGuide.eyebrow')}</span>
            <h1>{t('aiGuide.heroTitle')}</h1>
            <p>{t('aiGuide.heroSubtitle')}</p>
          </div>
        </section>

        {history.length > 0 && (
          <section className={styles.history}>
            <div className={styles.historyHeading}>
              <strong>{t('aiGuide.recentPlans')}</strong>
              <span>{t('aiGuide.savedRuns', { count: history.length })}</span>
            </div>
            <div className={styles.historyList}>
              {history.map((item) => (
                <button
                  key={item.run_id}
                  onClick={() => {
                    setRunId(item.run_id);
                    applySnapshot(item);
                    setRunning(false);
                    setRunError(item.error || null);
                  }}
                >
                  <span>{item.query}</span>
                  <small>{t(`aiGuide.runStatus.${item.status}`)}</small>
                </button>
              ))}
            </div>
          </section>
        )}

        <section className={styles.composer}>
          <label className={styles.promptLabel} htmlFor="agent-query">
            {t('aiGuide.promptLabel')}
          </label>
          <textarea
            id="agent-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('aiGuide.placeholder')}
            rows={4}
            maxLength={2000}
          />
          <div className={styles.composerActions}>
            {isChinese ? (
              <button className={styles.translateButton} onClick={translateQuery} disabled={translating || running}>
                ✦ {translating ? t('aiGuide.translating') : t('aiGuide.translatePrompt')}
              </button>
            ) : <span />}
            <span>{query.length}/2000</span>
          </div>

          <div className={styles.examples}>
            {examples.map((example) => (
              <button key={example} onClick={() => setQuery(example)}>{example}</button>
            ))}
          </div>

          <button className={styles.runButton} disabled={running} onClick={submit}>
            <span>{running ? t('aiGuide.running') : t('aiGuide.run')}</span>
            {!running && <RightOutline fontSize={15} />}
          </button>
          {running && <button className={styles.cancelButton} onClick={cancel}>{t('aiGuide.cancel')}</button>}
          <div className={styles.safetyNote}>
            <strong>{t('aiGuide.safetyTitle')}</strong>
            <span>{t('aiGuide.safetyText')}</span>
          </div>
        </section>

        {(running || events.length > 0) && (
          <section className={styles.collaboration}>
            <div className={styles.sectionHeading}>
              <div>
                <span>{t('aiGuide.liveRun')}</span>
                <h2>{t('aiGuide.collaboration')}</h2>
              </div>
              <div className={running ? styles.liveBadge : styles.doneBadge}>
                <i /> {running ? t('aiGuide.live') : t('aiGuide.finished')}
              </div>
            </div>

            <div className={styles.agentFlow}>
              {MULTI_AGENTS.map((agent, index) => {
                const status = agentStatus(agent);
                return (
                  <div className={styles.agentStep} key={agent}>
                    <div className={`${styles.agentDot} ${styles[status]}`}>
                      {status === 'completed' ? '✓' : index + 1}
                    </div>
                    <span>{t(`aiGuide.agents.${agent}`)}</span>
                  </div>
                );
              })}
            </div>

            <div className={styles.eventLog}>
              {events.slice(-8).map((event) => (
                <div key={event.sequence}>
                  <time>{new Date(event.created_at).toLocaleTimeString(isChinese ? 'zh-CN' : 'en-US', {
                    hour: '2-digit', minute: '2-digit', second: '2-digit',
                  })}</time>
                  <span>{eventMessage(event)}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {runError && (
          <div className={styles.errorCard}>
            <CloseCircleFill />
            <div><strong>{t('aiGuide.runFailed')}</strong><span>{runError}</span></div>
          </div>
        )}

        {result && (
          <section className={styles.results}>
            <div className={styles.resultSummary}>
              <div className={result.verification.valid ? styles.verified : styles.reviewNeeded}>
                {result.verification.valid ? <CheckCircleFill /> : <CloseCircleFill />}
                {result.verification.valid ? t('aiGuide.verified') : t('aiGuide.reviewNeeded')}
              </div>
              <h2>{t('aiGuide.resultSummary', {
                candidates: result.candidates.candidates.length,
                issues: result.verification.issues.length,
              })}</h2>
              <p>
                {result.metadata.modelProvider || 'heuristic'} · {result.metadata.rag || 'memory'} RAG ·{' '}
                {t('aiGuide.indexedDocuments', { count: result.metadata.indexedDocuments ?? 0 })}
              </p>
              {(result.metadata.personalization?.favoriteCount ?? 0) > 0 && (
                <div className={styles.personalizedNote}>
                  {t('aiGuide.personalized', {
                    count: result.metadata.personalization?.favoriteCount ?? 0,
                  })}
                </div>
              )}
              {result.candidates.relaxed_constraints?.length > 0 && (
                <div className={styles.relaxationNote}>
                  <strong>{t('aiGuide.closestMatches')}</strong>
                  <span>{t('aiGuide.relaxedTags')}</span>
                </div>
              )}
            </div>

            {result.candidates.candidates.map((shop) => {
              const evidence = evidenceByShop.get(shop.shop_id);
              const stop = itineraryByShop.get(shop.shop_id);
              return (
                <article className={styles.shopCard} key={shop.shop_id}>
                  <div className={styles.shopTop}>
                    <div>
                      <span className={styles.shopCategory}>{shop.category}</span>
                      <h3>{shop.name}</h3>
                      <p>{shop.neighborhood}{shop.borough ? `, ${shop.borough}` : ''}</p>
                    </div>
                    <div className={styles.price}>${(shop.avg_price_cents / 100).toFixed(0)}<small>{t('aiGuide.perPerson')}</small></div>
                  </div>
                  <div className={styles.facts}>
                    <span>★ {shop.score.toFixed(1)}</span>
                    <span>{formatDistance(stop?.distance_meters ?? shop.distance_meters)}</span>
                    {stop && <span>{t('aiGuide.estimated', { value: (stop.estimated_cost_cents / 100).toFixed(0) })}</span>}
                  </div>
                  <div className={styles.tags}>{shop.tags.slice(0, 5).map((tag) => <span key={tag}>{tag.replaceAll('_', ' ')}</span>)}</div>
                  {evidence?.citations.slice(0, 2).map((citation) => (
                    <blockquote key={citation.citation_id}>
                      <p>“{citation.excerpt}”</p>
                      <cite>{citation.content_type.replaceAll('_', ' ')} · {citation.source_id}</cite>
                    </blockquote>
                  ))}
                  <button className={styles.openShop} onClick={() => navigate(`/shop-detail/${shop.shop_id}`)}>
                    {t('aiGuide.viewShop')} <RightOutline />
                  </button>
                </article>
              );
            })}

            {!result.verification.valid && result.verification.issues.map((issue) => (
              <div className={styles.issue} key={`${issue.code}-${issue.shop_id || 0}`}>
                <strong>{issue.code.replaceAll('_', ' ')}</strong>
                <span>{issue.message}</span>
              </div>
            ))}
          </section>
        )}

        {actions.length > 0 && (
          <section className={styles.approvals}>
            <div className={styles.approvalHeading}>
              <span>✓</span>
              <div>
                <h2>{t('aiGuide.approvalTitle')}</h2>
                <p>{t('aiGuide.approvalSubtitle')}</p>
              </div>
            </div>
            {actions.map((action) => {
              const canDecide = action.status === 'proposed' || action.status === 'failed';
              return (
                <article className={styles.actionCard} key={action.action_id}>
                  <div className={styles.actionTop}>
                    <div className={styles.actionIcon}>{action.action_type === 'save_itinerary' ? '⌖' : action.action_type.includes('voucher') ? '%' : action.action_type.includes('reminder') ? '◷' : '♡'}</div>
                    <div>
                      <h3>{actionTitle(action)}</h3>
                      <p>{actionDescription(action)}</p>
                    </div>
                    <span className={`${styles.actionStatus} ${styles[action.status]}`}>
                      {t(`agentActions.status.${action.status}`)}
                    </span>
                  </div>
                  {action.error && <div className={styles.actionError}>{action.error}</div>}
                  {canDecide && (
                    <div className={styles.actionButtons}>
                      <button disabled={actionBusy === action.action_id} onClick={() => decideAction(action, 'reject')}>
                        {t('aiGuide.reject')}
                      </button>
                      <button disabled={actionBusy === action.action_id} onClick={() => decideAction(action, 'approve')}>
                        {actionBusy === action.action_id
                          ? t('aiGuide.executing')
                          : action.status === 'failed' ? t('aiGuide.retry') : t('aiGuide.approve')}
                      </button>
                    </div>
                  )}
                </article>
              );
            })}
          </section>
        )}
      </main>

      <FootBar activeBtn={5} />
    </div>
  );
}
