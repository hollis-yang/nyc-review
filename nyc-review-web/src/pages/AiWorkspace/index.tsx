import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Toast } from 'antd-mobile';
import { CheckCircleFill, CloseCircleFill, RightOutline } from 'antd-mobile-icons';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
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
import MerchantVisual from '../../components/MerchantVisual';
import { useAuth } from '../../hooks/useAuth';
import { buildAuthEntryUrl } from '../../utils/authRedirect';
import { cleanDisplayContent } from '../../utils/displayContent';
import styles from './AiWorkspace.module.css';
import {
  COLLABORATION_EDGES,
  deriveCollaborationStatuses,
  type CollaborationEdgeId,
  type CollaborationNodeId,
} from './collaborationGraph';

const MULTI_AGENTS = ['Supervisor', 'Discovery', 'Evidence', 'Itinerary', 'Verifier'] as const;
type MultiAgent = (typeof MULTI_AGENTS)[number];
type WorkflowStage =
  | 'constraints'
  | 'plan'
  | 'search'
  | 'evidence'
  | 'itinerary'
  | 'verify'
  | 'finalize';

const COLLABORATION_NODES: ReadonlyArray<{
  id: CollaborationNodeId;
  agent?: MultiAgent;
  marker: string;
  phase: WorkflowStage;
}> = [
  { id: 'workflow', marker: 'W', phase: 'constraints' },
  { id: 'supervisor_plan', agent: MULTI_AGENTS[0], marker: '1', phase: 'plan' },
  { id: 'discovery', agent: MULTI_AGENTS[1], marker: '2', phase: 'search' },
  { id: 'evidence', agent: MULTI_AGENTS[2], marker: '3', phase: 'evidence' },
  { id: 'itinerary', agent: MULTI_AGENTS[3], marker: '4', phase: 'itinerary' },
  { id: 'verifier', agent: MULTI_AGENTS[4], marker: '5', phase: 'verify' },
  { id: 'supervisor_finalize', agent: MULTI_AGENTS[0], marker: '1', phase: 'finalize' },
];

const GRAPH_NODE_CLASSES: Record<CollaborationNodeId, string> = {
  workflow: styles.graphWorkflow,
  supervisor_plan: styles.graphSupervisorPlan,
  discovery: styles.graphDiscovery,
  evidence: styles.graphEvidence,
  itinerary: styles.graphItinerary,
  verifier: styles.graphVerifier,
  supervisor_finalize: styles.graphSupervisorFinalize,
};

const MOBILE_GRAPH_PATHS: Record<CollaborationEdgeId, string> = {
  'workflow-to-supervisor-plan': 'M 100 28 L 100 56',
  'supervisor-plan-to-discovery': 'M 100 84 L 100 112',
  'discovery-to-evidence': 'M 100 140 C 100 154, 50 154, 50 168',
  'discovery-to-itinerary': 'M 100 140 C 100 154, 150 154, 150 168',
  'evidence-to-verifier': 'M 50 196 C 50 210, 100 210, 100 224',
  'itinerary-to-verifier': 'M 150 196 C 150 210, 100 210, 100 224',
  'verifier-to-supervisor-finalize': 'M 100 252 L 100 280',
};

const DESKTOP_GRAPH_PATHS: Record<CollaborationEdgeId, string> = {
  'workflow-to-supervisor-plan': 'M 64 71 L 136 71',
  'supervisor-plan-to-discovery': 'M 164 71 L 236 71',
  'discovery-to-evidence': 'M 264 71 C 300 71, 300 15, 336 15',
  'discovery-to-itinerary': 'M 264 71 C 300 71, 300 127, 336 127',
  'evidence-to-verifier': 'M 364 15 C 400 15, 400 71, 436 71',
  'itinerary-to-verifier': 'M 364 127 C 400 127, 400 71, 436 71',
  'verifier-to-supervisor-finalize': 'M 464 71 L 536 71',
};
const ACTIVE_RUN_STATUSES = new Set<AgentRunSnapshot['status']>([
  'created',
  'planning',
  'tool_running',
]);
const MAX_STREAM_RECONNECT_ATTEMPTS = 4;
const STREAM_RECONNECT_BASE_DELAY_MS = 500;
const STREAM_SNAPSHOT_POLL_INTERVAL_MS = 5_000;

const EVENT_KEYS: Record<string, string> = {
  'run.created': 'runCreated',
  'run.recovered': 'runRecovered',
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

function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === 'string') return error;
  if (error instanceof Error) return error.message;
  return fallback;
}

export default function AiWorkspace() {
  const { t, i18n } = useTranslation();
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedRunId = searchParams.get('runId');
  const isChinese = i18n.resolvedLanguage === 'zh-CN';
  const examples = [
    t('aiGuide.exampleOne'),
    t('aiGuide.exampleTwo'),
    t('aiGuide.exampleThree'),
    t('aiGuide.exampleFour'),
    t('aiGuide.exampleFive'),
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
  const [selectedShopId, setSelectedShopId] = useState<number | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [cancelBusy, setCancelBusy] = useState(false);
  const closeStreamRef = useRef<(() => void) | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const streamGenerationRef = useRef(0);
  const runContextGenerationRef = useRef(0);
  const activeRunIdRef = useRef<string | null>(null);
  const runSubmitLockRef = useRef(false);
  const actionLockRef = useRef<{ actionId: string; generation: number } | null>(null);
  const cancelLockRef = useRef<{ runId: string; generation: number } | null>(null);
  const queryTranslationLockRef = useRef(false);

  const clearStreamConnection = useCallback(() => {
    streamGenerationRef.current += 1;
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    const close = closeStreamRef.current;
    closeStreamRef.current = null;
    close?.();
  }, []);

  const beginRunContext = useCallback((nextRunId: string | null): number => {
    clearStreamConnection();
    const generation = ++runContextGenerationRef.current;
    activeRunIdRef.current = nextRunId;
    actionLockRef.current = null;
    cancelLockRef.current = null;
    return generation;
  }, [clearStreamConnection]);

  useEffect(() => () => clearStreamConnection(), [clearStreamConnection]);
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
  const selectedShop = useMemo(
    () => result?.candidates.candidates.find((shop) => shop.shop_id === selectedShopId)
      ?? result?.candidates.candidates[0]
      ?? null,
    [result, selectedShopId],
  );
  const selectedActions = useMemo(
    () => actions.filter((action) => (
      action.action_type === 'save_itinerary'
      || Number(action.payload.shopId) === selectedShop?.shop_id
    )),
    [actions, selectedShop],
  );
  const visibleIssues = useMemo(() => {
    const relaxed = new Set(result?.candidates.relaxed_constraints ?? []);
    const seen = new Set<string>();
    return (result?.verification.issues ?? []).filter((issue) => {
      if (issue.severity && issue.severity !== 'error') return false;
      if (issue.code === 'MISSING_DESIRED_TAGS' && relaxed.has('desired_tags')) return false;
      if (issue.code === 'COST_UNAVAILABLE' && relaxed.has('budget')) return false;
      const key = `${issue.code}:${issue.message}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [result]);
  const displayVerified = useMemo(
    () => Boolean(result && (result.verification.valid || visibleIssues.length === 0)),
    [result, visibleIssues],
  );
  const hasGeneralVerificationCaveat = useMemo(
    () => visibleIssues.some((issue) => issue.code !== 'UNSUPPORTED_DESIRED_TAGS'),
    [visibleIssues],
  );
  const collaborationStatuses = useMemo(
    () => deriveCollaborationStatuses(events, running),
    [events, running],
  );

  const applySnapshot = (snapshot: AgentRunSnapshot) => {
    setRunId(snapshot.run_id);
    setQuery(snapshot.query);
    setEvents(snapshot.events);
    setActions(snapshot.actions || []);
    setResult(snapshot.result || null);
    setRunError(snapshot.error || null);
    setRunning(ACTIVE_RUN_STATUSES.has(snapshot.status));
    setCancelBusy(false);
  };

  useEffect(() => {
    if (!requestedRunId || !sessionStorage.getItem('token')) return;
    const generation = beginRunContext(requestedRunId);
    getAgentRun(requestedRunId)
      .then((snapshot) => {
        if (
          runContextGenerationRef.current !== generation
          || activeRunIdRef.current !== requestedRunId
        ) return;
        applySnapshot(snapshot);
        listAgentRuns(5).then(setHistory).catch(() => {});
        if (ACTIVE_RUN_STATUSES.has(snapshot.status)) {
          attachRunStream(snapshot.run_id, generation);
        }
      })
      .catch((error) => {
        if (
          runContextGenerationRef.current !== generation
          || activeRunIdRef.current !== requestedRunId
        ) return;
        setRunning(false);
        setRunError(errorMessage(error, t('aiGuide.serviceUnavailable')));
      });
    return () => {
      if (
        runContextGenerationRef.current === generation
        && activeRunIdRef.current === requestedRunId
      ) {
        clearStreamConnection();
        runContextGenerationRef.current += 1;
        activeRunIdRef.current = null;
      }
    };
  // Restoring a saved itinerary is intentionally keyed only by the URL run ID.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedRunId]);

  async function loadFinalSnapshot(
    currentRunId: string,
    contextGeneration: number,
    expectedStreamGeneration: number,
  ): Promise<AgentRunSnapshot | null> {
    try {
      const snapshot = await getAgentRun(currentRunId);
      if (
        runContextGenerationRef.current !== contextGeneration
        || streamGenerationRef.current !== expectedStreamGeneration
        || activeRunIdRef.current !== currentRunId
      ) return null;
      applySnapshot(snapshot);
      if (sessionStorage.getItem('token')) {
        listAgentRuns(5).then(setHistory).catch(() => {});
      }
      return snapshot;
    } catch (error) {
      if (
        runContextGenerationRef.current === contextGeneration
        && streamGenerationRef.current === expectedStreamGeneration
        && activeRunIdRef.current === currentRunId
      ) {
        setRunError(errorMessage(error, t('aiGuide.serviceUnavailable')));
      }
      return null;
    }
  }

  function attachRunStream(
    currentRunId: string,
    contextGeneration: number,
    reconnectAttempt = 0,
  ) {
    if (
      runContextGenerationRef.current !== contextGeneration
      || activeRunIdRef.current !== currentRunId
    ) return;
    clearStreamConnection();
    const streamGeneration = streamGenerationRef.current;
    let recoveryStarted = false;

    const recoverStream = () => {
      if (recoveryStarted) return;
      recoveryStarted = true;
      void (async () => {
        const snapshot = await loadFinalSnapshot(
          currentRunId,
          contextGeneration,
          streamGeneration,
        );
        if (
          runContextGenerationRef.current !== contextGeneration
          || streamGenerationRef.current !== streamGeneration
          || activeRunIdRef.current !== currentRunId
        ) return;
        if (snapshot && !ACTIVE_RUN_STATUSES.has(snapshot.status)) return;
        if (reconnectAttempt >= MAX_STREAM_RECONNECT_ATTEMPTS) {
          setRunError(t('aiGuide.streamReconnectFailed'));
          const pollRunSnapshot = () => {
            if (
              runContextGenerationRef.current !== contextGeneration
              || streamGenerationRef.current !== streamGeneration
              || activeRunIdRef.current !== currentRunId
            ) return;
            reconnectTimerRef.current = window.setTimeout(() => {
              reconnectTimerRef.current = null;
              void (async () => {
                const polledSnapshot = await loadFinalSnapshot(
                  currentRunId,
                  contextGeneration,
                  streamGeneration,
                );
                if (
                  runContextGenerationRef.current !== contextGeneration
                  || streamGenerationRef.current !== streamGeneration
                  || activeRunIdRef.current !== currentRunId
                ) return;
                if (polledSnapshot && !ACTIVE_RUN_STATUSES.has(polledSnapshot.status)) return;
                if (polledSnapshot) setRunError(t('aiGuide.streamReconnectFailed'));
                pollRunSnapshot();
              })();
            }, STREAM_SNAPSHOT_POLL_INTERVAL_MS);
          };
          pollRunSnapshot();
          return;
        }
        const delay = Math.min(
          STREAM_RECONNECT_BASE_DELAY_MS * (2 ** reconnectAttempt),
          4_000,
        );
        reconnectTimerRef.current = window.setTimeout(() => {
          if (
            runContextGenerationRef.current === contextGeneration
            && streamGenerationRef.current === streamGeneration
            && activeRunIdRef.current === currentRunId
          ) {
            attachRunStream(currentRunId, contextGeneration, reconnectAttempt + 1);
          }
        }, delay);
      })();
    };

    closeStreamRef.current = subscribeToAgentRun(
      currentRunId,
      (event) => {
        if (
          runContextGenerationRef.current !== contextGeneration
          || streamGenerationRef.current !== streamGeneration
          || activeRunIdRef.current !== currentRunId
        ) return;
        setEvents((current) => {
          const bySequence = new Map(current.map((item) => [item.sequence, item]));
          bySequence.set(event.sequence, event);
          return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
        });
      },
      recoverStream,
      recoverStream,
    );
  }

  const submit = async () => {
    if (runSubmitLockRef.current) return;
    if (!query.trim()) {
      Toast.show({ icon: 'fail', content: t('aiGuide.queryRequired') });
      return;
    }
    runSubmitLockRef.current = true;
    const generation = beginRunContext(null);
    setActionBusy(null);
    if (requestedRunId) setSearchParams({}, { replace: true });
    setRunning(true);
    setRunId(null);
    setCancelBusy(false);
    setEvents([]);
    setActions([]);
    setResult(null);
    setSelectedShopId(null);
    setRunError(null);
    try {
      const created = await createAgentRun({
        mode: 'multi',
        query: query.trim(),
        latitude: 40.7614,
        longitude: -73.9776,
      });
      if (
        runContextGenerationRef.current !== generation
        || activeRunIdRef.current !== null
      ) return;
      activeRunIdRef.current = created.run_id;
      setRunId(created.run_id);
      attachRunStream(created.run_id, generation);
    } catch (error) {
      if (
        runContextGenerationRef.current === generation
        && activeRunIdRef.current === null
      ) {
        setRunning(false);
        setRunError(errorMessage(error, t('aiGuide.serviceUnavailable')));
      }
    } finally {
      runSubmitLockRef.current = false;
    }
  };

  const translateQuery = async () => {
    if (!query.trim() || queryTranslationLockRef.current) return;
    queryTranslationLockRef.current = true;
    setTranslating(true);
    try {
      const response = await translateText(query.trim(), 'en');
      const translated = String(response.data ?? response);
      if (translated) {
        setQuery(translated);
        Toast.show({ icon: 'success', content: t('aiGuide.translationSuccess') });
      }
    } catch (error) {
      Toast.show({ icon: 'fail', content: errorMessage(error, t('aiGuide.serviceUnavailable')) });
    } finally {
      queryTranslationLockRef.current = false;
      setTranslating(false);
    }
  };

  const cancel = async () => {
    const currentRunId = activeRunIdRef.current;
    if (!currentRunId) return;
    const generation = runContextGenerationRef.current;
    if (
      cancelLockRef.current?.runId === currentRunId
      && cancelLockRef.current.generation === generation
    ) return;
    cancelLockRef.current = { runId: currentRunId, generation };
    setCancelBusy(true);
    try {
      const snapshot = await cancelAgentRun(currentRunId);
      if (
        runContextGenerationRef.current !== generation
        || activeRunIdRef.current !== currentRunId
      ) return;
      applySnapshot(snapshot);
      clearStreamConnection();
      setRunning(false);
    } catch (error) {
      if (
        runContextGenerationRef.current === generation
        && activeRunIdRef.current === currentRunId
      ) {
        Toast.show({ icon: 'fail', content: errorMessage(error, t('aiGuide.serviceUnavailable')) });
      }
    } finally {
      if (
        cancelLockRef.current?.runId === currentRunId
        && cancelLockRef.current.generation === generation
      ) cancelLockRef.current = null;
      if (
        runContextGenerationRef.current === generation
        && activeRunIdRef.current === currentRunId
      ) setCancelBusy(false);
    }
  };

  const decideAction = async (action: AgentActionProposal, decision: 'approve' | 'reject') => {
    if (!runId) return;
    if (decision === 'approve' && !isAuthenticated) {
      const resumeTarget = `/ai?${new URLSearchParams({ runId }).toString()}`;
      Toast.show({ icon: 'fail', content: t('aiGuide.approvalLoginRequired') });
      navigate(buildAuthEntryUrl('/login', resumeTarget));
      return;
    }
    if (actionLockRef.current !== null) return;
    const currentRunId = runId;
    const generation = runContextGenerationRef.current;
    actionLockRef.current = { actionId: action.action_id, generation };
    setActionBusy(action.action_id);
    try {
      const snapshot = decision === 'approve'
        ? await approveAgentAction(currentRunId, action.action_id)
        : await rejectAgentAction(currentRunId, action.action_id);
      if (
        runContextGenerationRef.current !== generation
        || activeRunIdRef.current !== currentRunId
      ) return;
      applySnapshot(snapshot);
      if (ACTIVE_RUN_STATUSES.has(snapshot.status)) {
        attachRunStream(snapshot.run_id, generation);
      }
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
      if (
        runContextGenerationRef.current === generation
        && activeRunIdRef.current === currentRunId
      ) {
        Toast.show({ icon: 'fail', content: errorMessage(error, t('aiGuide.serviceUnavailable')) });
      }
    } finally {
      if (
        actionLockRef.current?.actionId === action.action_id
        && actionLockRef.current.generation === generation
      ) actionLockRef.current = null;
      if (
        runContextGenerationRef.current === generation
        && activeRunIdRef.current === currentRunId
      ) {
        setActionBusy(null);
      }
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
  const selectedEvidence = selectedShop ? evidenceByShop.get(selectedShop.shop_id) : undefined;
  const selectedStop = selectedShop ? itineraryByShop.get(selectedShop.shop_id) : undefined;
  const hasRunWorkspace = Boolean(
    requestedRunId
    || runId
    || running
    || events.length > 0
    || actions.length > 0
    || result
    || runError,
  );

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerSide} />
        <div className={styles.headerTitle}>{t('aiGuide.title')}</div>
        <div className={styles.headerSide} />
      </header>

      <main
        className={`${styles.scroll} ${hasRunWorkspace ? styles.activeWorkspace : styles.idleWorkspace}`}
        data-workspace-state={hasRunWorkspace ? 'active' : 'idle'}
      >
        <div className={styles.inputRail}>
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
                      const generation = beginRunContext(item.run_id);
                      setSearchParams({ runId: item.run_id }, { replace: true });
                      setActionBusy(null);
                      setCancelBusy(false);
                      applySnapshot(item);
                      setRunError(item.error || null);
                      if (ACTIVE_RUN_STATUSES.has(item.status)) {
                        attachRunStream(item.run_id, generation);
                      }
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
                <button
                  key={example}
                  onClick={() => setQuery(example)}
                  title={example}
                  type="button"
                >
                  {example}
                </button>
              ))}
            </div>

            <button className={styles.runButton} disabled={running} onClick={submit}>
              <span>{running ? t('aiGuide.running') : t('aiGuide.run')}</span>
              {!running && <RightOutline fontSize={15} />}
            </button>
            {running && (
              <button className={styles.cancelButton} disabled={cancelBusy} onClick={cancel}>
                {t('aiGuide.cancel')}
              </button>
            )}
            <div className={styles.safetyNote}>
              <strong>{t('aiGuide.safetyTitle')}</strong>
              <span>{t('aiGuide.safetyText')}</span>
            </div>
          </section>
        </div>

        <div className={styles.workArea}>
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

              <div className={styles.agentGraph}>
                <svg
                  aria-hidden="true"
                  className={`${styles.graphLinks} ${styles.mobileGraphLinks}`}
                  preserveAspectRatio="none"
                  viewBox="0 0 200 336"
                >
                  <defs>
                    <marker
                      id="collaboration-arrow-mobile"
                      markerHeight="6"
                      markerWidth="6"
                      orient="auto"
                      refX="7"
                      refY="4"
                      viewBox="0 0 8 8"
                    >
                      <path className={styles.graphArrow} d="M 0 0 L 8 4 L 0 8 z" />
                    </marker>
                  </defs>
                  {COLLABORATION_EDGES.map((edge) => (
                    <path
                      className={`${styles.graphLink} ${styles[collaborationStatuses[edge.to]]}`}
                      d={MOBILE_GRAPH_PATHS[edge.id]}
                      data-edge={edge.id}
                      key={edge.id}
                      markerEnd="url(#collaboration-arrow-mobile)"
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </svg>
                <svg
                  aria-hidden="true"
                  className={`${styles.graphLinks} ${styles.desktopGraphLinks}`}
                  preserveAspectRatio="none"
                  viewBox="0 0 600 168"
                >
                  <defs>
                    <marker
                      id="collaboration-arrow-desktop"
                      markerHeight="6"
                      markerWidth="6"
                      orient="auto"
                      refX="7"
                      refY="4"
                      viewBox="0 0 8 8"
                    >
                      <path className={styles.graphArrow} d="M 0 0 L 8 4 L 0 8 z" />
                    </marker>
                  </defs>
                  {COLLABORATION_EDGES.map((edge) => (
                    <path
                      className={`${styles.graphLink} ${styles[collaborationStatuses[edge.to]]}`}
                      d={DESKTOP_GRAPH_PATHS[edge.id]}
                      data-edge={edge.id}
                      key={edge.id}
                      markerEnd="url(#collaboration-arrow-desktop)"
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </svg>
                <ol
                  aria-label={t('aiGuide.workflowGraphLabel')}
                  className={styles.graphNodes}
                >
                  {COLLABORATION_NODES.map((node) => {
                    const status = collaborationStatuses[node.id];
                    const label = node.agent
                      ? t(`aiGuide.agents.${node.agent}`)
                      : t('aiGuide.workflow');
                    const phase = t(`aiGuide.workflowStages.${node.phase}`);
                    return (
                      <li
                        aria-busy={status === 'running' ? true : undefined}
                        aria-label={`${label}, ${phase}, ${t(`aiGuide.workflowStatus.${status}`)}`}
                        className={`${styles.graphNode} ${GRAPH_NODE_CLASSES[node.id]}`}
                        data-node={node.id}
                        data-status={status}
                        key={node.id}
                      >
                        <div className={`${styles.agentDot} ${node.id === 'workflow' ? styles.workflowDot : ''} ${styles[status]}`}>
                          {status === 'completed' ? '✓' : node.marker}
                        </div>
                        <span className={styles.graphNodeLabel}>{label}</span>
                        <small className={styles.graphNodePhase}>{phase}</small>
                      </li>
                    );
                  })}
                </ol>
              </div>

              <div className={styles.eventLog}>
                {events.slice(-8).map((event) => (
                  <div key={event.sequence}>
                    <time>{new Date(event.created_at).toLocaleTimeString(isChinese ? 'zh-CN' : 'en-US', {
                      hour: '2-digit', minute: '2-digit', second: '2-digit',
                    })}</time>
                    <span>{eventMessage(event)}</span>
                    {typeof event.details.durationMs === 'number' && (
                      <small>{Math.round(event.details.durationMs)} ms</small>
                    )}
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
              <div className={displayVerified ? styles.verified : styles.reviewNeeded}>
                {displayVerified ? <CheckCircleFill /> : <span className={styles.reviewIcon}>i</span>}
                {displayVerified ? t('aiGuide.verified') : t('aiGuide.reviewNeeded')}
              </div>
              <h2>{t('aiGuide.resultSummary', {
                candidates: result.candidates.candidates.length,
              })}</h2>
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
              {!displayVerified && (
                <div className={styles.verificationNote}>
                  <strong>{t('aiGuide.verificationNoteTitle')}</strong>
                  <span>{t(hasGeneralVerificationCaveat
                    ? 'aiGuide.verificationNoteGeneral'
                    : 'aiGuide.verificationNoteEvidence')}</span>
                </div>
              )}
            </div>

            <section className={styles.candidatePicker}>
              <div className={styles.candidatePickerHeading}>
                <h3>{t('aiGuide.recommendationListTitle')}</h3>
                <p>{t('aiGuide.chooseRecommendation')}</p>
              </div>
              <div className={styles.candidateList}>
                {result.candidates.candidates.map((shop, index) => (
                  <button
                    type="button"
                    key={shop.shop_id}
                    className={shop.shop_id === selectedShop?.shop_id ? styles.candidateActive : ''}
                    onClick={() => setSelectedShopId(shop.shop_id)}
                  >
                    <span>{index + 1}</span>
                    <div>
                      <strong>{shop.name}</strong>
                      <small>{shop.neighborhood}{shop.borough ? `, ${shop.borough}` : ''}</small>
                    </div>
                    <RightOutline />
                  </button>
                ))}
              </div>
            </section>

            {selectedShop && (
                <article className={styles.shopCard} key={selectedShop.shop_id}>
                  <div className={styles.shopVisual}>
                    <MerchantVisual
                      shopId={selectedShop.shop_id}
                      name={selectedShop.name}
                      alt={selectedShop.name}
                      loading="lazy"
                    />
                  </div>
                  <div className={styles.shopTop}>
                    <div>
                      <span className={styles.shopCategory}>{t(`shopTypes.${selectedShop.category}`, selectedShop.category)}</span>
                      <h3>{selectedShop.name}</h3>
                      <p>{selectedShop.neighborhood}{selectedShop.borough ? `, ${selectedShop.borough}` : ''}</p>
                    </div>
                    {selectedShop.avg_price_cents != null && (
                      <div className={styles.price}>${(selectedShop.avg_price_cents / 100).toFixed(0)}<small>{t('aiGuide.perPerson')}</small></div>
                    )}
                  </div>
                  <div className={styles.facts}>
                    {selectedShop.score != null && (
                      <span>★ {selectedShop.score.toFixed(1)}</span>
                    )}
                    <span>{formatDistance(selectedStop?.distance_meters ?? selectedShop.distance_meters)}</span>
                    {selectedStop && (
                      <span>
                        {selectedStop.estimated_cost_cents != null
                          ? t('aiGuide.estimated', { value: (selectedStop.estimated_cost_cents / 100).toFixed(0) })
                          : t('aiGuide.costUnavailable')}
                      </span>
                    )}
                  </div>
                  <div className={styles.tags}>{selectedShop.tags.slice(0, 5).map((tag) => (
                    <span key={tag}>{t(`tags.${tag}`, tag.replaceAll('_', ' '))}</span>
                  ))}</div>
                  {selectedEvidence?.citations.slice(0, 2).map((citation) => (
                    <blockquote key={citation.citation_id}>
                      <p>“{cleanDisplayContent(citation.excerpt)}”</p>
                    </blockquote>
                  ))}
                  <button className={styles.openShop} onClick={() => navigate(`/shop-detail/${selectedShop.shop_id}`)}>
                    {t('aiGuide.viewShop')} <RightOutline />
                  </button>
                </article>
            )}

            {selectedActions.length > 0 && (
              <section className={styles.approvals}>
                <div className={styles.approvalHeading}>
                  <span>✓</span>
                  <div>
                    <h2>{t('aiGuide.approvalTitle')}</h2>
                    <p>{t('aiGuide.selectedApprovalSubtitle', { shop: selectedShop?.name || '' })}</p>
                  </div>
                </div>
                {selectedActions.map((action) => {
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
                          <button disabled={actionBusy !== null} onClick={() => decideAction(action, 'reject')}>
                            {t('aiGuide.reject')}
                          </button>
                          <button disabled={actionBusy !== null} onClick={() => decideAction(action, 'approve')}>
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
            </section>
          )}
        </div>
      </main>

      <FootBar activeBtn={5} />
    </div>
  );
}
