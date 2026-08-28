# Password Login and International Phone Registration Runbook

## 1. Scope

The public authentication flow is now password-only:

- `/login` accepts a country/region selector, national phone number, and password.
- `/register` creates an account, initializes `tb_user_info`, and signs the user in.
- Spring stores every new phone as canonical E.164 and every new password as BCrypt.
- `/user/code` deliberately returns HTTP `410 Gone`; no SMS code is generated or logged.
- The old salted-MD5 format is read only. A successful legacy login immediately replaces it with BCrypt.
- Imported review authors with a blank password remain visible as content authors but cannot authenticate.

The selector currently includes `+1`, `+44`, `+61`, `+81`, `+82`, `+86`, `+852`, `+853`, `+886`, and several common regions. Number parsing and validation happen again in Spring; the browser value is never trusted as canonical.

Login attempts are limited by both a SHA-256-hashed phone identity and client IP. Registration is limited by client IP. Caddy supplies the public client address and the internal Nginx proxy forwards it; Spring, Redis, MySQL, RabbitMQ, Qdrant, and Agent ports must remain private.

## 2. Local migration

Back up `tb_user`, then run the idempotent migration after the active dataset import:

```bash
mysqldump -u root -p nyc_review tb_user tb_user_info > /tmp/nyc-review-users-before-password-auth.sql
mysql -u root -p nyc_review < src/main/resources/db/auth_password_registration.sql
```

The migration widens `phone` to 20 characters, converts original mainland-China national numbers to `+86` E.164 when collision-free, converts blank passwords to `NULL`, widens the hash column, and guarantees the single-column `uk_user_phone` unique index.

Audit the result without printing password hashes:

```bash
mysql -u root -p nyc_review -e "
SELECT COUNT(*) AS users,
       SUM(phone LIKE '+%') AS e164_users,
       SUM(password IS NULL OR TRIM(password) = '') AS no_login_password,
       SUM(password LIKE '\$2%') AS bcrypt_users,
       SUM(password LIKE '%@%') AS legacy_users
FROM tb_user;

SELECT phone, COUNT(*) AS duplicates
FROM tb_user
GROUP BY phone
HAVING COUNT(*) > 1;

SHOW INDEX FROM tb_user WHERE Key_name = 'uk_user_phone';
"
```

An empty duplicate result is required. A high `no_login_password` count is expected for generated review authors; the import bundle intentionally gives them no credentials.

## 3. Existing production deployment

MySQL init scripts run only for a brand-new volume. An already deployed server must apply this migration explicitly before switching both application images.

First create a Lightsail snapshot or a protected MySQL backup. Then upload the latest production bundle as described in `deploy/production/UPDATE.zh-CN.md`. On the server:

```bash
cd /opt/nyc-review
mkdir -p backups
chmod 700 backups

docker compose --env-file .env.production -f compose.production.yml exec -T mysql \
  sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction nyc_review tb_user tb_user_info' \
  > backups/users-before-password-auth.sql
chmod 600 backups/users-before-password-auth.sql

docker compose --env-file .env.production -f compose.production.yml stop web agent-service spring

docker compose --env-file .env.production -f compose.production.yml exec -T mysql \
  sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot nyc_review' \
  < src/main/resources/db/auth_password_registration.sql
```

Run the audit query from section 2 through the same `docker compose exec -T mysql` pattern. Then deploy the immutable application image SHA:

```bash
./scripts/deploy/update-production.sh <full-40-character-commit-sha>
```

Do not deploy only the frontend or only Spring: the old login UI and new API contract are intentionally replaced together. Do not use `docker compose down -v`.

For a fresh empty production volume, `compose.production.yml` mounts the same migration as `/docker-entrypoint-initdb.d/16-password-auth.sql`; no manual migration is needed in that one case.

## 4. API acceptance

Use an unused test number. The following NANP 555 number is an example; registering it creates a persistent smoke-test account:

```bash
curl -i -sS -X POST 'https://YOUR_DOMAIN/api/user/register' \
  -H 'Content-Type: application/json' \
  --data-raw '{"regionCode":"US","phoneNumber":"2125550198","password":"Correct-Horse-2026","nickName":"DeploymentCheck"}'
```

Expected: HTTP `200`, `"success":true`, and a token in `data`. The database phone must be `+12125550198`, while its password prefix must be `$2`.

Log out in the browser or use a new request, then verify login:

```bash
curl -i -sS -X POST 'https://YOUR_DOMAIN/api/user/login' \
  -H 'Content-Type: application/json' \
  --data-raw '{"regionCode":"US","phoneNumber":"2125550198","password":"Correct-Horse-2026"}'
```

Also verify the negative paths:

```bash
curl -i -sS -X POST 'https://YOUR_DOMAIN/api/user/login' \
  -H 'Content-Type: application/json' \
  --data-raw '{"regionCode":"US","phoneNumber":"2125550198","password":"Wrong-Password-2026"}'

curl -i -sS -X POST 'https://YOUR_DOMAIN/api/user/code'
```

The wrong password returns a generic credential error without revealing whether the phone exists. The code endpoint returns HTTP `410` and `SMS login is disabled`.

## 5. Browser acceptance

Check both English and Chinese modes:

1. Open `/register`; switch among `+1`, `+86`, `+886`, `+852`, and `+853` and confirm the national-number input remains editable.
2. Confirm password length, password confirmation, optional nickname, agreement, loading, duplicate-phone, and invalid-number messages.
3. Register and verify automatic sign-in plus redirect to the requested protected page.
4. Sign out, open `/login`, and sign in with the same region, number, and password.
5. Confirm `/login2` and `/login2.html` redirect to `/login`, and no SMS/code countdown UI remains.
6. Confirm Profile, favorites, itineraries, vouchers, AI Guide, DeepSeek translation in Chinese mode, and manual seckill still use the returned token normally.

## 6. Security and recovery boundaries

- Password policy: 8–64 Unicode characters, at most 72 UTF-8 bytes, with at least one letter, one number, and one non-whitespace special character.
- Passwords and raw phone numbers are not used in Redis rate-limit keys; identifiers are SHA-256 hashed.
- There is currently no SMS login and no self-service forgotten-password flow. Do not set passwords for generated authors or users directly to plaintext in MySQL.
- A legacy salted-MD5 account can upgrade only by presenting its correct current password. Blank-password accounts must register with another unused number until a separately designed, identity-verified recovery flow exists.
- Keep only ports 80/443 public and use HTTPS. Direct public access to Spring would make proxy-derived client-address limits unreliable.
- A code rollback can return to the previous images, but the schema widening, E.164 values, and BCrypt hashes should remain. Restoring the pre-migration user backup is only for a coordinated full rollback while writes are stopped.

## 7. Automated checks

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -e MAVEN_CONFIG=/tmp/.m2 \
  -v "$HOME/.m2:/tmp/.m2" \
  -v "$PWD:/workspace" -w /workspace \
  maven:3.9.11-eclipse-temurin-17 \
  mvn -Dmaven.repo.local=/tmp/.m2/repository -Dtest='!NycReviewApplicationTests' test

python3 -m unittest scripts/mock-data-generator/test_generate.py

cd nyc-review-web
npm run lint
npm run build
```

`NycReviewApplicationTests` remains excluded because it contains stateful database and Redis fixture operations.
