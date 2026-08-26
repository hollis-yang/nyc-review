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
| P11.5 | Complete; checkpoint ready | Improve images and per-person prices without a paid Places API | Bounded same-site gallery/menu/location/service crawl; sitemap, `srcset`, CSS and PDF support; official menu/service price distribution and deterministic category estimate | 1,871 merchant-image shops (37.42%); external price 918; official-menu average price 844; 5,000/5,000 map projection; v4 full-bundle gates pass |
| P12 | Complete; isolated checkpoint accepted | Upgrade RAG retrieval quality | Separate fact/evidence types; hybrid lexical/vector recall; bilingual query expansion; metadata filters; broad candidate pool; reranking; evidence deduplication; merchant diversity; Verifier improvements; frozen/current/stress eval layers | 145,000-point/72-case gate passed: Recall@10 99.54%; evidence and constraint satisfaction 100%; duplicate/security/version failures 0; local P95 5.20 s |
| P13 | Complete; checkpoint ready | Improve the depth and realism of the 5,000-shop corpus | Separated local browsable reviews from external rating metadata; generated diverse category-aware review threads, notes and comments; deepened bounded official-site/Wikimedia/NYC enrichment; rebuilt the full corpus after a balanced 600-shop Pilot | 5,000 stable real-source identities; 100,000 roots plus 63,500 replies; local review/API counts agree; exact duplicates 0 and near duplicates 0.294%; merchant images 38.12% (50% remains a stretch target); current-corpus RAG Recall@10 99.54%, evidence/constraints 100%, local P95 3.90 s |
| P13.5 | Complete; frontend-only | Raise merchant and note visual coverage without changing the P13 corpus | Added one frontend visual resolver; retained exact merchant images first; pinned 218 licensed contextual photos; added deterministic category/shop covers; replaced note defaults; added broken-image fallback, credits and visual audits across every React entry point | 5,000/5,000 photo-backed and non-default shop visuals; 10,000 generated notes with 0% default-image rate; exact merchant-image count remains 1,906; max contextual reuse 15; no backend/RAG identity change; build and audit pass |
| P14 | Pending | Stability, performance and bug closeout | RabbitMQ/Redis Lua load tests; idempotency and dead-letter tests; Agent concurrency, cancel and recovery without client execution deadlines; map/list performance; bilingual and UI regression | No oversell; zero duplicate orders; Agent recovery works; map/list stay responsive at target scale; core regression suite passes |
| P15 | Final-stage | Move Qdrant to server mode | Replace local-path storage; payload indexes; collection aliases; multiple Agent instances; backup and health checks | No local file lock or 20,000-point warning; concurrent Agent instances work; index versions switch without downtime |
| P16 | Final-stage | Final release-candidate alignment and rollback rehearsal | Freeze the latest accepted checkpoint; repeat MySQL/Redis/map/Qdrant identity audit; verify backup restoration and collection switch; cut the release candidate | MySQL, Redis, map, Agent and RAG share the same `dataVersion`, `datasetSha256` and `shopIdsSha256`; rollback is rehearsed |
| P17 | Closeout | Package the portfolio project | One-command Compose; CI; README and architecture diagrams; test manual; sample prompts; performance report; demo script; secret and temporary-file audit | Clean one-command startup; stable demo of seckill, RabbitMQ, multi-Agent, RAG, MCP, map clustering, bilingual UI and DeepSeek translation |

## Implementation sequence

```text
P9/P9.1 complete
  → P10/P11 checkpoint import and visual acceptance (`nyc-real-v3-7577e407-m20260824`)
  → P11.5 checkpoint import and visual acceptance (`nyc-real-v4-0f51676d-m20260824`)
  → P12 RAG quality (complete; `p12-rag-v1` / `hmdp_content_v2`)
  → P13 5,000-shop depth and content realism (complete; `nyc-real-v5-8b645404-m20260824`)
  → P13.5 frontend merchant/note visual coverage (complete; no data checkpoint change)
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
- P11.5 improves official image and menu-price evidence while leaving rating
  expansion to a future licensed or paid provider decision.
- P12 establishes the quality baseline before P13 changes corpus content and
  evidence distribution. P13 keeps the 5,000 merchant identities and IDs
  stable, and evaluates the refreshed corpus in a separate Qdrant path before
  checkpoint promotion.
- P13.5 consumes the accepted P13 frontend contract but changes only React
  assets, image resolution and fallback behavior. It does not alter MySQL,
  Redis, Spring, Agent Service, Qdrant, `dataVersion` or RAG evaluation inputs,
  so it neither requires a checkpoint import nor blocks independent P14 work.
- P14 establishes load limits before P15 enables multiple Agent instances.
- P15 must finish before the P16 production-style Qdrant alias switch.
- P17 documents only commands and metrics reproduced by P14–P16.
