# P14.1 Backend Load and Failure-Recovery Runbook

P14.1 turns the P14 correctness checks into a reproducible full-stack capacity
baseline. It does not change the active P13 merchant checkpoint. All destructive
fixture resets and failure drills are constrained to the Docker Compose project
`hmdp-p14-load`, database `hmdp_p14_load`, Redis sentinel
`hmdp:p14:environment=isolated-load-only`, RabbitMQ vhost `/hmdp-p14-load`,
voucher `9140001`, and reserved load-user range beginning at `9000000`.

## 1. Delivered scope

- A dedicated MySQL, Redis, RabbitMQ, Spring, Agent Service and Prometheus stack
  on ports `13306`, `16379`, `15673`/`15683`, `18081`/`19091`, `18090` and
  `19090` respectively.
- The complete accepted P13 5,000-shop import in an isolated database. Spring
  uses the `p14-load` profile with explicit Tomcat, Hikari, Redis and RabbitMQ
  load settings and exposes Micrometer/Prometheus metrics on port `19091`.
- Guarded fixture generation, before/after metrics collection, deterministic k6
  scenarios and cross-system order validation.
- Read baseline, flash-sale burst, repeated-user idempotency, mixed traffic and
  30-minute endurance stages. k6 treats an HTTP 200 business rejection as a
  business result rather than a successful order.
- RabbitMQ, MySQL and Redis outage/recovery drills. The MySQL drill validates
  the independent error queue and guarded replay path.
- Runtime token files are local-only and ignored by Git. No DeepSeek key or
  normal user token is required by this deterministic baseline.

## 2. Start and validate the isolated stack

Docker Desktop (or another Docker engine with Compose) must be running. From
the repository root:

```bash
docker compose \
  --project-name hmdp-p14-load \
  --file docker-compose.p14-load.yml \
  up --build -d

python3 scripts/p14_1/validate_environment.py
```

The validator must report:

```text
project: hmdp-p14-load
database: hmdp_p14_load
redisSentinel: isolated-load-only
activeDataset: nyc-real-v5-8b645404-m20260824|p13-full|5000
springHealth: UP
```

The safety check runs before every fixture reset and test stage. A missing or
mismatched identity stops the script before load is generated.

Useful local endpoints:

- Spring: `http://127.0.0.1:18081`
- Spring health/metrics: `http://127.0.0.1:19091/actuator`
- Agent Service: `http://127.0.0.1:18090`
- RabbitMQ management: `http://127.0.0.1:15683`
- Prometheus: `http://127.0.0.1:19090`

## 3. Visible checkpoints and full suite

Run one checkpoint at a time when inspecting the result:

```bash
python3 scripts/p14_1/run_suite.py smoke
python3 scripts/p14_1/run_suite.py read
python3 scripts/p14_1/run_suite.py seckill
python3 scripts/p14_1/run_suite.py duplicate
python3 scripts/p14_1/run_suite.py mixed
python3 scripts/p14_1/run_suite.py endurance
```

For a short developer feedback loop, append `--quick`. For an unattended full
rerun, use:

```bash
python3 scripts/p14_1/run_suite.py all
```

Each stage writes k6 output, machine-readable summary, before/after resource
snapshots and, for order scenarios, an independent consistency report below
`reports/p14-1/<stage>/`.

Acceptance gates:

- technical error rate below 1%;
- read P95 below 300 ms and P99 below 800 ms;
- mixed/endurance P95 below 500 ms and P99 below 1,200 ms;
- no Redis or MySQL stock below zero;
- Redis reservations equal MySQL orders after convergence;
- one order per user and globally unique order IDs;
- RabbitMQ ready/unacknowledged/error queues and Redis publisher recovery index
  return to zero.

## 4. Accepted capacity baseline

The accepted run used Docker Desktop on an Apple Silicon development machine.
These numbers are a local regression baseline, not a production SLA.

| Stage | Load | Result | P95 | P99 |
| --- | ---: | --- | ---: | ---: |
| Read | 9,001 requests at 50 RPS for 3 min | 0 failed checks | 70.52 ms | 71.91 ms |
| Flash-sale burst | 1,000 requests, 250 VUs, stock 500 | 500 accepted; no oversell | 201.16 ms | 245.21 ms |
| Duplicate users | 200 users × 5 attempts | exactly 200 unique orders | 51.71 ms | 60.60 ms |
| Mixed | 30,001 requests at 50 RPS for 10 min | 0 technical errors; exactly 500 orders | 15.91 ms | 21.28 ms |
| Endurance | 90,001 requests at 50 RPS for 30 min | 0 errors/drops; exactly 1,000 orders | 16.48 ms | 21.41 ms |

The flash-sale burst reached approximately 2,695 requests/s. The repeated-user
case reached approximately 5,087 requests/s. In every accepted order stage,
MySQL and Redis stock agreed and all RabbitMQ queues drained to zero.

The endurance before/after snapshots also recorded zero Redis blocked clients
and rejected connections, zero MySQL row-lock waits, slow queries and rolled
back transactions, and no RabbitMQ ready or unacknowledged messages.

## 5. Agent orchestration soak

The Compose Agent uses the Spring HTTP adapter, memory RAG and heuristic model.
This measures local orchestration and backend integration without Qdrant or
DeepSeek variance:

```bash
uv run --project agent-service python scripts/p14/run_agent_soak.py \
  --base-url http://127.0.0.1:18090 \
  --authorization p14-load-000001 \
  --runs 100 \
  --concurrency 10 \
  --output reports/p14-1/agent-soak.json
```

DeepSeek and Qdrant remain separate quality/provider tests. They must not be
mixed into the deterministic backend capacity gate.

Accepted result: 100/100 runs reached the approval boundary, 100/100 passed the
Verifier, zero failed or fell back, observed concurrency was 10, mean latency
was 650.66 ms and P95 was 1,073.22 ms. The full-stack run also exposed and
fixed missing dataset identity on in-memory citations; that adapter now carries
the mounted P13 `dataVersion` and `datasetSha256` through the Verifier.

## 6. Guarded failure drills

These scripts stop and restart only a service in the named isolated Compose
project. The exact project confirmation is mandatory:

```bash
python3 scripts/p14_1/run_failure_drill.py \
  rabbitmq --confirm-project hmdp-p14-load

python3 scripts/p14_1/run_failure_drill.py \
  mysql --confirm-project hmdp-p14-load

python3 scripts/p14_1/run_failure_drill.py \
  redis --confirm-project hmdp-p14-load
```

The RabbitMQ drill proves Redis publisher-recovery records survive broker
unavailability and drain after restart. The MySQL drill proves exhausted
consumer retries reach the independent error queue and can be replayed only
through the guarded tool:

```bash
python3 scripts/p14_1/replay_error_queue.py \
  --confirm-vhost /hmdp-p14-load
```

The Redis drill verifies Spring becomes unhealthy/unavailable while Redis is
down and recovers after restart. Never aim these drills at a shared vhost or
database.

Accepted result:

- RabbitMQ: ten Redis reservations survived broker downtime and replayed to
  exactly ten MySQL orders after restart.
- MySQL: five reservations exercised consumer retry and the independent error
  queue; guarded replay plus normal queue recovery produced exactly five
  orders and drained the DLQ.
- Redis: five in-flight requests timed out while Redis was unavailable, then
  completed after dependency recovery; no order bypassed the Lua reservation
  boundary and all stores converged.

Build the compact machine-readable acceptance report after all stages:

```bash
python3 scripts/p14_1/build_report.py
```

It must write `reports/p14-1/accepted-results.json` with `status: accepted`.

## 7. Offline and regression verification

```bash
python3 -m unittest scripts/p14_1/test_p14_1.py
uv run --project agent-service ruff check agent-service/app agent-service/tests scripts/p14 scripts/p14_1
uv run --project agent-service pytest agent-service/tests -q
mvn -Dtest='!HmDianPingApplicationTests' test
```

Accepted regression result: 67 Agent tests, 125 safe Java tests, four P14.1
offline contracts, Ruff, JavaScript syntax and Compose configuration all pass.

`HmDianPingApplicationTests` remains excluded because it creates database and
Redis fixtures and is not container-isolated.

## 8. Stop and restart

Stop containers while preserving the isolated database and metrics volumes:

```bash
docker compose \
  --project-name hmdp-p14-load \
  --file docker-compose.p14-load.yml \
  down
```

Do not add `--volumes` unless the isolated P14.1 data is intentionally being
discarded. Starting the same project again reuses the volumes.
