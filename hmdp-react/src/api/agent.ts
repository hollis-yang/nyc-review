import axios from 'axios';

export type AgentMode = 'single' | 'multi';
export type AgentRunStatus =
  | 'created'
  | 'planning'
  | 'tool_running'
  | 'waiting_confirmation'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface AgentRunCreateRequest {
  mode: AgentMode;
  query: string;
  latitude?: number;
  longitude?: number;
  neighborhood?: string;
  category?: string;
  party_size?: number;
  budget_cents?: number;
  desired_tags?: string[];
  visit_time?: string;
}

export interface AgentRunCreated {
  run_id: string;
  status: AgentRunStatus;
  stream_url: string;
}

export interface AgentCitation {
  citation_id: string;
  shop_id: number;
  content_type: string;
  excerpt: string;
  source_id: string;
  untrusted_content: boolean;
  source_type?: string;
  source_name?: string;
  source_url?: string;
  synthetic?: boolean;
}

export interface AgentRunEvent {
  sequence: number;
  event: string;
  agent?: string;
  status: string;
  message: string;
  created_at: string;
  details: Record<string, unknown>;
}

export interface AgentRunResponse {
  mode: AgentMode;
  status: AgentRunStatus;
  summary: string;
  candidates: {
    candidates: Array<{
      shop_id: number;
      name: string;
      category: string;
      neighborhood: string;
      borough?: string;
      address?: string;
      description?: string;
      avg_price_cents: number;
      score: number;
      tags: string[];
      distance_meters?: number;
      source_type?: string;
      external_id?: string;
      source_name?: string;
      source_url?: string;
      source_fetched_at?: string;
      synthetic_fields?: string[];
    }>;
    applied_constraints: string[];
    relaxed_constraints: string[];
    warnings: string[];
  };
  evidence: {
    evidence: Array<{
      shop_id: number;
      supported_tags: string[];
      cautions: string[];
      citations: AgentCitation[];
    }>;
  };
  itinerary: {
    stops: Array<{
      shop_id: number;
      sequence: number;
      estimated_cost_cents: number;
      distance_meters?: number;
    }>;
    total_estimated_cost_cents: number;
  };
  verification: {
    valid: boolean;
    issues: Array<{ code: string; message: string; shop_id?: number }>;
  };
  metadata: {
    events?: string[];
    adapter?: string;
    rag?: string;
    indexedDocuments?: number;
    dataVersion?: string;
    datasetSha256?: string;
    sourceCounts?: Record<string, number>;
    modelProvider?: string;
    model?: string;
    modelFallbackUsed?: boolean;
    traceId?: string;
    tokenUsage?: { input: number; output: number };
    constraints?: Record<string, unknown>;
    personalization?: {
      category?: string;
      neighborhood?: string;
      tags?: string[];
      favoriteCount?: number;
    };
  };
}

export type AgentActionType =
  | 'favorite_shop'
  | 'save_itinerary'
  | 'claim_standard_voucher'
  | 'create_seckill_reminder';

export type AgentActionStatus =
  | 'proposed'
  | 'approved'
  | 'executing'
  | 'completed'
  | 'rejected'
  | 'failed';

export interface AgentActionProposal {
  action_id: string;
  action_type: AgentActionType;
  title: string;
  description: string;
  risk: 'read_only' | 'reversible_write' | 'limited_write' | 'manual_only';
  status: AgentActionStatus;
  payload: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  created_at?: string;
  updated_at?: string;
}

export interface AgentRunSnapshot {
  run_id: string;
  mode: AgentMode;
  query: string;
  status: AgentRunStatus;
  created_at: string;
  updated_at: string;
  events: AgentRunEvent[];
  actions: AgentActionProposal[];
  result?: AgentRunResponse;
  error?: string;
}

const AGENT_BASE_URL = import.meta.env.VITE_AGENT_API_BASE_URL || '/agent-api';

const agentClient = axios.create({
  baseURL: AGENT_BASE_URL,
  timeout: 30000,
});

agentClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('token');
  if (token) config.headers.authorization = token;
  return config;
});

export async function createAgentRun(payload: AgentRunCreateRequest): Promise<AgentRunCreated> {
  const response = await agentClient.post<AgentRunCreated>('/v1/agent/runs', payload);
  return response.data;
}

export async function getAgentRun(runId: string): Promise<AgentRunSnapshot> {
  const response = await agentClient.get<AgentRunSnapshot>(`/v1/agent/runs/${runId}`);
  return response.data;
}

export async function listAgentRuns(limit: number = 5): Promise<AgentRunSnapshot[]> {
  const response = await agentClient.get<AgentRunSnapshot[]>('/v1/agent/runs', {
    params: { limit },
  });
  return response.data;
}

export async function cancelAgentRun(runId: string): Promise<AgentRunSnapshot> {
  const response = await agentClient.post<AgentRunSnapshot>(`/v1/agent/runs/${runId}/cancel`);
  return response.data;
}

export async function approveAgentAction(
  runId: string,
  actionId: string,
): Promise<AgentRunSnapshot> {
  const response = await agentClient.post<AgentRunSnapshot>(
    `/v1/agent/runs/${runId}/actions/${actionId}/approve`,
  );
  return response.data;
}

export async function rejectAgentAction(
  runId: string,
  actionId: string,
): Promise<AgentRunSnapshot> {
  const response = await agentClient.post<AgentRunSnapshot>(
    `/v1/agent/runs/${runId}/actions/${actionId}/reject`,
  );
  return response.data;
}

const STREAM_EVENTS = [
  'run.created',
  'run.recovered',
  'model.started',
  'model.completed',
  'agent.completed',
  'run.waiting_confirmation',
  'action.approved',
  'action.started',
  'action.completed',
  'action.failed',
  'action.rejected',
  'run.completed',
  'run.failed',
  'run.cancelled',
];

export function subscribeToAgentRun(
  runId: string,
  onEvent: (event: AgentRunEvent) => void,
  onClosed: () => void,
  onError: () => void,
): () => void {
  const controller = new AbortController();
  const token = sessionStorage.getItem('token');
  void (async () => {
    try {
      const response = await fetch(`${AGENT_BASE_URL}/v1/agent/runs/${runId}/events`, {
        headers: token ? { authorization: token } : {},
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error(`Agent stream returned ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (!controller.signal.aborted) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || '';
        for (const frame of frames) {
          const eventName = frame.match(/^event:\s*(.+)$/m)?.[1]?.trim();
          const data = frame.match(/^data:\s*(.+)$/m)?.[1];
          if (!eventName) continue;
          if (eventName === 'stream.closed') {
            onClosed();
            controller.abort();
            return;
          }
          if (data && STREAM_EVENTS.includes(eventName)) {
            onEvent(JSON.parse(data) as AgentRunEvent);
          }
        }
        if (done) break;
      }
    } catch {
      if (!controller.signal.aborted) onError();
    }
  })();
  return () => controller.abort();
}
