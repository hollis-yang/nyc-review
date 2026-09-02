# NYC Review Agent Service

This FastAPI service coordinates single-agent and multi-agent recommendations, Qdrant retrieval, approval-gated actions, traces, and a read-only MCP endpoint. Spring Boot remains the source of truth for business data and write operations.

## Run locally

```bash
cd agent-service
uv sync --dev
uv run uvicorn app.main:app --reload --port 8090
```

In another terminal:

```bash
curl http://127.0.0.1:8090/health
```

The defaults use an in-memory business adapter, in-memory retrieval, a deterministic parser, and a local SQLite run store. They require no external model or database.

To connect to Spring Boot, Qdrant, and a generated dataset:

```bash
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=http://127.0.0.1:6333 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-medium \
uv run uvicorn app.main:app --port 8090
```

See `.env.example` for optional embedding, retrieval, reranking, model, metrics, and MCP settings. Hash embeddings are for local tests only and are rejected in production unless explicitly allowed.

Run requests forward their authorization header to Spring Boot. Set `NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN` only as a fallback for workflows such as MCP calls or interrupted read-only recovery.

## Run API

Create a persistent run with a browser-generated session identifier:

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  -H 'authorization: <current-user-token>' \
  -d '{"mode":"multi","query":"Quiet vegan dinner in Midtown for 2 under $120"}'
```

Use the returned `run_id` with the same session and authorization headers:

```bash
RUN_ID=replace-with-run-id

curl -N "http://127.0.0.1:8090/v1/agent/runs/$RUN_ID/events" \
  -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  -H 'authorization: <current-user-token>'

curl -sS "http://127.0.0.1:8090/v1/agent/runs/$RUN_ID" \
  -H 'x-agent-session: 12345678-1234-4567-89ab-123456789abc' \
  -H 'authorization: <current-user-token>'
```

Runs support event streaming, cancellation, history, traces, and resumable execution. The service stores only a one-way owner key derived from the authorization token.

## Approvals and safety

- Read-only discovery and evidence tools may run automatically.
- Saving favorites or itineraries, claiming regular offers, and creating sale reminders require explicit approval.
- Flash-sale purchases are never exposed to the model and remain a direct user action.
- Approved writes use stable action identifiers for idempotency and auditability.
- Retrieved reviews and posts are treated as untrusted content and retain source references.
- Rate limits, prompt guards, owner isolation, timeouts, and recovery checks protect persisted runs.

## Retrieval

The service accepts validated real-identity datasets created by the [data generator](../scripts/mock-data-generator/README.md). Each root review and its replies form one retrieval document; merchant descriptions, posts, and post comments are indexed separately.

Qdrant synchronization checks dataset identity and content hashes, upserts only changed documents, and removes stale documents within the active dataset scope. Set `NYC_REVIEW_AGENT_RAG_SYNC_MODE=verify` only for a complete prebuilt collection; verify mode performs no index writes.

Use a persistent Qdrant server for the main dataset. A local path is suitable only for small, single-process tests.

## Models and observability

`NYC_REVIEW_AGENT_MODEL_PROVIDER=heuristic` is deterministic and offline. Set the provider and credentials described in `.env.example` to use a hosted model. Model failures may fall back to the deterministic parser unless fallback is disabled.

`GET /v1/agent/runs/{id}/trace` returns run spans. `GET /v1/agent/metrics` returns aggregate counts, latency, and model usage; set `NYC_REVIEW_AGENT_METRICS_TOKEN` to protect it.

## MCP

The Streamable HTTP endpoint at `http://127.0.0.1:8090/mcp` exposes six read-only tools: merchant search, merchant details, evidence, available offers, route calculation, and itinerary validation. Set `NYC_REVIEW_AGENT_MCP_API_KEY` to require bearer authentication.

## Checks

```bash
uv run ruff check .
uv run pytest
```
