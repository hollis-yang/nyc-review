# P10–P17 Delivery Roadmap

P9 established the full merchant-enrichment pipeline and validated the relaxed
official-site image strategy on a balanced 360-shop Pilot. P9.1 then corrected
Distance, Popularity and Rating semantics. Beginning with P10/P11, every phase
must expose a runnable checkpoint so its product result can be inspected before
the next phase starts. A checkpoint is promoted only after its isolated bundle,
backup, import, cross-system identity checks and UI acceptance all pass.

| Phase | Status | Primary goal | Required work | Exit criteria |
| --- | --- | --- | --- | --- |
| P10 | Complete; checkpoint ready | Expand the image strategy to all 5,000 shops | Crawled 2,740 official sites; validated responses; rejected trackers, logos, broken and undersized assets; deduplicated and ranked candidates; retained 1–3 images per shop with category fallback | 100% display coverage; 1,772 shops (35.44%) have merchant-specific images; full bundle validation passes |
| P11 | Complete; checkpoint ready | Continue real merchant-field enrichment | Added a pinned official JSON-LD provider with nested contact, hours, reservation, rating-scale and price-range resolution | External rating 21, price 152, phone 3,278, hours 2,831 and reservation URL 58; shared Spring/React/Agent contract remains in place |
| P12 | Pending | Upgrade RAG retrieval quality | Separate fact/evidence types; hybrid lexical/vector recall; query rewrite; metadata filters; reranking; evidence deduplication; merchant diversity; Verifier improvements; fixed eval set | Recall@10 at least 85%; evidence coverage at least 95%; structured-constraint satisfaction at least 90%; no duplicate merchant recommendations |
| P13 | Pending | Expand real merchant scale | Grow from 5,000 to 10,000+ across all six categories and five boroughs; incremental crawl; diff import; history and rollback metadata | Merchant identities remain 100% real-source; versions are traceable; refresh is incremental rather than full replacement |
| P14 | Pending | Stability, performance and bug closeout | RabbitMQ/Redis Lua load tests; idempotency and dead-letter tests; Agent concurrency, timeout, cancel and recovery; map/list performance; bilingual and UI regression | No oversell; zero duplicate orders; Agent recovery works; map/list stay responsive at target scale; core regression suite passes |
| P15 | Final-stage | Move Qdrant to server mode | Replace local-path storage; payload indexes; collection aliases; multiple Agent instances; backup and health checks | No local file lock or 20,000-point warning; concurrent Agent instances work; index versions switch without downtime |
| P16 | Final-stage | Final release-candidate alignment and rollback rehearsal | Freeze the latest accepted checkpoint; repeat MySQL/Redis/map/Qdrant identity audit; verify backup restoration and collection switch; cut the release candidate | MySQL, Redis, map, Agent and RAG share the same `dataVersion`, `datasetSha256` and `shopIdsSha256`; rollback is rehearsed |
| P17 | Closeout | Package the portfolio project | One-command Compose; CI; README and architecture diagrams; test manual; sample prompts; performance report; demo script; secret and temporary-file audit | Clean one-command startup; stable demo of seckill, RabbitMQ, multi-Agent, RAG, MCP, map clustering, bilingual UI and DeepSeek translation |

## Implementation sequence

```text
P9/P9.1 complete
  → P10/P11 checkpoint import and visual acceptance (`nyc-real-v3-7577e407-m20260824`)
  → P12 RAG quality
  → P13 10,000+ scale
  → P14 stability and performance
  → P15 Qdrant server mode
  → P16 final release-candidate alignment
  → P17 portfolio delivery
```

## Checkpoint policy

- Every phase first works on fixed snapshots and an isolated bundle. A phase
  may then replace the active **development** dataset once so the user can see
  and accept the result before continuing.
- Before a data checkpoint, drain RabbitMQ and the Redis pending-order index,
  stop Spring and Agent writes, validate the bundle and create a MySQL backup.
- Promote MySQL, the P7 map projection, Redis and Qdrant from the same bundle.
  A mixed-version checkpoint is never considered accepted.
- Use a new Qdrant local directory or a server collection alias for each
  checkpoint. Keep the previous directory/collection and database backup until
  visual acceptance succeeds.
- Official-site images without an explicit reusable license remain remote
  references. The pipeline must not download or redistribute the original.
- Merchant identity, name, address and coordinates remain real-source data.
  User reviews and replies may remain generated test data.
- Existing manual seckill, Redis Lua reservation, RabbitMQ delivery,
  translation, multi-Agent approval, RAG, MCP and Profile assets are protected
  regression capabilities in every phase.
- P16 remains the production-style release cutover, but it is no longer the
  first time the user can inspect integrated phase results.

## Phase dependencies

- P10 reuses the P9 official-site image Pilot and its URL/content validation.
- P11 resolves factual fields before P12 evaluates retrieval correctness.
- P12 establishes the quality baseline before P13 changes corpus scale.
- P14 establishes load limits before P15 enables multiple Agent instances.
- P15 must finish before the P16 production-style Qdrant alias switch.
- P17 documents only commands and metrics reproduced by P14–P16.
