import assert from 'node:assert/strict';
import test from 'node:test';

import type { AgentRunEvent } from '../src/api/agent.ts';
import {
  COLLABORATION_EDGES,
  deriveCollaborationStatuses,
} from '../src/pages/AiWorkspace/collaborationGraph.ts';

function event(
  sequence: number,
  eventName: string,
  node?: string,
): AgentRunEvent {
  return {
    sequence,
    event: eventName,
    agent: eventName.startsWith('model.') ? 'Supervisor' : undefined,
    status: eventName.endsWith('completed') ? 'completed' : 'running',
    message: eventName,
    created_at: '2026-09-02T12:00:00Z',
    details: node ? { node } : {},
  };
}

test('collaboration graph preserves the workflow fork and join topology', () => {
  assert.deepEqual(
    COLLABORATION_EDGES.map(({ from, to }) => `${from}->${to}`),
    [
      'workflow->supervisor_plan',
      'supervisor_plan->discovery',
      'discovery->evidence',
      'discovery->itinerary',
      'evidence->verifier',
      'itinerary->verifier',
      'verifier->supervisor_finalize',
    ],
  );
});

test('constraint extraction belongs only to Workflow, never Supervisor', () => {
  const started = deriveCollaborationStatuses([event(1, 'model.started')], true);
  assert.equal(started.workflow, 'running');
  assert.equal(started.supervisor_plan, 'waiting');

  const completed = deriveCollaborationStatuses([
    event(1, 'model.started'),
    event(2, 'model.completed'),
  ], true);
  assert.equal(completed.workflow, 'completed');
  assert.equal(completed.supervisor_plan, 'running');
  assert.equal(completed.supervisor_finalize, 'waiting');
});

test('Discovery fans out before Evidence and Itinerary join at Verifier', () => {
  const events = [
    event(1, 'model.completed'),
    event(2, 'agent.completed', 'supervisor_plan'),
    event(3, 'agent.completed', 'discovery'),
  ];
  const forked = deriveCollaborationStatuses(events, true);
  assert.equal(forked.evidence, 'running');
  assert.equal(forked.itinerary, 'running');
  assert.equal(forked.verifier, 'waiting');

  const oneBranch = deriveCollaborationStatuses([
    ...events,
    event(4, 'agent.completed', 'evidence'),
  ], true);
  assert.equal(oneBranch.evidence, 'completed');
  assert.equal(oneBranch.itinerary, 'running');
  assert.equal(oneBranch.verifier, 'waiting');

  const joined = deriveCollaborationStatuses([
    ...events,
    event(4, 'agent.completed', 'evidence'),
    event(5, 'agent.completed', 'itinerary'),
  ], true);
  assert.equal(joined.verifier, 'running');
  assert.equal(joined.supervisor_finalize, 'waiting');
});

test('the final Supervisor is tracked separately from the planning Supervisor', () => {
  const statuses = deriveCollaborationStatuses([
    event(1, 'model.completed'),
    event(2, 'agent.completed', 'supervisor_plan'),
    event(3, 'agent.completed', 'discovery'),
    event(4, 'agent.completed', 'evidence'),
    event(5, 'agent.completed', 'itinerary'),
    event(6, 'agent.completed', 'verifier'),
  ], true);

  assert.equal(statuses.supervisor_plan, 'completed');
  assert.equal(statuses.supervisor_finalize, 'running');
});

test('recovery starts a fresh collaboration attempt', () => {
  const statuses = deriveCollaborationStatuses([
    event(1, 'run.created'),
    event(2, 'model.completed'),
    event(3, 'agent.completed', 'supervisor_plan'),
    event(4, 'agent.completed', 'discovery'),
    event(5, 'agent.completed', 'evidence'),
    event(6, 'run.recovered'),
    event(7, 'model.started'),
  ], true);

  assert.equal(statuses.workflow, 'running');
  assert.deepEqual(
    Object.values(statuses).slice(1),
    Array.from({ length: 6 }, () => 'waiting'),
  );
});

test('a completed terminal run remains complete when inactive', () => {
  const statuses = deriveCollaborationStatuses([
    event(1, 'run.created'),
    event(2, 'model.completed'),
    event(3, 'agent.completed', 'supervisor_plan'),
    event(4, 'agent.completed', 'discovery'),
    event(5, 'agent.completed', 'evidence'),
    event(6, 'agent.completed', 'itinerary'),
    event(7, 'agent.completed', 'verifier'),
    event(8, 'agent.completed', 'supervisor_finalize'),
  ], false);

  assert.deepEqual(
    Object.values(statuses),
    Array.from({ length: 7 }, () => 'completed'),
  );
});
