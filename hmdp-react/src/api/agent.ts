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
    }>;
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
    modelProvider?: string;
    model?: string;
    modelFallbackUsed?: boolean;
    constraints?: Record<string, unknown>;
  };
}

export interface AgentRunSnapshot {
  run_id: string;
  mode: AgentMode;
  query: string;
  status: AgentRunStatus;
  created_at: string;
  updated_at: string;
  events: AgentRunEvent[];
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

export async function cancelAgentRun(runId: string): Promise<AgentRunSnapshot> {
  const response = await agentClient.post<AgentRunSnapshot>(`/v1/agent/runs/${runId}/cancel`);
  return response.data;
}

const STREAM_EVENTS = [
  'run.created',
  'model.started',
  'model.completed',
  'agent.completed',
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
  const source = new EventSource(`${AGENT_BASE_URL}/v1/agent/runs/${runId}/events`);
  STREAM_EVENTS.forEach((eventName) => {
    source.addEventListener(eventName, (rawEvent) => {
      onEvent(JSON.parse((rawEvent as MessageEvent).data) as AgentRunEvent);
    });
  });
  source.addEventListener('stream.closed', () => {
    source.close();
    onClosed();
  });
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) onError();
  };
  return () => source.close();
}
