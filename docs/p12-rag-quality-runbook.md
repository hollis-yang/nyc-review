# P12 RAG Quality Runbook

P12 upgrades retrieval without changing the accepted P11.5 MySQL or Redis
checkpoint. The frozen corpus remains
`nyc-real-v4-0f51676d-m20260824` with dataset SHA-256
`3eb30998c46f493fd0528cfea8788188ab3e4d30821f1324f7e7d3b8a03d3234`.
P12 adds an independent retrieval identity, `p12-rag-v1`, and uses collection
`nyc_review_content_v2` in a new Qdrant directory.

## What changed

- Every shop now has separate immutable identity and resolved-attribute FACT
  documents. Reviews, blogs and descriptions remain EVIDENCE documents.
- Query planning expands English synonyms and Chinese intent into canonical
  category/tag terms. Both Unicode lexical terms and dense vectors are indexed.
- Spring and the generated adapter return up to 50 candidates by default (100
  maximum). Qdrant fuses dense and sparse results with RRF, then combines tag,
  distance and rating signals to select the final five cards.
- Exact source identities are deduplicated and the same normalized brand is
  limited to two results. Evidence selection returns distinct sources and roots,
  prefers one FACT plus one review, and excludes security-test content.
- Verifier rejects duplicate IDs/merchant identities, citation/shop mismatch,
  duplicate evidence, security-test leakage and mixed dataset versions.
- Preview, Run, Trace and MCP search expose the same retrieval version and
  ranking metadata. MCP remains read-only.

## 1. Safe regression tests

From the repository root:

```bash
uv run --project agent-service pytest agent-service/tests -q
mvn -Dtest='!NycReviewApplicationTests' test
```

These commands do not import or modify MySQL/Redis. The Python suite uses only
in-memory Qdrant fixtures unless a test explicitly provides a temporary path.

## 2. Verify the committed frozen suite

The committed suite contains 72 cases: 60 English and 12 Chinese, balanced
across all six categories. Its gold labels are stable OSM external identities,
not mutable database row IDs.

```bash
cd agent-service
uv run python -m evals.p12.build_cases
git diff --exit-code -- evals/p12/cases.json
```

Expected values:

```text
cases: 72
dataVersion: nyc-real-v4-0f51676d-m20260824
datasetSha256: 3eb30998c46f493fd0528cfea8788188ab3e4d30821f1324f7e7d3b8a03d3234
caseSha256: a6ee9efc8211c5b2e68c5984fc860d2139b15fb7321cafaa63bd6f0e278384fa
indexedDocuments: 145000
```

## 3. Build the isolated full index and run the gate

Stop any Agent process that is using the same directory, then run:

```bash
cd agent-service
uv run python -m evals.p12.run_retrieval_eval \
  --qdrant-location ./.local/qdrant-p12 \
  --output ./.local/p12-eval-report.json
```

The first run creates about 145,000 points. Later runs hash-check and reuse
unchanged points. Local Qdrant will warn above 20,000 points and its payload
indexes are ineffective; those warnings are expected until P15 moves the
collection to Qdrant Server.

While tuning only the retrieval code, a completed isolated index can skip the
145,000-document hash scan; the evaluator still checks the exact point count:

```bash
uv run python -m evals.p12.run_retrieval_eval \
  --qdrant-location ./.local/qdrant-p12 \
  --reuse-index \
  --output ./.local/p12-eval-report.json
```

The command fails if any gate is missed:

- mean Recall@10 below 85%;
- evidence coverage below 95%;
- structured-constraint satisfaction below 90%;
- any duplicate merchant or more than two copies of a normalized brand;
- any security-test citation or mixed `dataVersion`/`datasetSha256`;
- P95 retrieval latency above 7 seconds in the local acceptance environment.

The latency ceiling is deliberately local-mode specific. P12 still records the
observed value, while P14 owns load targets and P15 makes payload indexes
effective by moving to Qdrant Server.

Accepted full-corpus result on 2026-08-24:

```text
indexed points:                    145000
mean Recall@10:                    0.9954
evidence coverage:                 1.0000
structured constraint satisfaction: 1.0000
duplicate merchant rate:           0.0000
excessive brand count:              0
security leakage count:             0
version mismatch rate:              0.0000
P95 local retrieval latency:        5201.775 ms
```

The complete local report is written to `.local/p12-eval-report.json`; `.local`
is intentionally not committed.

## 4. Start Agent Service with the P12 index

```bash
cd agent-service
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN='<current-user-token>' \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=./.local/qdrant-p12 \
NYC_REVIEW_AGENT_QDRANT_COLLECTION=nyc_review_content_v2 \
NYC_REVIEW_AGENT_RETRIEVAL_VERSION=p12-rag-v1 \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-real-p11-5-full \
NYC_REVIEW_AGENT_DISCOVERY_POOL_SIZE=50 \
NYC_REVIEW_AGENT_MAX_CANDIDATES=5 \
NYC_REVIEW_AGENT_RAG_INDEX_BATCH_SIZE=128 \
uv run uvicorn app.main:app --port 8090
```

This does not require a database migration. Spring must be restarted because
its internal Agent search limit increased from 20 to 100.

## 5. Product/API acceptance

Create a normal multi-Agent Run:

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs/preview \
  -H 'Content-Type: application/json' \
  -H 'authorization: <current-user-token>' \
  -d '{"mode":"multi","constraints":{"query":"安静且无障碍的 Midtown 餐厅","neighborhood":"Midtown","category":"Food & Dining","desired_tags":["quiet","wheelchair_accessible"]}}'
```

Check that:

- `metadata.retrievalVersion` is `p12-rag-v1`;
- Discovery events contain `candidate_pool_ready` and `hybrid_ranked`;
- candidate retrieval metadata reports a pool larger than or equal to the final
  count and `finalCandidates` is at most five;
- citations contain matching shop IDs and one FACT/review mix where available;
- Trace Discovery/Evidence spans include retrieval latency and hit counts;
- repeated merchants, security-test text and old dataset citations do not appear.

## 6. Evaluate a future corpus without moving the frozen baseline

P13 or later data must create a separate current-corpus suite and Qdrant path:

```bash
cd agent-service
uv run python -m evals.p12.build_cases \
  --dataset ../data/generated/<new-dataset> \
  --output ./.local/p12-current-cases.json

uv run python -m evals.p12.run_retrieval_eval \
  --cases ./.local/p12-current-cases.json \
  --data-directory ../data/generated/<new-dataset> \
  --qdrant-location ./.local/qdrant-current \
  --output ./.local/p12-current-report.json
```

The committed P11.5 suite measures regression against a fixed baseline; the
generated current suite measures robustness on newly added merchants. Unit
stress cases independently enforce duplicate, prompt-injection and version
isolation invariants. New data may change ranked results, but it cannot silently
rewrite the frozen benchmark.

## Rollback

P12 writes only the new Qdrant directory and code. To roll back, stop Agent
Service, start the previously accepted code/config against
`./.local/qdrant-p11-5`, and keep the P12 directory for diagnosis. MySQL and
Redis require no rollback because P12 never mutates them.
