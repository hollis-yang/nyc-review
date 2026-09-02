# NYC Data Generator

This tool creates deterministic local-business datasets without connecting to MySQL, Redis, Qdrant, or a model provider. It writes only to the requested output directory.

## Profiles

| Profile | Merchant identities | Root reviews | Use |
| --- | ---: | ---: | --- |
| `small` | 36 synthetic | 144 | Unit and container tests |
| `demo` | 250 synthetic | 2,500 | UI and agent tests |
| `medium` | 2,000 synthetic | 16,000 | Scale tests |
| `load` | 20,000 synthetic | 40,000 | Load tests |
| `real-small` | 12 sourced | 60 | Fast contract tests |
| `real-medium` | 5,000 sourced | 100,000 | Standard full dataset |
| `real-large` | 10,000 sourced | 200,000 | Larger validation |
| `real-load` | 15,000 sourced | 300,000 | Large load tests |

Review totals count rated root reviews. Sourced profiles also create deterministic first- and second-level replies. The default seed is `20260817`.

For sourced profiles, approximately 60% of merchants receive regular offers, 30% receive user-operated flash-sale offers, and 10% receive none. The groups do not overlap.

## Generate and validate

From the repository root:

```bash
python3 scripts/mock-data-generator/generate.py \
  --profile real-medium \
  --real-places data/sources/osm-nyc-places-2026-08-23.json \
  --illustrative-images data/sources/wikimedia-illustrative-images-v1.json \
  --output data/generated/nyc-real-medium

python3 scripts/mock-data-generator/validate_dataset.py \
  data/generated/nyc-real-medium
```

After generation, build the neighborhood projection. Replace the map filename below with the filename mounted by the active Compose file:

```bash
export NYC_REVIEW_DATA_DIR="$PWD/data/generated/nyc-real-medium"
export NYC_REVIEW_MAP_IMPORT="$NYC_REVIEW_DATA_DIR/replace-with-compose-map-filename"

python3 scripts/mock-data-generator/build_neighborhood_import.py \
  --dataset "$NYC_REVIEW_DATA_DIR" \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output "$NYC_REVIEW_MAP_IMPORT"
```

Use `--help` on any script for its full option list.

## Data sources

Sourced profiles use pinned inputs:

- OpenStreetMap supplies merchant names, external identifiers, locations, categories, and available tags under ODbL.
- NYC Neighborhood Tabulation Areas supply borough and neighborhood boundaries.
- Wikimedia Commons supplies attributed category illustrations, which may be reused and are not merchant photos.

Users, reviews, replies, ratings, posts, comments, offers, favorites, and other platform activity are synthetic. Missing hours, prices, and search tags may be filled by deterministic rules. Source type, snapshot identity, license metadata, record counts, and checksums are retained in the generated manifests.

To refresh public snapshots intentionally:

```bash
python3 scripts/mock-data-generator/nyc_nta.py fetch \
  --output data/sources/nyc-nta-2020-26b.geojson

python3 scripts/mock-data-generator/osm_places.py \
  --nta-snapshot data/sources/nyc-nta-2020-26b.geojson \
  --output data/sources/osm-nyc-places-2026-08-23.json

python3 scripts/mock-data-generator/wikimedia_images.py \
  --images-per-type 3 \
  --output data/sources/wikimedia-illustrative-images-v1.json
```

Refreshing a snapshot changes dataset checksums. Review and pin the new source before using it in a shared environment.

## Import safety

The generated bundle contains a transactional MySQL import, a scoped Redis seed, manifests, and RAG documents. The neighborhood builder adds the map projection used by Compose.

Importing the bundle replaces application data. Before import:

1. Stop new order traffic and drain RabbitMQ and pending Redis order records.
2. Stop Spring Boot and the agent service.
3. Back up the target database.
4. Apply unapplied files from `src/main/resources/db/migrations/`.
5. Import the MySQL data, map projection, and Redis seed in that order.

For a new database, import `src/main/resources/db/bootstrap-schema.sql` first. Never apply that bootstrap schema over an existing database. The Redis seed removes only project-owned derived keys; it does not run `FLUSHDB`.

Use the overlay builders in this directory when changing a supported subset such as offers or demo activity. Each script documents its inputs with `--help`; back up affected tables before applying an overlay.

## Test

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
```
