import type { AgentRunEvent } from '../../api/agent';

export const COLLABORATION_NODE_IDS = [
  'workflow',
  'supervisor_plan',
  'discovery',
  'evidence',
  'itinerary',
  'verifier',
  'supervisor_finalize',
] as const;

export type CollaborationNodeId = (typeof COLLABORATION_NODE_IDS)[number];
export type CollaborationStatus = 'waiting' | 'running' | 'completed';
export type CollaborationStatusMap = Record<CollaborationNodeId, CollaborationStatus>;

export const COLLABORATION_EDGES = [
  { id: 'workflow-to-supervisor-plan', from: 'workflow', to: 'supervisor_plan' },
  { id: 'supervisor-plan-to-discovery', from: 'supervisor_plan', to: 'discovery' },
  { id: 'discovery-to-evidence', from: 'discovery', to: 'evidence' },
  { id: 'discovery-to-itinerary', from: 'discovery', to: 'itinerary' },
  { id: 'evidence-to-verifier', from: 'evidence', to: 'verifier' },
  { id: 'itinerary-to-verifier', from: 'itinerary', to: 'verifier' },
  { id: 'verifier-to-supervisor-finalize', from: 'verifier', to: 'supervisor_finalize' },
] as const;

export type CollaborationEdgeId = (typeof COLLABORATION_EDGES)[number]['id'];

const AGENT_NODE_IDS = COLLABORATION_NODE_IDS.filter(
  (node): node is Exclude<CollaborationNodeId, 'workflow'> => node !== 'workflow',
);
const AGENT_NODE_ID_SET = new Set<string>(AGENT_NODE_IDS);
const PREDECESSORS: Record<CollaborationNodeId, readonly CollaborationNodeId[]> = {
  workflow: [],
  supervisor_plan: ['workflow'],
  discovery: ['supervisor_plan'],
  evidence: ['discovery'],
  itinerary: ['discovery'],
  verifier: ['evidence', 'itinerary'],
  supervisor_finalize: ['verifier'],
};

export function deriveCollaborationStatuses(
  events: AgentRunEvent[],
  active: boolean,
): CollaborationStatusMap {
  const executionBoundary = events.reduce(
    (latest, event) => (
      (event.event === 'run.created' || event.event === 'run.recovered')
      && event.sequence > latest
        ? event.sequence
        : latest
    ),
    Number.NEGATIVE_INFINITY,
  );
  const attemptEvents = Number.isFinite(executionBoundary)
    ? events.filter((event) => event.sequence > executionBoundary)
    : events;
  const completed = new Set<CollaborationNodeId>();
  const workflowStarted = attemptEvents.some((event) => event.event === 'model.started');
  if (attemptEvents.some((event) => event.event === 'model.completed')) {
    completed.add('workflow');
  }

  for (const event of attemptEvents) {
    const node = event.details.node;
    if (
      event.event === 'agent.completed'
      && typeof node === 'string'
      && AGENT_NODE_ID_SET.has(node)
    ) {
      completed.add(node as Exclude<CollaborationNodeId, 'workflow'>);
    }
  }

  const statuses = Object.fromEntries(
    COLLABORATION_NODE_IDS.map((node) => [node, 'waiting']),
  ) as CollaborationStatusMap;

  for (const node of COLLABORATION_NODE_IDS) {
    if (completed.has(node)) {
      statuses[node] = 'completed';
      continue;
    }
    if (node === 'workflow') {
      if (active && workflowStarted) statuses[node] = 'running';
      continue;
    }
    if (active && PREDECESSORS[node].every((predecessor) => completed.has(predecessor))) {
      statuses[node] = 'running';
    }
  }

  return statuses;
}
