# P14 Stability and Performance Runbook

P14 closes the main reliability, concurrency, latency, observability and UI
regression risks before Qdrant is moved to server mode in P15. It is a
code-and-test phase: it does not change the active P13 data checkpoint, MySQL
schema, Redis seed, map projection or Qdrant documents. No SQL or data import is
required.

## 1. Delivered behavior

### Redis Lua and RabbitMQ orders

- The existing manual flash-sale flow remains unchanged: Redis Lua atomically
  reserves stock and one order per user, RabbitMQ delivers the accepted order,
  and MySQL remains the final transactional store.
- The Rabbit publisher now exposes small internal sender and pending-store
  ports. Production still uses `RabbitTemplate` and Redis, while reliability
  tests can deterministically simulate broker ack, nack, replay and duplicate
  delivery without an external broker.
- A Redis recovery record is removed only after a positive Publisher Confirm.
  A nack keeps it for scheduled replay. A missing recovery hash is removed from
  the index without publishing an invalid message.
- Duplicate consumer delivery remains an idempotent success because the
  database unique constraint is treated as an already-created order.
- The durable retry and independent error-queue topology remains protected by
  the Rabbit contract test.

### Multi-Agent runs

- Natural-language result counts are supported in English and Chinese, with a
  default of five and a server ceiling of ten.
- Unicode normalization preserves Chinese while making accented forms such as
  `cafés` match their category. Word-boundary matching prevents `hair` inside
  `wheelchair` from selecting Beauty & Personal Care.
- Accessibility is a hard constraint. Preference tags, budget and visit time
  are verifier warnings; they no longer turn every otherwise useful result into
  an invalid run or create unattractive warning cards in the UI.
- The Discovery, single-Agent fallback, RAG ranking and action planner use the
  same requested result limit. Write actions are never proposed when hard
  verification errors exist.
- Run cancellation propagates to background work, runtime shutdown cancels
  active tasks, unfinished read-only runs recover after restart, and all Run,
  Trace and cancellation operations remain owner-isolated.
- DeepSeek Trace metadata distinguishes the requested provider from the
  effective provider and records fallback reason, finish reason, content
  length, input/output/reasoning tokens and total latency. Secrets and long
  upstream error bodies are not stored.
- The React Agent client no longer imposes a hidden 30-second Axios timeout.
  Cancellation belongs to the Run API and remains available to the user.
- The MCP FastMCP settings model is rebuilt at import time, removing the Python
  3.13 unresolved `lifespan` forward-reference warning.

### Map, bilingual UI and frontend quality

- Existing borough/neighborhood clustering, category filtering, request
  cancellation and the 500-marker cap are covered by an automated contract
  audit and real HTTP latency benchmark.
- English and Chinese locale key sets must remain identical, all six category
  translations must exist, AI Guide stays multi-Agent-only, and internal
  verifier warnings are not rendered as product error cards.
- The existing React lint baseline was repaired rather than waived globally.
  Authentication context typing, async effect loading and remaining `any`
  usages were corrected. Only the intentionally retained legacy duplicate
  profile file is excluded from lint.

## 2. Automated verification

Run these from the repository root. `HmDianPingApplicationTests` is excluded
because it builds database and Redis fixtures and must not be run against an
environment carrying useful data.

```bash
uv run --project agent-service pytest agent-service/tests -q
uv run --project agent-service ruff check agent-service/app agent-service/tests scripts/p14

mvn -Dtest='!HmDianPingApplicationTests' test

cd hmdp-react
npm run lint
npm run build
npm run visual:audit
cd ..

python3 scripts/p14/audit_frontend.py
PYTHONPYCACHEPREFIX=/private/tmp/hmdp-p14-pycache \
  python3 -m py_compile scripts/p14/*.py
```

Accepted P14 result:

| Gate | Result |
| --- | --- |
| Agent tests | 66 passed |
| Spring/Java tests | 124 passed, unsafe fixture test excluded |
| Rabbit reliability/contract tests | 10 passed |
| React lint | 0 errors, 0 warnings |
| React production build | passed |
| P13.5 visual audit | passed |
| P14 bilingual/frontend audit | 412/412 locale keys per language; all contracts passed |

If Maven is not installed on the shell path, the IntelliJ bundled Maven used
during P14 can run the same command:

```bash
'/Applications/IntelliJ IDEA.app/Contents/plugins/maven/lib/maven3/bin/mvn' \
  -Dtest='!HmDianPingApplicationTests' test
```

## 3. Live Redis Lua concurrency tests

These tests use generated, isolated voucher IDs and remove only their own test
keys in a `finally` block. They do not call MySQL or RabbitMQ. Start Redis, then
run:

```bash
uv run --project agent-service python scripts/p14/run_lua_concurrency.py \
  --stock 50 \
  --requests 200 \
  --unique-users 80 \
  --workers 32 \
  --output reports/p14/lua-concurrency.json

uv run --project agent-service python scripts/p14/run_lua_concurrency.py \
  --stock 200 \
  --requests 200 \
  --unique-users 80 \
  --workers 32 \
  --output reports/p14/lua-idempotency.json
```

Accepted P14 result:

- Exhausted-stock case: 50 accepted, 150 out of stock, stock 0, 50 unique
  users, 50 matching recovery records, no oversell.
- Repeated-user case: 80 accepted, 120 duplicate-user rejections, stock 120,
  80 unique users, 80 matching recovery records, no duplicate reservation.

## 4. Map and list latency benchmark

Start Spring on port `8081` with the accepted 5,000-shop checkpoint. The
benchmark is read-only and exercises borough clusters, neighborhood clusters,
shop markers and a sorted shop list:

```bash
uv run --project agent-service python scripts/p14/run_http_benchmarks.py \
  --base-url http://127.0.0.1:8081 \
  --requests 40 \
  --concurrency 8 \
  --output reports/p14/http-benchmarks.json
```

Accepted P14 result:

| Scenario | P95 | Limit | Maximum response items |
| --- | ---: | ---: | ---: |
| Borough clusters | 12.439 ms | 300 ms | 5 |
| Neighborhood clusters | 23.849 ms | 300 ms | 107 |
| Shop markers | 24.666 ms | 500 ms | 209 |
| Shop list | 14.296 ms | 500 ms | 10 |

All map responses remained under the 500-item cap.

## 5. Agent concurrency soak

The reproducible P14 smoke test uses the current Agent code with deterministic
mock tools and in-memory RAG, so it measures orchestration, persistence and Run
API behavior without DeepSeek or Qdrant network variance:

```bash
cd agent-service
HMDP_AGENT_ADAPTER=mock \
HMDP_AGENT_RAG_ADAPTER=memory \
HMDP_AGENT_MODEL_PROVIDER=heuristic \
HMDP_AGENT_RUNS_PER_MINUTE=120 \
HMDP_AGENT_RUN_STORE_PATH=/private/tmp/hmdp-p14-soak.sqlite3 \
uv run uvicorn app.main:app --host 127.0.0.1 --port 8091
```

In another terminal:

```bash
uv run --project agent-service python scripts/p14/run_agent_soak.py \
  --base-url http://127.0.0.1:8091 \
  --runs 18 \
  --concurrency 3 \
  --output reports/p14/agent-soak.json
```

Accepted P14 result: 18/18 terminal runs, 18 verified, zero failures, zero
fallbacks, observed concurrency 3 and P95 287.675 ms. The script deliberately
sets no client socket deadline.

For real DeepSeek/Qdrant observation, start the normal service on `8090` and
point the same script at it with the current user token. Provider latency is
reported rather than used as a hard local acceptance threshold:

```bash
uv run --project agent-service python scripts/p14/run_agent_soak.py \
  --base-url http://127.0.0.1:8090 \
  --authorization '<current-user-token>' \
  --runs 6 \
  --concurrency 2
```

## 6. Optional live RabbitMQ failure drill

The automated tests cover ack, nack, replay, duplicate delivery, retry topology
and the independent error queue without modifying a real broker. To demonstrate
the same behavior in a local full stack:

1. Confirm `hmdp.voucher.order.queue` and
   `hmdp.voucher.order.error.queue` are empty, then use a development voucher
   and user only.
2. Stop RabbitMQ, perform one manual flash sale, and verify the matching member
   remains in `seckill:pending:orders`.
3. Restart RabbitMQ. Within the configured replay interval, verify the pending
   member disappears and exactly one `(user_id, voucher_id)` row exists.
4. Publish a deliberately invalid development message to the order exchange.
   After the configured retry attempts, verify one message reaches
   `hmdp.voucher.order.error.queue` and no order row is created.
5. Inspect and acknowledge the error message. Do not purge non-empty production
   or shared queues.

## 7. Rollback and handoff

- P14 has no data migration to roll back. Reverting the P14 code returns the
  previous behavior; the active P13 data and P13.5 visual assets remain valid.
- The JSON evidence under `reports/p14/` is reproducible output, not runtime
  state. A failed rerun should not be hidden by overwriting the last accepted
  report without review.
- P15 can now move Qdrant to server mode using these Agent and HTTP metrics as
  its pre-migration baseline.

