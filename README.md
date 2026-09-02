# NYC Review

NYC Review is a full-stack local discovery platform for New York City. It combines a Spring Boot API, a React map interface, and a FastAPI agent service with multi-agent planning and retrieval-augmented generation.

## Components

| Path | Purpose |
| --- | --- |
| `src/` | Spring Boot API, business rules, and persistence |
| `nyc-review-web/` | React, TypeScript, Vite, and Leaflet web app |
| `agent-service/` | FastAPI, LangGraph, Qdrant RAG, traces, and approvals |
| `scripts/` | Data, quality, load-test, and deployment tools |
| `deploy/production/` | Production runbook and release metadata |

MySQL stores business data, Redis serves caches and atomic inventory operations, RabbitMQ processes asynchronous orders, and Qdrant stores retrieval vectors.

## Requirements

- Docker with Docker Compose for the full stack
- Java 17 and Maven 3.9+ for the API
- Node.js `^20.19.0` or `>=22.12.0`, and npm 10+ for the web app
- Python 3.11+ and `uv` for the agent service

## Run the full stack

Copy the local configuration and replace its placeholder secrets:

```bash
cp .env.example .env
```

Create a validated dataset and its neighborhood projection with the [data generator](scripts/mock-data-generator/README.md). The directory must contain every import file mounted by `compose.local.yml`. Then start the stack:

```bash
export NYC_REVIEW_DATA_DIR="$PWD/data/generated/nyc-real-medium"
docker compose -f compose.local.yml up --build
```

The local endpoints are:

- Web: `http://127.0.0.1:8080`
- Spring Boot: `http://127.0.0.1:8081`
- Agent service: `http://127.0.0.1:8090`

The database import runs only when the MySQL volume is empty. Back up existing data and apply unapplied files from `src/main/resources/db/migrations/` before replacing a populated dataset.

Each agent run forwards the requesting user's authorization header to Spring Boot. `NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN` is an optional fallback for workflows without request authorization. Never commit tokens or API keys.

## Run services separately

Start MySQL, Redis, and RabbitMQ before running the API:

```bash
mvn spring-boot:run
```

Run the agent service with its offline defaults:

```bash
cd agent-service
uv sync --dev
uv run uvicorn app.main:app --reload --port 8090
```

Run the web development server:

```bash
cd nyc-review-web
npm ci
npm run dev
```

Vite serves `http://127.0.0.1:3000` and proxies `/api` to Spring Boot and `/agent-api` to the agent service. See the [agent service README](agent-service/README.md) for HTTP, model, and RAG configuration.

## Data provenance

The main dataset uses traceable OpenStreetMap merchant identities and attributed Wikimedia Commons category images. Reviews, ratings, users, posts, offers, and platform activity are deterministic synthetic data. Missing hours, prices, and search tags may be filled with documented deterministic rules.

Generation does not connect to running services. Importing a dataset does replace application data, so stop new order traffic, drain RabbitMQ, back up the database, and verify the target environment first.

## Checks

```bash
mvn -Dtest='*Test' test

cd nyc-review-web
npm run release:check
```

Do not run data-building integration fixtures against an environment that contains valuable data.

## Deployment

Production uses immutable container images and exposes only Caddy on ports 80 and 443. Follow the [production runbook](deploy/production/README.md); do not use the local Compose file on a production host.

The Compose files have distinct purposes:

| File | Purpose |
| --- | --- |
| `compose.local.yml` | Local full-stack development |
| `compose.load-test.yml` | Isolated load and recovery tests |
| `compose.production.yml` | Production deployment from published images |
