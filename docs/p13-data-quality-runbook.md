# P13 5K Data Quality and Content Realism Runbook

P13 keeps the accepted 5,000 real-source NYC merchant identities and stable
shop IDs. It improves depth rather than scale: local/external rating semantics,
generated platform-content realism, and merchant-specific images and fields
obtainable from free, auditable sources.

## Scope and protected capabilities

- Keep exactly 5,000 merchants across all six categories and five boroughs.
- Keep merchant identity, name, address and coordinates real-source backed.
- The isolated generator never modifies a running database. The checkpoint
  import is intentionally a full development-data replacement, so stop writes
  and back up MySQL first; do not run it against a database whose user-created
  content must be retained.
- Do not scrape or copy Google/Yelp review text and do not require a paid Places
  API. Official sites, OSM, Wikidata/Wikimedia and relevant NYC Open Data remain
  the bounded enrichment sources.
- Manual seckill, Redis Lua reservation, RabbitMQ delivery, bilingual UI,
  DeepSeek translation, multi-Agent approvals, RAG, MCP, map clustering and
  Profile assets remain protected regression capabilities.

## Data contract correction

`comments`/`localReviewCount` means the number of locally browsable depth-zero
reviews. Replies never increase it. `localScore` is computed only from those
root reviews. `externalRatingCount` and `externalScore` are source observations
and are never presented as the number of locally browsable reviews. A user
review updates only the local aggregate.

The acceptance invariant is:

```text
shop.localReviewCount
  = GET /shop-review/{shopId}.total
  = COUNT(tb_shop_review WHERE shop_id = ? AND parent_id IS NULL/0)
```

This fixes cases such as Dino's Pizzeria, where an official-site
`ratingCount=1441` was previously labelled as 1,441 reviews even though the
local corpus contained 20 root reviews.

## Implementation sequence

1. Add the additive P13 schema migration and shared Spring/React/Agent contract.
2. Change live review aggregation and UI labels to local-only counts.
3. Introduce deterministic category-aware content generation V2 with latent
   per-shop quality, coherent 1–5-star sentiment and parent-aware replies.
4. Generate distinct note formats and comments that refer to their parent note.
5. Add exact/near-duplicate, rating-distribution, count-consistency and thread
   coherence quality gates.
6. Build a balanced 600-shop Pilot (`100 × 6 categories`) and inspect the UI and
   Agent evidence before generating all 5,000 shops.
7. Process the free-source missing-field queue: bounded official-site deep
   pages, JSON-LD, galleries/menus, Wikidata/Wikimedia and applicable NYC Open
   Data. Keep remote image references and reject icons, logos, trackers,
   undersized assets and cross-merchant duplicates.
8. Rebuild the full isolated bundle, map projection and a new Qdrant collection;
   run both the P12 frozen suite and a P13 current-corpus suite.

## Quality gates

| Gate | Required result |
| --- | --- |
| Merchant identity | 5,000/5,000 real-source identities; stable shop IDs |
| Review count | UI/API/DB depth-zero count agreement for every shop |
| Rating coverage | Every star level 1–5 represented; content sentiment agrees with rating |
| Per-shop rating shape | No 20-review merchant has a single repeated rating bucket |
| Exact duplicates | 0 normalized duplicate review roots, notes and non-security comments |
| Near duplicates | Less than 2% of roots above the configured similarity threshold |
| Content shape | Mixed short/medium/long roots; category-specific aspects; coherent replies |
| Merchant images | 100% display coverage; target at least 50% merchant-specific free-source coverage |
| Merchant fields | Target phone 75%, hours 70%, and real/menu-derived price 30% |
| RAG | P12 frozen security/version gates remain 100%; no material Recall/NDCG regression |

The image and field percentages are stretch targets, not permission to create false
matches. If safe free sources are exhausted, the coverage report records the
maximum verified result and the product keeps its existing fallback value.

## Checkpoint policy

The Pilot and full bundle use new output directories and a new Qdrant path. Do
not overwrite the accepted P11.5 MySQL backup or P12 collection. Before the full
development checkpoint, drain RabbitMQ and pending Redis order state, stop
Spring/Agent writes, back up MySQL, import one coherent bundle, rebuild the P7
map projection, seed Redis and then build the P13 RAG collection.

## Completed checkpoint

The accepted isolated bundle is:

```text
directory:       data/generated/nyc-real-p13-full
dataVersion:     nyc-real-v5-8b645404-m20260824
datasetSha256:   0bb014f6a2e0608a6437c09fc32ac0a6f0791599e988099466e80d272750f238
shops:           5,000
review roots:    100,000
depth-1 replies: 55,000
depth-2 replies: 8,500
notes:           10,000
note comments:   20,000
map locations:   5,000/5,000
```

Content V2 produced zero exact duplicate roots, notes or note comments. The
near-duplicate root rate is 0.294%; all sentiment/rating and local-count checks
agree. Every shop has at least three distinct star buckets across its 20 roots.
The aggregate shop-score range is 2.0–4.7 with standard deviation 0.534.

Free-source enrichment improved the P11.5 baseline without accepting false
matches:

| Field | P11.5 | P13 |
| --- | ---: | ---: |
| Merchant-specific image | 1,871 (37.42%) | 1,906 (38.12%) |
| Phone | 3,290 (65.80%) | 3,381 (67.62%) |
| Business hours | 2,837 (56.74%) | 2,986 (59.72%) |
| Official/menu average price | 844 (16.88%) | 1,014 (20.28%) |
| External price field | 918 (18.36%) | 1,078 (21.56%) |
| Reservation URL | 108 (2.16%) | 619 (12.38%) |

Display images remain 100% covered through the existing category fallback.
The 50% image, 75% phone, 70% hours and 30% price targets remain unmet stretch
targets; P13 records this honestly instead of weakening merchant matching.

The 72-case current-corpus RAG gate passed in the isolated
`agent-service/.local/qdrant-p13-v5-8b645404` directory: Recall@10 0.9954, evidence and
structured constraints 1.0, duplicate/security/version failures 0, and local
P95 3913.364 ms. The evaluator now refuses a collection containing another
corpus so an old scope cannot silently double point count and distort latency.

## Import into the development checkpoint

This is a full development-data replacement. Drain RabbitMQ and the Redis
pending-order index, stop Spring Boot and Agent Service, and back up `nyc_review`
before running these commands from the repository root:

```bash
mysql -u root -p nyc_review \
  < src/main/resources/db/p12_p13_data_quality.sql

mysql -u root -p nyc_review \
  < data/generated/nyc-real-p13-full/mysql_import.sql

mysql -u root -p nyc_review \
  < data/generated/nyc-real-p13-full/p7_neighborhood_import.sql

redis-cli --pipe \
  < data/generated/nyc-real-p13-full/redis_seed.resp

redis-cli DEL cache:shopType:list
```

The additive migration must run before `mysql_import.sql`, because the bundle
inserts the new local/external aggregate columns. The generated SQL sets its
session timezone to UTC and is safe from the NYC DST-gap import error.

Verify the promoted identity and the review-count invariant:

```sql
SELECT data_version, profile, dataset_sha256, shop_count, active
FROM tb_data_import
WHERE active = 1;

SELECT COUNT(*) AS map_locations FROM tb_shop_map_location;

SELECT COUNT(*) AS review_count_mismatches
FROM tb_shop shop
LEFT JOIN (
    SELECT shop_id, COUNT(*) AS root_count
    FROM tb_shop_review
    WHERE parent_id IS NULL OR parent_id = 0
    GROUP BY shop_id
) review_count ON review_count.shop_id = shop.id
WHERE shop.local_review_count <> COALESCE(review_count.root_count, 0)
   OR shop.comments <> COALESCE(review_count.root_count, 0);

SELECT name, local_review_count, comments, local_score,
       external_rating_count, external_score
FROM tb_shop
WHERE name = 'Dino''s Pizzeria';
```

Expected results are one active P13 version, `map_locations=5000`,
`review_count_mismatches=0`, and Dino's Pizzeria showing 20 local reviews while
its external aggregate remains separate.

## Start and verify Agent Service

After Spring Boot has restarted with the imported dataset, start Agent Service
from `agent-service` with the new isolated path:

```bash
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>' \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=./.local/qdrant-p13-v5-8b645404 \
NYC_REVIEW_AGENT_QDRANT_COLLECTION=nyc_review_content_v2 \
NYC_REVIEW_AGENT_RETRIEVAL_VERSION=p12-rag-v1 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-p13-full \
NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE=128 \
NYC_REVIEW_AGENT_MODEL_PROVIDER=deepseek \
uv run uvicorn app.main:app --port 8090
```

The first start may take several minutes. Local Qdrant's over-20,000-point and
payload-index warnings are expected until P15; `Application startup complete`
is the success signal. Never open the same local Qdrant directory from two
processes concurrently.

With Agent Service stopped, the reproducible current-corpus gate is:

```bash
cd agent-service
uv run python -m evals.p12.build_cases \
  --dataset ../data/generated/nyc-real-p13-full \
  --output ./.local/p13-current-cases.json

uv run python -m evals.p12.run_retrieval_eval \
  --cases ./.local/p13-current-cases.json \
  --data-directory ../data/generated/nyc-real-p13-full \
  --qdrant-location ./.local/qdrant-p13-v5-8b645404 \
  --reuse-index \
  --output ./.local/p13-current-report-v5.json
```

Use a new path or collection for a different dataset identity. The evaluator
will fail rather than mix another corpus into this acceptance collection.
