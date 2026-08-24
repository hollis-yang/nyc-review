# P10–P17 Delivery Roadmap

P9 established the full merchant-enrichment pipeline and validated the relaxed
official-site image strategy on a balanced 360-shop Pilot. P9.1 then corrected
Distance, Popularity and Rating semantics. The remaining work is fixed in the
following order so that experimental snapshots do not repeatedly replace the
user's active MySQL, Redis, map and Qdrant data.

| Phase | Status | Primary goal | Required work | Exit criteria |
| --- | --- | --- | --- | --- |
| P10 | Pending | Expand the image strategy to all 5,000 shops | Crawl official sites; validate responses; reject trackers, logos and broken assets; deduplicate images; rank candidates; retain 1–3 images per shop; keep category fallback | 100% display coverage; merchant-specific image target at least 30%; full bundle validation passes |
| P11 | Pending | Continue real merchant-field enrichment | Add official JSON-LD and compliant snapshot providers; improve rating, rating-count, price, hours, reservation URL and operating-status coverage | External rating and price coverage are no longer zero; phone/website/hours coverage increases; Spring, React and Agent fields agree |
| P12 | Pending | Upgrade RAG retrieval quality | Separate fact/evidence types; hybrid lexical/vector recall; query rewrite; metadata filters; reranking; evidence deduplication; merchant diversity; Verifier improvements; fixed eval set | Recall@10 at least 85%; evidence coverage at least 95%; structured-constraint satisfaction at least 90%; no duplicate merchant recommendations |
| P13 | Pending | Expand real merchant scale | Grow from 5,000 to 10,000+ across all six categories and five boroughs; incremental crawl; diff import; history and rollback metadata | Merchant identities remain 100% real-source; versions are traceable; refresh is incremental rather than full replacement |
| P14 | Pending | Stability, performance and bug closeout | RabbitMQ/Redis Lua load tests; idempotency and dead-letter tests; Agent concurrency, timeout, cancel and recovery; map/list performance; bilingual and UI regression | No oversell; zero duplicate orders; Agent recovery works; map/list stay responsive at target scale; core regression suite passes |
| P15 | Final-stage | Move Qdrant to server mode | Replace local-path storage; payload indexes; collection aliases; multiple Agent instances; backup and health checks | No local file lock or 20,000-point warning; concurrent Agent instances work; index versions switch without downtime |
| P16 | Final-stage | Perform the one final data import and version alignment | Import MySQL and neighborhood projection; seed Redis; rebuild/switch Qdrant; clear caches; run cross-system identity audit | MySQL, Redis, map, Agent and RAG share the same `dataVersion`, `datasetSha256` and `shopIdsSha256` |
| P17 | Closeout | Package the portfolio project | One-command Compose; CI; README and architecture diagrams; test manual; sample prompts; performance report; demo script; secret and temporary-file audit | Clean one-command startup; stable demo of seckill, RabbitMQ, multi-Agent, RAG, MCP, map clustering, bilingual UI and DeepSeek translation |

## Implementation sequence

```text
P9/P9.1 complete
  → P10 full image rollout
  → P11 real field coverage
  → P12 RAG quality
  → P13 10,000+ scale
  → P14 stability and performance
  → P15 Qdrant server mode
  → P16 final unified import
  → P17 portfolio delivery
```

## Cross-phase constraints

- P10–P15 operate on fixed snapshots, Pilot bundles and isolated test data.
  They must not repeatedly replace the active development database.
- Official-site images without an explicit reusable license remain remote
  references. The pipeline must not download or redistribute the original.
- Merchant identity, name, address and coordinates remain real-source data.
  User reviews and replies may remain generated test data.
- Existing manual seckill, Redis Lua reservation, RabbitMQ delivery,
  translation, multi-Agent approval, RAG, MCP and Profile assets are protected
  regression capabilities in every phase.
- P16 is the only planned final switch of MySQL, Redis, map projection and
  Qdrant to the completed bundle.

## Phase dependencies

- P10 reuses the P9 official-site image Pilot and its URL/content validation.
- P11 resolves factual fields before P12 evaluates retrieval correctness.
- P12 establishes the quality baseline before P13 changes corpus scale.
- P14 establishes load limits before P15 enables multiple Agent instances.
- P15 must finish before the P16 production-style Qdrant rebuild and alias
  switch.
- P17 documents only commands and metrics reproduced by P14–P16.

