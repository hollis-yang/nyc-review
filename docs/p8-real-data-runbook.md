# P8 Real-only NYC Data Runbook

P8 replaces the merchant catalog with traceable public-source identities across all six product categories. In the current `real-medium` profile, merchant names, addresses, coordinates, categories, Boroughs and NTA neighborhoods come from OpenStreetMap. Business hours use OSM `opening_hours` when the pinned snapshot supplies a supported weekly expression, then fall back to a stable category schedule. Ratings come from the generated review roots; per-person prices and sparse discovery attributes are stable estimates. Wikimedia Commons supplies category-matched images and reviews remain generated platform content.

The checked P8 bundle contains 5,000 real merchant identities, 5,000 attributed illustrative-image records and 152,500 synthetic review rows: 100,000 roots, 40,000 level-two replies and 12,500 level-three replies. Root reviews rotate through shop-specific location, price, service, atmosphere, accessibility and tag observations so RAG citations stay useful across repeated queries. The real-data profile, source snapshot and seed are part of `dataVersion`, while the complete content bundle is protected by `datasetSha256` so content-only refreshes also create a separate Qdrant scope.

## 1. Source snapshots and licenses

- Merchant identity: OpenStreetMap contributors, queried through Overpass API and used under ODbL 1.0. The raw dated snapshot is intentionally gitignored; its small `.manifest.json` sidecar records queries, filters, timestamp, counts, license and SHA-256.
- Neighborhood assignment: pinned NYC 2020 NTA `26b` polygons. P7 still performs the map projection and hash checks.
- Images: the pinned `data/sources/wikimedia-illustrative-images-v1.json` catalog retains each Commons file page, author and license URL. These are approximate category illustrations, not merchant images.
- Reviews: deterministic NYC Review test data with `sourceType=SYNTHETIC`. Only depth-0 reviews have ratings; replies have no rating.

P8's “real-only” guarantee applies to merchant identity. Provenance and derived-field metadata remain available to the backend, Agent trace and import validator, but the product UI renders only the merchant, image, score, price, hours and content themselves. Seeded blogs, blog comments and vouchers still carry `sourceType=SYNTHETIC` internally; content created through the online API is assigned `USER_SUBMITTED` by the server, regardless of any client-supplied source field.

## 2. Fetch and generate

Fetch the official NTA snapshot first if it is not already present:

```bash
python3 scripts/mock-data-generator/nyc_nta.py fetch \
  --output data/sources/nyc-nta-2020-26b.geojson
```

Fetch a normalized OSM snapshot. The downloader requires a name, usable address and point-in-polygon NTA assignment, retries transient Overpass failures and emits a sidecar manifest:

```bash
python3 scripts/mock-data-generator/osm_places.py \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/sources/osm-nyc-places-2026-08-23.json
```

Generate, validate and build the matching P7 projection:

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile real-medium \
  --seed 20260817 \
  --real-places data/sources/osm-nyc-places-2026-08-23.json \
  --illustrative-images data/sources/wikimedia-illustrative-images-v1.json \
  --output data/generated/nyc-real-medium

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-medium

python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset data/generated/nyc-real-medium \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/generated/nyc-real-medium/p7_neighborhood_import.sql
```

The checked local result is:

```text
dataVersion       nyc-real-v1-6c1c6380-m20260817
datasetSha256     7fbb75061c4f0f14baed464f2710ab628456dfcba7c2c9ca9a2e6a35c4678b5c
shops             5000 (OPENSTREETMAP only)
review rows       152500 (100000 / 40000 / 12500 by depth)
business hours    2311 OSM-derived, 2689 category fallback (35000 daily rows)
price/score/tags  5000 complete, no missing display values
NTA assignment    5000 POINT_IN_POLYGON, 0 unassigned
```

A new source fetch can legitimately produce a different hash and version. Use the values from that bundle's `manifest.json`; do not hard-code the sample version into application configuration.

## 3. Safe replacement checklist

`mysql_import.sql` replaces the active development users, shops, reviews, vouchers, orders and dependent Profile/Agent assets. First block new flash-sale traffic, but keep Spring running long enough for its RabbitMQ consumer to finish every accepted order. Both RabbitMQ queues and the Redis pending index must be empty, otherwise a durable message from the old dataset could be replayed against a reused numeric voucher ID:

```bash
rabbitmqctl list_queues -p / name messages_ready messages_unacknowledged
redis-cli ZCARD seckill:pending:orders
```

For Docker Compose, run the RabbitMQ check inside its container:

```bash
docker compose -f docker-compose.p4.yml exec rabbitmq \
  rabbitmqctl list_queues -p / name messages_ready messages_unacknowledged
```

Do not purge a non-empty queue as part of the migration. Let the order queue drain while Spring is still running, and investigate any failed/error messages. Only after the queues and pending index are empty should you stop Spring and Agent Service, verify the target database name, and back up anything you need before importing. Do not run the replacement against a database containing valuable user data.

## 4. MySQL, map and Redis import

If this database has already completed P6 and P7, do **not** rerun `p8_p6_data_provenance.sql`: that historical migration uses direct `ADD COLUMN` statements and is not idempotent. For the user's current P6/P7 database, apply only P10 before the replacement bundle, then rebuild the matching P7 projection:

```bash
mysql -u root -p nyc_review < src/main/resources/db/p10_p8_real_content.sql
mysql -u root -p nyc_review < data/generated/nyc-real-medium/mysql_import.sql
mysql -u root -p nyc_review < data/generated/nyc-real-medium/p7_neighborhood_import.sql
redis-cli --pipe < data/generated/nyc-real-medium/redis_seed.resp
```

For a fresh database initialized only from the base/P1-P5 migrations, apply the remaining schemas once in this order before the generated import:

```bash
mysql -u root -p nyc_review < src/main/resources/db/p8_p6_data_provenance.sql
mysql -u root -p nyc_review < src/main/resources/db/p9_p7_map_geospatial.sql
mysql -u root -p nyc_review < src/main/resources/db/p10_p8_real_content.sql
```

P9 and P10 are safe to rerun; P8 is not. In either path, the generated `mysql_import.sql` replaces the active dataset and the generated P7 SQL rebuilds its map projection.

The Redis bundle deletes old shop, review, geo, seckill, feed and sign dataset keys before reseeding. It intentionally does not delete login sessions. Because the MySQL user fixture is replaced, force a new login by deleting only login-token keys:

```bash
redis-cli --scan --pattern 'login:token:*' |
  while IFS= read -r key; do redis-cli DEL "$key"; done
```

Users must sign in again and use the new token for Spring, Agent runs and Profile assets.

Existing Agent run history may be retained for audit, but an action proposed by a
different `dataVersion` or `datasetSha256` is rejected before any Spring write tool
is called. To keep P8 history visually separate without deleting the old SQLite
store, set `NYC_REVIEW_AGENT_RUN_STORE_PATH=/data/runs/agent-runs-p8.sqlite3` when using
Docker Compose.

## 5. Read-only database acceptance

```sql
SELECT data_version, profile, dataset_sha256, shop_count, active
FROM tb_data_import
ORDER BY imported_at DESC LIMIT 1;

SELECT source_type, COUNT(*) AS shops
FROM tb_shop
GROUP BY source_type;

SELECT type_id, COUNT(*) AS shops
FROM tb_shop
GROUP BY type_id
ORDER BY type_id;

SELECT borough, COUNT(*) AS shops
FROM tb_shop
GROUP BY borough
ORDER BY borough;

SELECT COUNT(*) AS missing_provenance
FROM tb_shop
WHERE source_type <> 'OPENSTREETMAP'
   OR external_id IS NULL OR source_url IS NULL OR source_fetched_at IS NULL;

SELECT COUNT(*) AS duplicate_external_ids
FROM (
  SELECT source_type, external_id
  FROM tb_shop
  GROUP BY source_type, external_id
  HAVING COUNT(*) > 1
) AS duplicated;

SELECT
  SUM(avg_price IS NULL) AS missing_price,
  SUM(score IS NULL) AS missing_score,
  SUM(open_hours IS NULL) AS missing_hours
FROM tb_shop;

SELECT COUNT(DISTINCT shop_id) AS shops_with_seven_days
FROM (
  SELECT shop_id
  FROM tb_shop_business_hours
  GROUP BY shop_id
  HAVING COUNT(*) = 7
) AS complete_hours;

SELECT image_type, source_name, COUNT(*) AS images
FROM tb_shop_image
GROUP BY image_type, source_name;

SELECT depth, source_type, COUNT(*) AS reviews,
       SUM(rating IS NULL) AS null_ratings
FROM tb_shop_review
GROUP BY depth, source_type
ORDER BY depth;

SELECT 'blog' AS content_type, source_type, COUNT(*) AS rows_count
FROM tb_blog GROUP BY source_type
UNION ALL
SELECT 'blog_comment', source_type, COUNT(*)
FROM tb_blog_comments GROUP BY source_type
UNION ALL
SELECT 'voucher', source_type, COUNT(*)
FROM tb_voucher GROUP BY source_type;

SELECT assignment_method, COUNT(*) AS shops
FROM tb_shop_map_location
WHERE data_version = (
  SELECT data_version FROM tb_data_import WHERE active = 1 LIMIT 1
)
GROUP BY assignment_method;
```

Expected invariants: exactly one active import, `OPENSTREETMAP=5000`, all six `type_id` values and all five Boroughs are present, missing/duplicate provenance counts are zero, price/score/hours missing counts are zero, `shops_with_seven_days=5000`, all 152,500 reviews retain their internal `SYNTHETIC` type, reply ratings are `NULL`, and all map rows are `POINT_IN_POLYGON`.

## 6. Start Spring and Agent/RAG

Start Spring normally, then point Agent Service at the exact directory whose SQL was imported. A Qdrant server is recommended for this dataset; local-path Qdrant permits only one process and is less suitable for a 135,000-document index.

```bash
cd agent-service
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>' \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=http://127.0.0.1:6333 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-medium \
NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE=128 \
uv run uvicorn app.main:app --port 8090
```

Startup verifies file hashes, shop IDs, dynamic `dataVersion`, six-category coverage, unique traceable identities and `REAL_ONLY` provenance before indexing. Qdrant stores the complete `datasetSha256` in every payload and includes it in the point ID, synchronization scope and retrieval filter. It hashes each document, embeds only changed content in batches, and deletes stale points only after successful upserts.

Inspect Spring provenance and hierarchical evidence:

```bash
curl -sS -H 'authorization: <current-user-token>' \
  http://127.0.0.1:8081/internal/agent/tools/shops/1

curl -sS -H 'authorization: <current-user-token>' \
  'http://127.0.0.1:8081/internal/agent/tools/shops/1/evidence?limit=5'
```

Run the multi-Agent preview:

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs/preview \
  -H 'Content-Type: application/json' \
  -d '{"mode":"multi","constraints":{"query":"quiet dinner in Midtown","neighborhood":"Midtown","category":"Food & Dining"}}'
```

Check `metadata.dataVersion`, `datasetSha256`, `sourceCounts.OPENSTREETMAP=5000`, `ragIndexStats`, the five Agent node events and thread-level citations. Citation excerpts must contain only readable review/post text—no thread IDs, generator labels or source explanations. MCP still exposes exactly the six read-only P5 tools and no write or seckill tool.

## 7. UI acceptance

- English remains the default; Chinese remains selectable in Profile > Edit Profile.
- Shop cards, details, map popups and AI Guide show ratings and prices directly, without confidence, source, demo or synthetic labels.
- Blog cards/details, comments, reviews and vouchers show only their content and normal product metadata.
- Shop images render directly without illustrative-image or provenance explanations.
- Reviews render as level 1/2/3 threads. Chinese mode offers DeepSeek translation; English mode does not.
- Every generated shop has a price estimate and seven daily hour rows; OSM hours take precedence over fallback schedules.
- A relaxed desired-tag search is shown as a closest-match notice and is not repeated as one verifier error per candidate.
- The map still switches Borough clusters, NTA clusters and shop markers by zoom, with multi-category filtering.
- Manual flash sale, RabbitMQ delivery, Profile favorites/itineraries/vouchers/reminders, multi-Agent, RAG, Trace and the six read-only MCP tools continue to work.

## 8. Automated regression

These commands do not import into MySQL or mutate Redis:

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
python3 scripts/mock-data-generator/validate_dataset.py data/generated/nyc-real-medium
uv run --project agent-service pytest agent-service/tests -q
uv run --project agent-service ruff check agent-service/app agent-service/tests
mvn clean -Dtest='!NycReviewApplicationTests' test
cd nyc-review-web && npm run build
```

`NycReviewApplicationTests` still constructs database and Redis data and should not run against an environment carrying valuable state. Docker init scripts run only for a new MySQL volume; never delete an existing volume merely to trigger P8 initialization.
