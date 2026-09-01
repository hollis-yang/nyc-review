# NYC Review production deployment

For the repeatable Chinese release checklist, see
[`UPDATE.zh-CN.md`](./UPDATE.zh-CN.md).

This deployment targets one x86_64 Ubuntu 24.04 Lightsail instance with 4 GB RAM,
the 2 GB swap file described in the P15 plan, and Docker Compose. It runs one
Agent Service instance. MySQL, Redis, RabbitMQ, Qdrant, Spring, and Agent ports
are never published on the host; Caddy is the only public entry point on ports
80 and 443.

During the RAG M1-Mx development window, production deliberately separates the
application release from the Agent release. `IMAGE_TAG` advances Spring and Web,
while `AGENT_IMAGE_TAG` remains pinned to the last production-verified pre-M1
Agent image. This prevents unfinished embedding and index-layout changes from
reaching the existing Qdrant collection.

## 1. Publish application images

Push the production files to `main`. The `Publish production images` GitHub
Actions workflow builds Linux/amd64 images and publishes both an immutable
`sha-<full commit SHA>` tag and a moving `main` tag to GHCR. Deploy only the
immutable SHA tag.

If the GHCR packages are private, create a classic GitHub personal access token
with `read:packages` only for the server. Do not put that token in
`.env.production` or commit it.

## 2. Prepare deployment files locally

Create a small deployment bundle that excludes source code and generated data:

```bash
./scripts/deploy/package-production-bundle.sh
```

Create the separate P13 data archive:

```bash
tar -C data/generated -czf /tmp/nyc-real-p13-full.tar.gz nyc-real-p13-full
```

Upload both archives with the Lightsail SSH key. Replace the example paths and
static IP:

```bash
scp -i /path/to/LightsailDefaultKey-us-east-1.pem \
  dist/nyc-review-production-bundle.tar.gz \
  /tmp/nyc-real-p13-full.tar.gz \
  ubuntu@YOUR_STATIC_IPV4:/tmp/
```

## 3. Prepare the server directory

Run on Lightsail:

```bash
sudo mkdir -p /opt/nyc-review/data
sudo chown -R ubuntu:ubuntu /opt/nyc-review
tar -xzf /tmp/nyc-review-production-bundle.tar.gz -C /opt/nyc-review
tar -xzf /tmp/nyc-real-p13-full.tar.gz -C /opt/nyc-review/data
find /opt/nyc-review/data/nyc-real-p13-full -type d -exec chmod 0755 {} +
find /opt/nyc-review/data/nyc-real-p13-full -type f -exec chmod 0644 {} +
cd /opt/nyc-review
cp .env.production.example .env.production
chmod 600 .env.production
```

The explicit data permissions are required because macOS archives can preserve
owner-only modes. The Agent runs as an unprivileged container user and mounts
the P13 dataset read-only.

Edit `.env.production`. Generate a different safe value for every password and
service token:

```bash
openssl rand -hex 32
```

Set `IMAGE_TAG` to the exact `sha-<full commit SHA>` produced by the successful
workflow. Keep `AGENT_IMAGE_TAG` at the production-verified pre-M1 release
`sha-c2e712c9f5e55ac53a91024886df53ed806c371b`; this image was confirmed on the
production host on 2026-08-31. The checker rejects every other Agent tag during
the isolation window. For trusted HTTPS, point a DNS A record at the Lightsail
static IPv4 and set `APP_SITE_ADDRESS` to that hostname. Caddy then obtains and
renews the certificate automatically. A temporary IP-only smoke test can use
`APP_SITE_ADDRESS=http://YOUR_STATIC_IPV4`.

## 4. Validate without exposing secrets

The checker renders Compose into a protected temporary file, verifies that no
service is built on the server, rejects placeholders/reused short secrets,
checks the P13 files, and confirms that only 80/443 are published:

```bash
./scripts/deploy/check-production-config.sh .env.production
```

The committed example itself can be structurally checked with:

```bash
./scripts/deploy/check-production-config.sh --example
```

## 5. Authenticate and start

For private GHCR packages, log in without saving the token in shell history:

```bash
read -rsp "GHCR read token: " NYC_REVIEW_GHCR_TOKEN
echo
printf '%s' "$NYC_REVIEW_GHCR_TOKEN" | docker login ghcr.io -u hollis-yang --password-stdin
unset NYC_REVIEW_GHCR_TOKEN
```

Pull and start. Do not add `--build`:

```bash
docker compose --env-file .env.production -f compose.production.yml pull
docker compose --env-file .env.production -f compose.production.yml up -d
docker compose --env-file .env.production -f compose.production.yml ps
```

The first start imports the 97 MB P13 SQL bundle and incrementally indexes the
RAG dataset into Qdrant, so MySQL and Agent readiness can take several minutes.
Follow progress without printing environment variables:

```bash
docker compose --env-file .env.production -f compose.production.yml logs -f --tail=100 mysql agent-service
```

## 6. Verify the public boundary

From another computer:

```bash
curl --fail --show-error https://YOUR_DOMAIN/
curl --fail --show-error https://YOUR_DOMAIN/api/shop-type/list
curl --fail --show-error https://YOUR_DOMAIN/agent-api/health
```

On Lightsail, confirm resource usage and published sockets:

```bash
docker stats --no-stream
sudo ss -lntup
```

Docker should publish only 80/tcp, 443/tcp, and 443/udp. SSH remains managed by
the Lightsail firewall. Never publish 3306, 6379, 5672, 6333, 8081, 8090, or a
RabbitMQ management port.

## Updating

After a later successful workflow, change only `IMAGE_TAG` to the new immutable
SHA and run the checker, `pull`, and `up -d` again. Leave `AGENT_IMAGE_TAG`
unchanged throughout M1-Mx development. Compose replaces Spring and Web without
rebuilding on the server and keeps the old Agent image.

An Agent rollout is a separate production change. Before changing
`AGENT_IMAGE_TAG`, validate the selected embedding against a new versioned
Qdrant collection, confirm server/client compatibility and memory capacity, and
prepare an atomic rollback of both the Agent tag and its RAG configuration. Do
not point a 1024-dimensional embedding at the existing 64-dimensional
`nyc_review_content_v2` collection.

Do not run `docker compose down -v`; `-v` removes the persistent database,
broker, Qdrant, upload, certificate, and Agent-run volumes.
