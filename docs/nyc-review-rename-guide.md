# NYC Review Rename Guide

The product and engineering identifier is now **NYC Review**. Use
`nyc-review` for artifact, container, volume and service names,
`com.nycreview` for Java packages, and `NYC_REVIEW_` for environment
variables.

## Local configuration

The root `.env` has moved to these prefixes:

- Spring, MySQL, Redis, RabbitMQ and uploads: `NYC_REVIEW_`
- Agent Service: `NYC_REVIEW_AGENT_`

Copy `.env.example` again when creating a fresh environment. Existing secret
values do not change; only their keys and the database URL need to use the new
names.

## Existing MySQL data

The default database is now `nyc_review`. MySQL does not support an atomic
database rename, so migrate an existing local database through a dump:

```bash
mysqldump -u root -p <previous-database-name> > /tmp/nyc-review-before-rename.sql
mysql -u root -p -e "CREATE DATABASE nyc_review CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
mysql -u root -p nyc_review < /tmp/nyc-review-before-rename.sql
```

After verifying the application against `nyc_review`, keep or remove the
previous database according to your own backup policy. A fresh environment can
instead import `src/main/resources/db/nyc_review.sql` and the phase migrations
listed in the root README.

## RabbitMQ and Redis

RabbitMQ exchanges and queues now begin with `nyc-review.`. Before switching a
running environment, let the previous order queue drain so no accepted order is
stranded under the previous routing names. Spring declares the new durable
resources automatically on startup.

Redis business keys remain compatible unless they contained the former project
namespace. P14 load-test sentinels now begin with `nyc-review:`.

## Qdrant

The default collection is `nyc_review_content_v2`. Agent Service rebuilds or
incrementally synchronizes it from the configured RAG dataset. The previous
collection can be removed only after the new collection passes health and RAG
evaluation checks.

## Docker and frontend

The React application directory is `nyc-review-web`. Docker named volumes now
begin with `nyc-review-`; therefore the renamed Compose files create a fresh
set of volumes instead of silently attaching the previous stack's volumes.

The workspace's parent directory is not part of the application contract. It
can be renamed separately after stopping local processes and closing tools that
hold the current path open.

## Historical artifacts

Accepted P14.1 reports and already generated data bundles are immutable
snapshots. They can contain former runtime identifiers because changing them
would falsify recorded evidence or invalidate dataset hashes. New reports and
newly generated bundles use NYC Review identifiers.
