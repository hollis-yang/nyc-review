# Project scripts

This directory contains reproducible engineering tools rather than application runtime code. Generated datasets, planning documents, caches and test reports are intentionally stored outside this directory and ignored by Git.

| Directory | Purpose | Keep because |
| --- | --- | --- |
| `db/` | Build and verify the current empty MySQL bootstrap schema | Fresh Compose environments depend on the generated schema |
| `deploy/` | Validate, package and update the production deployment | Used by the server release workflow |
| `mock-data-generator/` | Create the deterministic base dataset, import bundle and neighborhood projection | Required to rebuild development and Agent/RAG data |
| `load-test/` | Run the isolated Compose, k6, Agent soak and failure-recovery suite | Provides repeatable backend performance and reliability checks |
| `quality/` | Run lightweight cross-frontend contract checks | Protects bilingual, map and multi-Agent UI contracts |

Common safe checks:

```bash
python3 -m unittest scripts/mock-data-generator/test_generate.py
python3 scripts/load-test/test_contracts.py
python3 scripts/quality/frontend_contracts.py
```

Rebuild and verify the three-part database initialization chain:

```bash
python3 scripts/db/build_bootstrap_schema.py \
  --verify-dataset data/generated/nyc-real-p13-full
```

The verification command uses an isolated, network-disabled temporary MySQL container and removes only that container when finished. Existing development and production databases are never targeted.
