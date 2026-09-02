# NYC Review Production Deployment

This runbook deploys NYC Review to one x86_64 Ubuntu 24.04 Lightsail instance with 4 GB RAM, 2 GB swap, Docker, and Docker Compose. Caddy is the only public entry point; application and data-service ports remain private.

## Prerequisites

- Point a DNS record to the instance, or use its static IP for an HTTP smoke test.
- Allow SSH, HTTP, and HTTPS in the Lightsail firewall.
- Install Docker Engine and the Compose plugin.
- Prepare the release dataset required by `.env.production.example` and the configuration checker. Make it readable by unprivileged containers.
- Provision the matching external Qdrant volume. If RAG verification is enabled, it must already contain the configured collection.

## Publish images

Push the release commit to `main`. The `Publish production images` workflow publishes Spring, Agent, and Web images to GHCR with immutable `sha-<full-commit-sha>` tags. Deploy only an immutable tag, and use the same commit for all three services.

If the packages are private, create a GitHub token with `read:packages` only. Keep it out of `.env.production` and shell history.

## Prepare the server

Create the deployment directory on the instance:

```bash
sudo mkdir -p /opt/nyc-review/data
sudo chown -R "$USER":"$USER" /opt/nyc-review
```

Package the deployment files locally:

```bash
./scripts/deploy/package-production-bundle.sh
```

Upload and extract `dist/nyc-review-production-bundle.tar.gz`, then upload the validated dataset to a directory under `/opt/nyc-review/data`. Ensure directories are mode `0755` and files are mode `0644` so the Agent container can read them.

On the server:

```bash
cd /opt/nyc-review
cp .env.production.example .env.production
chmod 600 .env.production
```

Replace every placeholder. Set the site address, immutable image tags, dataset path, Qdrant volume, provider credentials, and a different random value for every service secret:

```bash
openssl rand -hex 32
```

For automatic HTTPS, set `APP_SITE_ADDRESS` to the DNS name. For a temporary IP test, use `http://YOUR_STATIC_IPV4`.

## Validate and start

The checker validates secrets, image tags, dataset files, RAG settings, volume mounts, restart policies, and the public port boundary:

```bash
./scripts/deploy/check-production-config.sh .env.production
```

Authenticate to GHCR without storing the token in shell history:

```bash
read -rsp "GHCR read token: " NYC_REVIEW_GHCR_TOKEN
echo
printf '%s' "$NYC_REVIEW_GHCR_TOKEN" | docker login ghcr.io -u hollis-yang --password-stdin
unset NYC_REVIEW_GHCR_TOKEN
```

Start the release:

```bash
docker compose --env-file .env.production -f compose.production.yml pull
docker compose --env-file .env.production -f compose.production.yml up -d --wait --wait-timeout 900
docker compose --env-file .env.production -f compose.production.yml ps
```

Follow startup without printing environment variables:

```bash
docker compose --env-file .env.production -f compose.production.yml logs -f --tail=100 mysql agent-service
```

## Verify

From another machine:

```bash
curl --fail --show-error https://YOUR_DOMAIN/
curl --fail --show-error https://YOUR_DOMAIN/api/shop-type/list
curl --fail --show-error https://YOUR_DOMAIN/agent-api/health
```

On the server:

```bash
docker stats --no-stream
sudo ss -lntup
```

Docker should publish only ports 80 and 443. Never publish MySQL, Redis, RabbitMQ, Qdrant, Spring Boot, or Agent ports.

## Release updates

After all image jobs succeed, run the release helper with `HEAD` and `origin/main` at the target commit. Release inputs must be clean, and every manifest-declared generated payload must exist; unrelated working-tree changes are allowed.

```bash
RELEASE_COMMIT_SHA=replace-with-full-commit-sha

LIGHTSAIL_SSH_KEY=/path/to/key.pem \
LIGHTSAIL_SSH_TARGET=ubuntu@YOUR_STATIC_IPV4 \
NYC_REVIEW_REMOTE_ROOT=/opt/nyc-review \
./scripts/deploy/release-production.sh "$RELEASE_COMMIT_SHA"
```

The helper verifies the commit, packages declared database changes, uploads the release, applies each change once, and updates all application images together. A failed image update restores the previous tags and containers, but it does not roll back applied MySQL or Redis changes. Back up production data before every release.

Changing an embedding model, vector dimension, or collection requires a compatible prebuilt Qdrant volume and an explicit rollback plan.

Never run `docker compose down -v` in production. It deletes persistent database, queue, vector, upload, certificate, and run-store volumes.
