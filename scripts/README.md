# Project Scripts

This directory contains reproducible engineering tools, not application runtime code. Generated data, caches, and reports are stored elsewhere and ignored by Git.

| Directory | Purpose |
| --- | --- |
| `db/` | Build and verify the empty MySQL bootstrap schema |
| `deploy/` | Validate, package, and update production releases |
| `mock-data-generator/` | Build deterministic datasets and import bundles |
| `load-test/` | Run isolated load and recovery tests |
| `quality/` | Check frontend and cross-service contracts |

Common checks:

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
python3 scripts/load-test/test_contracts.py
python3 scripts/quality/frontend_contracts.py
```

Rebuild the empty bootstrap schema and verify the initialization chain against a generated dataset:

```bash
export NYC_REVIEW_DATA_DIR=/absolute/path/to/dataset
python3 scripts/db/build_bootstrap_schema.py \
  --verify-dataset "$NYC_REVIEW_DATA_DIR"
```

The command rewrites `src/main/resources/db/bootstrap-schema.sql`. It uses a temporary, network-disabled MySQL container and never targets an existing database.
