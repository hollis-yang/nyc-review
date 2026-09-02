# NYC Review Web

The web app provides merchant discovery, an interactive NYC map, reviews, offers, profiles, and an AI planning workspace. It uses React, TypeScript, Vite, Leaflet, and Ant Design Mobile.

## Run locally

Node.js `^20.19.0` or `>=22.12.0`, and npm 10+ are required.

```bash
cd nyc-review-web
npm ci
npm run dev
```

Vite serves `http://127.0.0.1:3000`. It proxies `/api` to Spring Boot at `http://127.0.0.1:8081` and `/agent-api` to the agent service at `http://127.0.0.1:8090`.

Override the proxy targets when needed:

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8081 \
VITE_AGENT_PROXY_TARGET=http://127.0.0.1:8090 \
npm run dev
```

## Checks

```bash
npm run lint
npm test
npm run build
```

`npm run release:check` also runs Python contract checks and the Agent lint and test suites, so Python 3.11+ and `uv` are required. Production output is written to `dist/`.
