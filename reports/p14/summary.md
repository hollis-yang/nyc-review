# P14 Accepted Results

P14 completed on 2026-08-26 against the accepted 5,000-shop development
checkpoint. It required no SQL import, Redis seed replacement or Qdrant rebuild.

| Area | Accepted result |
| --- | --- |
| Redis Lua stock race | 200 requests, stock 50: 50 accepted, 150 rejected, 0 oversell |
| Redis Lua idempotency | 200 requests, 80 users: 80 accepted, 120 duplicates, 0 duplicate reservation |
| RabbitMQ reliability | ack/nack/replay/duplicate-delivery and topology tests passed |
| Agent concurrency | 18/18 completed and verified, concurrency 3, P95 287.675 ms |
| Agent lifecycle | cancellation, shutdown cleanup, owner isolation and restart recovery tests passed |
| Map clusters | borough P95 12.439 ms; neighborhood P95 23.849 ms |
| Map markers | P95 24.666 ms; 209 items, below the 500 cap |
| Shop list | P95 14.296 ms |
| Agent suite | 66 passed |
| Spring/Java suite | 124 passed; unsafe fixture test excluded |
| React | lint, build and visual audit passed |
| Bilingual/frontend contract | 412 matching keys in each locale; all P14 checks passed |

Machine-readable details are stored beside this file:

- `lua-concurrency.json`
- `lua-idempotency.json`
- `http-benchmarks.json`
- `agent-soak.json`

The complete commands, safety boundaries and optional live failure drills are
documented in `docs/p14-stability-performance-runbook.md`.

