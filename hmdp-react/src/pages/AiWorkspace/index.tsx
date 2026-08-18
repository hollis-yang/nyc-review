import { useEffect, useMemo, useRef, useState } from 'react';
import { Toast } from 'antd-mobile';
import { CheckCircleFill, CloseCircleFill } from 'antd-mobile-icons';
import {
  cancelAgentRun,
  createAgentRun,
  getAgentRun,
  subscribeToAgentRun,
  type AgentMode,
  type AgentRunEvent,
  type AgentRunResponse,
} from '../../api/agent';
import { translateText } from '../../api/translate';
import FootBar from '../../components/FootBar';
import styles from './AiWorkspace.module.css';

const EXAMPLES = [
  'Quiet vegan dinner in Midtown for 2 under $120',
  'An accessible coffee shop in Chelsea with outdoor seating',
  'A late-night group spot in Williamsburg under $200',
];

const MULTI_AGENTS = ['Supervisor', 'Discovery', 'Evidence', 'Itinerary', 'Verifier'];

function errorMessage(error: unknown): string {
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  return 'The service is temporarily unavailable.';
}

function formatDistance(meters?: number): string {
  if (meters == null) return 'Distance unavailable';
  const miles = meters / 1609.344;
  return miles < 0.1 ? `${Math.round(meters * 3.28084)} ft` : `${miles.toFixed(1)} mi`;
}

export default function AiWorkspace() {
  const [query, setQuery] = useState(EXAMPLES[0]);
  const [mode, setMode] = useState<AgentMode>('multi');
  const [running, setRunning] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentRunEvent[]>([]);
  const [result, setResult] = useState<AgentRunResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const closeStreamRef = useRef<(() => void) | null>(null);

  useEffect(() => () => closeStreamRef.current?.(), []);

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

  const loadFinalSnapshot = async (currentRunId: string) => {
    try {
      const snapshot = await getAgentRun(currentRunId);
      setEvents(snapshot.events);
      if (snapshot.result) setResult(snapshot.result);
      if (snapshot.error) setRunError(snapshot.error);
    } catch (error) {
      setRunError(errorMessage(error));
    } finally {
      setRunning(false);
    }
  };

  const submit = async () => {
    if (!query.trim()) {
      Toast.show({ icon: 'fail', content: 'Describe the place or plan you need.' });
      return;
    }
    closeStreamRef.current?.();
    setRunning(true);
    setEvents([]);
    setResult(null);
    setRunError(null);
    try {
      const created = await createAgentRun({
        mode,
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
        Toast.show({ icon: 'success', content: 'Translated to English with DeepSeek' });
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
      await cancelAgentRun(runId);
      closeStreamRef.current?.();
      await loadFinalSnapshot(runId);
    } catch (error) {
      Toast.show({ icon: 'fail', content: errorMessage(error) });
    }
  };

  const changeMode = (nextMode: AgentMode) => {
    if (running || nextMode === mode) return;
    setMode(nextMode);
    setEvents([]);
    setResult(null);
    setRunError(null);
    setRunId(null);
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}>NYC AI GUIDE</div>
          <h1>Ask the neighborhood</h1>
          <p>Natural-language planning with verified local evidence.</p>
        </div>
        <div className={styles.headerMark}>AI</div>
      </header>

      <main className={styles.scroll}>
        <section className={styles.composer}>
          <div className={styles.modeSwitch} aria-label="Agent mode">
            <button className={mode === 'single' ? styles.modeActive : ''} onClick={() => changeMode('single')}>
              Single Agent
            </button>
            <button className={mode === 'multi' ? styles.modeActive : ''} onClick={() => changeMode('multi')}>
              Multi Agent
            </button>
          </div>

          <label className={styles.promptLabel} htmlFor="agent-query">What are you looking for?</label>
          <textarea
            id="agent-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="For example: a quiet dinner in Midtown for two under $120"
            rows={4}
            maxLength={2000}
          />
          <div className={styles.composerActions}>
            <button className={styles.translateButton} onClick={translateQuery} disabled={translating || running}>
              <span>✦</span> {translating ? 'DeepSeek is translating…' : 'Translate to English with DeepSeek'}
            </button>
            <span>{query.length}/2000</span>
          </div>

          <div className={styles.examples}>
            {EXAMPLES.map((example) => (
              <button key={example} onClick={() => setQuery(example)}>{example}</button>
            ))}
          </div>

          <button className={styles.runButton} disabled={running} onClick={submit}>
            {running ? 'Agents are working…' : `Run ${mode === 'multi' ? 'multi-agent' : 'single-agent'} search`}
          </button>
          {running && <button className={styles.cancelButton} onClick={cancel}>Cancel run</button>}
          <div className={styles.safetyNote}>
            <span>Manual checkout</span>
            AI can research promotions, but flash-sale purchase remains a user-only action on the shop page.
          </div>
        </section>

        {(running || events.length > 0) && (
          <section className={styles.collaboration}>
            <div className={styles.sectionHeading}>
              <div>
                <span>LIVE RUN</span>
                <h2>{mode === 'multi' ? 'Agent collaboration' : 'Single-agent baseline'}</h2>
              </div>
              <div className={running ? styles.liveBadge : styles.doneBadge}>
                <i /> {running ? 'Live' : 'Finished'}
              </div>
            </div>

            <div className={styles.agentGrid}>
              {(mode === 'multi' ? MULTI_AGENTS : ['Supervisor', 'Single Agent', 'Verifier']).map((agent) => {
                const status = agentStatus(agent);
                return (
                  <div className={`${styles.agentCard} ${styles[status]}`} key={agent}>
                    <span className={styles.agentIcon}>{status === 'completed' ? '✓' : status === 'running' ? '●' : '○'}</span>
                    <div>
                      <strong>{agent}</strong>
                      <small>{status === 'completed' ? 'Completed' : status === 'running' ? 'Working' : 'Waiting'}</small>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className={styles.eventLog}>
              {events.map((event) => (
                <div key={event.sequence}>
                  <time>{new Date(event.created_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })}</time>
                  <span>{event.message}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {runError && (
          <div className={styles.errorCard}>
            <CloseCircleFill />
            <div><strong>Run failed</strong><span>{runError}</span></div>
          </div>
        )}

        {result && (
          <section className={styles.results}>
            <div className={styles.resultSummary}>
              <div className={result.verification.valid ? styles.verified : styles.reviewNeeded}>
                {result.verification.valid ? <CheckCircleFill /> : <CloseCircleFill />}
                {result.verification.valid ? 'Verified result' : 'Review needed'}
              </div>
              <h2>{result.summary}</h2>
              <p>
                {result.metadata.modelProvider || 'heuristic'} model · {result.metadata.rag || 'memory'} RAG ·{' '}
                {result.metadata.indexedDocuments ?? 0} indexed documents
              </p>
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
                    <div className={styles.price}>${(shop.avg_price_cents / 100).toFixed(0)}<small>/person</small></div>
                  </div>
                  <div className={styles.facts}>
                    <span>★ {shop.score.toFixed(1)}</span>
                    <span>{formatDistance(stop?.distance_meters ?? shop.distance_meters)}</span>
                    {stop && <span>${(stop.estimated_cost_cents / 100).toFixed(0)} estimated</span>}
                  </div>
                  <div className={styles.tags}>{shop.tags.slice(0, 5).map((tag) => <span key={tag}>{tag.replaceAll('_', ' ')}</span>)}</div>
                  {evidence?.citations.slice(0, 2).map((citation) => (
                    <blockquote key={citation.citation_id}>
                      <p>“{citation.excerpt}”</p>
                      <cite>{citation.content_type.replaceAll('_', ' ')} · {citation.source_id}</cite>
                    </blockquote>
                  ))}
                  <button className={styles.openShop} onClick={() => window.location.assign(`/shop-detail/${shop.shop_id}`)}>
                    View shop and manual offers
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
      </main>

      <FootBar activeBtn={5} />
    </div>
  );
}
