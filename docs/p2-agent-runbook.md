# P2 Agent 产品化 Runbook

P2 将 P1 的多 Agent/RAG 纵向切片升级为可从 React 使用的完整运行链路：自然语言请求、模型约束解析、Single/Multi 两种模式、SQLite 持久化、SSE 事件、身份透传、Verifier 和统一英文界面。

## 1. 配置 Spring 与 DeepSeek 翻译

根目录 `.env` 至少包含数据库、Redis 和 DeepSeek 配置：

```properties
DEEPSEEK_API_KEY=replace-with-your-key
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

Spring 保留 `/translate/blog`、`/translate/comment`、`/translate/shop`，并新增受限长度的 `/translate/text`。所有翻译结果仍使用 Redis 缓存，任意文本以 SHA-256 作为缓存 ID。

## 2. 启动 Agent Service

```bash
cd agent-service
NYC_REVIEW_AGENT_ADAPTER=http \
NYC_REVIEW_AGENT_BACKEND_BASE_URL=http://127.0.0.1:8081 \
NYC_REVIEW_AGENT_BACKEND_AUTH_TOKEN=<current-user-token> \
NYC_REVIEW_AGENT_RAG_ADAPTER=qdrant \
NYC_REVIEW_AGENT_QDRANT_LOCATION=./.local/qdrant \
NYC_REVIEW_AGENT_RAG_DATA_DIRECTORY=../data/generated/nyc-small \
NYC_REVIEW_AGENT_MODEL_PROVIDER=deepseek \
DEEPSEEK_API_KEY=<your-key> \
uv run uvicorn app.main:app --port 8090
```

本地 Qdrant 路径一次只能被一个进程打开。并发实例请使用 Qdrant Server URL。

## 3. 验证自然语言 Run 与 SSE

```bash
curl -sS -X POST http://127.0.0.1:8090/v1/agent/runs \
  -H 'Content-Type: application/json' \
  -H 'authorization: <current-user-token>' \
  -d '{"mode":"multi","query":"Quiet vegan dinner in Midtown for 2 under $120"}'
```

```bash
curl -N http://127.0.0.1:8090/v1/agent/runs/<run-id>/events
curl -sS http://127.0.0.1:8090/v1/agent/runs/<run-id>
```

最终结果应包含候选商户、RAG 引用、预算/距离、Verifier 结果以及 `modelProvider`、`modelFallbackUsed`、`dataVersion`、`datasetSha256`。

## 4. 验证 DeepSeek 翻译

翻译接口需要有效登录 token：

```bash
curl -sS -X POST http://127.0.0.1:8081/translate/text \
  -H 'Content-Type: application/json' \
  -H 'authorization: <current-user-token>' \
  -d '{"text":"安静的纯素晚餐，两个人，预算120美元","targetLang":"en"}'
```

React AI Guide 中的 “Translate to English with DeepSeek” 调用同一接口。博客和评论页也保留显式 DeepSeek 翻译入口。

## 5. 自动化验证

```bash
uv run --project agent-service ruff check agent-service/app agent-service/tests
uv run --project agent-service pytest agent-service/tests -q
uv run --project agent-service python -m evals.run_eval
mvn clean -Dtest='!NycReviewApplicationTests' test
cd nyc-review-web && npm run build
```

最后打开 `http://127.0.0.1:3000/ai`，分别运行 Single Agent 与 Multi Agent，确认橙色移动端设计、实时节点状态、引用卡片、DeepSeek 翻译和底部 AI Guide 导航均可用。手动秒杀仍只存在于商户详情页，不进入模型工具。
