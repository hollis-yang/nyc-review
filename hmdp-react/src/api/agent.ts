import axios from 'axios';

export interface AgentRunRequest {
  mode: 'multi';
  constraints: {
    query: string;
    latitude?: number;
    longitude?: number;
    neighborhood?: string;
    category?: string;
    party_size: number;
    budget_cents?: number;
    desired_tags: string[];
  };
}

export interface AgentCitation {
  citation_id: string;
  shop_id: number;
  content_type: string;
  excerpt: string;
  source_id: string;
  untrusted_content: boolean;
}

export interface AgentRunResponse {
  status: string;
  summary: string;
  candidates: {
    candidates: Array<{
      shop_id: number;
      name: string;
      category: string;
      neighborhood: string;
      avg_price_cents: number;
      score: number;
      tags: string[];
    }>;
  };
  evidence: {
    evidence: Array<{
      shop_id: number;
      supported_tags: string[];
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
  };
}

const agentClient = axios.create({
  baseURL: import.meta.env.VITE_AGENT_API_BASE_URL || '/agent-api',
  timeout: 30000,
});

export async function runMultiAgent(payload: AgentRunRequest): Promise<AgentRunResponse> {
  const response = await agentClient.post<AgentRunResponse>('/v1/agent/runs/preview', payload);
  return response.data;
}
